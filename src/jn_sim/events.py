"""Event model (spec T8, R6).

The standard DVS model on log intensity (R6.1): each pixel holds a reference
level and a last-event time; per-pixel ON/OFF thresholds are drawn once per seed
(R6.2) and persist across episodes (R8.3). Between two sub-step frames the log
intensity is taken to move linearly, so every threshold crossing emits an event
with a linearly interpolated timestamp (R6.5). Events inside the per-pixel
refractory period are dropped (R6.3). Shot noise is added per period over the
whole frame (R6.4).

Thresholds come from the ON/OFF streams (keys (0,), (1,)); noise from the
episode noise stream (key (3, e)). Noise draws are a pure function of the seed,
episode and period -- never of the gimbal or the controller's commands (R2.5,
R7.4). Output is sorted by time and uses ``protocol.EVENT_DTYPE`` (R6.6).

Standard library + numpy only (R2.2).
"""

from __future__ import annotations

import numpy as np

from . import seeding
from .config import Config
from .protocol import EVENT_DTYPE

_EMPTY = np.empty(0, dtype=EVENT_DTYPE)


def empty_batch() -> np.ndarray:
    return _EMPTY.copy()


def sort_batch(events: np.ndarray) -> np.ndarray:
    """Return the events in a total order: time, then y, x, polarity (R6.6).

    A total order (not just by time) makes a batch independent of the pixel
    scan order, so the full-frame and ROI paths produce byte-identical output
    (R6.7, M10)."""
    if events.size <= 1:
        return events
    order = np.lexsort((events["p"], events["x"], events["y"], events["t"]))
    return events[order]


def combine(batches: list[np.ndarray]) -> np.ndarray:
    """Concatenate per-sub-step and noise batches, then sort by time (R6.6)."""
    nonempty = [b for b in batches if b.size]
    if not nonempty:
        return empty_batch()
    return sort_batch(np.concatenate(nonempty))


