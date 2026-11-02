"""Controller A (spec_ctl_a.md): geometry, servo model, tracker, filter, loop.

The controller module imports nothing from the simulator side (R1.3); these
tests do, to check it against camera.py and plant.py.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from jn_sim import camera
from jn_sim import classical as cl
from jn_sim.config import Intrinsics, PlantConfig
from jn_sim.plant import Plant

T = 0.01
INTR = Intrinsics(fx=277.12812921, fy=277.12812921, cx=159.5, cy=119.5)
_I = (INTR.fx, INTR.fy, INTR.cx, INTR.cy)


# =========================================================================== #
# T1: geometry (R2)
# =========================================================================== #
_POSES = [(math.radians(p), math.radians(t))
          for p in np.linspace(-60.0, 60.0, 7) for t in np.linspace(-30.0, 30.0, 5)]
_PIXELS = [(u, v) for u in (0.0, 41.3, 159.5, 230.0, 319.0) for v in (0.0, 77.7, 119.5, 239.0)]


def test_pixel_to_direction_matches_camera_unproject() -> None:
    worst_dir = worst_azel = 0.0
    for pan, tilt in _POSES:
        for u, v in _PIXELS:
            ref = camera.unproject(u, v, pan, tilt, INTR)
            got = np.array(cl.pixel_to_dir(u, v, pan, tilt, *_I))
            # angle between the two unit vectors, robust near 0
            worst_dir = max(worst_dir, float(np.linalg.norm(got - ref)))
            az_ref, el_ref = camera.azel_from_direction(ref)
            az, el = cl.pixel_to_azel(u, v, pan, tilt, *_I)
            worst_azel = max(worst_azel, abs(az - float(az_ref)), abs(el - float(el_ref)))
    assert worst_dir < 1e-9
    assert worst_azel < 1e-9


def test_direction_to_pixel_matches_camera_project() -> None:
    rng = np.random.default_rng(1)
    worst = 0.0
    for pan, tilt in _POSES:
        # directions in the field of view at this pose, plus a few random ones
        dirs = [cl.pixel_to_azel(u, v, pan, tilt, *_I) for u, v in _PIXELS]
        dirs += [(pan + rng.uniform(-0.4, 0.4), tilt + rng.uniform(-0.3, 0.3)) for _ in range(5)]
        for az, el in dirs:
            ur, vr, front = camera.project_azel(az, el, pan, tilt, INTR)
            u, v, ok = cl.azel_to_pixel(az, el, pan, tilt, *_I)
            assert ok == bool(front)
            worst = max(worst, abs(u - float(ur)), abs(v - float(vr)))
    assert worst < 1e-6


def test_pixel_round_trip_and_behind_camera() -> None:
    az, el = cl.pixel_to_azel(250.0, 30.0, 0.3, -0.2, *_I)
    u, v, ok = cl.azel_to_pixel(az, el, 0.3, -0.2, *_I)
    assert ok and u == pytest.approx(250.0, abs=1e-9) and v == pytest.approx(30.0, abs=1e-9)
    u, v, ok = cl.azel_to_pixel(math.pi, 0.0, 0.0, 0.0, *_I)  # straight behind
    assert not ok and math.isnan(u) and math.isnan(v)


def test_sign_conventions() -> None:
    # A target right of the image centre is at negative relative azimuth, one
    # below it at negative relative elevation (sim R3.4).
    az, el = cl.pixel_to_azel(INTR.cx + 50.0, INTR.cy + 30.0, 0.0, 0.0, *_I)
    assert az < 0.0 and el < 0.0


# =========================================================================== #
# T1: servo model (R3)
# =========================================================================== #
def _plant_poses(cmds: np.ndarray, **over) -> np.ndarray:
    """Pose of the simulator's plant at (k + 1) T, driven like the loop drives it:
    advance period k, then apply CMD_k at (k + 1) T (sim R5.3)."""
    cfg = PlantConfig()
    for key, val in over.items():
        setattr(cfg, key, val)
    plant = Plant(cfg)
    n_phys = round(T / cfg.dt_phys_s)
    out = np.empty((len(cmds), 2))
    for k, (pan, tilt) in enumerate(cmds):
        angles, _ = plant.advance(n_phys)
        out[k] = angles[-1]
        plant.apply_command(pan, tilt)
    return out


def _model_poses(cmds: np.ndarray, wn=25.0, zeta=0.8, d=1) -> np.ndarray:
    model = cl.ServoModel(wn, zeta, T, d)
    model.reset(0.0, 0.0)
    out = np.empty((len(cmds), 2))
    for k, (pan, tilt) in enumerate(cmds):
        model.advance()
        out[k] = model.pose
        model.command(pan, tilt)
    return out


def test_dead_time_command_first_moves_model_at_k_plus_2() -> None:
    # A setpoint change in CMD_k is active from (k + 2) T (R3.1, sim R5.3): the
    # model's pose is unchanged up to and including (k + 2) T and moves after.
    k = 7
    base = np.zeros((20, 2))
    step = base.copy()
    step[k:] = (0.2, -0.1)
    pb, ps = _model_poses(base), _model_poses(step)
    # row j is the pose at (j + 1) T, so (k + 2) T is row k + 1
    assert np.array_equal(pb[: k + 2], ps[: k + 2])
    assert abs(ps[k + 2, 0]) > 1e-4 and abs(ps[k + 2, 1]) > 1e-4

    # The interpolated pose just after (k + 2) T has started to move.
    model = cl.ServoModel(25.0, 0.8, T, 1)
    model.reset(0.0, 0.0)
    for j in range(k + 3):
        model.advance()  # pose now covers [jT, (j + 1) T]
        if j == k + 2:
            assert model.pose_at((k + 2) * T) == pytest.approx((0.0, 0.0), abs=1e-15)
            assert model.pose_at((k + 2.5) * T)[0] > 0.0
        model.command(*step[j])

    # The plant agrees: CMD_k first moves it right after (k + 2) T.
    pp = _plant_poses(step)
    assert np.all(pp[: k + 2] == 0.0) and abs(pp[k + 2, 0]) > 1e-4


def test_dead_time_follows_model_dead_periods() -> None:
    k = 4
    step = np.zeros((15, 2))
    step[k:] = (0.2, 0.0)
    for d in (0, 1, 3):
        p = _model_poses(step, d=d)
        assert np.all(p[: k + 1 + d, 0] == 0.0)  # pose at (k + 1 + d) T unchanged
        assert p[k + 1 + d, 0] > 1e-4  # moved by (k + 2 + d) T


def test_model_discretisation_is_exact() -> None:
    # The ZOH step response at a boundary equals the continuous closed form.
    wn, zeta, amp = 25.0, 0.8, 0.1
    cmds = np.full((40, 2), amp)
    p = _model_poses(cmds, d=0)  # CMD_0 active from T; row j is the pose at (j+1)T
    wd = wn * math.sqrt(1 - zeta**2)
    phi = math.acos(zeta)
    for j in range(1, 40):
        tau = j * T  # time since the setpoint became active
        exact = amp * (1 - math.exp(-zeta * wn * tau) * math.sin(wd * tau + phi) / math.sqrt(1 - zeta**2))
        assert p[j, 0] == pytest.approx(exact, abs=1e-12)


def _ramp(rate_deg_s: float, n: int) -> np.ndarray:
    t = np.arange(n) * T
    r = np.radians(rate_deg_s) * t
    return np.stack([r, -r], axis=1)


def test_model_matches_plant_ramp() -> None:
    cmds = _ramp(23.6, 150)  # 1.5 s, 35 deg: inside the tilt limit of 45 deg
    err = np.degrees(np.abs(_model_poses(cmds) - _plant_poses(cmds))).max()
    assert err < 0.05


def test_model_matches_plant_sine() -> None:
    t = np.arange(800) * T
    cmds = np.stack([np.radians(15.0) * np.sin(2 * math.pi * 0.25 * t),
                     np.radians(8.0) * np.sin(2 * math.pi * 0.35 * t)], axis=1)
    err = np.degrees(np.abs(_model_poses(cmds) - _plant_poses(cmds))).max()
    assert err < 0.05


def test_model_matches_plant_20deg_step() -> None:
    cmds = np.zeros((200, 2))
    cmds[10:] = (math.radians(20.0), math.radians(-20.0))
    err = np.degrees(np.abs(_model_poses(cmds) - _plant_poses(cmds))).max()
    assert err < 0.25


# =========================================================================== #
# T2: event-cluster tracker (R4), on synthetic batches
# =========================================================================== #
from jn_sim.protocol import EVENT_DTYPE  # noqa: E402

W, H = 320, 240
R_DISC = 7.3  # the target's radius in px (1.5 deg)


def _events(x, y, p, t) -> np.ndarray:
    ev = np.zeros(len(x), dtype=EVENT_DTYPE)
    ev["x"], ev["y"], ev["p"], ev["t"] = x, y, p, t
    return ev


def _noise(rng, n=77, t0_us=0, t1_us=10_000) -> np.ndarray:
    """Shot noise: uniform over the frame and the period, random polarity."""
    return _events(rng.integers(0, W, n), rng.integers(0, H, n),
                   rng.integers(0, 2, n), rng.integers(t0_us, t1_us, n))


def _merge(*batches) -> np.ndarray:
    ev = np.concatenate(batches)
    return ev[np.argsort(ev["t"], kind="stable")]


def _moving_disc(c0, c1, t0_us=0, t1_us=10_000, n_sub=20, theta=0.12, gain=1.0) -> np.ndarray:
    """Edge events of a bright disc moving from c0 to c1 over the period.

    A small DVS model, independent of the simulator's: a disc of intensity 1.0
    on 0.25 with a 1 px linear edge, log intensity, one event per threshold
    ``theta`` crossed, timestamps at the sub-step's middle. ``gain`` < 1 thins
    the events out (every other one, and so on).
    """
    lo_u = int(min(c0[0], c1[0]) - R_DISC - 3)
    hi_u = int(max(c0[0], c1[0]) + R_DISC + 4)
    lo_v = int(min(c0[1], c1[1]) - R_DISC - 3)
    hi_v = int(max(c0[1], c1[1]) + R_DISC + 4)
    uu, vv = np.meshgrid(np.arange(lo_u, hi_u), np.arange(lo_v, hi_v))
    uu, vv = uu.ravel(), vv.ravel()

    def log_i(f):
        cu = c0[0] + f * (c1[0] - c0[0])
        cv = c0[1] + f * (c1[1] - c0[1])
        cov = np.clip(R_DISC + 0.5 - np.hypot(uu - cu, vv - cv), 0.0, 1.0)
        return np.log(0.25 + 0.75 * cov + 1e-3)

    ref = log_i(0.0)
    xs, ys, ps, ts = [], [], [], []
    for j in range(1, n_sub + 1):
        k = np.trunc((log_i(j / n_sub) - ref) / theta).astype(int)
        ref = ref + k * theta
        idx = np.repeat(np.arange(uu.size), np.abs(k))
        xs.append(uu[idx]); ys.append(vv[idx])
        ps.append((k[idx] > 0).astype(int))
        ts.append(np.full(idx.size, int(t0_us + (t1_us - t0_us) * (j - 0.5) / n_sub)))
    ev = _events(np.concatenate(xs), np.concatenate(ys), np.concatenate(ps), np.concatenate(ts))
    if gain < 1.0:
        ev = ev[:: int(round(1.0 / gain))]
    return ev


def _disc_flash(c, pol, t_us=5_000) -> np.ndarray:
    """Every pixel of a disc at c changes at once: the target appearing (ON) or
    leaving (OFF) in a jump."""
    uu, vv = np.meshgrid(np.arange(W), np.arange(H))
    m = np.hypot(uu - c[0], vv - c[1]) <= R_DISC
    n = int(m.sum())
    return _events(uu[m], vv[m], np.full(n, pol), np.full(n, t_us))


def _tracker(**over) -> cl.ClusterTracker:
    kw = dict(cell=16, n_acq=20, r_win=12.0, ms_iter=3, n_meas=15, r_gate=24.0)
    kw.update(over)
    return cl.ClusterTracker(W, H, **kw)


def test_noise_only_never_acquires() -> None:
    rng = np.random.default_rng(0)
    trk = _tracker()
    worst = 0
    for _ in range(300):
        trk.load(_noise(rng))
        worst = max(worst, trk.block_n)
        assert trk.block_seed() is None
        assert trk.acquire() is None
    assert worst < 20  # n_acq is far above what noise reaches (R4.2)


def test_moving_disc_centre_within_1px_of_mid_period_position() -> None:
    rng = np.random.default_rng(1)
    trk = _tracker()
    for c0, c1 in [((100.0, 80.0), (102.0, 81.0)), ((231.4, 170.2), (228.9, 168.0)),
                   ((40.0, 200.0), (40.6, 199.1))]:
        mid = ((c0[0] + c1[0]) / 2, (c0[1] + c1[1]) / 2)
        for _ in range(5):
            trk.load(_merge(_moving_disc(c0, c1), _noise(rng)))
            c = trk.acquire()  # ON-grid seed, then mean-shift (R4.2, R4.3)
            assert c is not None
            assert math.hypot(c.u - mid[0], c.v - mid[1]) < 1.0
            assert 4_000 < c.t_us < 6_000  # mean timestamp near mid-period
            # The same from a gate seed a few px off (R4.4).
            meas, jump, _ = trk.gate(mid[0] + 6.0, mid[1] - 4.0)
            assert jump is None and meas is not None
            assert math.hypot(meas.u - mid[0], meas.v - mid[1]) < 1.0


def test_jump_fires_and_seed_is_at_new_position() -> None:
    rng = np.random.default_rng(2)
    trk = _tracker()
    old, new = (120.0, 100.0), (215.0, 140.0)
    trk.load(_merge(_disc_flash(old, 0), _disc_flash(new, 1), _noise(rng)))
    meas, jump, at_gate = trk.gate(*old)  # the gate still at the old position
    assert at_gate.n_on < trk.block_n  # the old window holds OFF events only
    seed = trk.block_seed()
    assert math.hypot(seed[0] - new[0], seed[1] - new[1]) < 1.0
    assert jump is not None  # R4.5 fired
    assert math.hypot(jump.u - new[0], jump.v - new[1]) < 1.0


def test_no_jump_when_gate_window_holds_more_on_events() -> None:
    # A weaker ON blob far away doesn't pull a healthy track (R4.5).
    rng = np.random.default_rng(3)
    trk = _tracker()
    tracked = _moving_disc((100.0, 100.0), (103.0, 101.0))
    blob = _disc_flash((250.0, 60.0), 1)[:40]  # 40 ON events, above n_acq
    trk.load(_merge(tracked, blob, _noise(rng)))
    meas, jump, c = trk.gate(101.5, 100.5)
    assert c.n_on > 40 and jump is None and meas is not None


@pytest.mark.parametrize("speed", [1.0, 2.0, 4.0, 8.0, 12.0, 20.0])
@pytest.mark.parametrize("direction", [(1.0, 0.0), (-0.6, 0.8)])
def test_no_jump_on_smooth_motion_with_lagging_prediction(speed, direction) -> None:
    # One disc moving `speed` px per period, the gate seed 19 px behind its
    # mid-period position: the target's own leading edge makes a strong ON
    # block more than r_gate from the seed, but mean-shift from it converges
    # on the same disc as the gate's, so R4.5 must not fire (review S1).
    rng = np.random.default_rng(int(speed * 10))
    trk = _tracker()
    dx, dy = direction
    c0 = (150.0 - dx * speed / 2, 120.0 - dy * speed / 2)
    c1 = (150.0 + dx * speed / 2, 120.0 + dy * speed / 2)
    seed = (150.0 - 19.0 * dx, 120.0 - 19.0 * dy)
    trk.load(_merge(_moving_disc(c0, c1), _noise(rng)))
    meas, jump, at_gate = trk.gate(*seed)
    assert jump is None
    assert meas is not None and meas.n >= 15


def test_too_few_events_in_gate_is_no_measurement() -> None:
    rng = np.random.default_rng(4)
    trk = _tracker()
    few = _events(np.full(10, 150), np.full(10, 110), np.ones(10, int), np.full(10, 5000))
    trk.load(_merge(few, _noise(rng)))
    meas, jump, c = trk.gate(150.0, 110.0)
    assert c.n < 15 and meas is None and jump is None
    # Enough events, but the cluster centre lies outside r_gate of the seed.
    trk = _tracker(r_gate=8.0)
    many = _events(np.full(30, 150), np.full(30, 110), np.ones(30, int), np.full(30, 5000))
    trk.load(many)
    meas, _, c = trk.gate(150.0 - 11.0, 110.0)  # inside r_win, outside r_gate
    assert c.n == 30 and c.u == pytest.approx(150.0) and meas is None


def test_empty_batch() -> None:
    trk = _tracker()
    trk.load(np.zeros(0, dtype=EVENT_DTYPE))
    assert trk.block_n == 0 and trk.acquire() is None
    meas, jump, c = trk.gate(160.0, 120.0)
    assert meas is None and jump is None and c.n == 0


# =========================================================================== #
# T3: filter, track states, command law, registration (R1, R5, R6)
# =========================================================================== #
from jn_sim import testctl  # noqa: E402
from jn_sim.host import Host  # noqa: E402
from jn_sim.link import InProcLink  # noqa: E402
from jn_sim.protocol import Hello, Obs  # noqa: E402
from jn_sim.runlog import summarise  # noqa: E402
from jn_sim.sim import Simulator  # noqa: E402

from test_sim import MemLogger, _cfg  # noqa: E402


def _hello(episode: int = 0) -> Hello:
    return Hello(episode, W, H, 10_000, INTR.fx, INTR.fy, INTR.cx, INTR.cy, 0.0, 0.0, 1)


def _ctl(**params) -> cl.ClassicalController:
    c = cl.ClassicalController(params)
    assert c.reset(_hello()) == "classical"
    return c


def test_filter_converges_on_constant_velocity_target() -> None:
    # Measurements of a target moving at constant angular rate, fed through the
    # controller's own init/update path (R5.1, R5.2, R5.4). The model pose stays
    # at rest, so the cluster pixel is the target's projection at pose 0.
    c = _ctl()
    v_true = (math.radians(12.0), math.radians(-7.0))
    a0 = (math.radians(-6.0), math.radians(4.0))
    for k in range(100):
        t = (k + 0.5) * T
        az, el = a0[0] + v_true[0] * t, a0[1] + v_true[1] * t
        u, v, _ = cl.azel_to_pixel(az, el, 0.0, 0.0, *_I)
        cluster = cl.Cluster(u, v, 200, t * 1e6, 100)
        if k == 0:
            c._init_track(cluster)
            assert c.kf_x[0, 1] == 0.0 and c.kf_x[1, 1] == 0.0  # rate 0 (R5.4)
        else:
            c._update_track(cluster)
        if t >= 0.5:
            rate_err = np.degrees(np.abs(c.kf_x[:, 1] - v_true))
            assert rate_err.max() < 1.0, (k, rate_err)
    assert np.degrees(abs(c.kf_x[0, 0] - (a0[0] + v_true[0] * c.kf_t))) < 0.01


def test_kalman_steps_match_matrix_form() -> None:
    x, v, p00, p01, p11 = 0.1, 0.3, 2e-5, 1e-6, 0.2
    dt, q, r, z = 0.013, 0.25, 1.3e-5, 0.105
    F = np.array([[1, dt], [0, 1]])
    Q = q * np.array([[dt**3 / 3, dt**2 / 2], [dt**2 / 2, dt]])
    P = np.array([[p00, p01], [p01, p11]])
    xs = F @ np.array([x, v])
    P = F @ P @ F.T + Q
    K = P[:, 0] / (P[0, 0] + r)
    xs = xs + K * (z - xs[0])
    P = P - np.outer(K, P[0])
    got = cl.kf_update(*cl.kf_predict(x, v, p00, p01, p11, dt, q), z, r)
    assert np.allclose(got, [xs[0], xs[1], P[0, 0], P[0, 1], P[1, 1]], rtol=1e-12, atol=1e-15)


def _run_ctl(controller, trajectory="sine", duration=3.0, seed=0, episodes=1, **cfg_over):
    cfg = _cfg(trajectory)
    for dotted, val in cfg_over.items():
        section, key = dotted.split("__")
        setattr(getattr(cfg, section), key, val)
    log = MemLogger()
    Simulator(cfg, seed).run("lockstep", InProcLink(controller), episodes=episodes,
                             duration_s=duration, host=Host(), logger=log)
    return cfg, log


def _summary(cfg, log) -> dict:
    return summarise(log.rows, period_s=cfg.loop.period_s, warmup_s=cfg.run.warmup_s,
                     success_in_fov=cfg.run.success_in_fov, fx=cfg.intrinsics().fx)["overall"]


class _Spy:
    """Wraps a controller and records its state after every step."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.params = inner.params
        self.trace: list[dict] = []

    def reset(self, hello):
        return self.inner.reset(hello)

    def step(self, obs):
        out = self.inner.step(obs)
        c = self.inner
        self.trace.append({"k": obs.k, "state": c.state, "cmd": tuple(out),
                           "pid_i": c.pid_i.copy(), "ki": c.params["ki"]})
        return out


