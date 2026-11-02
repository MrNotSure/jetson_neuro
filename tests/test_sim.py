"""T12: the closed loop — determinism, realtime==lockstep, tracking, aborts (R7, R14.1)."""

from __future__ import annotations

import contextlib
import queue as queue_mod
import threading
import time

import numpy as np
import pytest

from jn_sim import camera, protocol, provenance, render, seeding, testctl
from jn_sim import sim as simmod
from jn_sim.config import Config
from jn_sim.host import Host
from jn_sim.link import InProcLink, TcpLink
from jn_sim.render import Renderer, UniformBackground
from jn_sim.runlog import TIMING_COLUMNS
from jn_sim.sim import Simulator
from jn_sim.target import make_trajectory


class MemLogger:
    """In-memory logger capturing period rows (no filesystem)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []
        self.events: list[np.ndarray] = []
        self.run_dir = None
        self.ctl_seeds: dict[int, int] = {}
        self.achieved_hz = None
        self.controller_meta = None

    def start(self, meta, trajectory, name) -> None:
        self.controller_meta = meta
        self.run_dir = f"mem:{trajectory}_{name}"

    def set_ctl_seed(self, e, s) -> None:
        self.ctl_seeds[e] = s

    def set_achieved_hz(self, hz) -> None:
        self.achieved_hz = hz

    def log_period(self, row, events) -> None:
        self.rows.append(dict(row))
        self.events.append(events)

    def finalize(self, status, reason) -> None:
        self.final = (status, reason)


def _cfg(trajectory="sine", **run_over) -> Config:
    c = Config()
    c.target.trajectory = trajectory
    for k, v in run_over.items():
        setattr(c.run, k, v)
    return c


def _run(cfg, mode, controller="inproc:centroid", seed=0, episodes=1, duration=0.5, link=None):
    from jn_sim.link import make_link

    sim = Simulator(cfg, seed)
    log = MemLogger()
    link = link or make_link(controller)
    res = sim.run(mode, link, episodes=episodes, duration_s=duration, host=Host(), logger=log)
    return res, log


def _nontiming(row: dict) -> dict:
    return {k: v for k, v in row.items() if k not in TIMING_COLUMNS}


# -- determinism (R7.2) ---------------------------------------------------- #
def test_lockstep_deterministic() -> None:
    _, a = _run(_cfg(), "lockstep")
    _, b = _run(_cfg(), "lockstep")
    assert len(a.rows) == len(b.rows) > 0
    for ra, rb in zip(a.rows, b.rows):
        assert _nontiming(ra) == _nontiming(rb)


# -- realtime equals lockstep with zero misses (R7.4) ---------------------- #
def test_realtime_equals_lockstep() -> None:
    res_l, lock = _run(_cfg(), "lockstep", duration=0.3)
    res_r, real = _run(_cfg(), "realtime", duration=0.3)
    assert res_r.status == "completed"
    assert sum(r["miss"] for r in real.rows) == 0  # inproc never misses
    assert len(lock.rows) == len(real.rows)
    for rl, rr in zip(lock.rows, real.rows):
        assert _nontiming(rl) == _nontiming(rr)


# -- centroid tracking (R14.1) --------------------------------------------- #
def test_centroid_tracks_sine() -> None:
    _, log = _run(_cfg("sine"), "lockstep", duration=3.0)
    warm = [r for r in log.rows if r["t_us"] >= 1_000_000]
    assert all(r["in_fov"] for r in warm)  # 100% in view after warm-up
    errs = np.array([r["err_px"] for r in warm])
    rms = float(np.sqrt(np.mean(errs**2)))
    assert rms < 30.0


def test_hold_leaves_gimbal_still() -> None:
    _, log = _run(_cfg("sine"), "lockstep", controller="inproc:hold", duration=0.5)
    assert all(abs(r["pan"]) < 1e-9 and abs(r["tilt"]) < 1e-9 for r in log.rows)
    assert all(r["miss"] == 0 for r in log.rows)


# -- invalid commands are data, not errors (R8.9) -------------------------- #
class _NaNOnce:
    def __init__(self, bad_k: int, pan: float = float("nan")) -> None:
        self.bad_k = bad_k
        self.pan = pan

    def reset(self, hello) -> str:
        return "hold"

    def step(self, obs):
        if obs.k == self.bad_k:
            return self.pan, 0.0
        return 0.0, 0.0


def test_nan_command_completes_and_is_counted() -> None:
    cfg = _cfg("static", episode_length_s=0.3)
    sim = Simulator(cfg, 0)
    log = MemLogger()
    res = sim.run("lockstep", InProcLink(_NaNOnce(5)), episodes=1, duration_s=0.3,
                  host=Host(), logger=log)
    assert res.status == "completed"
    bad = log.rows[5]
    assert bad["cmd_invalid"] == 1 and bad["miss"] == 0
    assert sum(r["cmd_invalid"] for r in log.rows) == 1


class _CtrlCController:
    """Simulates Ctrl-C by raising KeyboardInterrupt mid-run (R7.5)."""

    def reset(self, hello) -> str:
        return "hold"

    def step(self, obs):
        if obs.k == 3:
            raise KeyboardInterrupt
        return 0.0, 0.0


def test_ctrl_c_interrupts_cleanly() -> None:
    cfg = _cfg("static", episode_length_s=0.5)
    sim = Simulator(cfg, 0)
    log = MemLogger()
    res = sim.run("lockstep", InProcLink(_CtrlCController()), episodes=1, duration_s=0.5,
                  host=Host(), logger=log)
    assert res.status == "interrupted" and res.exit_code == 130
    assert log.final[0] == "interrupted"  # logs still finalised (R7.5)


def test_out_of_range_command_clamped_and_counted() -> None:
    cfg = _cfg("static", episode_length_s=0.3)
    sim = Simulator(cfg, 0)
    log = MemLogger()
    res = sim.run("lockstep", InProcLink(_NaNOnce(5, pan=100.0)), episodes=1, duration_s=0.3,
                  host=Host(), logger=log)
    assert res.status == "completed"
    assert log.rows[5]["cmd_clamped"] == 1
    assert sum(r["cmd_clamped"] for r in log.rows) == 1


# -- episodes over one connection (R8.3) ----------------------------------- #
def test_three_episodes_rerun_identically() -> None:
    _, a = _run(_cfg("sine"), "lockstep", episodes=3, duration=0.3)
    _, b = _run(_cfg("sine"), "lockstep", episodes=3, duration=0.3)
    assert sorted({r["episode"] for r in a.rows}) == [0, 1, 2]
    for ra, rb in zip(a.rows, b.rows):
        assert _nontiming(ra) == _nontiming(rb)
    # thresholds persist across episodes: event counts of episode 0 vs rerun match
    assert len(a.ctl_seeds) == 3


# -- connection loss aborts the run (R7.6) --------------------------------- #
class _CrashController:
    def __init__(self, crash_k: int) -> None:
        self.crash_k = crash_k

    def reset(self, hello) -> str:
        return "centroid"

    def step(self, obs):
        if obs.k >= self.crash_k:
            raise RuntimeError("controller crashed")
        return 0.0, 0.0


def test_connection_loss_aborts(server_factory) -> None:
    meta = provenance.controller_metadata("centroid", {})
    port = server_factory(lambda: _CrashController(5), meta, once=True)
    cfg = _cfg("static", episode_length_s=0.5)
    sim = Simulator(cfg, 0)
    log = MemLogger()
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    res = sim.run("lockstep", link, episodes=1, duration_s=0.5, host=Host(), logger=log)
    assert res.status == "aborted" and res.exit_code == 1
    assert "connection lost" in (res.reason or "")
    assert len(log.rows) <= 6  # completed periods up to the crash
    assert log.final == ("aborted", res.reason)


# -- startup: run before ctl, connects once ctl is up (R7.7) --------------- #
def test_startup_run_before_ctl() -> None:
    import socket

    from jn_sim import ctl

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    port = srv.getsockname()[1]
    srv.close()  # free the port; ctl binds it shortly

    result: dict = {}

    def do_run():
        cfg = _cfg("static", episode_length_s=0.2)
        sim = Simulator(cfg, 0)
        link = TcpLink("127.0.0.1", port, connect_timeout=8)
        result["res"] = sim.run(
            "lockstep", link, episodes=1, duration_s=0.2, host=Host(), logger=MemLogger()
        )

    stop = threading.Event()

    def do_ctl():
        ctl.serve(
            lambda: testctl.make_controller("hold"),
            provenance.controller_metadata("hold", {}),
            "127.0.0.1", port, once=True, should_stop=stop.is_set, poll=0.05,
        )

    runner = threading.Thread(target=do_run, daemon=True)
    runner.start()
    time.sleep(0.5)  # the run is now retrying to connect
    ctl_thread = threading.Thread(target=do_ctl, daemon=True)
    ctl_thread.start()
    runner.join(timeout=10)
    stop.set()
    ctl_thread.join(timeout=5)
    assert result["res"].status == "completed"


# ========================================================================== #
# Loop-behaviour tests added after the final-checkpoint review (M1, M3–M5, m1).
# Each is written so a single-line regression in the loop fails a test.
# ========================================================================== #


class ScriptLink:
    """A Link whose reply per (episode, k) a test scripts; None means a miss.

    Deterministic, so realtime misses, late-reply waits and timing can be
    exercised without real network timing. Records BYEs and late-reply waits.
    """

    def __init__(self, plan, name="centroid", late_ok=True):
        self._plan = plan
        self._name = name
        self.controller_meta = {"name": name}
        self.byes: list[int] = []
        self.waited: list[tuple[int, int]] = []
        self.late_ok = late_ok

    def open(self, hello):
        self.hello = hello
        return self._name

    def exchange(self, obs, deadline=None, obs_bytes=None):
        r = self._plan(obs.episode, obs.k)
        if r is None:
            return None  # a miss
        pan, tilt = r[0], r[1]
        flags = r[2] if len(r) > 2 else 0
        rx = r[3] if len(r) > 3 else 1000
        tx = r[4] if len(r) > 4 else 2000
        return protocol.Cmd(obs.episode, obs.k, pan, tilt, flags, rx, tx)

    def wait_for_late(self, episode, k, deadline):
        self.waited.append((episode, k))
        return self.late_ok

    def send_bye(self, episode):
        self.byes.append(episode)

    def close(self):
        pass


def _run_link(cfg, mode, link, *, seed=0, episodes=1, duration=0.2, host=None):
    sim = Simulator(cfg, seed)
    log = MemLogger()
    res = sim.run(mode, link, episodes=episodes, duration_s=duration,
                  host=host or Host(), logger=log)
    return res, log, sim


# -- L1: a miss holds the previous setpoint (R7.3) ------------------------- #
def test_miss_holds_setpoint(monkeypatch) -> None:
    monkeypatch.setattr(simmod, "_sleep_until_ns", lambda ns: None)
    cfg = _cfg("static", episode_length_s=0.2)  # 20 periods

    def plan(e, k):
        return None if k >= 10 else (0.4, 0.2, 0)  # command then stop replying

    res, log, _ = _run_link(cfg, "realtime", ScriptLink(plan), duration=0.2)
    assert res.status == "completed"
    assert log.rows[15]["miss"] == 1
    # the setpoint in effect is held at the last applied command, not reset.
    assert log.rows[15]["pan_sp"] == pytest.approx(0.4)
    assert log.rows[15]["tilt_sp"] == pytest.approx(0.2)


# -- L2: the realtime schedule is absolute, not relative (R7.3) ------------ #
def test_realtime_schedule_is_absolute(monkeypatch) -> None:
    targets: list[int] = []
    monkeypatch.setattr(simmod, "_sleep_until_ns", lambda ns: targets.append(ns))
    cfg = _cfg("static", episode_length_s=0.1)  # 10 periods
    res, _, sim = _run_link(cfg, "realtime", ScriptLink(lambda e, k: (0.0, 0.0, 0)),
                            duration=0.1)
    assert res.status == "completed"
    assert len(targets) == 10
    diffs = {targets[i + 1] - targets[i] for i in range(len(targets) - 1)}
    assert diffs == {sim.period_ns}  # exact T spacing: an absolute schedule


# -- L3: the uniform ROI loop equals a full-frame loop (R6.7) -------------- #
class _FullFrameFlag:
    """Same intensity as its inner background but flagged non-uniform, so the
    loop takes the full-frame path over the identical scene (R6.7)."""

    uniform = False

    def __init__(self, inner):
        self._inner = inner

    def intensity(self, u, v, pan, tilt):
        return self._inner.intensity(u, v, pan, tilt)


def test_roi_loop_equals_full_frame_loop() -> None:
    # A continuously moving target (sine), so there are scene events every
    # period; the ROI path must reproduce the full-frame path exactly (R6.7).
    cfg = _cfg("sine", episode_length_s=0.5)
    cfg.events.noise_rate_hz = 0.0
    _, roi, _ = _run_link(cfg, "lockstep", ScriptLink(lambda e, k: (0.0, 0.0, 0)),
                          duration=0.5)

    cfg2 = _cfg("sine", episode_length_s=0.5)
    cfg2.events.noise_rate_hz = 0.0
    sim2 = Simulator(cfg2, 0)
    sim2.renderer = Renderer(cfg2, background=_FullFrameFlag(UniformBackground(cfg2.scene.i_bg)))
    full = MemLogger()
    r2 = sim2.run("lockstep", ScriptLink(lambda e, k: (0.0, 0.0, 0)),
                  episodes=1, duration_s=0.5, host=Host(), logger=full)
    assert r2.status == "completed"
    assert len(roi.events) == len(full.events) > 0
    for a, b in zip(roi.events, full.events):
        assert np.array_equal(a.view(np.uint8), b.view(np.uint8))


# -- L4: sub-stepping is active for fast moves (R6.5) ---------------------- #
def test_substepping_changes_fast_move_events() -> None:
    def events_for(max_px):
        cfg = _cfg("sine", episode_length_s=0.3)
        cfg.events.noise_rate_hz = 0.0
        cfg.target.sine_az_freq_hz = 6.0
        cfg.target.sine_el_freq_hz = 5.0
        cfg.events.max_px_substep = max_px
        _, log, _ = _run_link(cfg, "lockstep", ScriptLink(lambda e, k: (0.0, 0.0, 0)),
                              duration=0.3)
        return [bytes(e.view(np.uint8).tobytes()) for e in log.events]

    fine = events_for(1.0)       # adaptive sub-stepping
    coarse = events_for(1.0e9)   # forces n_sub == 1
    assert fine != coarse  # the sub-step count changes the events on a fast move


# -- L5: a lockstep miss aborts the run (R7.2, R7.6) ----------------------- #
def test_lockstep_miss_aborts() -> None:
    cfg = _cfg("static", episode_length_s=0.2)
    link = ScriptLink(lambda e, k: None if k == 3 else (0.0, 0.0, 0))
    res, _, _ = _run_link(cfg, "lockstep", link, duration=0.2)
    assert res.status == "aborted" and "lockstep" in (res.reason or "")


# -- L6: a silent link aborts after max_consecutive_misses (R7.6) ---------- #
def test_silent_link_aborts(monkeypatch) -> None:
    monkeypatch.setattr(simmod, "_sleep_until_ns", lambda ns: None)
    cfg = _cfg("static", episode_length_s=0.2)
    cfg.loop.max_consecutive_misses = 3
    res, _, _ = _run_link(cfg, "realtime", ScriptLink(lambda e, k: None), duration=0.2)
    assert res.status == "aborted" and "silent link" in (res.reason or "")


# -- L9: BYE is sent on Ctrl-C (R7.5) -------------------------------------- #
def test_bye_sent_on_ctrl_c() -> None:
    cfg = _cfg("static", episode_length_s=0.5)

    def plan(e, k):
        if k == 3:
            raise KeyboardInterrupt
        return (0.0, 0.0, 0)

    link = ScriptLink(plan)
    res, _, _ = _run_link(cfg, "lockstep", link, duration=0.5)
    assert res.status == "interrupted"
    assert link.byes == [0]  # BYE still sent on the way out


# -- L11: keep-awake is entered in realtime (R2.1) ------------------------- #
class _RecordingHost(Host):
    def __init__(self):
        super().__init__()
        self.kept = False

    @contextlib.contextmanager
    def keep_awake(self):
        self.kept = True
        yield None


def test_keep_awake_used_in_realtime(monkeypatch) -> None:
    monkeypatch.setattr(simmod, "_sleep_until_ns", lambda ns: None)
    cfg = _cfg("static", episode_length_s=0.1)
    host = _RecordingHost()
    _run_link(cfg, "realtime", ScriptLink(lambda e, k: (0.0, 0.0, 0)), duration=0.1, host=host)
    assert host.kept is True


# -- L12: ctl_us is a controller-clock delta, not across clocks (R12.2) ---- #
def test_ctl_us_is_controller_clock_delta() -> None:
    cfg = _cfg("static", episode_length_s=0.05)
    link = ScriptLink(lambda e, k: (0.0, 0.0, 0, 1000, 3000))  # rx=1000ns, tx=3000ns
    _, log, _ = _run_link(cfg, "lockstep", link, duration=0.05)
    assert all(r["ctl_us"] == pytest.approx(2.0) for r in log.rows)  # (3000-1000)/1000


# -- L7/L8: each episode's noise and ctl_seed come from (3,e)/(4,e) -------- #
def test_noise_stream_reset_per_episode() -> None:
    cfg = _cfg("static", episode_length_s=0.2)  # static scene: events are noise only
    _, log, _ = _run_link(cfg, "lockstep", ScriptLink(lambda e, k: (0.0, 0.0, 0)),
                          episodes=2, duration=0.2)
    ep0 = [r["n_events"] for r in log.rows if r["episode"] == 0]
    ep1 = [r["n_events"] for r in log.rows if r["episode"] == 1]
    assert ep0 and ep1 and ep0 != ep1  # different noise streams per episode


def test_ctl_seed_depends_on_episode() -> None:
    _, log, _ = _run_link(_cfg("sine"), "lockstep",
                          ScriptLink(lambda e, k: (0.0, 0.0, 0)), episodes=3, duration=0.1)
    seeds = log.ctl_seeds
    assert len(seeds) == 3 and len(set(seeds.values())) == 3  # distinct per episode


# -- m1: in-process and TCP lockstep runs agree exactly (R9.2) ------------- #
def test_inproc_matches_tcp_lockstep(server_factory) -> None:
    cfg = _cfg("sine", episode_length_s=0.3)
    _, inproc = _run(cfg, "lockstep", controller="inproc:centroid", duration=0.3)

    meta = provenance.controller_metadata("centroid", {})
    port = server_factory(lambda: testctl.make_controller("centroid"), meta, once=True)
    sim = Simulator(_cfg("sine", episode_length_s=0.3), 0)
    tcp = MemLogger()
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    sim.run("lockstep", link, episodes=1, duration_s=0.3, host=Host(), logger=tcp)

    assert len(inproc.rows) == len(tcp.rows) > 0
    for a, b in zip(inproc.rows, tcp.rows):
        assert a["cmd_pan"] == b["cmd_pan"]  # f32-identical via the wire round-trip
        assert a["cmd_tilt"] == b["cmd_tilt"]
    for ea, eb in zip(inproc.events, tcp.events):
        assert np.array_equal(ea.view(np.uint8), eb.view(np.uint8))


# -- M1: an unexpected loop error finalises aborted, then propagates (R7.8) - #
class _RaisingController:
    def reset(self, hello):
        return "centroid"

    def step(self, obs):
        if obs.k == 3:
            raise RuntimeError("boom")
        return 0.0, 0.0


def test_unexpected_exception_finalises_aborted_then_raises() -> None:
    cfg = _cfg("static", episode_length_s=0.3)
    sim = Simulator(cfg, 0)
    log = MemLogger()
    with pytest.raises(RuntimeError, match="boom"):
        sim.run("lockstep", InProcLink(_RaisingController()), episodes=1,
                duration_s=0.3, host=Host(), logger=log)
    assert log.final[0] == "aborted"
    assert "unexpected error" in log.final[1] and "boom" in log.final[1]


# -- M3: a non-uniform background produces full-frame events --------------- #
class _GradientBg:
    """World-fixed azimuth gradient, so panning shifts it across the frame."""

    uniform = False

    def __init__(self, intr):
        self._intr = intr

    def intensity(self, u, v, pan, tilt):
        d = camera.unproject(u, v, pan, tilt, self._intr)
        az, _ = camera.azel_from_direction(d)
        return 0.5 + 0.3 * np.sin(az * 6.0)


def test_nonuniform_background_produces_full_frame_events() -> None:
    cfg = _cfg("static", episode_length_s=0.3)
    cfg.events.noise_rate_hz = 0.0
    sim = Simulator(cfg, 0)
    sim.renderer = Renderer(cfg, background=_GradientBg(cfg.intrinsics()))
    traj = make_trajectory(cfg.target, seeding.trajectory_rng(0, 0), 10 * cfg.loop.period_s)
    noise = seeding.noise_rng(0, 0)
    sim.events.reset_episode(sim.renderer.render_full(0.0, 0.0, *traj.az_el(0.0)))
    sim.plant.apply_command(0.5, 0.0)  # pan, so the world-fixed gradient shifts
    last = None
    for k in range(6):
        last, _ = sim._period(k, traj, noise)
    assert last is not None and last.size > 2000  # background events, not a target ROI
    assert int(last["x"].max()) - int(last["x"].min()) > 200  # spanning the frame width


# -- M4: episode boundary — the late last reply is waited for (R7.3, R14.1) - #
def test_episode_boundary_waits_for_late_last_reply(monkeypatch) -> None:
    monkeypatch.setattr(simmod, "_sleep_until_ns", lambda ns: None)
    cfg = _cfg("static", episode_length_s=0.05)  # 5 periods, last k = 4

    def plan(e, k):
        return None if (e == 0 and k == 4) else (0.0, 0.0, 0)  # miss episode 0's last OBS

    link = ScriptLink(plan)
    res, _, _ = _run_link(cfg, "realtime", link, episodes=2, duration=0.05)
    assert res.status == "completed"
    assert link.waited == [(0, 4)]  # waited for the outstanding reply before BYE
    assert link.byes == [0, 1]


def test_episode_boundary_late_reply_over_tcp_completes(server_factory) -> None:
    # A controller that misses the deadline on episode 0's last OBS: the
    # simulator must collect that reply before BYE, or it collides with
    # episode 1's handshake and the run aborts (R7.3, R14.1).
    class _SlowLast:
        def __init__(self):
            self.episode = None

        def reset(self, hello):
            self.episode = hello.episode
            return "hold"

        def step(self, obs):
            if self.episode == 0 and obs.k == 4:
                time.sleep(0.08)  # past the 5 ms deadline
            return 0.0, 0.0

    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: _SlowLast(), meta, once=True)
    cfg = _cfg("static", episode_length_s=0.05)  # 5 periods, last k = 4
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    res, log, _ = _run_link_tcp(cfg, "realtime", link, episodes=2, duration=0.05)
    assert res.status == "completed"


def test_episode_boundary_stale_cmd_during_next_episode_aborts() -> None:
    # A CMD for episode 0 that arrives after episode 1 has started is malformed
    # and aborts the run (R8.5, R14.1). A raw server injects it.
    import socket

    ready: "queue_mod.Queue[int]" = queue_mod.Queue()
    stop = threading.Event()

    def raw_server():
        srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        ready.put(srv.getsockname()[1])
        conn, _ = srv.accept()
        meta = provenance.controller_metadata("hold", {})
        try:
            while not stop.is_set():
                msg = protocol.read_message(conn)
                if isinstance(msg, protocol.Hello):
                    protocol.send_message(conn, protocol.HelloAck("hold", meta))
                    current = msg.episode
                elif isinstance(msg, protocol.Obs):
                    if current == 1:
                        # stale episode-0 CMD during episode 1
                        protocol.send_message(conn, protocol.Cmd(0, msg.k, 0.0, 0.0, 0, 1, 2))
                    else:
                        protocol.send_message(conn, protocol.Cmd(msg.episode, msg.k, 0.0, 0.0, 0, 1, 2))
                elif isinstance(msg, protocol.Bye):
                    continue
        except Exception:
            pass
        finally:
            conn.close()
            srv.close()

    th = threading.Thread(target=raw_server, daemon=True)
    th.start()
    port = ready.get(timeout=5)
    cfg = _cfg("static", episode_length_s=0.05)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    res, _, _ = _run_link_tcp(cfg, "lockstep", link, episodes=2, duration=0.05)
    stop.set()
    th.join(timeout=5)
    assert res.status == "aborted" and "episode" in (res.reason or "")


def _run_link_tcp(cfg, mode, link, *, episodes=1, duration=0.05):
    sim = Simulator(cfg, 0)
    log = MemLogger()
    res = sim.run(mode, link, episodes=episodes, duration_s=duration, host=Host(), logger=log)
    return res, log, sim


# -- R8.9 invalid command: the setpoint is held for that period ------------ #
class _CommandThenNaN:
    def __init__(self, bad_k):
        self.bad_k = bad_k

    def reset(self, hello):
        return "hold"

    def step(self, obs):
        if obs.k == self.bad_k:
            return float("nan"), 0.3
        return 0.3, 0.3


def test_invalid_command_holds_setpoint() -> None:
    cfg = _cfg("static", episode_length_s=0.3)
    _, log, _ = _run_link(cfg, "lockstep", InProcLink(_CommandThenNaN(10)), duration=0.3)
    bad = log.rows[10]
    assert bad["cmd_invalid"] == 1 and bad["miss"] == 0
    # the NaN pan held the previous setpoint, so pan_sp stays finite near 0.3.
    assert np.isfinite(bad["pan_sp"]) and bad["pan_sp"] == pytest.approx(0.3, abs=1e-6)
