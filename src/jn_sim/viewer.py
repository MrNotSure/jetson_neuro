"""Live viewer (spec T14, R12.1, R2.4).

matplotlib runs in a separate ``spawn`` child process fed by a size-1 queue
that drops stale snapshots, so drawing can never stall the loop (R12.1). The
child shows the last period's events (ON/OFF in different colours) with a centre
crosshair and the true-target marker, a rolling 10 s plot of pan/tilt against
the target azimuth/elevation and the tracking error, and a status line.

This module imports matplotlib only inside the child entry point, so a run
without ``--view`` never imports it (R2.4). ``check_available`` fails before the
run starts if matplotlib is absent or there is no usable display.

Standard library only at module scope; simulation-host side.
"""

from __future__ import annotations

import contextlib
import importlib.util
import multiprocessing as mp
import queue
from typing import Any


class ViewerUnavailable(RuntimeError):
    """``--view`` cannot be honoured (no matplotlib, or no usable display)."""


def check_available(host, env: dict[str, str] | None = None) -> str:
    """Return the backend to use, or raise before the run starts (R2.4)."""
    if importlib.util.find_spec("matplotlib") is None:
        raise ViewerUnavailable(
            "matplotlib is not installed; install it with  pip install -e '.[view]'"
        )
    backend = host.viewer_backend(env)
    if backend is None:
        raise ViewerUnavailable(
            "no usable display for the viewer: set DISPLAY or WAYLAND_DISPLAY and "
            "install tkinter, or run without --view"
        )
    return backend


class Viewer:
    def __init__(self, backend: str, cfg) -> None:
        self.backend = backend
        self._view = {
            "width": cfg.camera.width,
            "height": cfg.camera.height,
            "cx": cfg.intrinsics().cx,
            "cy": cfg.intrinsics().cy,
            "max_fps": cfg.view.max_fps,
            "window_s": cfg.view.window_s,
        }
        self._ctx = mp.get_context("spawn")
        self._queue: mp.Queue = self._ctx.Queue(maxsize=1)
        self._stop = self._ctx.Event()
        self._ready = self._ctx.Event()
        self._proc: mp.process.BaseProcess | None = None

    def start(self) -> None:
        self._proc = self._ctx.Process(
            target=_viewer_main,
            args=(self.backend, self._view, self._queue, self._stop, self._ready),
            daemon=True,
        )
        self._proc.start()
        # Block until the child has initialised matplotlib, so its start-up
        # can't stall the first periods of the run (R12.1, B3).
        self._ready.wait(timeout=10.0)

    def update(self, snapshot: dict) -> None:
        """Enqueue the latest snapshot, dropping any stale one (never blocks)."""
        try:
            self._queue.get_nowait()
        except queue.Empty:
            pass
        try:
            self._queue.put_nowait(snapshot)
        except queue.Full:
            pass

    def close(self) -> None:
        if self._proc is None:
            return
        self._stop.set()  # the child breaks even if the queue is full
        self._proc.join(timeout=4.0)
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=1.0)
        # Close the queue's feeder thread so no semaphore is left behind (n1).
        with contextlib.suppress(Exception):
            self._queue.close()
            self._queue.join_thread()


def _viewer_main(backend: str, view: dict, q, stop, ready) -> None:  # pragma: no cover - child process
    import time
    from collections import deque

    import matplotlib

    matplotlib.use(backend)
    import matplotlib.pyplot as plt
    import numpy as np

    w, h = view["width"], view["height"]
    cx, cy = view["cx"], view["cy"]
    max_fps = view["max_fps"]
    window_s = view["window_s"]
    _NON_INTERACTIVE = {"agg", "pdf", "svg", "ps", "template", "cairo", "pgf"}
    interactive = backend.lower() not in _NON_INTERACTIVE

    fig, (ax_ev, ax_tr, ax_err) = plt.subplots(1, 3, figsize=(13, 4))
    if interactive:
        fig.canvas.manager.set_window_title("jn_sim live view")
    ax_ev.set_xlim(0, w)
    ax_ev.set_ylim(h, 0)
    ax_ev.set_title("events")
    ax_ev.axhline(cy, color="0.6", lw=0.5)
    ax_ev.axvline(cx, color="0.6", lw=0.5)
    on_sc = ax_ev.scatter([], [], s=3, c="#2ca02c")
    off_sc = ax_ev.scatter([], [], s=3, c="#d62728")
    tgt_mk, = ax_ev.plot([], [], "o", mfc="none", mec="#1f77b4", ms=10)

    hist: deque = deque()
    ax_tr.set_title("pan/tilt vs target (deg)")
    ax_err.set_title("tracking error (px)")
    status = fig.text(0.01, 0.01, "", fontsize=8, family="monospace")

    plt.tight_layout()
    if interactive:
        plt.show(block=False)
    ready.set()  # tell the parent the child is up (B3)

    last_draw = 0.0
    while not stop.is_set():
        try:
            snap = q.get(timeout=0.05)
        except queue.Empty:
            if interactive:
                plt.pause(0.001)
            continue
        if snap is None:
            break
        now = time.monotonic()
        if now - last_draw < 1.0 / max_fps:
            continue
        last_draw = now

        ev = snap["events"]
        on = ev[ev["p"] == 1]
        off = ev[ev["p"] == 0]
        on_sc.set_offsets(np.c_[on["x"], on["y"]] if on.size else np.empty((0, 2)))
        off_sc.set_offsets(np.c_[off["x"], off["y"]] if off.size else np.empty((0, 2)))
        if snap["in_fov"]:
            tgt_mk.set_data([snap["target_u"]], [snap["target_v"]])
        else:
            tgt_mk.set_data([], [])

        t = snap["sim_time"]
        hist.append((t, np.degrees(snap["pan"]), np.degrees(snap["tilt"]),
                     np.degrees(snap["target_az"]), np.degrees(snap["target_el"]),
                     snap["err_px"]))
        while hist and hist[0][0] < t - window_s:
            hist.popleft()
        arr = np.array(hist)
        ax_tr.clear()
        ax_tr.set_title("pan/tilt vs target (deg)")
        ax_tr.plot(arr[:, 0], arr[:, 1], "C0", label="pan")
        ax_tr.plot(arr[:, 0], arr[:, 3], "C0--", label="target az")
        ax_tr.plot(arr[:, 0], arr[:, 2], "C1", label="tilt")
        ax_tr.plot(arr[:, 0], arr[:, 4], "C1--", label="target el")
        ax_tr.legend(loc="upper right", fontsize=7)
        ax_err.clear()
        ax_err.set_title("tracking error (px)")
        ax_err.plot(arr[:, 0], arr[:, 5], "C3")

        status.set_text(
            f"k={snap['k']:>6}  t={t:6.2f}s  events={snap['n_events']:>6}  "
            f"sim={snap['sim_us']:>5}us  rtt={snap['rtt_us']}  "
            f"misses={snap.get('misses', snap['miss'])}"  # cumulative count (m9)
        )
        try:
            if interactive:
                fig.canvas.draw_idle()
                plt.pause(0.001)
            else:
                fig.canvas.draw()  # headless (Agg): render without a window
        except Exception:
            break
    plt.close(fig)
