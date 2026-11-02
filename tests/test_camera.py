"""T4: camera and gimbal geometry — conventions and round trip (R3)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from jn_sim import camera
from jn_sim.config import Config

INTR = Config().intrinsics()
W, H = 320, 240


def test_boresight_projects_to_principal_point() -> None:
    u, v, in_front = camera.project_azel(0.0, 0.0, 0.0, 0.0, INTR)
    assert bool(in_front)
    assert u == pytest.approx(INTR.cx)
    assert v == pytest.approx(INTR.cy)


def test_target_10deg_left_at_zero_pan() -> None:
    # R3.4 worked example: a target 10 deg left (az=+10) at zero pan.
    az = math.radians(10.0)
    u, v, in_front = camera.project_azel(az, 0.0, 0.0, 0.0, INTR)
    assert bool(in_front)
    assert u == pytest.approx(INTR.cx - INTR.fx * math.tan(az))
    assert v == pytest.approx(INTR.cy)


def test_positive_pan_moves_fixed_target_toward_plus_u() -> None:
    # Fixed target straight ahead; a positive pan step -> larger u (R3.4).
    small = math.radians(3.0)
    u0, _, _ = camera.project_azel(0.0, 0.0, 0.0, 0.0, INTR)
    u1, _, _ = camera.project_azel(0.0, 0.0, small, 0.0, INTR)
    assert u1 > u0
    assert float(u1) == pytest.approx(INTR.cx + INTR.fx * math.tan(small))


def test_positive_tilt_moves_fixed_target_toward_plus_v() -> None:
    small = math.radians(3.0)
    _, v0, _ = camera.project_azel(0.0, 0.0, 0.0, 0.0, INTR)
    _, v1, _ = camera.project_azel(0.0, 0.0, 0.0, small, INTR)
    assert v1 > v0
    assert float(v1) == pytest.approx(INTR.cy + INTR.fy * math.tan(small))


def test_target_up_appears_above_centre() -> None:
    # A target above the boresight (el>0) appears at v < cy.
    _, v, _ = camera.project_azel(0.0, math.radians(5.0), 0.0, 0.0, INTR)
    assert float(v) < INTR.cy


def test_target_left_appears_left_of_centre() -> None:
    u, _, _ = camera.project_azel(math.radians(5.0), 0.0, 0.0, 0.0, INTR)
    assert float(u) < INTR.cx


def test_behind_camera_not_in_front() -> None:
    # A direction pointing backwards (az = 180 deg) is not in front.
    _, _, in_front = camera.project_azel(math.pi, 0.0, 0.0, 0.0, INTR)
    assert not bool(in_front)


def test_pixel_direction_pixel_roundtrip() -> None:
    rng = np.random.default_rng(0)
    us = rng.uniform(0, W - 1, size=50)
    vs = rng.uniform(0, H - 1, size=50)
    pans = rng.uniform(-0.3, 0.3, size=50)
    tilts = rng.uniform(-0.2, 0.2, size=50)
    d = camera.unproject(us, vs, pans, tilts, INTR)
    u2, v2, in_front = camera.project_direction(d, pans, tilts, INTR)
    assert np.all(in_front)
    assert np.allclose(u2, us, atol=1e-9)
    assert np.allclose(v2, vs, atol=1e-9)


def test_vectorised_over_poses() -> None:
    pans = np.array([0.0, 0.1, -0.1])
    tilts = np.array([0.0, 0.05, -0.05])
    az = np.array([0.0, 0.1, -0.1])
    el = np.array([0.0, 0.05, -0.05])
    u, v, in_front = camera.project_azel(az, el, pans, tilts, INTR)
    assert u.shape == (3,) and v.shape == (3,)
    # pose 1 tracks its own target exactly -> projects to the centre.
    assert u[1] == pytest.approx(INTR.cx)
    assert v[1] == pytest.approx(INTR.cy)


def test_pixel_radius_matches_datasheet_default() -> None:
    # 1.5 deg angular radius -> about 7 px at the default intrinsics (R4.1).
    r = camera.pixel_radius(math.radians(1.5), INTR)
    assert r == pytest.approx(7.26, abs=0.1)


def test_in_fov_bounds() -> None:
    assert bool(camera.in_fov(0.0, 0.0, 0.0, 0.0, INTR, W, H))
    # 40 deg left is well outside a 60 deg horizontal FOV.
    assert not bool(camera.in_fov(math.radians(40.0), 0.0, 0.0, 0.0, INTR, W, H))
