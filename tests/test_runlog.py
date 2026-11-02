"""T13: run logging — files, meta, summary, mission metrics, events.bin (R12.2-R12.3)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import numpy as np
import pytest

from jn_sim import protocol, provenance, testctl
from jn_sim.config import Config
from jn_sim.host import Host
from jn_sim.link import TcpLink, make_link
from jn_sim.protocol import EVENT_DTYPE
from jn_sim.runlog import RunLogger, mission_metrics, summarise
from jn_sim.sim import Simulator

# Needs a git checkout with a commit; skips in a ZIP download (see test_ctl.py).
needs_git_checkout = pytest.mark.skipif(
    provenance.git_info()["sha"] == "unknown",
    reason="not a git checkout with a commit: no SHA to record",
)


def _cfg(trajectory="sine", **run_over) -> Config:
    c = Config()
    c.target.trajectory = trajectory
    for k, v in run_over.items():
        setattr(c.run, k, v)
    return c


def _run(tmp_path, cfg, *, controller="inproc:centroid", episodes=1, duration=0.3,
         save_events=False, scenario=None, overrides=None, scenario_exact=False,
         seed=0, link=None, mode="lockstep"):
    logger = RunLogger(
        tmp_path, cfg, seed=seed, scenario=scenario, overrides=overrides or [],
        scenario_exact=scenario_exact, endpoint_type="inproc",
        warmup_s=cfg.run.warmup_s, success_in_fov=cfg.run.success_in_fov, save_events=save_events,
    )
    sim = Simulator(cfg, seed)
    link = link or make_link(controller)
    res = sim.run(mode, link, episodes=episodes, duration_s=duration, host=Host(), logger=logger)
    return res, Path(logger.run_dir)


# -- mission metrics on a synthetic sequence (R12.2) ----------------------- #
def test_mission_metrics_known_sequence() -> None:
    in_fov = [1, 1, 0, 0, 1, 1, 0, 1, 0, 0, 0]
    times = [i * 0.01 for i in range(len(in_fov))]
    m = mission_metrics(in_fov, times, success_in_fov=0.95)
    assert m["target_losses"] == 3
    assert m["reacquire_mean_s"] == pytest.approx(0.015)
    assert m["reacquire_max_s"] == pytest.approx(0.02)
    assert m["unrecovered_losses"] == 1
    assert m["longest_out_of_view_s"] == pytest.approx(0.02)
    assert m["in_fov_fraction"] == pytest.approx(5 / 11)
    assert m["success"] is False  # failed episode


def test_mission_metrics_open_at_start() -> None:
    m = mission_metrics([0, 0, 1], [0.0, 0.01, 0.02], success_in_fov=0.5)
    assert m["target_losses"] == 1  # a loss already open at the first sample
    assert m["reacquire_max_s"] == pytest.approx(0.02)
    assert m["unrecovered_losses"] == 0


# -- files and their contents ---------------------------------------------- #
def test_all_files_created_and_one_row_per_period(tmp_path) -> None:
    cfg = _cfg(episode_length_s=0.3)
    _, rd = _run(tmp_path, cfg, save_events=True)
    assert {p.name for p in rd.iterdir()} == {"meta.json", "periods.csv", "summary.json", "events.bin"}
    with (rd / "periods.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 30  # 0.3 s / 10 ms


@needs_git_checkout
def test_meta_has_sha_dirty_and_controller(tmp_path) -> None:
    cfg = _cfg(episode_length_s=0.2)
    _, rd = _run(tmp_path, cfg, episodes=2)
    meta = json.loads((rd / "meta.json").read_text())
    assert meta["git_sha"] != "unknown" and len(meta["git_sha"]) == 40
    assert isinstance(meta["git_dirty"], bool)
    assert meta["controller"]["name"] == "centroid"
    assert set(meta["ctl_seed"]) == {"0", "1"}  # ctl_seed per episode


def test_meta_unknown_without_git(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-for-this-test")
    cfg = _cfg(episode_length_s=0.1)
    _, rd = _run(tmp_path, cfg)
    meta = json.loads((rd / "meta.json").read_text())
    assert meta["git_sha"] == "unknown" and meta["git_dirty"] is None


def test_meta_records_overrides_and_scenario_exact(tmp_path) -> None:
    cfg = _cfg(episode_length_s=0.1)
    _, rd = _run(tmp_path, cfg, scenario="track-sine-v1",
                 overrides=["run.seed=5 (config=x.json)"], scenario_exact=False)
    meta = json.loads((rd / "meta.json").read_text())
    assert meta["scenario"] == "track-sine-v1"
    assert meta["overrides"] == ["run.seed=5 (config=x.json)"]
    assert meta["scenario_exact"] is False
    assert json.loads((rd / "summary.json").read_text())["scenario_exact"] is False


def test_summary_recomputed_from_csv_matches(tmp_path) -> None:
    cfg = _cfg(episode_length_s=2.0)  # longer than the 1 s warm-up
    _, rd = _run(tmp_path, cfg, duration=2.0)
    summary = json.loads((rd / "summary.json").read_text())
    with (rd / "periods.csv").open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    misses = sum(int(r["miss"]) for r in rows)
    infov = sum(int(r["in_fov"]) for r in rows if int(r["t_us"]) >= 1_000_000)
    warm = sum(1 for r in rows if int(r["t_us"]) >= 1_000_000)
    assert summary["overall"]["misses"] == misses
    assert abs(summary["overall"]["mission"]["in_fov_fraction"] - infov / warm) < 1e-9


def test_events_bin_splits_by_n_events(tmp_path) -> None:
    cfg = _cfg(episode_length_s=0.3)
    _, rd = _run(tmp_path, cfg, save_events=True)
    ev = np.fromfile(rd / "events.bin", dtype=EVENT_DTYPE)
    with (rd / "periods.csv").open(newline="") as fh:
        total = sum(int(r["n_events"]) for r in csv.DictReader(fh))
    assert ev.size == total


# -- aborted run still leaves a valid CSV and summary (R7.6) ---------------- #
class _CrashController:
    def reset(self, hello) -> str:
        return "centroid"

    def step(self, obs):
        if obs.k >= 3:
            raise RuntimeError("crash")
        return 0.0, 0.0


def test_aborted_run_leaves_valid_outputs(tmp_path, server_factory) -> None:
    meta = provenance.controller_metadata("centroid", {})
    port = server_factory(lambda: _CrashController(), meta, once=True)
    cfg = _cfg("static", episode_length_s=0.5)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    res, rd = _run(tmp_path, cfg, link=link, duration=0.5)
    assert res.status == "aborted"
    assert (rd / "periods.csv").exists() and (rd / "summary.json").exists()
    summary = json.loads((rd / "summary.json").read_text())
    assert summary["status"] == "aborted" and summary["reason"]
    with (rd / "periods.csv").open(newline="") as fh:
        assert len(list(csv.DictReader(fh))) <= 4  # complete up to the crash


# ========================================================================== #
# Added after the final-checkpoint review (B1, B2, M2, m5, L13, L14).
# ========================================================================== #

from datetime import datetime, timezone

from jn_sim.runlog import PERIOD_COLUMNS


def _synth_row(episode, k, in_fov, *, t_us=None):
    return {
        "episode": episode, "k": k, "t_us": t_us if t_us is not None else (k + 1) * 10000,
        "pan": 0.0, "tilt": 0.0, "pan_rate": 0.0, "tilt_rate": 0.0,
        "pan_sp": 0.0, "tilt_sp": 0.0, "cmd_pan": 0.0, "cmd_tilt": 0.0,
        "cmd_invalid": 0, "cmd_clamped": 0, "ctl_flags": 0,
        "target_az": 0.0, "target_el": 0.0, "target_u": 0.0, "target_v": 0.0,
        "err_px": 5.0 if in_fov else float("nan"), "in_fov": in_fov,
        "n_events": 10, "n_on": 5, "n_off": 5,
        "sim_us": 100, "ctl_us": 50.0, "rtt_us": 80.0, "link_us": 30.0, "miss": 0,
        "ctl_rx_ns": 0, "ctl_tx_ns": 50000, "send_lateness_us": float("nan"),
    }


# -- B2: overall mission metrics aggregate the per-episode results --------- #
@pytest.mark.parametrize("n_episodes", [2, 3])
def test_overall_mission_aggregates_per_episode(n_episodes) -> None:
    fx = Config().intrinsics().fx
    rows = []
    for e in range(n_episodes):
        for k in range(10):
            rows.append(_synth_row(e, k, in_fov=0 if k >= 7 else 1))  # loses view, never recovers
    s = summarise(rows, period_s=0.01, warmup_s=0.0, success_in_fov=0.95, fx=fx)
    o = s["overall"]["mission"]
    # One unrecovered loss per episode; not merged into one time series (B2).
    assert o["unrecovered_losses"] == n_episodes
    assert o["target_losses"] == n_episodes
    assert o["reacquire_mean_s"] == 0.0  # no loss ever ended
    assert o["longest_out_of_view_s"] >= 0.0


# -- m5: error has angular (all-period) and in-view px/deg fields ---------- #
def test_error_fields_all_and_in_view(tmp_path) -> None:
    cfg = _cfg(episode_length_s=2.0)
    _, rd = _run(tmp_path, cfg, duration=2.0)
    err = json.loads((rd / "summary.json").read_text())["overall"]["error"]
    assert set(err) == {
        "rms_deg", "max_deg",
        "rms_px_in_view", "max_px_in_view", "rms_deg_in_view", "max_deg_in_view",
    }
    assert err["rms_deg"] is not None and err["rms_px_in_view"] is not None


def test_angular_error_counts_out_of_view_periods() -> None:
    # The angular error is defined even out of view, so it can only grow when
    # the target is lost (m5): a run that loses the target has rms_deg strictly
    # larger than its in-view rms_deg.
    fx = Config().intrinsics().fx
    rows = [_synth_row(0, k, in_fov=1) for k in range(5)]
    # add out-of-view rows whose boresight-to-target angle is large
    for k in range(5, 10):
        r = _synth_row(0, k, in_fov=0)
        r["target_az"] = 0.5  # 0.5 rad off boresight while pan stays 0
        rows.append(r)
    s = summarise(rows, period_s=0.01, warmup_s=0.0, success_in_fov=0.95, fx=fx)
    err = s["overall"]["error"]
    assert err["rms_deg"] > err["rms_deg_in_view"]


# -- L14: the warm-up is applied in the summary (R12.2) -------------------- #
def test_summary_applies_warmup() -> None:
    fx = Config().intrinsics().fx
    rows = [_synth_row(0, k, in_fov=0) for k in range(9)]          # pre-warm, out of view
    rows += [_synth_row(0, k, in_fov=1) for k in range(9, 30)]     # warm, in view
    s = summarise(rows, period_s=0.01, warmup_s=0.1, success_in_fov=0.95, fx=fx)
    # warm-up rows (t_us < 0.1 s) are excluded, so the fraction is 1.0.
    assert s["overall"]["mission"]["in_fov_fraction"] == 1.0


# -- L13: periods.csv column order is exactly the R12.2 list --------------- #
def test_period_columns_exact_order() -> None:
    assert PERIOD_COLUMNS == [
        "episode", "k", "t_us",
        "pan", "tilt", "pan_rate", "tilt_rate", "pan_sp", "tilt_sp",
        "cmd_pan", "cmd_tilt", "cmd_invalid", "cmd_clamped", "ctl_flags",
        "target_az", "target_el", "target_u", "target_v", "err_px", "in_fov",
        "n_events", "n_on", "n_off",
        "sim_us", "ctl_us", "rtt_us", "link_us", "miss",
        "ctl_rx_ns", "ctl_tx_ns", "send_lateness_us",
    ]


# -- M2: two runs in the same second get distinct directories -------------- #
def test_two_runs_same_second_distinct_dirs(tmp_path) -> None:
    ts = datetime(2026, 10, 25, 12, 0, 0, tzinfo=timezone.utc)
    names = []
    for _ in range(2):
        lg = RunLogger(
            tmp_path, Config(), seed=0, scenario=None, overrides=[], scenario_exact=False,
            endpoint_type="inproc", warmup_s=1.0, success_in_fov=0.95,
        )
        lg._start_utc = ts
        lg.start(None, "sine", "centroid")
        names.append(lg.run_dir.name)
        lg.finalize("completed", None)
    assert names[0] == "20261025T120000Z_sine_centroid"
    assert names[1] == "20261025T120000Z_sine_centroid_2"
    assert (tmp_path / names[0]).is_dir() and (tmp_path / names[1]).is_dir()
