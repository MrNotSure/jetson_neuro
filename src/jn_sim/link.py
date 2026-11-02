"""Connection adapters (spec T10, R9). Shared with the Jetson controller.

The loop talks to a controller only through a :class:`Link` (R9.1):
``open(hello) -> name``, ``exchange(obs, deadline) -> cmd | None``, ``close()``.
A per-episode ``send_bye`` rounds out the protocol (R8.2); the loop does not
know which adapter is behind the interface.

Adapters (R9.2):

* ``inproc:NAME`` -- runs the controller in-process (tests, fast local runs);
* ``tcp://HOST:PORT`` -- direct TCP to a running controller;
* ``ssh://DEST/PORT`` and ``@NAME`` -- optional (T11); they give a clear "not
  built yet" error until then.

The SSH adapter is imported lazily, only for ``ssh://`` endpoints (R1.3).
Standard library + numpy only.
"""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass
from typing import Any

from . import protocol, provenance


class EndpointError(ValueError):
    """An endpoint string could not be parsed, or its adapter is not built."""


class LinkConnectError(ConnectionError):
    """Could not establish the initial connection at startup (R7.7).

    Distinct from a mid-run ``ConnectionResetError``/``BrokenPipeError`` (also
    ``OSError`` subclasses) so the loop can report a startup failure as "could
    not connect" and a mid-run drop as "connection lost" (R7.6, m6).
    """


@dataclass
class Endpoint:
    kind: str  # "inproc" | "tcp"
    name: str = ""  # inproc controller name
    host: str = ""  # tcp host
    port: int = 0  # tcp port


def parse_endpoint(endpoint: str) -> Endpoint:
    """Parse an endpoint string into an :class:`Endpoint` (R9.2)."""
    if endpoint.startswith("inproc:"):
        name = endpoint[len("inproc:") :]
        protocol.validate_controller_name(name)
        return Endpoint("inproc", name=name)
    if endpoint.startswith("tcp://"):
        rest = endpoint[len("tcp://") :]
        if ":" not in rest:
            raise EndpointError(f"tcp endpoint {endpoint!r} must be tcp://HOST:PORT")
        host, _, port_s = rest.rpartition(":")
        if not host:
            raise EndpointError(f"tcp endpoint {endpoint!r} is missing a host")
        try:
            port = int(port_s)
        except ValueError:
            raise EndpointError(f"tcp endpoint {endpoint!r} has a non-numeric port") from None
        if not (1 <= port <= 65535):
            raise EndpointError(f"tcp endpoint {endpoint!r} port out of range")
        return Endpoint("tcp", host=host, port=port)
    if endpoint.startswith("ssh://"):
        raise EndpointError(
            "ssh:// endpoints are an optional task (T11) and are not built yet"
        )
    if endpoint.startswith("@"):
        raise EndpointError(
            "@NAME endpoints are an optional task (T11) and are not built yet"
        )
    raise EndpointError(
        f"unrecognised endpoint {endpoint!r} "
        "(use inproc:NAME or tcp://HOST:PORT)"
    )


def _call_step(controller: Any, obs: Any) -> tuple[float, float, int]:
    """Call ``step`` and normalise its result to (pan, tilt, flags) (R8.1)."""
    result = controller.step(obs)
    if len(result) == 2:
        pan, tilt = result
        return float(pan), float(tilt), 0
    pan, tilt, flags = result
    return float(pan), float(tilt), int(flags)


class InProcLink:
    """Runs the controller inside the simulator process (R9.2)."""

    def __init__(self, controller: Any) -> None:
        self.controller = controller
        self.name: str | None = None
        self.controller_meta: dict[str, Any] | None = None

    def open(self, hello) -> str:
        # Round-trip HELLO through the wire so the controller sees the f32
        # intrinsics a TCP run delivers, not float64 (R9.2, m1).
        hello = protocol.decode_message(protocol.encode_message(hello))
        name = self.controller.reset(hello)
        protocol.validate_controller_name(name)
        self.name = name
        if self.controller_meta is None:
            self.controller_meta = provenance.controller_metadata(
                name, getattr(self.controller, "params", {})
            )
        return name

    def exchange(self, obs, deadline: float | None = None, obs_bytes: bytes | None = None):
        # OBS and CMD go through encode/decode too (R9.2, m1): the controller
        # reads the same bytes a TCP peer would, the 16 MiB cap applies (R8.8),
        # and the returned setpoints are quantised to f32.
        if obs_bytes is None:
            obs_bytes = protocol.encode_message(obs)
        obs = protocol.decode_message(obs_bytes)
        t_rx = time.monotonic_ns()
        pan, tilt, flags = _call_step(self.controller, obs)
        t_tx = time.monotonic_ns()
        cmd = protocol.Cmd(obs.episode, obs.k, pan, tilt, flags, t_rx, t_tx)
        return protocol.decode_message(protocol.encode_message(cmd))

    def wait_for_late(self, episode: int, k: int, deadline: float) -> bool:
        return True  # in-process replies are synchronous; never a late reply

    def send_bye(self, episode: int) -> None:
        pass

    def close(self) -> None:
        pass