def test_anti_windup_while_clamped() -> None:
    # Pan limited to 4 deg against a 15 deg sine: the setpoint sits on the
    # clamp for long stretches with a large image error (R6.2, R6.3).
    spy = _Spy(cl.ClassicalController({"pan_lim_deg": 4.0}))
    cfg, log = _run_ctl(spy, "sine", duration=4.0)
    lim, i_max = cl.f32_bound(math.radians(4.0)), math.radians(2.0)
    assert lim <= math.radians(4.0) and spy.inner.lim[0] == lim
    clamped = 0
    for prev, cur in zip(spy.trace, spy.trace[1:]):
        assert abs(cur["ki"] * cur["pid_i"][0]) <= i_max + 1e-15
        if abs(cur["cmd"][0]) == lim:
            clamped += 1
            assert cur["pid_i"][0] == prev["pid_i"][0]  # frozen while clamped
    assert clamped > 50
    assert all(r["cmd_clamped"] == 0 for r in log.rows)  # A's own clamp acts first


def test_integral_bounded_by_i_max() -> None:
    # A persistent image error, no clamp: |ki * integral| saturates at i_max.
    c = _ctl(ki=5.0)
    u, v, _ = cl.azel_to_pixel(math.radians(3.0), 0.0, 0.0, 0.0, *_I)
    c._init_track(cl.Cluster(u, v, 200, 5_000.0, 100))
    for k in range(300):
        c._command(k, cl.Cluster(u, v, 200, (k + 0.5) * 1e4, 100))
    assert abs(5.0 * c.pid_i[0]) == pytest.approx(math.radians(2.0))


