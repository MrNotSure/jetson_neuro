"""Run logging (spec T13, R12.2-R12.3).

Writes one run directory ``runs/<YYYYMMDDTHHMMSSZ>_<trajectory>_<controller>/``
containing ``meta.json`` (resolved config, seed, scenario and overrides, the
simulation host's git SHA, endpoint type, versions, per-episode ``ctl_seed``
and the controller metadata), ``periods.csv`` (one streamed row per period),
``summary.json`` (status, tracking and mission metrics, timing and counts), and
``events.bin`` when ``--save-events`` is set.

Rows and events stream to disk and the summary is computed from ``periods.csv``
at the end, so memory stays bounded for long runs (R12.3). Each timing column
comes from a single host's clock and absolute timestamps from different hosts
are never subtracted (R12.2).

Standard library + numpy; simulation-host side.
"""

from __future__ import annotations

import csv
import json
import math
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from . import camera, provenance
from .config import Config

PERIOD_COLUMNS = [
    "episode", "k", "t_us",
    "pan", "tilt", "pan_rate", "tilt_rate", "pan_sp", "tilt_sp",
    "cmd_pan", "cmd_tilt", "cmd_invalid", "cmd_clamped", "ctl_flags",
    "target_az", "target_el", "target_u", "target_v", "err_px", "in_fov",
    "n_events", "n_on", "n_off",
    "sim_us", "ctl_us", "rtt_us", "link_us", "miss",
    "ctl_rx_ns", "ctl_tx_ns", "send_lateness_us",
]
# Columns excluded from the determinism comparison (R2.3): measured timings.
TIMING_COLUMNS = {"sim_us", "ctl_us", "rtt_us", "link_us", "ctl_rx_ns", "ctl_tx_ns", "send_lateness_us"}

_FLAG_BITS = {"fault": 1, "detect": 2, "recover": 4}


