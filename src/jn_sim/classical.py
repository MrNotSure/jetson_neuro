"""Controller A: event-cluster tracker, Kalman filter and PID (spec_ctl_a.md).

Shared with the Jetson controller: standard library and numpy only, and nothing
from the simulator side (R1.3). A knows only HELLO and its parameters (R1.4).

This module holds, in the order of the spec's tasks:

* geometry (R2): pixel <-> world direction at a gimbal pose, written from the
  conventions of sim R3 (world x forward, y left, z up; pan about z, tilt about
  the panned y axis; u right, v down);
* the camera-pose model (R3): a linear second-order servo per axis, discretised
  exactly (zero-order hold) at the period, with the setpoint dead time of sim
  R5.3. It is the designer's model of the servo ("efference copy"), since OBS
  carries no pan/tilt (sim R8.4);
* the event-cluster tracker (R4): a coarse grid of ON events for acquisition,
  gated mean-shift over all events for tracking, and the jump check;
* the controller (R1, R5, R6): a constant-velocity Kalman filter per axis of
  the target's world angle, the ACQUIRE / TRACK / COAST states, and the
  command: filter feedforward with ramp lead plus a PID on the image error.

Fault sites (R1.5) are named attributes of :class:`ClassicalController`:
``meas`` (the cluster measurement), ``kf_x`` and ``kf_P`` (each axis's filter
state and covariance), ``pid_i`` (each axis's PID integrator) and ``cmd`` (the
last command). All are float64 numpy arrays.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, NamedTuple

import numpy as np

from .protocol import EVENT_DTYPE  # shared module (R1.3)


# --------------------------------------------------------------------------- #
# Geometry (R2)
# --------------------------------------------------------------------------- #
# At pan = tilt = 0 the camera looks along +x, image right is world -y and image
# down is world -z. Tilt rotates forward towards +z about the (base) y axis, then
# pan rotates everything about world +z. The camera axes in world coordinates:
#
#     right   = (sin p, -cos p, 0)
#     down    = (cos p sin t, sin p sin t, -cos t)
#     forward = (cos t cos p, cos t sin p, sin t)
#
# Scalar math throughout: A converts one or two points per period, where the
# math module is several times faster than numpy.


def pixel_to_dir(u, v, pan, tilt, fx, fy, cx, cy):
    """Unit world direction (x, y, z) of pixel (u, v) at pose (pan, tilt) (R2.1)."""
    xc = (u - cx) / fx
    yc = (v - cy) / fy
    cp, sp = math.cos(pan), math.sin(pan)
    ct, st = math.cos(tilt), math.sin(tilt)
    # world = xc * right + yc * down + 1 * forward
    dx = xc * sp + yc * cp * st + ct * cp
    dy = -xc * cp + yc * sp * st + ct * sp
    dz = -yc * ct + st
    norm = math.sqrt(dx * dx + dy * dy + dz * dz)
    return dx / norm, dy / norm, dz / norm


def pixel_to_azel(u, v, pan, tilt, fx, fy, cx, cy):
    """Azimuth and elevation (rad) of pixel (u, v) at pose (pan, tilt) (R2.1)."""
    dx, dy, dz = pixel_to_dir(u, v, pan, tilt, fx, fy, cx, cy)
    return math.atan2(dy, dx), math.atan2(dz, math.hypot(dx, dy))


def azel_to_pixel(az, el, pan, tilt, fx, fy, cx, cy):
    """Pixel (u, v) of world direction (az, el) at pose (pan, tilt) (R2.2).

    Returns ``(u, v, in_front)``; u and v are NaN when the direction is not in
    front of the camera.
    """
    ce = math.cos(el)
    dx, dy, dz = ce * math.cos(az), ce * math.sin(az), math.sin(el)
    cp, sp = math.cos(pan), math.sin(pan)
    ct, st = math.cos(tilt), math.sin(tilt)
    xr = dx * sp - dy * cp  # . right
    yd = (dx * cp + dy * sp) * st - dz * ct  # . down
    zf = (dx * cp + dy * sp) * ct + dz * st  # . forward
    if not zf > 0.0:
        return math.nan, math.nan, False
    return cx + fx * xr / zf, cy + fy * yd / zf, True


# --------------------------------------------------------------------------- #
# Camera-pose model (R3)
# --------------------------------------------------------------------------- #


def _expm(m: np.ndarray) -> np.ndarray:
    """Matrix exponential by scaling and squaring with a Taylor series.

    Only used at reset, for a 3 x 3 matrix, so clarity beats speed. Scaling to an
    infinity norm below 0.5 makes 20 Taylor terms exact to rounding.
    """
    n = m.shape[0]
    norm = float(np.abs(m).sum(axis=1).max())
    s = max(0, int(math.ceil(math.log2(norm / 0.5)))) if norm > 0.5 else 0
    a = m / (2.0**s)
    result = np.eye(n)
    term = np.eye(n)
    for i in range(1, 21):
        term = term @ a / i
        result = result + term
    for _ in range(s):
        result = result @ result
    return result


class ServoModel:
    """Per-axis linear second-order servo, exact ZOH at the period (R3).

    theta'' = wn^2 (sp - theta) - 2 zeta wn theta', the same on both axes. The
    setpoint from CMD_j is active over [(j + 1 + d) T, (j + 2 + d) T) (R3.1).
    The rate limit is ignored (R3.2), the pose between period boundaries is
    interpolated linearly (R3.3), and every recorded command is assumed to have
    been applied, including one that missed its deadline (R3.4).

    Use: at the start of step k call :meth:`advance` (the pose then covers
    [kT, (k + 1)T]), and at its end :meth:`command` with CMD_k.
    """

    def __init__(self, wn: float, zeta: float, period_s: float, dead_periods: int) -> None:
        self.wn = float(wn)
        self.zeta = float(zeta)
        self.period_s = float(period_s)
        self.dead_periods = int(dead_periods)
        a = np.array([[0.0, 1.0, 0.0], [-self.wn**2, -2.0 * self.zeta * self.wn, self.wn**2],
                      [0.0, 0.0, 0.0]])
        e = _expm(a * self.period_s)
        # theta' = a00 theta + a01 omega + b0 sp ; omega' = a10 theta + a11 omega + b1 sp
        self._a00, self._a01, self._b0 = (float(x) for x in e[0])
        self._a10, self._a11, self._b1 = (float(x) for x in e[1])
        self.reset(0.0, 0.0)

    def reset(self, pan0: float, tilt0: float) -> None:
        start = (float(pan0), float(tilt0))
        self.theta = list(start)  # pose at boundary m * T
        self.omega = [0.0, 0.0]
        self.theta_prev = list(start)  # pose at (m - 1) * T
        self.m = 0
        # setpoints of CMD_{m-1-d} ... CMD_{m-1}; the initial pose stands in for
        # the commands before CMD_0.
        self.sp_hist: deque = deque([start] * (self.dead_periods + 1),
                                    maxlen=self.dead_periods + 1)

    def advance(self) -> None:
        """Advance the pose by one period, from m T to (m + 1) T."""
        sp = self.sp_hist[0]  # CMD_{m-1-d}, active over [mT, (m+1)T)
        th, om = self.theta, self.omega
        self.theta_prev = [th[0], th[1]]
        new_th = [0.0, 0.0]
        new_om = [0.0, 0.0]
        for ax in (0, 1):
            new_th[ax] = self._a00 * th[ax] + self._a01 * om[ax] + self._b0 * sp[ax]
            new_om[ax] = self._a10 * th[ax] + self._a11 * om[ax] + self._b1 * sp[ax]
        self.theta = new_th
        self.omega = new_om
        self.m += 1

    def command(self, pan: float, tilt: float) -> None:
        """Record the next command's setpoint (CMD_{m-1} after advance)."""
        self.sp_hist.append((float(pan), float(tilt)))

    def pose_at(self, t: float) -> tuple[float, float]:
        """Pose at time t (s), linear between the last two boundaries (R3.3)."""
        t1 = self.m * self.period_s
        f = (t - t1) / self.period_s + 1.0  # 0 at (m - 1) T, 1 at m T
        p0, p1 = self.theta_prev, self.theta
        return p0[0] + f * (p1[0] - p0[0]), p0[1] + f * (p1[1] - p0[1])

    @property
    def pose(self) -> tuple[float, float]:
        """Pose at the latest boundary, m T."""
        return self.theta[0], self.theta[1]


