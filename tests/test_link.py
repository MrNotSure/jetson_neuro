"""T10: Link adapters, endpoints, round trips, misses, episodes (R9, R8)."""

from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pytest

from jn_sim import protocol, provenance, testctl
from jn_sim.link import (
    Endpoint,
    EndpointError,
    InProcLink,
    TcpLink,
    make_link,
    parse_endpoint,
)
from jn_sim.protocol import Bye, Cmd, EVENT_DTYPE, Hello, HelloAck, Obs

EMPTY = np.empty(0, dtype=EVENT_DTYPE)


def _hello(episode: int = 0) -> Hello:
    return Hello(episode, 320, 240, 10000, 277.1, 277.1, 159.5, 119.5, 0.1, 0.2, 42)


def _obs(k: int, episode: int = 0, events=EMPTY) -> Obs:
    return Obs(episode, k, k * 10000, (k + 1) * 10000, events)


def _deadline(seconds: float = 5.0) -> float:
    return time.monotonic() + seconds


# -- endpoint parsing (R9.2) ----------------------------------------------- #
def test_parse_valid_endpoints() -> None:
    assert parse_endpoint("inproc:centroid") == Endpoint("inproc", name="centroid")
    assert parse_endpoint("tcp://127.0.0.1:5555") == Endpoint("tcp", host="127.0.0.1", port=5555)


@pytest.mark.parametrize(
    "endpoint",
    [
        "ssh://remote/5555",  # optional T11
        "@remote",  # optional T11
        "garbage",
        "tcp://nohost",
        "tcp://host:notaport",
        "tcp://host:0",
        "inproc:bad name",  # invalid controller name
    ],
)
def test_parse_invalid_endpoints(endpoint: str) -> None:
    with pytest.raises((EndpointError, protocol.ProtocolError)):
        parse_endpoint(endpoint)


def test_ssh_and_named_say_not_built() -> None:
    with pytest.raises(EndpointError, match="T11"):
        parse_endpoint("ssh://remote/5555")
    with pytest.raises(EndpointError, match="T11"):
        parse_endpoint("@remote")


# -- in-process adapter ----------------------------------------------------- #
def test_inproc_round_trip() -> None:
    link = make_link("inproc:hold")
    assert isinstance(link, InProcLink)
    name = link.open(_hello())
    assert name == "hold"
    assert link.controller_meta["name"] == "hold"
    cmd = link.exchange(_obs(0))
    assert cmd.pan == pytest.approx(0.1, rel=1e-5)
    assert cmd.tilt == pytest.approx(0.2, rel=1e-5)
    assert cmd.t_tx_ns >= cmd.t_rx_ns
    link.close()


# -- TCP round trip (R9.2) -------------------------------------------------- #
def test_tcp_round_trip_localhost(server_factory) -> None:
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=True)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link.open(_hello()) == "hold"
    assert link.controller_meta["name"] == "hold"
    for k in range(3):
        cmd = link.exchange(_obs(k), _deadline())
        assert cmd is not None and cmd.k == k
        assert cmd.pan == pytest.approx(0.1, rel=1e-5)
        assert cmd.t_tx_ns >= cmd.t_rx_ns
    link.send_bye(0)
    link.close()


# -- slow controller: miss + late reply discarded (R7.3) ------------------- #
class _SlowController:
    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.pan0 = 0.0
        self.tilt0 = 0.0

    def reset(self, hello) -> str:
        self.pan0, self.tilt0 = hello.pan0, hello.tilt0
        return "hold"

    def step(self, obs):
        time.sleep(self.delay)
        return self.pan0, self.tilt0


def test_slow_controller_miss_and_late_discard(server_factory) -> None:
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: _SlowController(0.2), meta, once=True)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    link.open(_hello())

    # Tight deadline: the controller is still sleeping -> a miss.
    assert link.exchange(_obs(0), _deadline(0.02)) is None

    # Let CMD_0 land in the buffer, then the next exchange must discard it
    # (k=0 < 1) and return CMD_1.
    time.sleep(0.3)
    cmd = link.exchange(_obs(1), _deadline(5.0))
    assert cmd is not None and cmd.k == 1
    link.close()


# -- several episodes over one connection (R8.3) --------------------------- #
def test_multiple_episodes_one_connection(server_factory) -> None:
    meta = provenance.controller_metadata("centroid", {})
    port = server_factory(lambda: testctl.make_controller("centroid"), meta, once=True)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    for e in range(3):
        assert link.open(_hello(e)) == "centroid"
        for k in range(2):
            cmd = link.exchange(_obs(k, episode=e), _deadline())
            assert cmd is not None and cmd.episode == e and cmd.k == k
        link.send_bye(e)
    link.close()