class EventModel:
    def __init__(self, cfg: Config, seed: int) -> None:
        self.width = int(cfg.camera.width)
        self.height = int(cfg.camera.height)
        self.n = self.width * self.height
        self._all_idx = np.arange(self.n)
        ev = cfg.events
        self.refractory = float(ev.refractory_s)
        self.noise_rate = float(ev.noise_rate_hz)

        # Per-pixel thresholds, drawn once per seed and clipped (R6.2). ON and
        # OFF come from independent streams, so they never shift each other.
        on_rng = seeding.on_threshold_rng(seed)
        off_rng = seeding.off_threshold_rng(seed)
        shape = (self.height, self.width)
        self.theta_on = np.maximum(
            on_rng.normal(ev.threshold_median, ev.threshold_sigma, size=shape),
            ev.threshold_min,
        ).ravel()
        self.theta_off = np.maximum(
            off_rng.normal(ev.threshold_median, ev.threshold_sigma, size=shape),
            ev.threshold_min,
        ).ravel()

        self.ref: np.ndarray | None = None
        self.last_t: np.ndarray | None = None

    # -- episode state (thresholds persist; reference and timing reset) ---- #
    def reset_episode(self, initial_log_frame: np.ndarray) -> None:
        self.ref = initial_log_frame.astype(float).ravel().copy()
        self.last_t = np.full(self.n, -np.inf, dtype=float)

    # -- scene events between two sub-step frames (R6.1, R6.5) ------------- #
    def update(
        self, l_prev: np.ndarray, l_new: np.ndarray, t_prev: float, t_new: float
    ) -> np.ndarray:
        """Full-frame event generation (the reference path, R6.7)."""
        if self.ref is None or self.last_t is None:
            raise RuntimeError("reset_episode() must be called before update()")
        return self._update_pixels(
            self._all_idx, np.asarray(l_prev).ravel(), np.asarray(l_new).ravel(), t_prev, t_new
        )

    def update_region(
        self,
        l_prev_box: np.ndarray,
        l_new_box: np.ndarray,
        box: tuple[int, int, int, int],
        t_prev: float,
        t_new: float,
    ) -> np.ndarray:
        """Event generation over a sub-region only (R6.7, M10).

        ``box`` is ``(v0, v1, u0, u1)`` and the patches are that slice of the
        frame. With a uniform background, the pixels outside the box cannot
        change, so this gives events identical to :meth:`update` over the whole
        frame, while touching only the region.
        """
        if self.ref is None or self.last_t is None:
            raise RuntimeError("reset_episode() must be called before update_region()")
        v0, v1, u0, u1 = box
        rows = np.arange(v0, v1)
        cols = np.arange(u0, u1)
        idx = (rows[:, None] * self.width + cols[None, :]).ravel()
        return self._update_pixels(
            idx, np.asarray(l_prev_box).ravel(), np.asarray(l_new_box).ravel(), t_prev, t_new
        )

    def _update_pixels(self, idx, lp, ln, t_prev, t_new) -> np.ndarray:
        ref = self.ref[idx]
        ton = self.theta_on[idx]
        tof = self.theta_off[idx]

        up = ln > ref
        dn = ln < ref
        n_on = np.where(up, np.floor((ln - ref) / ton), 0.0).astype(np.int64)
        n_off = np.where(dn, np.floor((ref - ln) / tof), 0.0).astype(np.int64)

        loc_on, t_on = self._emit(n_on, ref, ton, lp, ln, t_prev, t_new, +1.0)
        loc_off, t_off = self._emit(n_off, ref, tof, lp, ln, t_prev, t_new, -1.0)

        # Advance the reference by the thresholds crossed (R6.1).
        self.ref[idx] = ref + n_on * ton - n_off * tof

        # Map local positions back to global pixel indices.
        pix = np.concatenate([idx[loc_on], idx[loc_off]])
        t_s = np.concatenate([t_on, t_off])
        pol = np.concatenate(
            [np.ones(loc_on.size, dtype=np.uint8), np.zeros(loc_off.size, dtype=np.uint8)]
        )
        pix, t_s, pol = self._apply_refractory(pix, t_s, pol)
        return self._build(pix, t_s, pol)

    # -- shot noise over the whole frame for a period (R6.4) --------------- #
    def noise(self, t_start: float, t_end: float, rng: np.random.Generator) -> np.ndarray:
        if self.noise_rate <= 0.0:
            return empty_batch()
        duration = t_end - t_start
        lam = self.noise_rate * duration
        # Fixed-shape per-pixel Poisson draw, independent of the scene (R2.5).
        counts = rng.poisson(lam, size=self.n)
        total = int(counts.sum())
        if total == 0:
            return empty_batch()
        pix = np.repeat(np.arange(self.n), counts)
        t_s = t_start + rng.uniform(0.0, duration, size=total)
        pol = rng.integers(0, 2, size=total).astype(np.uint8)
        return self._build(pix, t_s, pol)

    # -- internals --------------------------------------------------------- #
    def _emit(self, counts, ref, theta, lp, ln, t0, t1, sign):
        total = int(counts.sum())
        if total == 0:
            return np.empty(0, dtype=np.int64), np.empty(0, dtype=float)
        pix = np.repeat(np.arange(counts.size), counts)
        k = _ranges(counts)  # 1..counts[i] per event
        level = ref[pix] + sign * k * theta[pix]
        denom = (ln - lp)[pix]
        with np.errstate(divide="ignore", invalid="ignore"):
            frac = (level - lp[pix]) / denom
        frac = np.where(np.isfinite(frac), frac, 1.0)
        frac = np.clip(frac, 0.0, 1.0)
        t_s = t0 + frac * (t1 - t0)
        return pix, t_s

    def _apply_refractory(self, pix, t_s, pol):
        assert self.last_t is not None
        if pix.size == 0:
            return pix, t_s, pol
        if self.refractory <= 0.0:
            np.maximum.at(self.last_t, pix, t_s)
            return pix, t_s, pol
        # Greedy per-pixel refractory, vectorised over event rank-within-pixel.
        order = np.lexsort((t_s, pix))
        pix_s, t_sort, pol_s = pix[order], t_s[order], pol[order]
        _, first_idx, counts = np.unique(pix_s, return_index=True, return_counts=True)
        ranks = np.arange(pix_s.size) - np.repeat(first_idx, counts)
        accepted = np.zeros(pix_s.size, dtype=bool)
        last = self.last_t
        for r in range(int(counts.max())):
            sel = np.nonzero(ranks == r)[0]
            if sel.size == 0:
                continue
            p = pix_s[sel]
            tt = t_sort[sel]
            ok = tt >= last[p] + self.refractory
            accepted[sel] = ok
            last[p[ok]] = tt[ok]
        return pix_s[accepted], t_sort[accepted], pol_s[accepted]

    def _build(self, pix, t_s, pol) -> np.ndarray:
        ev = np.empty(pix.size, dtype=EVENT_DTYPE)
        # Floor to microseconds so an event in [t_start, t_end) can never be
        # stamped at t_end_us (m6); period k covers [kT, (k+1)T).
        t_us = np.floor(np.asarray(t_s) * 1e6)
        ev["t"] = np.clip(t_us, 0, np.iinfo(np.uint32).max).astype(np.uint32)
        ev["x"] = (pix % self.width).astype(np.uint16)
        ev["y"] = (pix // self.width).astype(np.uint16)
        ev["p"] = np.asarray(pol, dtype=np.uint8)
        return sort_batch(ev)


def _ranges(counts: np.ndarray) -> np.ndarray:
    """Concatenated 1..counts[i] for each i (1-based within-group index)."""
    total = int(counts.sum())
    idx = np.arange(total)
    offsets = np.repeat(np.cumsum(counts) - counts, counts)
    return idx - offsets + 1
