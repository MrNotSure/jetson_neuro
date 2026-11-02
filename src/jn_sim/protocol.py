"""Wire protocol (spec T9, R8.2). Shared with the Jetson controller.

Message layouts, encode/decode, the event dtype, an exact-length socket read
and the validation checks (size, magic, version, the 16 MiB cap, controller
name, HELLO_ACK metadata and the reserved flag bits).

Standard library + numpy only, Python 3.12 features only (R1.3). Everything is
little-endian, packed, with no padding (R8.2).
"""

from __future__ import annotations

import json
import re
import socket
import struct
import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

# -- framing (R8.2) --------------------------------------------------------- #
MAGIC = b"JNSM"
VERSION = 1
HEADER_SIZE = 12  # magic(4) + version(u16) + type(u16) + payload_len(u32)
MAX_PAYLOAD = 16 * 1024 * 1024  # 16 MiB cap (R8.8)
MAX_META = 64 * 1024  # HELLO_ACK metadata cap, 64 KiB (R8.10)

# -- message types (R8.2) --------------------------------------------------- #
MSG_HELLO = 1
MSG_HELLO_ACK = 2
MSG_OBS = 3
MSG_CMD = 4
MSG_BYE = 5

# -- CMD flag bits (R8.11): others are reserved and must be 0 (R8.5) -------- #
FLAG_FAULT = 1 << 0  # a fault was injected in this decision
FLAG_DETECT = 1 << 1  # a detector fired
FLAG_RECOVER = 1 << 2  # a recovery was applied
FLAG_MASK = FLAG_FAULT | FLAG_DETECT | FLAG_RECOVER

# -- event record (R8.2): t u32 (us), x u16, y u16, p u8 (1=ON, 0=OFF) ------ #
# Little-endian and packed: itemsize is exactly 9 bytes, no padding.
EVENT_DTYPE = np.dtype(
    {
        "names": ["t", "x", "y", "p"],
        "formats": ["<u4", "<u2", "<u2", "u1"],
        "offsets": [0, 4, 6, 8],
        "itemsize": 9,
    }
)
assert EVENT_DTYPE.itemsize == 9, "event record must be 9 bytes, packed"

# -- struct layouts --------------------------------------------------------- #
_HEADER = struct.Struct("<4sHHI")  # 12
_HELLO = struct.Struct("<IHHIffffffQ")  # 44
_CMD = struct.Struct("<IIffIQQ")  # 36
_BYE = struct.Struct("<I")  # 4
_OBS_HEAD = struct.Struct("<IIIII")  # 20
_ACK_HEAD = struct.Struct("<32sI")  # 36 (name + meta_len)

assert _HEADER.size == HEADER_SIZE
assert _HELLO.size == 44
assert _CMD.size == 36
assert _OBS_HEAD.size == 20
assert _ACK_HEAD.size == 36

MAX_EVENTS = (MAX_PAYLOAD - _OBS_HEAD.size) // EVENT_DTYPE.itemsize  # ~1.86 M

# Fixed payload sizes, so an over-large claim is rejected before the body is
# read (M5). Variable types: HELLO_ACK <= 36 + MAX_META, OBS <= MAX_PAYLOAD.
_FIXED_PAYLOAD = {MSG_HELLO: _HELLO.size, MSG_CMD: _CMD.size, MSG_BYE: _BYE.size}
_MAX_ACK_PAYLOAD = _ACK_HEAD.size + MAX_META

_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
_U32_MAX = 0xFFFFFFFF


class ProtocolError(Exception):
    """A malformed message or a protocol-level violation (R8.5)."""


class ConnectionClosed(ProtocolError):
    """The peer closed the connection mid-message (R7.6)."""


# -- validators ------------------------------------------------------------- #
def validate_controller_name(name: str) -> str:
    """Controller names match ``[A-Za-z0-9_.-]{1,32}`` (R8.7)."""
    if not isinstance(name, str) or not _NAME_RE.match(name):
        raise ProtocolError(
            f"invalid controller name {name!r} (must match [A-Za-z0-9_.-]{{1,32}})"
        )
    return name


