"""Controller runner (spec T10, R8.6, R9.6). Shared with the Jetson controller.

``jn-sim ctl`` listens for simulator connections and serves them one after
another until Ctrl-C; ``--once`` exits after the first connection closes
(R8.6). Each connection gets a fresh controller instance; ``reset`` runs at each
HELLO (R8.3). The controller metadata (R8.10) is built once per connection and
sent in every HELLO_ACK, with ``null`` for the fault and stage-log fields until
T22 / T23. Timestamps on the controller's monotonic clock go into every CMD
(R12.2). The server binds ``127.0.0.1`` by default (R9.6).

Imports only the standard library, numpy and the shared modules (R1.3): it must
never load the simulator, ``host.py`` or matplotlib. Validated by the T15
import-boundary test.
"""

from __future__ import annotations

import socket
import sys
import time
import traceback
from typing import Any, Callable

from . import protocol, provenance, testctl

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 5555
# How long to wait for a HELLO (connection start / between episodes) before
# dropping an idle connection (M1).
HANDSHAKE_TIMEOUT = 15.0
# How long a connection may go silent mid-run before it is dropped, so a
# half-open peer (pulled cable) cannot wedge the single-threaded server (B1).
# Chosen over TCP keepalive: an explicit read deadline is portable and testable.
IDLE_TIMEOUT = 30.0


class CtlUsageError(ValueError):
    """A usage or configuration error (exit status 2, R7.8)."""


def parse_params(items: list[str]) -> dict[str, Any]:
    """Parse ``KEY=VALUE`` controller parameters, coercing numbers."""
    params: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise CtlUsageError(f"--param {item!r} must be KEY=VALUE")
        key, _, raw = item.partition("=")
        params[key.strip()] = _coerce(raw)
    return params


def _coerce(raw: str) -> Any:
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        return raw


def parse_listen(listen: str | None) -> tuple[str, int]:
    if not listen:
        return DEFAULT_HOST, DEFAULT_PORT
    host, sep, port_s = listen.rpartition(":")
    if not sep:
        raise CtlUsageError(f"--listen {listen!r} must be HOST:PORT")
    try:
        port = int(port_s)
    except ValueError:
        raise CtlUsageError(f"--listen {listen!r} has a non-numeric port") from None
    if not (0 <= port <= 65535):
        # Validate here so an out-of-range port is a usage error (exit 2, R7.8),
        # not an OverflowError traceback at bind time (m8). Port 0 is allowed:
        # the OS picks an ephemeral port.
        raise CtlUsageError(f"--listen {listen!r} port out of range (0..65535)")
    return (host or DEFAULT_HOST), port


def _call_step(controller: Any, obs: Any) -> tuple[float, float, int]:
    result = controller.step(obs)
    if len(result) == 2:
        pan, tilt = result
        return float(pan), float(tilt), 0
    pan, tilt, flags = result
    return float(pan), float(tilt), int(flags)


def _handle_connection(
    conn: socket.socket,
    factory: Callable[[], Any],
    meta: dict,
    handshake_timeout: float = HANDSHAKE_TIMEOUT,
    idle_timeout: float = IDLE_TIMEOUT,
) -> None:
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    controller = factory()  # one instance per connection
    expecting_hello = True  # the next message should be a HELLO (R8.3)
    current_episode: int | None = None
    while True:
        # Waiting for a HELLO: handshake timeout. During a run: idle timeout, so
        # a silent/half-open peer can't wedge the single-threaded server (B1).
        conn.settimeout(handshake_timeout if expecting_hello else idle_timeout)
        try:
            msg = protocol.read_message(conn)
        except protocol.ConnectionClosed:
            return
        except (socket.timeout, TimeoutError):
            return  # idle too long: drop this connection
        if isinstance(msg, protocol.Hello):
            current_episode = msg.episode
            name = controller.reset(msg)
            protocol.validate_controller_name(name)
            protocol.send_message(conn, protocol.HelloAck(name, meta))
            expecting_hello = False
        elif isinstance(msg, protocol.Obs):
            if msg.episode != current_episode:
                raise protocol.ProtocolError(
                    f"OBS for episode {msg.episode}, current episode is {current_episode}"
                )
            t_rx = time.monotonic_ns()
            pan, tilt, flags = _call_step(controller, msg)
            t_tx = time.monotonic_ns()
            protocol.send_message(
                conn, protocol.Cmd(msg.episode, msg.k, pan, tilt, flags, t_rx, t_tx)
            )
        elif isinstance(msg, protocol.Bye):
            expecting_hello = True  # BYE ends an episode, not the connection (R8.6)
            continue
        else:
            raise protocol.ProtocolError(
                f"unexpected message on the controller: {type(msg).__name__}"
            )


def serve(
    factory: Callable[[], Any],
    meta: dict,
    host: str,
    port: int,
    *,
    once: bool = False,
    on_ready: Callable[[tuple[str, int]], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
    poll: float = 0.2,
    handshake_timeout: float = HANDSHAKE_TIMEOUT,
    idle_timeout: float = IDLE_TIMEOUT,
) -> None:
    """Accept and serve connections one at a time (R8.6).

    A malformed message, a peer that dies mid-run, or an exception raised by the
    controller ends only that connection; the server logs to stderr and goes
    back to accepting, until Ctrl-C or ``once`` (B1). Only accept() is
    interrupted by the stop poll.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        srv.bind((host, port))
        srv.listen(1)
        srv.settimeout(poll)
        if on_ready is not None:
            on_ready(srv.getsockname())
        while True:
            if should_stop is not None and should_stop():
                return
            try:
                conn, _ = srv.accept()
            except (socket.timeout, TimeoutError):
                continue
            try:
                _handle_connection(conn, factory, meta, handshake_timeout, idle_timeout)
            except protocol.ProtocolError as exc:
                print(f"jn-sim ctl: dropping connection (malformed): {exc}", file=sys.stderr, flush=True)
            except OSError as exc:
                print(f"jn-sim ctl: dropping connection (socket error): {exc}", file=sys.stderr, flush=True)
            except Exception:  # noqa: BLE001 - a controller bug must not stop ctl
                print("jn-sim ctl: dropping connection (controller raised):", file=sys.stderr, flush=True)
                traceback.print_exc()
            finally:
                conn.close()
            if once:
                return


def main(args: Any) -> int:
    name = args.controller
    try:
        protocol.validate_controller_name(name)  # R8.7 at startup
        params = parse_params(args.param)
        # Fail fast on an unknown controller or unknown parameter (R8.6, m3).
        probe = testctl.make_controller(name, params)
        host, port = parse_listen(args.listen)
    except (CtlUsageError, protocol.ProtocolError, ValueError) as exc:
        print(f"jn-sim ctl: {exc}", file=sys.stderr, flush=True)
        return 2

    # Record the controller's effective parameters, not just what was passed (m3).
    meta = provenance.controller_metadata(name, probe.params)

    def factory() -> Any:
        return testctl.make_controller(name, params)

    bound: dict[str, Any] = {}

    def on_ready(addr: tuple[str, int]) -> None:
        bound["addr"] = addr
        print(f"jn-sim ctl: {name} listening on {addr[0]}:{addr[1]}", flush=True)

    idle_timeout = getattr(args, "idle_timeout", IDLE_TIMEOUT)
    try:
        serve(factory, meta, host, port, once=args.once, on_ready=on_ready, idle_timeout=idle_timeout)
    except KeyboardInterrupt:
        return 0
    return 0
