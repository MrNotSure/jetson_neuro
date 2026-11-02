"""Test controllers (spec T10, R11). Shared with the Jetson controller.

These are fixtures for exercising the loop, not algorithms A-D.

* ``hold`` always returns the initial setpoint (R11.1); it doubles as the
  measurement harness's no-op controller.
* ``centroid`` takes the mean position of a period's events, turns it into an
  angular error with the intrinsics, and adds gain x error to its setpoint,
  skipping periods with fewer than ``n_min`` events (R11.2).

A controller implements ``reset(hello) -> name`` and ``step(obs) -> (pan, tilt)``
or ``(pan, tilt, flags)`` (R8.1). Standard library + numpy only (R1.3).
"""

from __future__ import annotations

import math
from typing import Any


def _check_params(params: dict[str, Any] | None, allowed: set[str], name: str) -> dict[str, Any]:
    params = dict(params or {})
    unknown = set(params) - allowed
    if unknown:
        raise ValueError(
            f"{name}: unknown parameter(s) {', '.join(sorted(unknown))}; allowed: "
            f"{', '.join(sorted(allowed)) or '(none)'}"
        )
    return params


class HoldController:
    """Always commands the initial setpoint (R11.1)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        _check_params(params, set(), "hold")
        self.params: dict[str, Any] = {}  # effective parameters (R8.10)
        self._pan0 = 0.0
        self._tilt0 = 0.0

    def reset(self, hello) -> str:
        self._pan0 = float(hello.pan0)
        self._tilt0 = float(hello.tilt0)
        return "hold"

    def step(self, obs):
        return self._pan0, self._tilt0


class CentroidController:
    """Event-centroid tracker with integral action on the image error (R11.2)."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        given = _check_params(params, {"gain", "n_min"}, "centroid")
        self.gain = float(given.get("gain", 0.2))  # tuned in T12 (was 0.05)
        self.n_min = int(given.get("n_min", 200))
        # effective parameters, recorded in the metadata (R8.10, m3)
        self.params: dict[str, Any] = {"gain": self.gain, "n_min": self.n_min}
        self.fx = self.fy = 1.0
        self.cx = self.cy = 0.0
        self.pan = 0.0
        self.tilt = 0.0

    def reset(self, hello) -> str:
        self.fx = float(hello.fx)
        self.fy = float(hello.fy)
        self.cx = float(hello.cx)
        self.cy = float(hello.cy)
        self.pan = float(hello.pan0)
        self.tilt = float(hello.tilt0)
        return "centroid"

    def step(self, obs):
        events = obs.events
        if events.size < self.n_min:
            return self.pan, self.tilt  # too few events: hold
        u = float(events["x"].mean())
        v = float(events["y"].mean())
        # Angular error of the centroid relative to the boresight. A target to
        # the right (u > cx) is at negative azimuth; driving the setpoint by its
        # relative angle centres it (R3.4).
        rel_az = -math.atan((u - self.cx) / self.fx)
        rel_el = -math.atan((v - self.cy) / self.fy)
        self.pan += self.gain * rel_az
        self.tilt += self.gain * rel_el
        return self.pan, self.tilt


def make_controller(name: str, params: dict[str, Any] | None = None):
    if name == "hold":
        return HoldController(params)
    if name == "centroid":
        return CentroidController(params)
    if name == "classical":
        # Controller A (spec_ctl_a.md R1.2), imported lazily so the hold and
        # centroid paths never load it.
        from .classical import ClassicalController

        return ClassicalController(params)
    raise ValueError(
        f"unknown controller {name!r} (choose 'hold', 'centroid' or 'classical')"
    )
