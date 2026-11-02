"""T10/R11: test controllers — n_min skip, parameter validation (m3, m7)."""

from __future__ import annotations

import numpy as np
import pytest

from jn_sim.protocol import EVENT_DTYPE, Hello, Obs
from jn_sim.testctl import CentroidController, make_controller


def _hello() -> Hello:
    return Hello(0, 320, 240, 10000, 277.1, 277.1, 159.5, 119.5, 0.0, 0.0, 1)


def _obs(n: int) -> Obs:
    ev = np.zeros(n, dtype=EVENT_DTYPE)
    ev["x"] = 220  # right of cx=159.5
    ev["y"] = 119
    return Obs(0, 0, 0, 10000, ev)


def test_centroid_skips_below_n_min() -> None:
    # m7/M24: with fewer than n_min events the setpoint is held.
    c = CentroidController({"gain": 0.05, "n_min": 50})
    c.reset(_hello())
    start = (c.pan, c.tilt)
    assert c.step(_obs(10)) == start  # too few events -> hold
    moved = c.step(_obs(100))  # >= n_min -> move
    assert moved != start


def test_centroid_rejects_unknown_param() -> None:
    with pytest.raises(ValueError):
        make_controller("centroid", {"gian": 0.1})  # typo'd key


def test_hold_rejects_any_param() -> None:
    with pytest.raises(ValueError):
        make_controller("hold", {"gain": 0.1})


def test_centroid_records_effective_params() -> None:
    c = make_controller("centroid", {"gain": 0.07})
    assert c.params == {"gain": 0.07, "n_min": 200}


def test_hold_has_no_params() -> None:
    assert make_controller("hold").params == {}