def _validate_flags(flags: int) -> None:
    if not (0 <= flags <= _U32_MAX):
        raise ProtocolError(f"CMD flags out of range: {flags}")
    if flags & ~FLAG_MASK:
        raise ProtocolError(f"CMD flags set reserved bits (R8.11): {flags:#x}")


# -- messages --------------------------------------------------------------- #
@dataclass
class Hello:
    episode: int
    width: int
    height: int
    period_us: int
    fx: float
    fy: float
    cx: float
    cy: float
    pan0: float
    tilt0: float
    ctl_seed: int

    def encode(self) -> bytes:
        return _HELLO.pack(
            self.episode,
            self.width,
            self.height,
            self.period_us,
            self.fx,
            self.fy,
            self.cx,
            self.cy,
            self.pan0,
            self.tilt0,
            self.ctl_seed,
        )

    @classmethod
    def decode(cls, payload: bytes) -> "Hello":
        if len(payload) != _HELLO.size:
            raise ProtocolError(f"HELLO payload must be {_HELLO.size} bytes, got {len(payload)}")
        return cls(*_HELLO.unpack(payload))


@dataclass
class HelloAck:
    name: str
    meta: dict[str, Any] = field(default_factory=dict)

    def encode(self) -> bytes:
        validate_controller_name(self.name)
        meta_bytes = json.dumps(self.meta).encode("utf-8")
        if len(meta_bytes) > MAX_META:
            raise ProtocolError(
                f"HELLO_ACK metadata is {len(meta_bytes)} bytes, over the {MAX_META} cap"
            )
        return _ACK_HEAD.pack(self.name.encode("ascii"), len(meta_bytes)) + meta_bytes

    @classmethod
    def decode(cls, payload: bytes) -> "HelloAck":
        if len(payload) < _ACK_HEAD.size:
            raise ProtocolError("HELLO_ACK payload shorter than its header")
        name_b, meta_len = _ACK_HEAD.unpack(payload[: _ACK_HEAD.size])
        if meta_len > MAX_META:
            raise ProtocolError(f"HELLO_ACK metadata over the {MAX_META} cap")
        if len(payload) != _ACK_HEAD.size + meta_len:
            raise ProtocolError("HELLO_ACK payload length does not match meta_len")
        trimmed = name_b.split(b"\x00", 1)[0]
        # Everything after the first NUL must also be NUL (R8.7, M6): reject
        # "hold\0garbage" rather than silently reading it as "hold".
        if name_b != trimmed.ljust(len(name_b), b"\x00"):
            raise ProtocolError("controller name field has non-NUL padding")
        try:
            name = trimmed.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ProtocolError("controller name is not ASCII") from exc
        validate_controller_name(name)
        raw = payload[_ACK_HEAD.size :]
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("HELLO_ACK metadata is not valid UTF-8") from exc
        try:
            # Deeply nested JSON raises RecursionError on 3.12, not
            # JSONDecodeError; treat both as malformed rather than crashing (M5).
            meta = json.loads(text) if text else {}
        except (json.JSONDecodeError, RecursionError, ValueError) as exc:
            raise ProtocolError("HELLO_ACK metadata is not valid JSON") from exc
        if not isinstance(meta, dict):
            raise ProtocolError("HELLO_ACK metadata must be a JSON object")
        return cls(name, meta)


@dataclass
class Obs:
    episode: int
    k: int
    t_start_us: int
    t_end_us: int
    events: np.ndarray

    def encode(self) -> bytes:
        ev = np.ascontiguousarray(self.events, dtype=EVENT_DTYPE)
        n = int(ev.size)
        if n > MAX_EVENTS:
            raise ProtocolError(
                f"OBS batch of {n} events exceeds the 16 MiB cap "
                f"({MAX_EVENTS} events); the run aborts (R8.8)"
            )
        head = _OBS_HEAD.pack(self.episode, self.k, self.t_start_us, self.t_end_us, n)
        return head + ev.tobytes()

    @classmethod
    def decode(cls, payload: bytes) -> "Obs":
        if len(payload) < _OBS_HEAD.size:
            raise ProtocolError("OBS payload shorter than its header")
        episode, k, t_start, t_end, n = _OBS_HEAD.unpack(payload[: _OBS_HEAD.size])
        expected = _OBS_HEAD.size + n * EVENT_DTYPE.itemsize
        if len(payload) != expected:
            raise ProtocolError(
                f"OBS payload is {len(payload)} bytes, expected {expected} for n={n}"
            )
        events = np.frombuffer(
            payload, dtype=EVENT_DTYPE, count=n, offset=_OBS_HEAD.size
        ).copy()
        return cls(episode, k, t_start, t_end, events)