def _record_obs(trajectory="sine", duration=2.0, seed=0):
    """OBS of a closed-loop run of A, as A received them."""
    seen: list[Obs] = []

    class _Rec(_Spy):
        def step(self, obs):
            seen.append(obs)
            return self.inner.step(obs)

    _run_ctl(_Rec(cl.ClassicalController()), trajectory, duration=duration, seed=seed)
    return seen


def test_reset_restores_initial_state_and_replay_is_identical() -> None:
    obs = _record_obs("step", duration=4.0)  # includes a jump at 3 s
    fresh = _ctl()
    initial = {k: (v.copy() if isinstance(v, np.ndarray) else v)
               for k, v in vars(fresh).items() if not k.startswith("_")
               and isinstance(v, (np.ndarray, int, float))}
    c = _ctl()
    first = [c.step(o) for o in obs]
    assert c.n_inits >= 1
    c.reset(_hello(1))
    for key, val in initial.items():
        got = getattr(c, key)
        assert np.array_equal(got, val, equal_nan=True) if isinstance(val, np.ndarray) else got == val, key
    second = [c.step(o) for o in obs]
    assert first == second  # same OBS sequence, same commands (R1.5)


def test_two_episodes_one_instance_identical_commands() -> None:
    # The in-process link keeps one instance across episodes (R1.5). With shot
    # noise off, both episodes see the same scene, so they must command alike.
    cfg, log = _run_ctl(cl.ClassicalController(), "sine", duration=1.5, episodes=2,
                        events__noise_rate_hz=0.0)
    ep = [[(r["cmd_pan"], r["cmd_tilt"]) for r in log.rows if r["episode"] == e] for e in (0, 1)]
    assert len(ep[0]) == 150 and ep[0] == ep[1]