# -- flags returned by step arrive in the CMD (R8.11) ---------------------- #
class _FlagController:
    def reset(self, hello) -> str:
        return "hold"

    def step(self, obs):
        return 0.0, 0.0, protocol.FLAG_FAULT | protocol.FLAG_DETECT


def test_flags_from_step_arrive_in_cmd(server_factory) -> None:
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: _FlagController(), meta, once=True)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    link.open(_hello())
    cmd = link.exchange(_obs(0), _deadline())
    assert cmd.flags == (protocol.FLAG_FAULT | protocol.FLAG_DETECT)
    link.close()


# -- metadata that changes between episodes is rejected (R8.10) ------------ #
def test_metadata_change_between_episodes_rejected() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run_server() -> None:
        conn, _ = srv.accept()
        with conn:
            # episode 0
            protocol.read_message(conn)  # HELLO
            protocol.send_message(conn, HelloAck("hold", {"git_sha": "aaa"}))
            # episode 1 with DIFFERENT metadata
            protocol.read_message(conn)  # HELLO
            protocol.send_message(conn, HelloAck("hold", {"git_sha": "bbb"}))

    th = threading.Thread(target=run_server, daemon=True)
    th.start()
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    try:
        assert link.open(_hello(0)) == "hold"
        with pytest.raises(protocol.ProtocolError, match="metadata changed"):
            link.open(_hello(1))
    finally:
        link.close()
        srv.close()
        th.join(timeout=5)


# -- late CMD from a previous episode aborts the run (S1, abort) ----------- #
def _crafted_server(handler):
    """Start a one-connection server running ``handler(conn)``; return port."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]

    def run() -> None:
        conn, _ = srv.accept()
        with conn:
            handler(conn)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    return port, srv, th


def test_exchange_past_episode_cmd_aborts() -> None:
    # S1 (abort): a CMD from an earlier episode is malformed, not discarded.
    def handler(conn):
        protocol.read_message(conn)  # HELLO (episode 1)
        protocol.send_message(conn, HelloAck("hold", {"git_sha": "x"}))
        protocol.read_message(conn)  # OBS (episode 1)
        protocol.send_message(conn, Cmd(0, 7, 0.0, 0.0))  # stale, episode 0

    port, srv, th = _crafted_server(handler)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    try:
        link.open(_hello(1))
        with pytest.raises(protocol.ProtocolError, match="episode 0.*during episode 1"):
            link.exchange(_obs(0, episode=1), _deadline())
    finally:
        link.close()
        srv.close()
        th.join(timeout=5)


def test_open_rejects_cmd_during_handshake() -> None:
    # S1: no stale-CMD discard; a CMD before HELLO_ACK is malformed.
    def handler(conn):
        protocol.read_message(conn)  # HELLO
        protocol.send_message(conn, Cmd(0, 3, 0.0, 0.0))  # not a HELLO_ACK

    port, srv, th = _crafted_server(handler)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    try:
        with pytest.raises(protocol.ProtocolError):
            link.open(_hello(1))
    finally:
        link.close()
        srv.close()
        th.join(timeout=5)


def test_exchange_future_episode_cmd_aborts() -> None:
    def handler(conn):
        protocol.read_message(conn)  # HELLO (episode 0)
        protocol.send_message(conn, HelloAck("hold", {}))
        protocol.read_message(conn)  # OBS (episode 0)
        protocol.send_message(conn, Cmd(2, 0, 0.0, 0.0))  # a later episode

    port, srv, th = _crafted_server(handler)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    try:
        link.open(_hello(0))
        with pytest.raises(protocol.ProtocolError, match="episode"):
            link.exchange(_obs(0, episode=0), _deadline())
    finally:
        link.close()
        srv.close()
        th.join(timeout=5)


def test_exchange_future_period_cmd_aborts() -> None:
    # M6/M20: a CMD for a future period of the current episode is malformed.
    def handler(conn):
        protocol.read_message(conn)  # HELLO (episode 0)
        protocol.send_message(conn, HelloAck("hold", {}))
        protocol.read_message(conn)  # OBS (episode 0, k=0)
        protocol.send_message(conn, Cmd(0, 5, 0.0, 0.0))  # future period

    port, srv, th = _crafted_server(handler)
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    try:
        link.open(_hello(0))
        with pytest.raises(protocol.ProtocolError, match="future period"):
            link.exchange(_obs(0, episode=0), _deadline())
    finally:
        link.close()
        srv.close()
        th.join(timeout=5)


# -- connect retry / timeout (R7.7) ---------------------------------------- #
def test_connect_timeout_raises_quickly() -> None:
    # Nothing is listening on this port; connect should give up after the
    # short timeout with a clear error.
    link = TcpLink("127.0.0.1", 1, connect_timeout=0.4, retry_interval=0.1)
    start = time.monotonic()
    with pytest.raises(ConnectionError):
        link.open(_hello())
    assert time.monotonic() - start < 3.0
