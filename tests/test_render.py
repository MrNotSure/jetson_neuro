"""T7: renderer — ROI == full frame, swappable background, coverage (R4.1, R6.7)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from jn_sim import camera
from jn_sim.config import Config
from jn_sim.render import Renderer


class GradientBackground:
    """Test-only non-uniform background: linear intensity in pixel azimuth.

    Demonstrates that the background layer can be swapped (R4.1) and that a
    non-uniform background goes through the full-frame path (R6.7).
    """

    uniform = False

    def intensity(self, u, v, pan, tilt):
        d = camera.unproject(u, v, pan, tilt, _INTR)
        az, _ = camera.azel_from_direction(d)
        return 0.5 + 0.3 * np.sin(az * 6.0)


_INTR = Config().intrinsics()


def _renderer(**target_over) -> Renderer:
    cfg = Config()
    for k, val in target_over.items():
        setattr(cfg.target, k, val)
    return Renderer(cfg)


@pytest.mark.parametrize(
    "pan,tilt,az,el",
    [
        (0.0, 0.0, 0.0, 0.0),  # centred
        (0.1, -0.05, 0.12, -0.04),  # off centre
        (0.0, 0.0, 0.18, 0.0),  # partly off the right edge
        (-0.02, 0.0, -0.20, 0.10),  # partly off a corner
    ],
)
def test_roi_equals_full_frame(pan, tilt, az, el) -> None:
    r = _renderer()
    full = r.render_full(pan, tilt, az, el)
    roi = r.render_roi(pan, tilt, az, el)
    assert np.array_equal(full, roi)


def test_render_picks_roi_for_uniform() -> None:
    r = _renderer()
    assert np.array_equal(r.render(0.05, 0.0, 0.05, 0.0), r.render_roi(0.05, 0.0, 0.05, 0.0))


def test_target_off_sensor_gives_uniform_frame() -> None:
    cfg = Config()
    r = Renderer(cfg)
    # Target far to the left, well outside a 60 deg FOV.
    frame = r.render(0.0, 0.0, math.radians(80.0), 0.0)
    expected = math.log(cfg.scene.i_bg + cfg.events.log_eps)
    assert np.allclose(frame, expected)


def test_behind_camera_gives_uniform_frame() -> None:
    cfg = Config()
    r = Renderer(cfg)
    frame = r.render(0.0, 0.0, math.pi, 0.0)  # target behind
    expected = math.log(cfg.scene.i_bg + cfg.events.log_eps)
    assert np.allclose(frame, expected)


def test_total_coverage_matches_pi_r_squared() -> None:
    r = _renderer()
    cov = r.coverage(0.0, 0.0, 0.0, 0.0)
    expected = math.pi * r.radius_px**2
    assert cov.sum() == pytest.approx(expected, rel=0.02)


def test_gradient_background_full_path() -> None:
    cfg = Config()
    r_uniform = Renderer(cfg)
    r_grad = Renderer(cfg, background=GradientBackground())

    # render() routes the non-uniform background through the full-frame path.
    assert np.array_equal(
        r_grad.render(0.0, 0.0, math.radians(80.0), 0.0),
        r_grad.render_full(0.0, 0.0, math.radians(80.0), 0.0),
    )

    # The background actually shows through, away from the target.
    frame = r_grad.render_full(0.0, 0.0, 0.0, 0.0)
    # a pixel far from the centre (top-left) carries the gradient value
    d = camera.unproject(np.array(0.0), np.array(0.0), 0.0, 0.0, _INTR)
    az, _ = camera.azel_from_direction(d)
    expected = math.log(0.5 + 0.3 * math.sin(float(az) * 6.0) + cfg.events.log_eps)
    assert frame[0, 0] == pytest.approx(expected)

    # and it differs from the uniform render (the layer matters)
    assert not np.allclose(frame, r_uniform.render_full(0.0, 0.0, 0.0, 0.0))


def test_render_region_matches_full_slice() -> None:
    # render_region gives exactly the full frame's slice (M10 wiring for T12).
    r = _renderer()
    pose = (0.05, -0.02, 0.06, 0.01)
    full = r.render_full(*pose)
    box = r.roi_box(*pose)
    assert box is not None
    v0, v1, u0, u1 = box
    patch = r.render_region(*pose, box)
    assert patch.shape == (v1 - v0, u1 - u0)
    assert np.array_equal(patch, full[v0:v1, u0:u1])


def test_anti_aliased_edge_is_one_pixel() -> None:
    # Coverage values strictly between 0 and 1 form a ~1 px ring.
    r = _renderer()
    cov = r.coverage(0.0, 0.0, 0.0, 0.0)
    partial = cov[(cov > 0.0) & (cov < 1.0)]
    assert partial.size > 0  # there is an anti-aliased edge