def _obs(k: int, *batches) -> Obs:
    ev = _merge(*batches) if batches else np.zeros(0, dtype=EVENT_DTYPE)
    return Obs(0, k, k * 10_000, (k + 1) * 10_000, ev)


def _gate_seed(c: cl.ClassicalController, k: int) -> tuple[float, float]:
    """Where step(OBS_k) will put the gate seed (R4.4), from a copy."""
    import copy

    cc = copy.deepcopy(c)
    cc.model.advance()
    t_mid = (k + 0.5) * T
    su, sv, front = cl.azel_to_pixel(*cc._predict(t_mid), *cc.model.pose_at(t_mid), *_I)
    assert front
    return su, sv


def _establish_track(c: cl.ClassicalController, n: int = 6) -> int:
    """Acquire and track a disc moving 2 px per period; returns the next k."""
    rng = np.random.default_rng(7)
    for k in range(n):
        c0, c1 = (110.0 + 2 * k, 100.0 + k), (112.0 + 2 * k, 101.0 + k)
        c.step(_obs(k, _moving_disc(c0, c1, k * 10_000, (k + 1) * 10_000), _noise(rng, 77, k * 10_000, (k + 1) * 10_000)))
    assert c.state == cl.TRACK and c.n_inits == 1
    return n


def test_jump_reacquires_through_step() -> None:
    # Review C1: after a track is established, OFF events at the old position
    # (a valid gated measurement) and ON events at a distant new one: step()
    # re-acquires at the new position (R4.5, R5.4) with rates 0, the
    # covariance reset and the PID cleared, then the same-period PID update
    # (R6.2). The mutant `if jump is not None:` -> `if False:` fails this test.
    c = _ctl()
    k = _establish_track(c)
    assert np.all(c.kf_x[:, 1] != 0.0) and np.all(c.pid_i != 0.0) and c.pid_k == k - 1

    old = _gate_seed(c, k)
    new = (old[0] + 80.0, old[1] + 50.0)
    t_flash = k * 10_000 + 5_000
    ev = _merge(_disc_flash(old, 0, t_flash), _disc_flash(new, 1, t_flash))

    # The tracker alone: the old OFF cluster is a valid gated measurement,
    # and the jump check fires too.
    import copy

    probe = copy.deepcopy(c.tracker)
    probe.load(ev)
    meas, jump, _ = probe.gate(*old)
    assert meas is not None and math.hypot(meas.u - old[0], meas.v - old[1]) < 1.0
    assert jump is not None

    c.step(_obs(k, ev))
    assert c.n_jumps == 1 and c.n_inits == 2 and c.state == cl.TRACK
    u, v, n, t = c.meas
    assert math.hypot(u - new[0], v - new[1]) < 1.0 and n >= 15
    assert t == pytest.approx(t_flash * 1e-6)
    # Filter re-initialised at the new position (R5.4).
    az, el = cl.pixel_to_azel(u, v, *c.model.pose_at(t), *_I)
    assert c.kf_x.tolist() == [[az, 0.0], [el, 0.0]]
    v0 = math.radians(30.0) ** 2
    assert c.kf_P.tolist() == [[c.r_meas[0], 0.0, v0], [c.r_meas[1], 0.0, v0]]
    assert c.kf_t == t
    # PID cleared, then this period's update: e*T, no derivative (R6.2).
    e = np.array([-math.atan((u - INTR.cx) / INTR.fx), -math.atan((v - INTR.cy) / INTR.fy)])
    p = c.params
    assert np.allclose(c.pid_i, e * T, rtol=0, atol=1e-15)
    assert np.allclose(c.pid_e, e, rtol=0, atol=1e-15)
    assert c.pid_k == k
    assert np.allclose(c.pid_u, p["kp"] * e + p["ki"] * e * T, rtol=0, atol=1e-15)