@dataclass
class Cmd:
    episode: int
    k: int
    pan: float
    tilt: float
    flags: int = 0
    t_rx_ns: int = 0
    t_tx_ns: int = 0

    def encode(self) -> bytes:
        _validate_flags(self.flags)
        # pan/tilt may be non-finite (R8.9); struct packs the f32 bits as-is.
        return _CMD.pack(
            self.episode, self.k, self.pan, self.tilt, self.flags, self.t_rx_ns, self.t_tx_ns
        )

    @classmethod
    def decode(cls, payload: bytes) -> "Cmd":
        if len(payload) != _CMD.size:
            raise ProtocolError(f"CMD payload must be {_CMD.size} bytes, got {len(payload)}")
        episode, k, pan, tilt, flags, rx, tx = _CMD.unpack(payload)
        _validate_flags(flags)  # reserved bits are malformed (R8.5/R8.11)
        return cls(episode, k, pan, tilt, flags, rx, tx)


@dataclass
class Bye:
    episode: int

    def encode(self) -> bytes:
        return _BYE.pack(self.episode)

    @classmethod
    def decode(cls, payload: bytes) -> "Bye":
        if len(payload) != _BYE.size:
            raise ProtocolError(f"BYE payload must be {_BYE.size} bytes, got {len(payload)}")
        return cls(*_BYE.unpack(payload))


_TYPE_TO_CLASS: dict[int, type] = {
    MSG_HELLO: Hello,
    MSG_HELLO_ACK: HelloAck,
    MSG_OBS: Obs,
    MSG_CMD: Cmd,
    MSG_BYE: Bye,
}
_CLASS_TO_TYPE: dict[type, int] = {v: k for k, v in _TYPE_TO_CLASS.items()}


# -- framing + I/O ---------------------------------------------------------- #
def encode_message(msg: Any) -> bytes:
    """Frame a message: 12-byte header + payload."""
    try:
        mtype = _CLASS_TO_TYPE[type(msg)]
    except KeyError:
        raise ProtocolError(f"not a protocol message: {type(msg).__name__}") from None
    payload = msg.encode()
    if len(payload) > MAX_PAYLOAD:
        raise ProtocolError(f"payload {len(payload)} bytes exceeds the {MAX_PAYLOAD} cap")
    return _HEADER.pack(MAGIC, VERSION, mtype, len(payload)) + payload


def decode_payload(mtype: int, payload: bytes) -> Any:
    cls = _TYPE_TO_CLASS.get(mtype)
    if cls is None:
        raise ProtocolError(f"unknown message type {mtype}")
    return cls.decode(payload)


def check_header(magic: bytes, version: int, mtype: int, plen: int) -> None:
    """Validate a framed header and the per-type payload size (M5, M6).

    Raises before the body is read, so an over-large or malformed claim never
    allocates a large buffer. For OBS the size must be ``20 + 9n``.
    """
    if magic != MAGIC:
        raise ProtocolError(f"bad magic {magic!r}")
    if version != VERSION:
        raise ProtocolError(f"unsupported protocol version {version}")
    if mtype not in _TYPE_TO_CLASS:
        raise ProtocolError(f"unknown message type {mtype}")
    if plen > MAX_PAYLOAD:
        raise ProtocolError(f"payload length {plen} exceeds the {MAX_PAYLOAD} cap")
    expected = _FIXED_PAYLOAD.get(mtype)
    if expected is not None and plen != expected:
        raise ProtocolError(
            f"message type {mtype} must have a {expected}-byte payload, got {plen}"
        )
    if mtype == MSG_HELLO_ACK and plen > _MAX_ACK_PAYLOAD:
        raise ProtocolError(
            f"HELLO_ACK payload {plen} exceeds the metadata cap ({_MAX_ACK_PAYLOAD})"
        )
    if mtype == MSG_OBS and (plen < _OBS_HEAD.size or (plen - _OBS_HEAD.size) % EVENT_DTYPE.itemsize):
        raise ProtocolError(f"OBS payload length {plen} is not 20 + 9n")


