"""Target trajectories in azimuth/elevation (spec T5, R4.2-R4.3).

Four trajectories, each with a vectorised ``az_el(t)`` returning radians, where
``t`` is seconds since episode start. Randomness comes from the episode's
trajectory stream (R2.5); the same seed gives an identical trajectory (R4.3).

Amplitudes and ranges are configured in degrees (TargetConfig) and converted to
radians here. Standard library + numpy only (R2.2).
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from .config import TargetConfig

_TWO_PI = 2.0 * math.pi


class Trajectory(Protocol):
    def az_el(self, t):  # -> (az, el) in radians, shaped like t
        ...


class StaticTrajectory:
    """A fixed target straight ahead (az = el = 0)."""

    def az_el(self, t):
        t = np.asarray(t, dtype=float)
        return np.zeros_like(t), np.zeros_like(t)


class SineTrajectory:
    """A Lissajous path: an independent sinusoid per axis (R4.2)."""

    def __init__(self, cfg: TargetConfig) -> None:
        self.a_az = math.radians(cfg.sine_az_amp_deg)
        self.f_az = cfg.sine_az_freq_hz
        self.p_az = math.radians(cfg.sine_az_phase_deg)
        self.a_el = math.radians(cfg.sine_el_amp_deg)
        self.f_el = cfg.sine_el_freq_hz
        self.p_el = math.radians(cfg.sine_el_phase_deg)

    def az_el(self, t):
        t = np.asarray(t, dtype=float)
        az = self.a_az * np.sin(_TWO_PI * self.f_az * t + self.p_az)
        el = self.a_el * np.sin(_TWO_PI * self.f_el * t + self.p_el)
        return az, el


class StepTrajectory:
    """A jump every T_step, each at most step_max from the previous position,
    staying within the configured ranges (R4.2)."""

    def __init__(self, cfg: TargetConfig, rng: np.random.Generator, duration_s: float) -> None:
        self.interval = cfg.step_interval_s
        n = int(math.ceil(max(duration_s, 0.0) / self.interval)) + 2
        az_range = math.radians(cfg.step_az_range_deg)
        el_range = math.radians(cfg.step_el_range_deg)
        step_max = math.radians(cfg.step_max_deg)

        az = np.empty(n, dtype=float)
        el = np.empty(n, dtype=float)
        # Draw the whole sequence up front so the trajectory is independent of
        # query order (R2.5). The prefix is identical regardless of n, so the
        # trajectory is deterministic by seed and unaffected by duration (R4.3).
        az[0] = rng.uniform(-az_range, az_range)
        el[0] = rng.uniform(-el_range, el_range)
        for k in range(1, n):
            angle = rng.uniform(0.0, _TWO_PI)
            mag = rng.uniform(0.0, step_max)
            # Clip into range. Projection onto the box is non-expansive and the
            # previous point is inside it, so the realised jump stays <= mag.
            az[k] = np.clip(az[k - 1] + mag * math.cos(angle), -az_range, az_range)
            el[k] = np.clip(el[k - 1] + mag * math.sin(angle), -el_range, el_range)
        self._az = az
        self._el = el

    def az_el(self, t):
        t = np.asarray(t, dtype=float)
        k = np.floor(t / self.interval).astype(np.int64)
        k = np.clip(k, 0, self._az.shape[0] - 1)
        return self._az[k], self._el[k]


class SmoothRandomTrajectory:
    """A sum of n sinusoids per axis, frequencies in [f_min, f_max], bounded by
    the amplitude (R4.2). Positive weights summing to one keep |path| <= A."""

    def __init__(self, cfg: TargetConfig, rng: np.random.Generator) -> None:
        self.a_az = math.radians(cfg.random_az_amp_deg)
        self.a_el = math.radians(cfg.random_el_amp_deg)
        n = cfg.random_n_sines
        f_lo, f_hi = cfg.random_f_min_hz, cfg.random_f_max_hz

        self.f_az = rng.uniform(f_lo, f_hi, size=n)
        self.ph_az = rng.uniform(0.0, _TWO_PI, size=n)
        self.w_az = _normalised_weights(rng, n)
        self.f_el = rng.uniform(f_lo, f_hi, size=n)
        self.ph_el = rng.uniform(0.0, _TWO_PI, size=n)
        self.w_el = _normalised_weights(rng, n)

    def _axis(self, t, amp, freq, phase, weight):
        # t: (...,); freq/phase/weight: (n,) -> broadcast to (..., n), sum over n
        phases = _TWO_PI * np.multiply.outer(t, freq) + phase
        return amp * np.tensordot(np.sin(phases), weight, axes=([-1], [0]))

    def az_el(self, t):
        t = np.asarray(t, dtype=float)
        az = self._axis(t, self.a_az, self.f_az, self.ph_az, self.w_az)
        el = self._axis(t, self.a_el, self.f_el, self.ph_el, self.w_el)
        return az, el


def _normalised_weights(rng: np.random.Generator, n: int) -> np.ndarray:
    w = rng.uniform(0.0, 1.0, size=n)
    total = w.sum()
    if total == 0.0:  # vanishingly unlikely; keep it bounded anyway
        w = np.ones(n)
        total = float(n)
    return w / total


def make_trajectory(
    cfg: TargetConfig,
    rng: np.random.Generator | None = None,
    duration_s: float = 3600.0,
) -> Trajectory:
    """Build the configured trajectory. ``rng`` is the episode trajectory
    stream (R2.5); it is required for ``step`` and ``random``."""
    kind = cfg.trajectory
    if kind == "static":
        return StaticTrajectory()
    if kind == "sine":
        return SineTrajectory(cfg)
    if rng is None:
        raise ValueError(f"trajectory {kind!r} requires a random stream")
    if kind == "step":
        return StepTrajectory(cfg, rng, duration_s)
    if kind == "random":
        return SmoothRandomTrajectory(cfg, rng)
    raise ValueError(f"unknown trajectory {kind!r}")
