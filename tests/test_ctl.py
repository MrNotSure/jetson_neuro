"""T10: controller runner — usage, serve one-at-a-time, provenance (R8.6, R8.10)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from jn_sim import ctl, protocol, provenance, testctl
from jn_sim.ctl import CtlUsageError, parse_listen, parse_params
from jn_sim.link import TcpLink
from jn_sim.protocol import EVENT_DTYPE, Hello, Obs

# The provenance tests check that the running code's commit SHA is recorded.
# Outside a git checkout with a commit (a ZIP download, say) there is no SHA
# to record, so they skip instead of failing.
needs_git_checkout = pytest.mark.skipif(
    provenance.git_info()["sha"] == "unknown",
    reason="not a git checkout with a commit: no SHA to record",
)

import numpy as np

EMPTY = np.empty(0, dtype=EVENT_DTYPE)


def _hello() -> Hello:
    return Hello(0, 320, 240, 10000, 277.1, 277.1, 159.5, 119.5, 0.0, 0.0, 1)


# -- argument parsing ------------------------------------------------------- #
def test_parse_params_coerces_types() -> None:
    p = parse_params(["gain=0.05", "n_min=200", "label=foo"])
    assert p == {"gain": 0.05, "n_min": 200, "label": "foo"}
    assert isinstance(p["n_min"], int) and isinstance(p["gain"], float)


def test_parse_params_bad() -> None:
    with pytest.raises(CtlUsageError):
        parse_params(["noequals"])


def test_parse_listen() -> None:
    assert parse_listen(None) == ("127.0.0.1", 5555)
    assert parse_listen("0.0.0.0:6000") == ("0.0.0.0", 6000)
    assert parse_listen("127.0.0.1:0") == ("127.0.0.1", 0)  # ephemeral is allowed
    with pytest.raises(CtlUsageError):
        parse_listen("noport")


def test_parse_listen_rejects_out_of_range() -> None:
    with pytest.raises(CtlUsageError):
        parse_listen("127.0.0.1:70000")  # would OverflowError at bind (m8)


def test_main_rejects_out_of_range_listen() -> None:
    args = SimpleNamespace(
        controller="hold", param=[], listen="127.0.0.1:70000", once=True, idle_timeout=30.0
    )
    assert ctl.main(args) == 2  # usage error, not a traceback


# -- startup validation (R8.6, R8.7) --------------------------------------- #
@pytest.mark.parametrize("name", ["bogus", "bad name", ""])
def test_main_rejects_bad_controller(name: str) -> None:
    args = SimpleNamespace(controller=name, param=[], listen=None, once=True)
    assert ctl.main(args) == 2


# -- serve one at a time (R8.6) -------------------------------------------- #
def test_once_serves_one_connection(server_factory) -> None:
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=True)

    link1 = TcpLink("127.0.0.1", port, connect_timeout=5)
    link1.open(_hello())
    link1.exchange(Obs(0, 0, 0, 10000, EMPTY), time.monotonic() + 5)
    link1.close()
    time.sleep(0.1)  # let the server finish and stop listening

    # With --once the server is gone; a second connection fails quickly.
    link2 = TcpLink("127.0.0.1", port, connect_timeout=0.4, retry_interval=0.1)
    with pytest.raises(ConnectionError):
        link2.open(_hello())


def test_without_once_second_connection_succeeds(server_factory) -> None:
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=False)

    link1 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link1.open(_hello()) == "hold"
    link1.close()
    time.sleep(0.1)

    link2 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link2.open(_hello()) == "hold"
    link2.close()


# -- provenance metadata (R8.10) ------------------------------------------- #
@needs_git_checkout
def test_metadata_reports_sha_and_dirty() -> None:
    meta = provenance.controller_metadata("hold", {"gain": 0.05})
    assert meta["name"] == "hold"
    assert meta["params"] == {"gain": 0.05}
    assert meta["fault"] is None and meta["stage_log"] is None
    assert meta["git_sha"] != "unknown" and len(meta["git_sha"]) == 40
    assert isinstance(meta["git_dirty"], bool)
    assert meta["numpy"] == np.__version__


def test_metadata_unknown_when_git_hidden(monkeypatch) -> None:
    monkeypatch.setenv("PATH", "/nonexistent-path-for-this-test")
    meta = provenance.controller_metadata("hold", {})
    assert meta["git_sha"] == "unknown"
    assert meta["git_dirty"] is None


@needs_git_checkout
def test_metadata_sha_independent_of_cwd(monkeypatch, tmp_path) -> None:
    # The SHA comes from the running code's checkout, not the process cwd (M3).
    monkeypatch.chdir(tmp_path)  # a directory with no git repo
    meta = provenance.controller_metadata("hold", {})
    assert meta["git_sha"] != "unknown" and len(meta["git_sha"]) == 40


# -- B1: the server survives a bad or broken connection -------------------- #
def test_server_survives_garbage_then_serves(server_factory) -> None:
    import socket

    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=False)

    # 20 garbage bytes -> bad magic on the server -> connection dropped.
    c1 = socket.create_connection(("127.0.0.1", port), timeout=5)
    c1.sendall(b"not-a-valid-header!!")
    c1.close()
    time.sleep(0.2)

    # The server is still alive and serves a proper client.
    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link.open(_hello()) == "hold"
    link.close()


def test_server_survives_peer_death_midrun(server_factory) -> None:
    import socket
    import struct

    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=False)

    link1 = TcpLink("127.0.0.1", port, connect_timeout=5)
    link1.open(_hello())
    link1.exchange(Obs(0, 0, 0, 10000, EMPTY), time.monotonic() + 5)
    # Abortive close (SO_LINGER 0) sends a RST, so the server sees a
    # ConnectionResetError (OSError), exercising that handler (B1).
    link1.sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    link1.sock.close()
    link1.sock = None
    time.sleep(0.2)

    link2 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link2.open(_hello()) == "hold"
    link2.close()


def test_server_drops_silent_peer_midrun(server_factory) -> None:
    # B1: a peer that completes the handshake then goes silent is dropped after
    # the idle timeout, so it can't wedge the single-threaded server.
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(
        lambda: testctl.make_controller("hold"), meta, once=False, idle_timeout=0.3
    )
    link1 = TcpLink("127.0.0.1", port, connect_timeout=5)
    link1.open(_hello())  # handshake done, then send no OBS
    time.sleep(0.6)  # server drops the idle connection after ~0.3 s

    link2 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link2.open(_hello()) == "hold"
    link2.close()
    link1.close()


def test_ctl_rejects_obs_for_wrong_episode(server_factory) -> None:
    # An OBS for an episode other than the current one is malformed; the server
    # drops that connection but keeps serving (R8.5, M6).
    meta = provenance.controller_metadata("hold", {})
    port = server_factory(lambda: testctl.make_controller("hold"), meta, once=False)

    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    link.open(_hello())  # HELLO episode 0
    with pytest.raises(protocol.ProtocolError):
        link.exchange(Obs(1, 0, 0, 10000, EMPTY), time.monotonic() + 3)  # OBS episode 1
    link.close()

    link2 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link2.open(_hello()) == "hold"  # the server survived
    link2.close()


def test_server_survives_controller_exception(server_factory) -> None:
    # B1: an exception raised by the controller drops only that connection.
    meta = provenance.controller_metadata("centroid", {})
    port = server_factory(lambda: testctl.make_controller("centroid"), meta, once=False)

    # fx=0 makes centroid divide by zero once it has >= n_min events.
    bad_hello = Hello(0, 320, 240, 10000, 0.0, 0.0, 159.5, 119.5, 0.0, 0.0, 1)
    ev = np.zeros(300, dtype=EVENT_DTYPE)
    ev["x"] = 100
    ev["y"] = 100

    link = TcpLink("127.0.0.1", port, connect_timeout=5)
    link.open(bad_hello)
    with pytest.raises(protocol.ProtocolError):
        link.exchange(Obs(0, 0, 0, 10000, ev), time.monotonic() + 3)
    link.close()

    # The server survived the controller's ZeroDivisionError.
    link2 = TcpLink("127.0.0.1", port, connect_timeout=5)
    assert link2.open(_hello()) == "centroid"
    link2.close()


# -- M1: handshake timeouts ------------------------------------------------- #
def test_client_handshake_timeout() -> None:
    import socket

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    accepted = []

    def run():
        conn, _ = srv.accept()
        accepted.append(conn)  # accept but never reply
        time.sleep(1.5)

    th = threading.Thread(target=run, daemon=True)
    th.start()
    link = TcpLink("127.0.0.1", port, connect_timeout=0.4)
    try:
        with pytest.raises(protocol.ProtocolError, match="handshake timed out"):
            link.open(_hello())
    finally:
        link.close()
        for c in accepted:
            c.close()
        srv.close()
        th.join(timeout=5)


def test_server_handshake_timeout_drops_idle_client(server_factory) -> None:
    import socket

    meta = provenance.controller_metadata("hold", {})
    port = server_factory(
        lambda: testctl.make_controller("hold"), meta, once=False, handshake_timeout=0.3
    )
    idle = socket.create_connection(("127.0.0.1", port), timeout=5)  # sends nothing
    try:
        time.sleep(0.6)  # server should drop it after ~0.3 s and resume accepting
        link = TcpLink("127.0.0.1", port, connect_timeout=5)
        assert link.open(_hello()) == "hold"
        link.close()
    finally:
        idle.close()
