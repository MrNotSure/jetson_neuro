"""T14: live viewer — availability checks and clean start/stop (R12.1, R2.4)."""

from __future__ import annotations

import time

import numpy as np
import pytest

from jn_sim import viewer as viewermod
from jn_sim.config import Config
from jn_sim.host import Host
from jn_sim.protocol import EVENT_DTYPE
from jn_sim.viewer import Viewer, ViewerUnavailable, check_available


def test_check_available_requires_matplotlib(monkeypatch) -> None:
    monkeypatch.setattr(viewermod.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(ViewerUnavailable, match="matplotlib"):
        check_available(Host(), env={"MPLBACKEND": "Agg"})


def test_check_available_requires_display() -> None:
    # Linux host with no DISPLAY -> no backend -> unavailable, before the run.
    with pytest.raises(ViewerUnavailable, match="display"):
        check_available(Host(os_name="linux"), env={})


def test_check_available_returns_backend() -> None:
    assert check_available(Host(), env={"MPLBACKEND": "Agg"}) == "Agg"
    assert check_available(Host(os_name="macos"), env={}) == "macosx"


def test_viewer_starts_and_stops_cleanly() -> None:
    cfg = Config()
    v = Viewer("Agg", cfg)
    v.start()
    for k in range(4):
        ev = np.zeros(20, dtype=EVENT_DTYPE)
        ev["x"] = 160
        ev["y"] = 120
        ev["p"] = k % 2
        v.update({
            "k": k, "sim_time": k * 0.01, "events": ev, "target_u": 160.0, "target_v": 120.0,
            "pan": 0.0, "tilt": 0.0, "target_az": 0.0, "target_el": 0.0, "err_px": 1.0,
            "in_fov": 1, "n_events": 20, "sim_us": 100, "rtt_us": 50, "miss": 0,
            "width": 320, "height": 240, "cx": 159.5, "cy": 119.5,
        })
        time.sleep(0.03)
    time.sleep(0.2)
    v.close()
    assert v._proc.exitcode == 0