def test_pid_time_base_with_kd_and_a_gap() -> None:
    # R6.2 (review S2): with a measurement gap, the derivative divides by the
    # periods since the last measured one, (k - k_prev) T, not by the gap
    # between the clusters' timestamps; the integral adds e*T per measured
    # period.
    kd = 0.02
    c = _ctl(kd=kd)
    a = (170.0, 110.0)
    c.step(_obs(0, _disc_flash(a, 1, 2_000)))  # acquire at k = 0, t = 2 ms
    assert c.state == cl.TRACK and c.pid_k == 0
    e0 = c.pid_e.copy()
    assert np.allclose(c.pid_i, e0 * T, rtol=0, atol=1e-15)  # init period: e*T ...
    p = c.params
    assert np.allclose(c.pid_u, p["kp"] * e0 + p["ki"] * e0 * T, rtol=0, atol=1e-15)  # ... no kd term
    for k in (1, 2):  # no events: COAST, PID held
        c.step(_obs(k))
        assert c.state == cl.COAST and c.pid_k == 0
    b = _gate_seed(c, 3)
    b = (b[0] + 3.0, b[1] - 2.0)
    c.step(_obs(3, _disc_flash(b, 1, 34_000)))  # measured at k = 3, t = 34 ms
    assert c.state == cl.TRACK and c.n_inits == 1 and c.pid_k == 3
    e3 = c.pid_e.copy()
    de = (e3 - e0) / (3 * T)  # 30 ms of periods, not the clusters' 32 ms
    integ = (e0 + e3) * T
    assert np.allclose(c.pid_i, integ, rtol=0, atol=1e-15)
    assert np.allclose(c.pid_u, p["kp"] * e3 + p["ki"] * integ + kd * de, rtol=0, atol=1e-13)
    wrong = (e3 - e0) / 0.032
    assert not np.allclose(c.pid_u, p["kp"] * e3 + p["ki"] * integ + kd * wrong, rtol=0, atol=1e-6)


