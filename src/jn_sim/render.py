"""Renderer (spec T7, R4.1, R6.7).

The scene is a background layer with one target composited over it, in linear
intensity (no gamma). The renderer talks to the background only through one
call -- the linear intensity of a pixel window at a given gimbal pose -- and a
flag saying whether the background is uniform (R4.1). Nothing else depends on
the background type, so stage 2 can swap in a textured layer without touching
the loop, protocol, controllers or logs.

The target is a disc of intensity I_t and angular radius r_t with a 1 px linear
anti-aliased edge. Output is log intensity L = ln(I + eps) (R6.1).

Two paths that must give identical frames (R6.7):

* full frame -- every pixel; used for any non-uniform background and as the
  reference;
* region of interest -- with a uniform background, only the pixels the target
  can cover change, so the rest stays at the (constant) background. The frames
  are identical because the untouched pixels equal the background exactly.

Standard library + numpy only (R2.2).
"""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from . import camera
from .config import Config, ConfigError, SceneConfig


class Background(Protocol):
    uniform: bool

    def intensity(self, u, v, pan: float, tilt: float):
        """Linear intensity at pixel coordinates (u, v) for the gimbal pose."""
        ...


class UniformBackground:
    """A flat background of constant linear intensity (R4.1, stage 1)."""

    uniform = True

    def __init__(self, i_bg: float) -> None:
        self.i_bg = float(i_bg)

    def intensity(self, u, v, pan: float, tilt: float):
        u = np.asarray(u, dtype=float)
        return np.full(u.shape, self.i_bg, dtype=float)


def make_background(scene: SceneConfig) -> Background:
    if scene.background == "uniform":
        return UniformBackground(scene.i_bg)
    raise ConfigError(f"background {scene.background!r} is not supported (only 'uniform')")


class Renderer:
    def __init__(self, cfg: Config, background: Background | None = None) -> None:
        self.intr = cfg.intrinsics()
        self.width = int(cfg.camera.width)
        self.height = int(cfg.camera.height)
        self.i_t = float(cfg.target.i_t)
        self.radius_rad = math.radians(cfg.target.radius_deg)
        self.radius_px = camera.pixel_radius(self.radius_rad, self.intr)
        self.eps = float(cfg.events.log_eps)
        self.bg = background if background is not None else make_background(cfg.scene)
        self._us = np.arange(self.width, dtype=float)
        self._vs = np.arange(self.height, dtype=float)

    # -- public API -------------------------------------------------------- #
    def render(self, pan: float, tilt: float, az: float, el: float) -> np.ndarray:
        """Render a log-intensity frame, choosing the path by background type."""
        if self.bg.uniform:
            return self.render_roi(pan, tilt, az, el)
        return self.render_full(pan, tilt, az, el)

    def render_full(self, pan: float, tilt: float, az: float, el: float) -> np.ndarray:
        d = camera.direction_from_azel(az, el)
        uu, vv = np.meshgrid(self._us, self._vs)  # (H, W)
        intensity = self._composite(uu, vv, pan, tilt, d)
        return np.log(intensity + self.eps)

    def render_roi(self, pan: float, tilt: float, az: float, el: float) -> np.ndarray:
        if not self.bg.uniform:
            raise ValueError("render_roi requires a uniform background (R6.7)")
        # The uniform background is a single constant; fill the frame with it.
        bg_const = float(self.bg.intensity(np.zeros(1), np.zeros(1), pan, tilt)[0])
        frame = np.full((self.height, self.width), math.log(bg_const + self.eps))
        box = self.roi_box(pan, tilt, az, el)
        if box is not None:
            frame[box[0] : box[1], box[2] : box[3]] = self.render_region(
                pan, tilt, az, el, box
            )
        return frame

    def roi_box(self, pan, tilt, az, el):
        """ROI box ``(v0, v1, u0, u1)`` covering the target disc, or None.

        Used by the loop (T12) to render and generate events over only the
        region the target can touch (R6.7, M10)."""
        return self._roi_box(pan, tilt, az, el)

    def render_region(self, pan, tilt, az, el, box) -> np.ndarray:
        """Log-intensity patch over ``box = (v0, v1, u0, u1)``."""
        v0, v1, u0, u1 = box
        d = camera.direction_from_azel(az, el)
        uu, vv = np.meshgrid(self._us[u0:u1], self._vs[v0:v1])
        intensity = self._composite(uu, vv, pan, tilt, d)
        return np.log(intensity + self.eps)

    def coverage(self, pan: float, tilt: float, az: float, el: float) -> np.ndarray:
        """The disc coverage (alpha in [0, 1]) over the full frame."""
        d = camera.direction_from_azel(az, el)
        uu, vv = np.meshgrid(self._us, self._vs)
        return self._coverage(uu, vv, pan, tilt, d)

    def project_target(self, pan: float, tilt: float, az: float, el: float):
        """(u, v, in_front) of the target centre, for logging/ROI."""
        d = camera.direction_from_azel(az, el)
        return camera.project_direction(d, pan, tilt, self.intr)

    # -- internals --------------------------------------------------------- #
    def _coverage(self, uu, vv, pan, tilt, d) -> np.ndarray:
        uc, vc, in_front = camera.project_direction(d, pan, tilt, self.intr)
        if not bool(in_front):
            return np.zeros(np.shape(uu), dtype=float)
        dist = np.hypot(uu - uc, vv - vc)
        # 1 px linear ramp centred on the disc edge: alpha=1 inside, 0 outside.
        return np.clip(self.radius_px + 0.5 - dist, 0.0, 1.0)

    def _composite(self, uu, vv, pan, tilt, d) -> np.ndarray:
        bg_i = np.asarray(self.bg.intensity(uu, vv, pan, tilt), dtype=float)
        alpha = self._coverage(uu, vv, pan, tilt, d)
        return (1.0 - alpha) * bg_i + alpha * self.i_t

    def _roi_box(self, pan, tilt, az, el):
        uc, vc, in_front = self.project_target(pan, tilt, az, el)
        if not bool(in_front):
            return None
        reach = self.radius_px + 1.0  # cover the full anti-aliased edge
        u0 = max(0, int(math.floor(float(uc) - reach)))
        u1 = min(self.width, int(math.ceil(float(uc) + reach)) + 1)
        v0 = max(0, int(math.floor(float(vc) - reach)))
        v1 = min(self.height, int(math.ceil(float(vc) + reach)) + 1)
        if u0 >= u1 or v0 >= v1:
            return None
        return v0, v1, u0, u1