def recv_exact(sock: Any, n: int) -> bytes:
    """Read exactly ``n`` bytes into one preallocated buffer (R8.2).

    Uses ``recv_into`` so a slow/byte-at-a-time peer cannot blow memory up with
    millions of small chunk objects (M5): the buffer is a single allocation of
    ``n`` bytes, and ``n`` is bounded by the header checks (<= 16 MiB)."""
    if n == 0:
        return b""
    buf = bytearray(n)
    view = memoryview(buf)
    got = 0
    while got < n:
        r = sock.recv_into(view[got:])
        if r == 0:
            raise ConnectionClosed("connection closed mid-message")
        got += r
    return bytes(buf)


def read_message(sock: Any) -> Any:
    """Read and decode one framed message (blocking), honouring the socket's
    own timeout if one is set. Used by the controller server."""
    header = recv_exact(sock, HEADER_SIZE)
    magic, version, mtype, plen = _HEADER.unpack(header)
    check_header(magic, version, mtype, plen)
    payload = recv_exact(sock, plen)
    return decode_payload(mtype, payload)


def decode_message(data: bytes) -> Any:
    """Parse one fully-framed message from ``data`` (header + payload).

    The pure counterpart of :func:`encode_message`, with no socket. The
    in-process adapter round-trips every message through this pair so an
    in-process run gives the same bytes a TCP run would (R9.2): f32 setpoints
    and intrinsics are quantised, and the 16 MiB cap (R8.8) applies.
    """
    if len(data) < HEADER_SIZE:
        raise ProtocolError("message shorter than its header")
    magic, version, mtype, plen = _HEADER.unpack_from(data, 0)
    check_header(magic, version, mtype, plen)
    if len(data) != HEADER_SIZE + plen:
        raise ProtocolError(
            f"framed message is {len(data)} bytes, expected {HEADER_SIZE + plen}"
        )
    return decode_payload(mtype, data[HEADER_SIZE:])


class MessageReader:
    """Buffered, deadline-aware message reader for the simulator side.

    Keeps a single bytearray buffer, so partial bytes are preserved across
    reads (a CMD split by a deadline is not lost, m1), and a whole message is
    bounded by one deadline rather than per ``recv`` (M1). Reads with
    ``recv_into`` into a reused chunk (M5).
    """

    def __init__(self, sock: Any, chunk_size: int = 65536) -> None:
        self.sock = sock
        self._buf = bytearray()
        self._chunk = bytearray(chunk_size)

    def read(self, deadline: float | None = None) -> Any:
        """Read one message. ``deadline`` is an absolute ``time.monotonic``
        value; on expiry raises ``socket.timeout`` with the buffer intact."""
        self._fill(HEADER_SIZE, deadline)
        magic, version, mtype, plen = _HEADER.unpack_from(self._buf, 0)
        check_header(magic, version, mtype, plen)
        need = HEADER_SIZE + plen
        self._fill(need, deadline)
        payload = bytes(self._buf[HEADER_SIZE:need])
        del self._buf[:need]
        return decode_payload(mtype, payload)

    def _fill(self, n: int, deadline: float | None) -> None:
        view = memoryview(self._chunk)
        while len(self._buf) < n:
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0.0:
                    raise socket.timeout("deadline exceeded")
                self.sock.settimeout(remaining)
            else:
                self.sock.settimeout(None)
            got = self.sock.recv_into(view)
            if got == 0:
                raise ConnectionClosed("connection closed mid-message")
            self._buf += view[:got]


def send_message(sock: Any, msg: Any, timeout: float | None = None) -> None:
    """Send a framed message. With ``timeout`` the send is bounded (M1)."""
    if timeout is not None:
        sock.settimeout(timeout)
    sock.sendall(encode_message(msg))