def test_coast_expiry_returns_to_acquire_with_rates_zero() -> None:
    c = _ctl()
    k = _establish_track(c)
    assert np.all(c.kf_x[:, 1] != 0.0)
    cmax = c.params["coast_max"]
    rng = np.random.default_rng(11)
    for i in range(1, cmax + 3):
        before = c.cmd.tolist()
        out = c.step(_obs(k, _noise(rng, 77, k * 10_000, (k + 1) * 10_000)))
        if i < cmax:
            assert c.state == cl.COAST and c.coast_n == i
        else:
            assert c.state == cl.ACQUIRE  # after coast_max periods (R5.3)
            assert c.kf_x[0, 1] == 0.0 and c.kf_x[1, 1] == 0.0
            assert list(out) == before  # ACQUIRE holds the last setpoint
        k += 1


def test_behind_camera_prediction_runs_acquisition() -> None:
    # R4.4 (revised): a prediction that doesn't project runs acquisition; a
    # seed re-acquires, no seed means COAST.
    c = _ctl()
    k = _establish_track(c)
    c.kf_x[0] = (math.pi, 0.0)  # straight behind the camera
    c.step(_obs(k, _noise(np.random.default_rng(3), 77, k * 10_000, (k + 1) * 10_000)))
    assert c.state == cl.COAST and c.n_inits == 1
    c.kf_x[0] = (math.pi, 0.0)
    target = (200.0, 90.0)
    c.step(_obs(k + 1, _disc_flash(target, 1, (k + 1) * 10_000 + 5_000)))
    assert c.state == cl.TRACK and c.n_inits == 2
    assert math.hypot(c.meas[0] - target[0], c.meas[1] - target[1]) < 1.0
    assert abs(c.kf_x[0, 0]) < 1.0  # re-initialised in front of the camera


