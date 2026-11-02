"""Shared test fixtures: a controller server in a background thread."""

from __future__ import annotations

import queue
import threading

import pytest

from jn_sim import ctl


@pytest.fixture
def server_factory():
    """Start ``ctl.serve`` in a daemon thread; returns the bound port.

    Cleans up by signalling the stop event and joining the thread(s).
    """
    stops: list[threading.Event] = []
    threads: list[threading.Thread] = []

    def start(
        factory,
        meta,
        once: bool = False,
        handshake_timeout: float = 15.0,
        idle_timeout: float = 30.0,
    ) -> int:
        stop = threading.Event()
        portq: "queue.Queue[int]" = queue.Queue()
        th = threading.Thread(
            target=ctl.serve,
            kwargs=dict(
                factory=factory,
                meta=meta,
                host="127.0.0.1",
                port=0,
                once=once,
                on_ready=lambda addr: portq.put(addr[1]),
                should_stop=stop.is_set,
                poll=0.02,
                handshake_timeout=handshake_timeout,
                idle_timeout=idle_timeout,
            ),
            daemon=True,
        )
        th.start()
        stops.append(stop)
        threads.append(th)
        return portq.get(timeout=5)

    yield start

    for stop in stops:
        stop.set()
    for th in threads:
        th.join(timeout=5)