def _fmt(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        return repr(value)  # shortest round-trippable, deterministic
    return str(value)


class RunLogger:
    def __init__(
        self,
        out_base: str | Path,
        cfg: Config,
        *,
        seed: int,
        scenario: str | None,
        overrides: list[str],
        scenario_exact: bool,
        endpoint_type: str,
        warmup_s: float,
        success_in_fov: float,
        save_events: bool = False,
        cwd: str | None = None,
    ) -> None:
        self.out_base = Path(out_base)
        self.cfg = cfg
        self.seed = seed
        self.scenario = scenario
        self.overrides = list(overrides)
        self.scenario_exact = scenario_exact
        self.endpoint_type = endpoint_type
        self.warmup_s = warmup_s
        self.success_in_fov = success_in_fov
        self.save_events = save_events
        self._cwd = cwd

        self.run_dir: Path | None = None
        self._csv_fh = None
        self._csv_writer = None
        self._events_fh = None
        self._ctl_seeds: dict[int, int] = {}
        self._controller_meta: dict | None = None
        self._start_utc = datetime.now(timezone.utc)
        self._achieved_hz: float | None = None
        self._summary: _Summary | None = None
        self.summary: dict | None = None  # the written summary, for the CLI (m3)

    # -- lifecycle --------------------------------------------------------- #
    def start(self, controller_meta: dict | None, trajectory: str, controller_name: str) -> None:
        ts = self._start_utc.strftime("%Y%m%dT%H%M%SZ")
        self.run_dir = self._make_run_dir(f"{ts}_{trajectory}_{controller_name}")
        self._controller_meta = controller_meta
        self._summary = _Summary(
            period_s=self.cfg.loop.period_s,
            warmup_s=self.warmup_s,
            success_in_fov=self.success_in_fov,
            fx=self.cfg.intrinsics().fx,
        )
        self._csv_fh = (self.run_dir / "periods.csv").open("w", encoding="utf-8", newline="")
        self._csv_writer = csv.writer(self._csv_fh)
        self._csv_writer.writerow(PERIOD_COLUMNS)
        if self.save_events:
            self._events_fh = (self.run_dir / "events.bin").open("wb")

    def _make_run_dir(self, base: str) -> Path:
        """Create the run directory exclusively; on a name clash add ``_2`` …

        Two runs in the same second (same trajectory and controller) therefore
        never share a directory, and nothing is overwritten (R12.2, M2).
        """
        self.out_base.mkdir(parents=True, exist_ok=True)
        candidate = self.out_base / base
        n = 1
        while True:
            try:
                candidate.mkdir(exist_ok=False)
                return candidate
            except FileExistsError:
                n += 1
                candidate = self.out_base / f"{base}_{n}"

    def set_ctl_seed(self, episode: int, ctl_seed: int) -> None:
        self._ctl_seeds[episode] = int(ctl_seed)

    def set_achieved_hz(self, hz: float) -> None:
        self._achieved_hz = hz

    def log_period(self, row: dict, events: np.ndarray) -> None:
        self._csv_writer.writerow([_fmt(row[c]) for c in PERIOD_COLUMNS])
        if self._events_fh is not None:
            self._events_fh.write(np.ascontiguousarray(events).tobytes())
        # Accumulate the summary as rows stream, so memory stays bounded for
        # long runs (R12.3, B1): no list of rows is ever held.
        if self._summary is not None:
            self._summary.add_row(row)

    def finalize(self, status: str, reason: str | None) -> None:
        if self._csv_fh is not None:
            self._csv_fh.flush()
            self._csv_fh.close()
        if self._events_fh is not None:
            self._events_fh.close()
        if self.run_dir is None:
            return
        self._write_meta()
        self._write_summary(status, reason)

    # -- meta.json --------------------------------------------------------- #
    def _write_meta(self) -> None:
        host = provenance.host_metadata(self._cwd)
        meta = {
            "config": self.cfg.to_dict(),
            "seed": self.seed,
            "scenario": self.scenario,
            "overrides": self.overrides,
            "scenario_exact": self.scenario_exact,
            "endpoint_type": self.endpoint_type,
            "git_sha": host["git_sha"],
            "git_dirty": host["git_dirty"],
            "os": host["os"],
            "arch": host["arch"],
            "python": host["python"],
            "numpy": host["numpy"],
            "matplotlib": host["matplotlib"],
            "ctl_seed": {str(e): s for e, s in sorted(self._ctl_seeds.items())},
            "controller": self._controller_meta,
            "start_utc": self._start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        with (self.run_dir / "meta.json").open("w", encoding="utf-8") as fh:
            json.dump(meta, fh, indent=2)
            fh.write("\n")

    # -- summary.json ------------------------------------------------------ #
    def _write_summary(self, status: str, reason: str | None) -> None:
        assert self._summary is not None
        body = self._summary.result()
        summary = {
            "status": status,
            "reason": reason,
            "scenario_exact": self.scenario_exact,
            "achieved_hz": self._achieved_hz,
            **body,
        }
        self.summary = summary  # expose for the CLI to print (m3)
        with (self.run_dir / "summary.json").open("w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2)
            fh.write("\n")


# --------------------------------------------------------------------------- #
# Summary computation. The summary is accumulated one row at a time so memory
# stays bounded for long runs (R12.3, B1); the overall figures come from the
# per-episode results, never from one time series across episodes, since t_us
# restarts each episode (R12.2, B2).
# --------------------------------------------------------------------------- #

# Bound the per-metric sample store so a 60-min run can't grow it without
# limit (R12.3): keep every value below the cap (so typical runs are exact),
# and a uniform reservoir sample above it.
_RESERVOIR_CAP = 1 << 18  # 262144


class _Reservoir:
    """Running mean/max plus a bounded sample for percentiles (R12.3)."""

    def __init__(self) -> None:
        self._vals: list[float] = []
        self._count = 0
        self._sum = 0.0
        self._max = -math.inf
        self._rng = random.Random(0)  # deterministic sampling given the input

    def add(self, value: Any) -> None:
        if value is None:
            return
        x = float(value)
        if math.isnan(x):
            return  # misses leave ctl_us/rtt_us/link_us NaN; skip them
        i = self._count
        self._count += 1
        self._sum += x
        if x > self._max:
            self._max = x
        if i < _RESERVOIR_CAP:
            self._vals.append(x)
        else:  # Algorithm R: keep a uniform sample of the stream
            j = self._rng.randint(0, i)
            if j < _RESERVOIR_CAP:
                self._vals[j] = x

    def stats(self, p: float) -> dict:
        key = f"p{int(p)}"
        if self._count == 0:
            return {"mean": None, key: None, "max": None}
        arr = np.asarray(self._vals, dtype=float)
        return {
            "mean": self._sum / self._count,
            key: float(np.percentile(arr, p)),
            "max": self._max,
        }


class _ErrorAcc:
    """Tracking error: angular over all periods, px/deg over in-view (m5)."""

    def __init__(self, fx: float) -> None:
        self.fx = fx
        self._sumsq_deg_all = 0.0
        self._max_deg_all = 0.0
        self._n_all = 0
        self._sumsq_px = 0.0
        self._max_px = 0.0
        self._sumsq_deg_iv = 0.0
        self._max_deg_iv = 0.0
        self._n_iv = 0

    def add(self, err_deg: float, err_px: float, in_view: bool) -> None:
        # Over all periods: the boresight-to-target angle, always defined, so
        # losing the target can't improve the RMS (R12.2, m5).
        if err_deg is not None and not math.isnan(err_deg):
            self._sumsq_deg_all += err_deg * err_deg
            self._max_deg_all = max(self._max_deg_all, err_deg)
            self._n_all += 1
        # Over in-view periods only: the pixel error and its angle.
        if in_view and err_px is not None and not math.isnan(err_px):
            self._sumsq_px += err_px * err_px
            self._max_px = max(self._max_px, err_px)
            deg = math.degrees(math.atan(err_px / self.fx))
            self._sumsq_deg_iv += deg * deg
            self._max_deg_iv = max(self._max_deg_iv, deg)
            self._n_iv += 1

    def result(self) -> dict:
        out: dict[str, Any] = {}
        if self._n_all:
            out["rms_deg"] = math.sqrt(self._sumsq_deg_all / self._n_all)
            out["max_deg"] = self._max_deg_all
        else:
            out["rms_deg"] = out["max_deg"] = None
        if self._n_iv:
            out["rms_px_in_view"] = math.sqrt(self._sumsq_px / self._n_iv)
            out["max_px_in_view"] = self._max_px
            out["rms_deg_in_view"] = math.sqrt(self._sumsq_deg_iv / self._n_iv)
            out["max_deg_in_view"] = self._max_deg_iv
        else:
            out["rms_px_in_view"] = out["max_px_in_view"] = None
            out["rms_deg_in_view"] = out["max_deg_in_view"] = None
        return out


class _MissionAcc:
    """Incremental target-loss metrics over one episode's warm rows (R12.2)."""

    def __init__(self) -> None:
        self.open_start: float | None = None
        self.losses = 0
        self.reacq_sum = 0.0
        self.reacq_count = 0
        self.reacq_max = 0.0
        self.longest = 0.0
        self.in_fov_count = 0
        self.total = 0
        self.last_t: float | None = None

    def add(self, fov: int, t: float) -> None:
        self.total += 1
        self.in_fov_count += int(fov)
        self.last_t = t
        if fov == 0 and self.open_start is None:
            self.open_start = t
            self.losses += 1
        elif fov == 1 and self.open_start is not None:
            dur = t - self.open_start
            self.reacq_sum += dur
            self.reacq_count += 1
            self.reacq_max = max(self.reacq_max, dur)
            self.longest = max(self.longest, dur)
            self.open_start = None

    def longest_out_of_view(self) -> float:
        longest = self.longest
        if self.open_start is not None and self.last_t is not None:
            longest = max(longest, self.last_t - self.open_start)
        return longest

    def result(self, success_in_fov: float) -> dict:
        if self.total == 0:
            return {
                "in_fov_fraction": 0.0, "target_losses": 0, "reacquire_mean_s": 0.0,
                "reacquire_max_s": 0.0, "unrecovered_losses": 0,
                "longest_out_of_view_s": 0.0, "success": False,
            }
        frac = self.in_fov_count / self.total
        return {
            "in_fov_fraction": frac,
            "target_losses": self.losses,
            "reacquire_mean_s": (self.reacq_sum / self.reacq_count) if self.reacq_count else 0.0,
            "reacquire_max_s": self.reacq_max,
            "unrecovered_losses": 1 if self.open_start is not None else 0,
            "longest_out_of_view_s": self.longest_out_of_view(),
            "success": frac >= success_in_fov,
        }


def mission_metrics(in_fov: list[int], times_s: list[float], success_in_fov: float) -> dict:
    """Target-loss metrics over a (warm-up-trimmed) in-FOV sequence (R12.2).

    An out-of-view interval already open at the first sample counts as a loss
    starting then; a loss still open at the end is unrecovered. Kept as a pure
    function (the streaming path uses the same :class:`_MissionAcc`).
    """
    acc = _MissionAcc()
    for fov, t in zip(in_fov, times_s):
        acc.add(fov, t)
    return acc.result(success_in_fov)


def _aggregate_missions(accs: list[_MissionAcc], success_in_fov: float) -> dict:
    """Overall mission metrics from the per-episode accumulators (B2).

    Counts are summed, the reacquire mean is weighted by each episode's ended
    losses, maxima take the largest per-episode value, and the in-FOV fraction
    is pooled over all post-warm-up periods. No value crosses the episode
    boundary, so a loss open at an episode's end never merges into the next.
    """
    total = sum(a.total for a in accs)
    in_fov = sum(a.in_fov_count for a in accs)
    reacq_sum = sum(a.reacq_sum for a in accs)
    reacq_count = sum(a.reacq_count for a in accs)
    frac = (in_fov / total) if total else 0.0
    return {
        "in_fov_fraction": frac,
        "target_losses": sum(a.losses for a in accs),
        "reacquire_mean_s": (reacq_sum / reacq_count) if reacq_count else 0.0,
        "reacquire_max_s": max((a.reacq_max for a in accs), default=0.0),
        "unrecovered_losses": sum(1 for a in accs if a.open_start is not None),
        "longest_out_of_view_s": max((a.longest_out_of_view() for a in accs), default=0.0),
        "success": frac >= success_in_fov,
    }


class _EpisodeAcc:
    def __init__(self, fx: float) -> None:
        self.periods = 0
        self.events = _Reservoir()
        self.error = _ErrorAcc(fx)
        self.mission = _MissionAcc()


def _angular_error_deg(row: dict) -> float:
    """Boresight-to-target angle (deg) for a row, always defined (m5)."""
    return float(
        camera.angular_error_deg(
            row["pan"], row["tilt"], row["target_az"], row["target_el"]
        )
    )


class _Summary:
    """Streaming summary accumulator (R12.2–R12.3, B1/B2)."""

    _TIMING = ("sim_us", "ctl_us", "rtt_us", "link_us", "send_lateness_us")

    def __init__(self, *, period_s: float, warmup_s: float,
                 success_in_fov: float, fx: float) -> None:
        self.period_s = period_s
        self.warmup_us = warmup_s * 1e6
        self.success_in_fov = success_in_fov
        self.fx = fx
        self._episodes: dict[int, _EpisodeAcc] = {}
        self.n_periods = 0
        self.misses = 0
        self.cmd_invalid = 0
        self.cmd_clamped = 0
        self.flag_counts = {name: 0 for name in _FLAG_BITS}
        self.events = _Reservoir()
        self.timing = {c: _Reservoir() for c in self._TIMING}
        self.error_all = _ErrorAcc(fx)

    def add_row(self, row: dict) -> None:
        self.n_periods += 1
        self.misses += int(row["miss"])
        self.cmd_invalid += int(row["cmd_invalid"])
        self.cmd_clamped += int(row["cmd_clamped"])
        flags = int(row["ctl_flags"])
        for name, bit in _FLAG_BITS.items():
            if flags & bit:
                self.flag_counts[name] += 1
        self.events.add(row["n_events"])
        for c in self._TIMING:
            self.timing[c].add(row[c])

        e = int(row["episode"])
        acc = self._episodes.get(e)
        if acc is None:
            acc = self._episodes[e] = _EpisodeAcc(self.fx)
        acc.periods += 1
        acc.events.add(row["n_events"])

        if float(row["t_us"]) >= self.warmup_us:  # metrics skip the warm-up
            err_deg = _angular_error_deg(row)
            in_view = int(row["in_fov"]) == 1
            err_px = float(row["err_px"])
            acc.error.add(err_deg, err_px, in_view)
            acc.mission.add(int(row["in_fov"]), float(row["t_us"]) / 1e6)
            self.error_all.add(err_deg, err_px, in_view)

    def result(self) -> dict:
        order = sorted(self._episodes)
        per_ep = []
        successes = 0
        for e in order:
            acc = self._episodes[e]
            mission = acc.mission.result(self.success_in_fov)
            if mission["success"]:
                successes += 1
            per_ep.append({
                "episode": e,
                "periods": acc.periods,
                "error": acc.error.result(),
                "mission": mission,
                "events": acc.events.stats(95),
            })
        missions = [self._episodes[e].mission for e in order]
        overall = {
            "periods": self.n_periods,
            "episodes": len(order),
            "error": self.error_all.result(),
            "mission": _aggregate_missions(missions, self.success_in_fov),
            "events_per_period": self.events.stats(95),
            "timing": {c: self.timing[c].stats(99) for c in self._TIMING},
            "misses": self.misses,
            "cmd_invalid": self.cmd_invalid,
            "cmd_clamped": self.cmd_clamped,
            "ctl_flags": dict(self.flag_counts),
            "success_rate": (successes / len(order)) if order else 0.0,
        }
        return {"episodes": per_ep, "overall": overall}


def summarise(rows: list[dict], *, period_s: float, warmup_s: float,
              success_in_fov: float, fx: float) -> dict:
    """Summarise a list of period rows (the pure counterpart of the streaming
    accumulator, for tests). Feeds each row through the same :class:`_Summary`."""
    acc = _Summary(period_s=period_s, warmup_s=warmup_s,
                   success_in_fov=success_in_fov, fx=fx)
    for row in rows:
        acc.add_row(row)
    return acc.result()