def test_f32_bound() -> None:
    for lim in (math.radians(90.0), math.radians(45.0), math.radians(4.0), 0.1, 1.0, 2.0):
        b = cl.f32_bound(lim)
        assert b <= lim and float(np.float32(b)) == b
        assert float(np.nextafter(np.float32(b), np.float32(10.0))) > lim


@pytest.mark.parametrize("sign", [(1, 1), (1, -1), (-1, 1), (-1, -1)])
def test_default_clamp_survives_protocol_and_plant(sign) -> None:
    # Review C3, R6.3: a saturated command in each direction, through the
    # float32 wire and the simulator's validation, doesn't set cmd_clamped.
    from jn_sim.protocol import Cmd, decode_message, encode_message

    c = _ctl()
    _establish_track(c)
    c.kf_x[:, 1] = 0.0
    c.kf_x[:, 0] = (2.0 * sign[0], 1.2 * sign[1])  # beyond +-90 / +-45 deg
    pan, tilt = c._command(6, None)
    assert abs(pan) == cl.f32_bound(math.radians(90.0))
    assert abs(tilt) == cl.f32_bound(math.radians(45.0))
    cmd = decode_message(encode_message(Cmd(0, 6, pan, tilt, 0, 0, 0)))
    assert (cmd.pan, cmd.tilt) == (pan, tilt)  # exact in float32
    assert abs(math.degrees(cmd.pan)) <= 90.0 and abs(math.degrees(cmd.tilt)) <= 45.0
    _, invalid, clamped = Plant(PlantConfig()).apply_command(cmd.pan, cmd.tilt)
    assert not invalid and not clamped