class TcpLink:
    """Direct TCP to a running controller (R9.2), simulator side."""

    def __init__(
        self,
        host: str,
        port: int,
        connect_timeout: float = 10.0,
        retry_interval: float = 0.2,
        attempt_timeout: float = 2.0,
    ) -> None:
        self.host = host
        self.port = port
        self.connect_timeout = connect_timeout
        self.retry_interval = retry_interval
        self.attempt_timeout = attempt_timeout
        self.sock: socket.socket | None = None
        self._reader: protocol.MessageReader | None = None
        self.name: str | None = None
        self.controller_meta: dict[str, Any] | None = None

    def _connect(self) -> None:
        # Retry every retry_interval up to connect_timeout, so run and ctl can
        # start in either order (R7.7). The per-attempt timeout is separate from
        # the retry interval (m11); deadlines use monotonic ns (R2.2).
        deadline_ns = time.monotonic_ns() + int(self.connect_timeout * 1e9)
        last_err: OSError | None = None
        while True:
            try:
                sock = socket.create_connection(
                    (self.host, self.port), timeout=self.attempt_timeout
                )
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                self.sock = sock
                self._reader = protocol.MessageReader(sock)
                return
            except OSError as exc:
                last_err = exc
                if time.monotonic_ns() >= deadline_ns:
                    raise LinkConnectError(
                        f"could not connect to {self.host}:{self.port} within "
                        f"{self.connect_timeout}s: {last_err}"
                    ) from last_err
                time.sleep(self.retry_interval)

    def open(self, hello) -> str:
        if self.sock is None:
            self._connect()
        assert self.sock is not None and self._reader is not None
        # One deadline for the whole handshake (M1): a peer that accepts but
        # never completes it cannot hang the run. S1: there is no stale-CMD
        # discard here; a CMD during the handshake is malformed.
        deadline = time.monotonic() + self.connect_timeout
        try:
            protocol.send_message(self.sock, hello, timeout=self.connect_timeout)
            ack = self._reader.read(deadline)
        except (socket.timeout, TimeoutError) as exc:
            raise protocol.ProtocolError(
                f"handshake timed out after {self.connect_timeout}s"
            ) from exc
        if not isinstance(ack, protocol.HelloAck):
            raise protocol.ProtocolError(
                f"expected HELLO_ACK, got {type(ack).__name__}"
            )
        if self.name is None:
            self.name = ack.name
            self.controller_meta = ack.meta
        elif ack.name != self.name or ack.meta != self.controller_meta:
            # Metadata must be identical across episodes (R8.10 / R8.5).
            raise protocol.ProtocolError(
                "controller metadata changed between episodes (R8.10)"
            )
        return ack.name

    def exchange(self, obs, deadline: float, obs_bytes: bytes | None = None):
        assert self.sock is not None and self._reader is not None
        if obs_bytes is None:
            protocol.send_message(self.sock, obs, timeout=self.connect_timeout)
        else:
            # The sim pre-encoded the OBS inside its sim_us window (m4); send it
            # verbatim rather than re-encoding.
            self.sock.settimeout(self.connect_timeout)
            self.sock.sendall(obs_bytes)
        while True:
            try:
                msg = self._reader.read(deadline)
            except (socket.timeout, TimeoutError):
                return None  # miss (realtime) / timeout (lockstep)
            if not isinstance(msg, protocol.Cmd):
                raise protocol.ProtocolError(
                    f"expected CMD, got {type(msg).__name__}"
                )
            if msg.episode != obs.episode:
                # A CMD for any other episode is malformed and aborts the run
                # (R8.5, R7.6; review decision S1).
                raise protocol.ProtocolError(
                    f"late CMD for episode {msg.episode}, period {msg.k} arrived "
                    f"during episode {obs.episode} (R8.5)"
                )
            if msg.k == obs.k:
                return msg
            if msg.k < obs.k:
                continue  # a late reply for a past period of this episode (R7.3)
            raise protocol.ProtocolError(
                f"CMD for future period {msg.k} (expected {obs.k})"
            )

    def wait_for_late(self, episode: int, k: int, deadline: float) -> bool:
        """Collect and discard the reply to an episode's last OBS before BYE.

        R7.3: if that reply missed its deadline, the simulator waits for it (up
        to the CMD timeout) and discards it, so it can't leak into the next
        episode's handshake. Returns True once the matching CMD is seen; raises
        ``ProtocolError`` for a foreign/malformed message (abort, R8.5); returns
        False on timeout, which the caller treats as a lost connection (R7.6).
        """
        assert self._reader is not None
        while True:
            try:
                msg = self._reader.read(deadline)
            except (socket.timeout, TimeoutError):
                return False
            if not isinstance(msg, protocol.Cmd):
                raise protocol.ProtocolError(f"expected CMD, got {type(msg).__name__}")
            if msg.episode != episode:
                raise protocol.ProtocolError(
                    f"late CMD for episode {msg.episode}, period {msg.k} arrived while "
                    f"awaiting the reply to episode {episode}, period {k} (R8.5)"
                )
            if msg.k == k:
                return True  # collected and discarded
            if msg.k < k:
                continue  # an even earlier late reply; discard it too
            raise protocol.ProtocolError(
                f"CMD for future period {msg.k} (expected {k})"
            )

    def send_bye(self, episode: int) -> None:
        assert self.sock is not None
        protocol.send_message(self.sock, protocol.Bye(episode), timeout=self.connect_timeout)

    def close(self) -> None:
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None


def make_link(endpoint: str, connect_timeout: float = 10.0) -> Any:
    """Build the Link for an endpoint string (R9.2)."""
    spec = parse_endpoint(endpoint)
    if spec.kind == "inproc":
        from . import testctl

        return InProcLink(testctl.make_controller(spec.name))
    if spec.kind == "tcp":
        return TcpLink(spec.host, spec.port, connect_timeout=connect_timeout)
    raise EndpointError(f"no adapter for endpoint kind {spec.kind!r}")  # unreachable
