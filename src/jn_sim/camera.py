"""Camera and gimbal geometry (spec T4, R3).

Conventions (R3.1-R3.4):

* World frame: x forward, y left, z up (right-handed). A target direction is
  azimuth (positive = left, toward +y) and elevation (positive = up, toward
  +z).
* Positive pan turns the camera left; positive tilt turns it up; the tilt axis
  rotates with pan. At pan = tilt = 0 the camera looks along +x.
* Image coordinates: u to the right, v down, origin at the centre of the
  top-left pixel. A positive pan step moves a fixed target towards +u, a
  positive tilt step towards +v.

At pan = tilt = 0 the camera axes in world coordinates are right = (0,-1,0),
down = (0,0,-1), forward = (1,0,0). The gimbal applies tilt about the base
right axis, then pan about world +z, so the camera axes are:

    forward = (cos t cos p, cos t sin p, sin t)
    right   = (sin p, -cos p, 0)
    down    = (cos p sin t, sin p sin t, -cos t)

Everything is vectorised over arrays of poses, because sub-steps arrive in
batches (R6.5). Standard library + numpy only (R2.2).
"""

from __future__ import annotations

from typing import Protocol

import numpy as np


class HasIntrinsics(Protocol):
    fx: float
    fy: float
    cx: float
    cy: float


def direction_from_azel(az, el):
    """Unit world direction(s) from azimuth/elevation (radians)."""
    az = np.asarray(az, dtype=float)
    el = np.asarray(el, dtype=float)
    ce = np.cos(el)
    return np.stack([ce * np.cos(az), ce * np.sin(az), np.sin(el)], axis=-1)


def azel_from_direction(d):
    """Azimuth/elevation (radians) from a world direction (need not be unit)."""
    d = np.asarray(d, dtype=float)
    x, y, z = d[..., 0], d[..., 1], d[..., 2]
    az = np.arctan2(y, x)
    el = np.arctan2(z, np.hypot(x, y))
    return az, el


def camera_axes(pan, tilt):
    """Return (right, down, forward) world-frame axes for pose(s).

    Each output has shape ``pan.shape + (3,)``.
    """
    pan = np.asarray(pan, dtype=float)
    tilt = np.asarray(tilt, dtype=float)
    cp, sp = np.cos(pan), np.sin(pan)
    ct, st = np.cos(tilt), np.sin(tilt)
    zero = np.zeros_like(cp)
    forward = np.stack([ct * cp, ct * sp, st], axis=-1)
    right = np.stack([sp, -cp, zero], axis=-1)
    down = np.stack([cp * st, sp * st, -ct], axis=-1)
    return right, down, forward


def project_direction(d, pan, tilt, intr: HasIntrinsics):
    """Project world direction(s) ``d`` into the image at pose(s) (pan, tilt).

    Returns ``(u, v, in_front)``. ``in_front`` is True where the direction is
    in front of the camera (positive forward component); u/v are NaN there.
    """
    d = np.asarray(d, dtype=float)
    right, down, forward = camera_axes(pan, tilt)
    x = np.sum(d * right, axis=-1)
    y = np.sum(d * down, axis=-1)
    z = np.sum(d * forward, axis=-1)
    in_front = z > 0.0
    z_safe = np.where(in_front, z, np.nan)
    u = intr.cx + intr.fx * (x / z_safe)
    v = intr.cy + intr.fy * (y / z_safe)
    return u, v, in_front


def project_azel(az, el, pan, tilt, intr: HasIntrinsics):
    """Project a target direction given as azimuth/elevation (radians)."""
    return project_direction(direction_from_azel(az, el), pan, tilt, intr)


def unproject(u, v, pan, tilt, intr: HasIntrinsics):
    """Back-project pixel(s) (u, v) at pose(s) to a unit world direction."""
    u = np.asarray(u, dtype=float)
    v = np.asarray(v, dtype=float)
    xc = (u - intr.cx) / intr.fx
    yc = (v - intr.cy) / intr.fy
    zc = np.ones_like(xc)
    right, down, forward = camera_axes(pan, tilt)
    # world = xc*right + yc*down + zc*forward
    d = (
        right * xc[..., None]
        + down * yc[..., None]
        + forward * zc[..., None]
    )
    norm = np.linalg.norm(d, axis=-1, keepdims=True)
    return d / norm


def angular_error_deg(pan, tilt, az, el):
    """Angle (degrees) between the camera boresight and the target direction.

    Always defined, including with the target out of the sensor or behind the
    camera, so a tracking summary can count every period and losing the target
    cannot improve the error (R12.2, m5). Returns a scalar or array matching the
    broadcast of the inputs.
    """
    _, _, forward = camera_axes(pan, tilt)
    d = direction_from_azel(az, el)
    cos = np.clip(np.sum(forward * d, axis=-1), -1.0, 1.0)
    return np.degrees(np.arccos(cos))


def pixel_radius(angular_radius_rad: float, intr: HasIntrinsics) -> float:
    """On-axis pixel radius of a disc of the given angular radius.

    A disc of angular radius r centred on the boresight projects to a circle of
    radius fx*tan(r). Off axis the projection is an ellipse; this on-axis value
    is used to size the ROI bounds (R6.7), which add a margin, so the simple
    circle model is adequate.
    """
    return float(intr.fx * np.tan(angular_radius_rad))


def in_fov(az, el, pan, tilt, intr: HasIntrinsics, width: int, height: int):
    """True where the target direction projects inside the sensor (R12.2).

    The sensor covers pixel centres u in [0, width-1], i.e. the area
    [-0.5, width-0.5] x [-0.5, height-0.5].
    """
    u, v, in_front = project_azel(az, el, pan, tilt, intr)
    inside = (
        in_front
        & (u >= -0.5)
        & (u <= width - 0.5)
        & (v >= -0.5)
        & (v <= height - 0.5)
    )
    return inside
