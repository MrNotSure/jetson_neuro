"""T5: target trajectories — determinism, formulae, bounds (R4.2-R4.3)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from jn_sim import seeding, target
from jn_sim.config import TargetConfig


def _cfg(trajectory: str) -> TargetConfig:
    c = TargetConfig()
    c.trajectory = trajectory
    return c


def test_sine_matches_formula() -> None:
    cfg = _cfg("sine")
    traj = target.make_trajectory(cfg)
    t = np.linspace(0, 20, 2001)
    az, el = traj.az_el(t)
    exp_az = math.radians(cfg.sine_az_amp_deg) * np.sin(
        2 * math.pi * cfg.sine_az_freq_hz * t + math.radians(cfg.sine_az_phase_deg)
    )
    exp_el = math.radians(cfg.sine_el_amp_deg) * np.sin(
        2 * math.pi * cfg.sine_el_freq_hz * t + math.radians(cfg.sine_el_phase_deg)
    )
    assert np.allclose(az, exp_az)
    assert np.allclose(el, exp_el)


def test_static_is_zero() -> None:
    traj = target.make_trajectory(_cfg("static"))
    az, el = traj.az_el(np.linspace(0, 5, 10))
    assert np.all(az == 0.0) and np.all(el == 0.0)


@pytest.mark.parametrize("kind", ["step", "random"])
def test_determinism_by_seed(kind: str) -> None:
    cfg = _cfg(kind)
    t = np.linspace(0, 30, 3001)

    def build(seed: int):
        rng = seeding.trajectory_rng(seed, episode=0)
        return target.make_trajectory(cfg, rng, duration_s=30.0).az_el(t)

    a1 = build(0)
    a2 = build(0)
    a3 = build(1)
    assert np.array_equal(a1[0], a2[0]) and np.array_equal(a1[1], a2[1])
    # a different seed gives a different trajectory
    assert not (np.array_equal(a1[0], a3[0]) and np.array_equal(a1[1], a3[1]))


def test_step_jumps_bounded_and_within_range() -> None:
    cfg = _cfg("step")
    rng = seeding.trajectory_rng(0, episode=0)
    traj = target.make_trajectory(cfg, rng, duration_s=60.0)
    az, el = traj._az, traj._el  # the realised step sequence
    step_max = math.radians(cfg.step_max_deg)
    az_range = math.radians(cfg.step_az_range_deg)
    el_range = math.radians(cfg.step_el_range_deg)

    jumps = np.hypot(np.diff(az), np.diff(el))
    assert np.all(jumps <= step_max + 1e-12)
    assert np.all(np.abs(az) <= az_range + 1e-12)
    assert np.all(np.abs(el) <= el_range + 1e-12)


def test_step_changes_only_at_multiples_of_interval() -> None:
    cfg = _cfg("step")
    rng = seeding.trajectory_rng(0, episode=0)
    traj = target.make_trajectory(cfg, rng, duration_s=30.0)
    dt = cfg.step_interval_s
    for k in range(1, 8):
        before = traj.az_el(k * dt - 1e-6)
        after = traj.az_el(k * dt + 1e-6)
        start = traj.az_el(k * dt - dt + 1e-6)
        # constant within the interval [ (k-1)dt, k dt )
        assert before[0] == pytest.approx(start[0])
        # a (possible) change exactly at the multiple
        assert after[0] == pytest.approx(traj._az[k])


def test_smooth_random_within_amplitude() -> None:
    cfg = _cfg("random")
    rng = seeding.trajectory_rng(0, episode=0)
    traj = target.make_trajectory(cfg, rng)
    t = np.linspace(0, 120, 120001)
    az, el = traj.az_el(t)
    assert np.max(np.abs(az)) <= math.radians(cfg.random_az_amp_deg) + 1e-9
    assert np.max(np.abs(el)) <= math.radians(cfg.random_el_amp_deg) + 1e-9
    # frequencies stay within the configured band
    assert np.all(traj.f_az >= cfg.random_f_min_hz) and np.all(traj.f_az <= cfg.random_f_max_hz)


def test_scalar_time_input() -> None:
    traj = target.make_trajectory(_cfg("sine"))
    az, el = traj.az_el(1.0)
    assert np.ndim(az) == 0 and np.ndim(el) == 0
