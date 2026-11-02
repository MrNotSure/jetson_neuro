"""T6: gimbal plant — command validation, step response, limits (R5, R8.9)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from jn_sim.config import PlantConfig
from jn_sim.plant import Plant


def _plant(**over) -> Plant:
    cfg = PlantConfig()
    for k, v in over.items():
        setattr(cfg, k, v)
    return Plant(cfg)


def test_nan_holds_axis_other_unaffected() -> None:
    p = _plant()
    # First, a valid command on both axes.
    p.apply_command(0.3, 0.2)
    p.advance(500)  # settle
    held_pan = p.last_sp[0]
    # Now NaN on pan, a new valid value on tilt.
    used, invalid, clamped = p.apply_command(float("nan"), 0.1)
    assert invalid is True
    assert clamped is False
    assert used[0] == pytest.approx(held_pan)  # pan held
    assert used[1] == pytest.approx(0.1)  # tilt updated
    p.advance(500)
    assert np.all(np.isfinite(p.theta)) and np.all(np.isfinite(p.omega))


def test_inf_holds_axis() -> None:
    p = _plant()
    used, invalid, clamped = p.apply_command(float("inf"), float("-inf"))
    assert invalid is True and clamped is False
    assert np.allclose(used, [0.0, 0.0])  # both held at the initial setpoint


def test_out_of_range_clamped() -> None:
    p = _plant()
    used, invalid, clamped = p.apply_command(10.0, -10.0)  # far beyond limits
    assert clamped is True and invalid is False
    assert used[0] == pytest.approx(math.radians(90.0))
    assert used[1] == pytest.approx(-math.radians(45.0))


def test_unchanged_setpoint_no_motion() -> None:
    p = _plant()
    p.apply_command(0.0, 0.0)
    angles, rates = p.advance(1000)
    assert np.allclose(angles, 0.0)
    assert np.allclose(rates, 0.0)


def test_dead_time_delay() -> None:
    p = _plant()  # tau_d = 10 ms, dt = 1 ms -> 10 steps
    p.apply_command(0.3, 0.0)
    angles, _ = p.advance(200)
    moved = np.where(np.abs(angles[:, 0]) > 1e-6)[0]
    assert moved.size > 0
    first = int(moved[0])
    assert abs(first - p.dead_steps) <= 1  # within +/- one dt_phys


def test_step_response_settles_with_expected_overshoot() -> None:
    p = _plant()
    amp = 0.05  # small enough that the rate limit is not reached
    p.apply_command(amp, 0.0)
    angles, _ = p.advance(2000)  # 2 s
    pan = angles[:, 0]
    # settles to within 2 %
    assert abs(pan[-1] - amp) <= 0.02 * amp
    # overshoot consistent with zeta = 0.8 (Mp ~= 1.52 %)
    mp_theory = math.exp(-p.zeta * math.pi / math.sqrt(1 - p.zeta**2))
    overshoot = (pan.max() - amp) / amp
    assert overshoot == pytest.approx(mp_theory, abs=0.006)


def test_rate_limit_never_exceeded() -> None:
    p = _plant()
    p.apply_command(1.0, 0.8)  # large steps that demand a high rate
    _, rates = p.advance(3000)
    assert np.max(np.abs(rates)) <= p.rate_limit + 1e-9


def test_dead_time_is_exactly_tau_d() -> None:
    # Default tau_d = 10 ms, dt_phys = 1 ms -> 10 steps. The command applied at
    # step 0 takes effect exactly at step 10 (R5.3, M9).
    p = _plant()
    assert p.dead_steps == 10
    p.apply_command(0.3, 0.0)
    a0, _ = p.advance(10)  # steps 0..9 = the dead time
    assert np.all(a0[:, 0] == 0.0)  # no motion during tau_d
    a1, _ = p.advance(1)  # step 10
    assert a1[0, 0] != 0.0  # motion begins exactly at tau_d


def test_angle_limits_clamp_state() -> None:
    p = _plant()
    p.apply_command(5.0, 5.0)  # beyond limits -> clamped setpoint
    angles, _ = p.advance(5000)
    assert np.all(np.abs(angles[:, 0]) <= math.radians(90.0) + 1e-9)
    assert np.all(np.abs(angles[:, 1]) <= math.radians(45.0) + 1e-9)
    assert angles[-1, 0] == pytest.approx(math.radians(90.0), abs=1e-3)