# --------------------------------------------------------------------------- #
# Event-cluster tracker (R4)
# --------------------------------------------------------------------------- #
_MS_EPS_PX = 0.1  # mean-shift stops when the shift is under this (R4.3)


class Cluster(NamedTuple):
    """Result of one mean-shift (R4.3)."""

    u: float  # centre, px
    v: float
    n: int  # events in the final window, all polarities
    t_us: float  # their mean timestamp, us since episode start (NaN if n == 0)
    n_on: int  # ON events in the final window (the gate window of R4.5)


class ClusterTracker:
    """Per-period event clustering (R4). Holds no state across periods.

    Call :meth:`load` once per period with that period's events, then
    :meth:`acquire` (no track) or :meth:`gate` (tracking).
    """

    def __init__(self, width: int, height: int, *, cell: int, n_acq: int, r_win: float,
                 ms_iter: int, n_meas: int, r_gate: float) -> None:
        self.width = int(width)
        self.height = int(height)
        self.cell = int(cell)
        self.n_acq = int(n_acq)
        self.r_win = float(r_win)
        self.ms_iter = int(ms_iter)
        self.n_meas = int(n_meas)
        self.r_gate = float(r_gate)
        self.ncols = -(-self.width // self.cell)
        self.nrows = -(-self.height // self.cell)
        self._padded = np.zeros((self.nrows + 2, self.ncols + 2), dtype=np.intp)
        self.load(np.zeros(0, dtype=EVENT_DTYPE))

    # -- per period -------------------------------------------------------- #
    def load(self, events: np.ndarray) -> None:
        """Decode a batch and count ON events on the coarse grid (R4.1)."""
        self.x = events["x"].astype(np.float64)
        self.y = events["y"].astype(np.float64)
        self.t = events["t"].astype(np.float64)
        self.on = events["p"] == 1
        ci = np.minimum(events["x"][self.on].astype(np.intp) // self.cell, self.ncols - 1)
        ri = np.minimum(events["y"][self.on].astype(np.intp) // self.cell, self.nrows - 1)
        self._on_ci, self._on_ri = ci, ri
        grid = np.bincount(ri * self.ncols + ci, minlength=self.nrows * self.ncols)
        g = self._padded
        g[1:-1, 1:-1] = grid.reshape(self.nrows, self.ncols)
        # 3 x 3 block sums centred on each cell (zero beyond the border), separably
        h = g[:, :-2] + g[:, 1:-1] + g[:, 2:]
        blocks = h[:-2] + h[1:-1] + h[2:]
        i = int(blocks.argmax())
        self.block_n = int(blocks.flat[i])  # ON events in the best block
        self.block_rc = divmod(i, self.ncols)  # its centre cell (row, col)

    def block_seed(self) -> tuple[float, float] | None:
        """Acquisition seed (R4.2): the mean position of the best block's ON
        events, if it holds at least ``n_acq``; otherwise None."""
        if self.block_n < self.n_acq:
            return None
        r, c = self.block_rc
        ci, ri = self._on_ci, self._on_ri
        m = (ci >= c - 1) & (ci <= c + 1) & (ri >= r - 1) & (ri <= r + 1)
        n = int(np.count_nonzero(m))
        xo = self.x[self.on][m]
        yo = self.y[self.on][m]
        return float(xo.sum()) / n, float(yo.sum()) / n

    def mean_shift(self, su: float, sv: float) -> Cluster:
        """Uniform-window mean-shift from (su, sv), all polarities (R4.3)."""
        reach = self.ms_iter * self.r_win  # no window can leave this box
        x, y = self.x, self.y
        pre = (np.abs(x - su) <= reach) & (np.abs(y - sv) <= reach)
        xs, ys = x[pre], y[pre]
        r2 = self.r_win * self.r_win
        cu, cv = su, sv
        last = None  # mask of the last non-empty window
        n = 0
        for _ in range(self.ms_iter):
            dx = xs - cu
            dy = ys - cv
            m = dx * dx + dy * dy <= r2
            cnt = int(np.count_nonzero(m))
            if cnt == 0:
                break
            last, n = m, cnt
            nu = float(xs[m].sum()) / cnt
            nv = float(ys[m].sum()) / cnt
            shift = math.hypot(nu - cu, nv - cv)
            cu, cv = nu, nv
            if shift < _MS_EPS_PX:
                break
        if last is None:
            return Cluster(su, sv, 0, math.nan, 0)
        t_us = float(self.t[pre][last].sum()) / n
        n_on = int(np.count_nonzero(self.on[pre][last]))
        return Cluster(cu, cv, n, t_us, n_on)

    def acquire(self) -> Cluster | None:
        """Look for a new target (R4.2, R4.3). A cluster of fewer than
        ``n_meas`` events is not a measurement, so it doesn't start a track."""
        seed = self.block_seed()
        if seed is None:
            return None
        c = self.mean_shift(*seed)
        return c if c.n >= self.n_meas else None

    def gate(self, su: float, sv: float) -> tuple[Cluster | None, Cluster | None, Cluster]:
        """Track from the predicted seed (su, sv) (R4.4) and run the jump check
        (R4.5).

        Returns ``(measurement, jump, cluster)``: the gated measurement or None;
        the cluster to re-acquire from if the jump check fired, else None; and
        the gate window, the mean-shift result from the seed (its centre is the
        seed itself if the window was empty).
        """
        c = self.mean_shift(su, sv)  # the gate window (R4.4)
        jump = None
        # Jump check (R4.5): a strong ON block far from the seed, stronger than
        # the gate window's ON events, is a candidate. It is a jump only if
        # mean-shift from it converges more than r_gate from the gate window's
        # centre: when the prediction lags, the target's own leading edge makes
        # such a block, but both mean-shifts then land on the same disc.
        if self.block_n >= self.n_acq and self.block_n > c.n_on:
            bu, bv = self.block_seed()
            if math.hypot(bu - su, bv - sv) > self.r_gate:
                a = self.mean_shift(bu, bv)
                if a.n >= self.n_meas and math.hypot(a.u - c.u, a.v - c.v) > self.r_gate:
                    jump = a
        ok = c.n >= self.n_meas and math.hypot(c.u - su, c.v - sv) <= self.r_gate
        return (c if ok else None), jump, c


# --------------------------------------------------------------------------- #
# Kalman filter (R5.1), per axis: state (angle, rate), covariance (p00, p01, p11)
# --------------------------------------------------------------------------- #


def kf_predict(x, v, p00, p01, p11, dt, q):
    """Constant-velocity prediction over dt with white-noise acceleration of
    spectral density q (rad^2 s^-3)."""
    dt2 = dt * dt
    return (
        x + dt * v,
        v,
        p00 + dt * (2.0 * p01 + dt * p11) + q * dt2 * dt / 3.0,
        p01 + dt * p11 + q * dt2 / 2.0,
        p11 + q * dt,
    )


def kf_update(x, v, p00, p01, p11, z, r):
    """Update with an angle measurement z of variance r."""
    s = p00 + r
    k0 = p00 / s
    k1 = p01 / s
    y = z - x
    return (
        x + k0 * y,
        v + k1 * y,
        p00 - k0 * p00,
        p01 - k0 * p01,
        p11 - k1 * p01,
    )


# --------------------------------------------------------------------------- #
# Controller A (R1, R5, R6)
# --------------------------------------------------------------------------- #
NAME = "classical"

ACQUIRE, TRACK, COAST = 0, 1, 2  # track states (R5.3)
STATE_NAMES = ("ACQUIRE", "TRACK", "COAST")

_SIGMA_V0 = math.radians(30.0)  # initial rate sd, above the scenarios' 24 deg/s (R5.4)

# Defaults: spec_ctl_a.md §3 Defaults. The ones marked "tune" there were tuned
# in T4 (docs/ctl_a.md): q, kp and ki changed; n_meas, r_gate, sigma_px,
# coast_max and kd kept their initial values.
DEFAULTS: dict[str, Any] = {
    "cell": 16,  # px, coarse ON grid (R4.1)
    "n_acq": 20,  # ON events per 3 x 3 block to acquire (R4.2)
    "r_win": 12.0,  # px, mean-shift window radius (R4.3)
    "ms_iter": 3,  # mean-shift iterations (R4.3)
    "n_meas": 15,  # events for a measurement (R4.4)
    "r_gate": 24.0,  # px, gate radius (R4.4, R4.5)
    "sigma_px": 1.0,  # px, measurement sd (R5.2)
    "q": 2.0,  # rad^2 s^-3, acceleration noise (R5.1); tuned, was 0.25
    "coast_max": 30,  # periods without a measurement before ACQUIRE (R5.3)
    "kp": 0.3,  # PID on the image error (R6.2); tuned, was 0.1
    "ki": 8.0,  # s^-1; tuned, was 1.0
    "kd": 0.0,  # s
    "i_max_deg": 2.0,  # anti-windup bound on |ki * integral| (R6.2)
    "model_wn": 25.0,  # rad/s, servo model (R3.1)
    "model_zeta": 0.8,
    "model_dead_periods": 1,  # setpoint dead time in periods (R3.1)
    "pan_lim_deg": 90.0,  # A's own setpoint clamp (R6.3)
    "tilt_lim_deg": 45.0,
}
_INT_PARAMS = {"cell", "n_acq", "ms_iter", "n_meas", "coast_max", "model_dead_periods"}
_POSITIVE = {"cell", "n_acq", "r_win", "ms_iter", "n_meas", "r_gate", "sigma_px", "coast_max",
             "model_wn", "model_zeta", "pan_lim_deg", "tilt_lim_deg"}  # > 0; the rest >= 0


def f32_bound(limit: float) -> float:
    """The largest float32 value not beyond ``limit`` (> 0), as a float.

    CMD carries float32 (sim R8.2). Clamping to this bound keeps a saturated
    setpoint inside the limit after the wire's rounding, so the simulator's
    own clamp never acts (R3.2, R6.3): radians(90) would otherwise round up
    to 90.0000025 deg.
    """
    f = np.float32(limit)
    if float(f) > limit:
        f = np.nextafter(f, np.float32(0.0))
    return float(f)


def effective_params(given: dict[str, Any] | None) -> dict[str, Any]:
    """Validate parameters against :data:`DEFAULTS`; return every effective one.

    Unknown names and bad values raise ``ValueError``, so ``jn-sim ctl`` fails
    at startup (R1.2).
    """
    given = dict(given or {})
    unknown = set(given) - set(DEFAULTS)
    if unknown:
        raise ValueError(
            f"{NAME}: unknown parameter(s) {', '.join(sorted(unknown))}; allowed: "
            f"{', '.join(sorted(DEFAULTS))}"
        )
    out: dict[str, Any] = {}
    for key, default in DEFAULTS.items():
        val = given.get(key, default)
        if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
            raise ValueError(f"{NAME}: parameter {key} must be a finite number, got {val!r}")
        if key in _INT_PARAMS:
            if val != int(val):
                raise ValueError(f"{NAME}: parameter {key} must be an integer, got {val!r}")
            val = int(val)
        else:
            val = float(val)
        if (key in _POSITIVE and not val > 0) or val < 0:
            bound = "> 0" if key in _POSITIVE else ">= 0"
            raise ValueError(f"{NAME}: parameter {key} must be {bound}, got {val!r}")
        out[key] = val
    return out


class ClassicalController:
    """Controller A (spec_ctl_a.md): ``reset(hello) -> "classical"``,
    ``step(obs) -> (pan, tilt)``, absolute setpoints in radians (R1.1)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params: dict[str, Any] = effective_params(params)  # sim R8.10
        p = self.params
        self.d = p["model_dead_periods"]
        self.tau_lead = 2.0 * p["model_zeta"] / p["model_wn"]  # ramp lag of the servo (R6.1)
        # Setpoint clamp bounds: float32-safe, never beyond the limits (R6.3).
        self.lim = (f32_bound(math.radians(p["pan_lim_deg"])),
                    f32_bound(math.radians(p["tilt_lim_deg"])))
        self.i_max = math.radians(p["i_max_deg"])
        self.model: ServoModel | None = None
        self.tracker: ClusterTracker | None = None
        self._episode_state(0.0, 0.0)

    # -- episode state ----------------------------------------------------- #
    def _episode_state(self, pan0: float, tilt0: float) -> None:
        """Everything an episode changes, at its initial value (R1.5)."""
        self.state = ACQUIRE
        self.coast_n = 0  # periods since the last measurement
        # Fault sites (R1.5)
        self.meas = np.full(4, math.nan)  # last cluster measurement: u, v (px), n, t (s)
        self.kf_x = np.zeros((2, 2))  # per axis (pan, tilt): angle (rad), rate (rad/s)
        self.kf_P = np.zeros((2, 3))  # per axis: covariance p00, p01, p11
        self.pid_i = np.zeros(2)  # per axis: integral of the image error (rad s)
        self.cmd = np.array([pan0, tilt0], dtype=np.float64)  # last command (rad)
        # Other filter and PID state
        self.kf_t = 0.0  # time of the filter state (s)
        self.pid_u = np.zeros(2)  # last PID output (rad), held without a measurement
        self.pid_e = np.zeros(2)  # last image error (rad), for the derivative
        self.pid_k = -1  # period of the last PID update; -1 for none since (re-)init
        # Diagnostics only
        self.n_inits = 0
        self.n_jumps = 0

    def reset(self, hello) -> str:
        p = self.params
        self.T = float(hello.period_us) * 1e-6
        self.fx, self.fy = float(hello.fx), float(hello.fy)
        self.cx, self.cy = float(hello.cx), float(hello.cy)
        self._intr = (self.fx, self.fy, self.cx, self.cy)
        pan0, tilt0 = float(hello.pan0), float(hello.tilt0)
        self.r_meas = ((p["sigma_px"] / self.fx) ** 2, (p["sigma_px"] / self.fy) ** 2)
        self.model = ServoModel(p["model_wn"], p["model_zeta"], self.T, self.d)
        self.model.reset(pan0, tilt0)
        self.tracker = ClusterTracker(
            int(hello.width), int(hello.height), cell=p["cell"], n_acq=p["n_acq"],
            r_win=p["r_win"], ms_iter=p["ms_iter"], n_meas=p["n_meas"], r_gate=p["r_gate"],
        )
        self._episode_state(pan0, tilt0)
        return NAME

    # -- one decision ------------------------------------------------------ #
    def step(self, obs):
        k = int(obs.k)
        model, trk = self.model, self.tracker
        model.advance()  # model pose over [kT, (k + 1) T]: OBS_k's interval
        trk.load(obs.events)

        c = None  # this period's measurement
        if self.state == ACQUIRE:
            c = trk.acquire()
            if c is not None:
                self._init_track(c)
        else:
            t_mid = (k + 0.5) * self.T
            az, el = self._predict(t_mid)
            su, sv, front = azel_to_pixel(az, el, *model.pose_at(t_mid), *self._intr)
            meas = jump = None
            if front:
                meas, jump, _ = trk.gate(su, sv)
            else:
                # The prediction doesn't project (behind the camera): run
                # acquisition as in ACQUIRE (R4.4). A seed re-acquires.
                jump = trk.acquire()
            if jump is not None:  # R4.5: re-acquire where the target is now
                c = jump
                if front:
                    self.n_jumps += 1
                self._init_track(c)
            elif meas is not None:
                c = meas
                self._update_track(c)
            else:
                self.coast_n += 1
                if self.coast_n >= self.params["coast_max"]:
                    self.state = ACQUIRE  # track lost (R5.3)
                    self.kf_x[:, 1] = 0.0
                else:
                    self.state = COAST
        return self._command(k, c)

    def _measure(self, c: Cluster) -> tuple[float, float, float]:
        """World angle of the cluster centre at the model pose at t (R5.2)."""
        t = c.t_us * 1e-6
        self.meas[:] = (c.u, c.v, c.n, t)
        az, el = pixel_to_azel(c.u, c.v, *self.model.pose_at(t), *self._intr)
        return az, el, t

    def _init_track(self, c: Cluster) -> None:
        """(Re-)initialise the filter and PID from a measurement (R5.4)."""
        az, el, t = self._measure(c)
        v0 = _SIGMA_V0 * _SIGMA_V0
        self.kf_x[0] = (az, 0.0)
        self.kf_x[1] = (el, 0.0)
        self.kf_P[0] = (self.r_meas[0], 0.0, v0)
        self.kf_P[1] = (self.r_meas[1], 0.0, v0)
        self.kf_t = t
        self.pid_i[:] = 0.0
        self.pid_u[:] = 0.0
        self.pid_e[:] = 0.0
        self.pid_k = -1
        self.state = TRACK
        self.coast_n = 0
        self.n_inits += 1

    def _update_track(self, c: Cluster) -> None:
        """Predict both axes' filters to the measurement time and update (R5.1)."""
        az, el, t = self._measure(c)
        dt = t - self.kf_t
        q = self.params["q"]
        for ax, z in ((0, az), (1, el)):
            x, v = self.kf_x[ax].tolist()
            p00, p01, p11 = self.kf_P[ax].tolist()
            x, v, p00, p01, p11 = kf_predict(x, v, p00, p01, p11, dt, q)
            x, v, p00, p01, p11 = kf_update(x, v, p00, p01, p11, z, self.r_meas[ax])
            self.kf_x[ax] = (x, v)
            self.kf_P[ax] = (p00, p01, p11)
        self.kf_t = t
        self.state = TRACK
        self.coast_n = 0

    def _predict(self, t: float) -> tuple[float, float]:
        """Both axes' predicted angles at time t, without changing the filter."""
        (x0, v0), (x1, v1) = self.kf_x.tolist()
        dt = t - self.kf_t
        return x0 + v0 * dt, x1 + v1 * dt

    def _command(self, k: int, c: Cluster | None):
        """Setpoint for CMD_k (R6.1-R6.3)."""
        if self.state == ACQUIRE:
            pan, tilt = self.cmd.tolist()  # hold the last setpoint
            self.model.command(pan, tilt)
            return pan, tilt

        p = self.params
        kp, ki, kd, T = p["kp"], p["ki"], p["kd"], self.T
        # Feedforward: the prediction at the middle of the period in which
        # CMD_k is active, led by the servo's ramp lag (R6.1).
        lead = (k + 1.5 + self.d) * T - self.kf_t + self.tau_lead
        (x0, v0), (x1, v1) = self.kf_x.tolist()
        ff = (x0 + v0 * lead, x1 + v1 * lead)

        integ = self.pid_i.tolist()
        u_out = self.pid_u.tolist()
        e_prev = self.pid_e.tolist()
        if c is not None:
            # Image error: boresight to cluster centre, from the pixel offset
            # and the intrinsics only (R6.2). Right of centre is negative pan.
            e = (-math.atan((c.u - self.cx) / self.fx), -math.atan((c.v - self.cy) / self.fy))
            # Time base: periods, not event timestamps (R6.2). The integral
            # adds e*T per measured period; the derivative divides by the
            # periods since the last measured one. After a (re-)init (pid_k =
            # -1, integral and e_prev cleared) there is no derivative term.
            gap = (k - self.pid_k) * T if self.pid_k >= 0 else 0.0
        out = [0.0, 0.0]
        for ax in (0, 1):
            lim = self.lim[ax]
            if c is not None:
                ei = e[ax]
                de = (ei - e_prev[ax]) / gap if gap > 0.0 else 0.0
                i_new = integ[ax]
                if ki > 0.0:
                    cap = self.i_max / ki  # |ki * integral| <= i_max
                    i_new = min(cap, max(-cap, i_new + ei * T))
                u = kp * ei + ki * i_new + kd * de
                if abs(ff[ax] + u) > lim:
                    # Clamped: the integral is frozen (R6.2).
                    i_new = integ[ax]
                    u = kp * ei + ki * i_new + kd * de
                integ[ax] = i_new
                u_out[ax] = u
                e_prev[ax] = ei
            s = ff[ax] + u_out[ax]
            out[ax] = lim if s > lim else (-lim if s < -lim else s)  # R6.3
        if c is not None:
            self.pid_i[:] = integ
            self.pid_u[:] = u_out
            self.pid_e[:] = e_prev
            self.pid_k = k
        self.cmd[:] = out
        self.model.command(out[0], out[1])
        return out[0], out[1]