def test_fault_sites_are_named_float64_arrays() -> None:
    c = _ctl()
    for name, shape in (("meas", (4,)), ("kf_x", (2, 2)), ("kf_P", (2, 3)),
                        ("pid_i", (2,)), ("cmd", (2,))):
        arr = getattr(c, name)
        assert isinstance(arr, np.ndarray) and arr.dtype == np.float64 and arr.shape == shape


def test_unknown_parameter_rejected() -> None:
    with pytest.raises(ValueError, match="unknown parameter"):
        testctl.make_controller("classical", {"kpp": 0.2})


@pytest.mark.parametrize("bad", [{"cell": 0}, {"n_meas": 2.5}, {"q": -1.0}, {"kp": "x"},
                                 {"r_gate": float("nan")}, {"ms_iter": True}])
def test_bad_parameter_values_rejected(bad) -> None:
    with pytest.raises(ValueError):
        cl.ClassicalController(bad)


def test_params_lists_every_effective_parameter() -> None:
    c = testctl.make_controller("classical", {"kp": 0.25, "n_meas": 12.0})
    assert set(c.params) == set(cl.DEFAULTS)
    assert c.params["kp"] == 0.25 and c.params["n_meas"] == 12
    assert isinstance(c.params["n_meas"], int) and isinstance(c.params["q"], float)
    assert {k: v for k, v in c.params.items() if k not in ("kp", "n_meas")} == {
        k: v for k, v in cl.DEFAULTS.items() if k not in ("kp", "n_meas")}


def test_unknown_controller_message_lists_classical() -> None:
    with pytest.raises(ValueError, match="classical"):
        testctl.make_controller("kalman")


def test_loop_sine_beats_centroid() -> None:
    # sim R14.1 style: in-process lockstep, 3 s of sine.
    cfg, log_a = _run_ctl(testctl.make_controller("classical"), "sine", duration=3.0)
    _, log_c = _run_ctl(testctl.make_controller("centroid"), "sine", duration=3.0)
    warm = [r for r in log_a.rows if r["t_us"] >= 1_000_000]
    assert warm and all(r["in_fov"] == 1 for r in warm)
    a, c = _summary(cfg, log_a), _summary(cfg, log_c)
    assert a["mission"]["in_fov_fraction"] == 1.0
    assert a["error"]["rms_deg"] < c["error"]["rms_deg"]
    assert a["cmd_clamped"] == 0 and a["cmd_invalid"] == 0


def test_loop_static_does_not_move() -> None:
    # A still target on a still camera gives shot noise only: A never acquires
    # and holds the initial setpoint (R4.2, R8.2 static).
    spy = _Spy(testctl.make_controller("classical"))
    cfg, log = _run_ctl(spy, "static", duration=3.0)
    assert all(s["state"] == cl.ACQUIRE and s["cmd"] == (0.0, 0.0) for s in spy.trace)
    assert _summary(cfg, log)["error"]["max_deg"] <= 0.2
