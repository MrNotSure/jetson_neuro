"""Gimbal plant (spec T6, R5).

Each axis is a second-order position servo (natural frequency omega_n, damping
zeta) with a rate limit, angle limits and a fixed dead time on the setpoint. It
is integrated with semi-implicit (symplectic) Euler at a fixed step dt_phys.

The dead time is fixed (R5.3), so the plant never depends on measured network
latency and runs stay deterministic: a command applied at sim time t takes
effect at t + tau_d. In the loop, a command is applied at the end of its period
k, i.e. at (k+1)T, so it takes effect at (k+1)T + tau_d exactly as R5.3 states.

Setpoints reach the integrator only through :meth:`Plant.apply_command`, which
applies the command-as-data rules (R8.9): a non-finite axis holds that axis's
previous setpoint and flags ``cmd_invalid``; a finite out-of-range axis is
clamped to the limit and flags ``cmd_clamped``. Neither aborts the run.

Standard library + numpy only (R2.2).
"""

from __future__ import annotations

import collections
import math

import numpy as np

from .config import PlantConfig


class Plant:
    def __init__(self, cfg: PlantConfig) -> None:
        self.wn = float(cfg.omega_n)
        self.zeta = float(cfg.zeta)
        self.rate_limit = float(cfg.rate_limit)
        self.dt = float(cfg.dt_phys_s)
        self.limits = np.array(
            [math.radians(cfg.pan_limit_deg), math.radians(cfg.tilt_limit_deg)],
            dtype=float,
        )
        self.dead_steps = int(round(cfg.dead_time_s / self.dt))
        self.reset()

    # -- state ------------------------------------------------------------- #
    def reset(self, pan0: float = 0.0, tilt0: float = 0.0) -> None:
        start = np.array([pan0, tilt0], dtype=float)
        self.theta = start.copy()
        self.omega = np.zeros(2, dtype=float)
        self.active_sp = start.copy()
        self.last_sp = start.copy()  # previous commanded setpoint (R8.9 hold)
        self.pending: collections.deque[tuple[int, np.ndarray]] = collections.deque()
        self.step = 0

    @property
    def time(self) -> float:
        return self.step * self.dt

    @property
    def pose(self) -> tuple[float, float]:
        return float(self.theta[0]), float(self.theta[1])

    # -- the single setpoint entry point (R5.4) ---------------------------- #
    def apply_command(self, pan_cmd: float, tilt_cmd: float):
        """Validate a CMD (R8.9) and schedule it to take effect after tau_d.

        Returns ``(used, cmd_invalid, cmd_clamped)``: the two-axis setpoint
        actually used, and the two flags. This is the only way a setpoint ever
        reaches the integrator (R5.4).
        """
        used, invalid, clamped = self._validate(pan_cmd, tilt_cmd)
        self.pending.append((self.step + self.dead_steps, used.copy()))
        return used, invalid, clamped

    def _validate(self, pan_cmd: float, tilt_cmd: float):
        cmd = (float(pan_cmd), float(tilt_cmd))
        used = self.last_sp.copy()
        invalid = False
        clamped = False
        for ax in (0, 1):
            value = cmd[ax]
            if not math.isfinite(value):
                used[ax] = self.last_sp[ax]  # hold the previous setpoint
                invalid = True
                continue
            lim = self.limits[ax]
            if value > lim:
                used[ax] = lim
                clamped = True
            elif value < -lim:
                used[ax] = -lim
                clamped = True
            else:
                used[ax] = value
        self.last_sp = used.copy()
        return used, invalid, clamped

    # -- integration ------------------------------------------------------- #
    def advance(self, n_steps: int) -> tuple[np.ndarray, np.ndarray]:
        """Integrate ``n_steps`` physics steps. Returns per-step angles and
        rates, each shaped ``(n_steps, 2)`` (axis order: pan, tilt)."""
        angles = np.empty((n_steps, 2), dtype=float)
        rates = np.empty((n_steps, 2), dtype=float)
        wn2 = self.wn * self.wn
        damp = 2.0 * self.zeta * self.wn
        dt = self.dt
        rl = self.rate_limit
        lim = self.limits
        for i in range(n_steps):
            # Switch to any pending setpoint whose dead time has elapsed.
            while self.pending and self.pending[0][0] <= self.step:
                self.active_sp = self.pending.popleft()[1]
            acc = wn2 * (self.active_sp - self.theta) - damp * self.omega
            self.omega = np.clip(self.omega + dt * acc, -rl, rl)
            new_theta = self.theta + dt * self.omega
            over = new_theta > lim
            under = new_theta < -lim
            self.theta = np.clip(new_theta, -lim, lim)
            # A hard stop at the limit arrests that axis (zero its rate).
            self.omega = np.where(over | under, 0.0, self.omega)
            self.step += 1
            angles[i] = self.theta
            rates[i] = self.omega
        return angles, rates
