"""T8: event model — thresholds, refractory, noise, determinism (R6)."""

from __future__ import annotations

import numpy as np
import pytest

from jn_sim import seeding
from jn_sim.config import Config
from jn_sim.events import EventModel
from jn_sim.protocol import EVENT_DTYPE


def _model(width=1, height=1, sigma=0.0, refractory=0.0, noise=0.0, seed=0) -> EventModel:
    cfg = Config()
    cfg.camera.width = width
    cfg.camera.height = height
    cfg.events.threshold_sigma = sigma
    cfg.events.refractory_s = refractory
    cfg.events.noise_rate_hz = noise
    return EventModel(cfg, seed)


def test_rise_of_3_5_thresholds_gives_3_on_events() -> None:
    m = _model()
    theta = m.theta_on[0]
    m.reset_episode(np.zeros((1, 1)))
    ev = m.update(np.zeros((1, 1)), np.full((1, 1), 3.5 * theta), 0.0, 0.01)
    assert ev.size == 3
    assert np.all(ev["p"] == 1)
    assert np.all(ev["x"] == 0) and np.all(ev["y"] == 0)
    expected_us = np.rint(np.array([1, 2, 3]) / 3.5 * 0.01 * 1e6).astype(np.uint32)
    assert np.array_equal(ev["t"], expected_us)


def test_fall_gives_off_events() -> None:
    m = _model()
    theta = m.theta_off[0]
    m.reset_episode(np.zeros((1, 1)))
    ev = m.update(np.zeros((1, 1)), np.full((1, 1), -3.5 * theta), 0.0, 0.01)
    assert ev.size == 3
    assert np.all(ev["p"] == 0)


def test_refractory_drops_events() -> None:
    theta = _model().theta_on[0]
    frame = np.full((1, 1), 3.5 * theta)

    m0 = _model(refractory=0.0)
    m0.reset_episode(np.zeros((1, 1)))
    assert m0.update(np.zeros((1, 1)), frame, 0.0, 0.01).size == 3

    m1 = _model(refractory=1.0)  # longer than the whole sub-step
    m1.reset_episode(np.zeros((1, 1)))
    assert m1.update(np.zeros((1, 1)), frame, 0.0, 0.01).size == 1


def test_no_change_no_noise_gives_zero_events() -> None:
    m = _model(width=16, height=16, sigma=0.03, noise=0.0)
    m.reset_episode(np.zeros((16, 16)))
    ev = m.update(np.zeros((16, 16)), np.zeros((16, 16)), 0.0, 0.01)
    assert ev.size == 0
    rng = seeding.noise_rng(0, 0)
    assert m.noise(0.0, 0.01, rng).size == 0


def test_noise_rate_within_5_percent() -> None:
    m = _model(width=320, height=240, noise=0.1)
    rng = seeding.noise_rng(0, 0)
    seconds = 10.0
    ev = m.noise(0.0, seconds, rng)
    rate = ev.size / (m.n * seconds)
    assert rate == pytest.approx(0.1, rel=0.05)


def test_deterministic_and_sorted() -> None:
    def run(seed: int):
        m = _model(width=8, height=8, sigma=0.03, seed=seed)
        m.reset_episode(np.zeros((8, 8)))
        grad = np.linspace(-0.5, 0.5, 64).reshape(8, 8)
        return m.update(np.zeros((8, 8)), grad, 0.0, 0.01)

    a = run(0)
    b = run(0)
    assert a.dtype == EVENT_DTYPE
    assert np.array_equal(a.view(np.uint8), b.view(np.uint8))  # bit-identical
    assert np.all(np.diff(a["t"].astype(np.int64)) >= 0)  # sorted by time
    # both ON and OFF appear (gradient rises and falls across the reference)
    assert np.any(a["p"] == 1) and np.any(a["p"] == 0)


def test_output_dtype_is_event_dtype() -> None:
    m = _model()
    m.reset_episode(np.zeros((1, 1)))
    ev = m.update(np.zeros((1, 1)), np.full((1, 1), 0.5), 0.0, 0.01)
    assert ev.dtype == EVENT_DTYPE
    assert ev.dtype.itemsize == 9


def _union(b1, b2):
    v0 = min(b1[0], b2[0])
    v1 = max(b1[1], b2[1])
    u0 = min(b1[2], b2[2])
    u1 = max(b1[3], b2[3])
    return v0, v1, u0, u1


def test_thresholds_drawn_from_on_off_streams() -> None:
    # M8: ON thresholds come from key (0,), OFF from (1,).
    cfg = Config()
    cfg.camera.width = 8
    cfg.camera.height = 8
    cfg.events.threshold_sigma = 0.03
    seed = 123
    m = EventModel(cfg, seed)
    e = cfg.events
    exp_on = np.maximum(
        seeding.on_threshold_rng(seed).normal(e.threshold_median, e.threshold_sigma, size=(8, 8)),
        e.threshold_min,
    ).ravel()
    exp_off = np.maximum(
        seeding.off_threshold_rng(seed).normal(e.threshold_median, e.threshold_sigma, size=(8, 8)),
        e.threshold_min,
    ).ravel()
    assert np.array_equal(m.theta_on, exp_on)
    assert np.array_equal(m.theta_off, exp_off)


def test_thresholds_clipped_at_floor() -> None:
    # m7/M13: a large spread still clips at threshold_min (no <= 0 thresholds).
    cfg = Config()
    cfg.camera.width = 64
    cfg.camera.height = 64
    cfg.events.threshold_sigma = 0.2  # wide enough to draw values below the floor
    cfg.events.threshold_min = 0.01
    m = EventModel(cfg, seed=0)
    assert m.theta_on.min() >= 0.01
    assert m.theta_off.min() >= 0.01


def test_noise_has_both_polarities() -> None:
    # m7/M23: shot noise has random polarity, not always ON.
    m = _model(width=320, height=240, noise=0.1)
    ev = m.noise(0.0, 10.0, seeding.noise_rng(0, 0))
    assert np.any(ev["p"] == 0) and np.any(ev["p"] == 1)


def test_noise_timestamps_below_t_end() -> None:
    # m6: an event in [t_start, t_end) is never stamped at t_end_us.
    m = _model(width=320, height=240, noise=5.0)
    ev = m.noise(0.0, 0.01, seeding.noise_rng(0, 0))
    assert ev.size > 0
    assert ev["t"].max() < 10000  # t_end = 0.01 s = 10000 us


def test_region_update_equals_full_frame() -> None:
    # R6.7 / M10: the ROI path gives events (and state) identical to the full
    # frame, while touching only the region the target can cover.
    from jn_sim.render import Renderer

    cfg = Config()  # default 320x240 uniform background
    r = Renderer(cfg)
    pose_a = (0.05, 0.0, 0.05, 0.0)
    pose_b = (0.06, 0.01, 0.075, 0.02)
    la = r.render_full(*pose_a)
    lb = r.render_full(*pose_b)

    full = EventModel(cfg, seed=0)
    full.reset_episode(la)
    ev_full = full.update(la, lb, 0.0, 0.01)

    region = EventModel(cfg, seed=0)
    region.reset_episode(la)
    box = _union(r.roi_box(*pose_a), r.roi_box(*pose_b))
    v0, v1, u0, u1 = box
    ev_region = region.update_region(la[v0:v1, u0:u1], lb[v0:v1, u0:u1], box, 0.0, 0.01)

    assert ev_full.size > 0
    assert np.array_equal(ev_full.view(np.uint8), ev_region.view(np.uint8))
    assert np.array_equal(full.ref, region.ref)
    assert np.array_equal(full.last_t, region.last_t)
