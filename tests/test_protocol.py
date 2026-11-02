"""T9: wire protocol — sizes, round trips, validation (R8.2, R8.5-R8.11)."""

from __future__ import annotations

import json
import math
import struct

import numpy as np
import pytest

from jn_sim import protocol as P
from jn_sim.protocol import (
    Bye,
    Cmd,
    Hello,
    HelloAck,
    Obs,
    ProtocolError,
    EVENT_DTYPE,
)


class FakeSock:
    """A socket-like byte source; ``chunk`` caps bytes returned per recv."""

    def __init__(self, data: bytes, chunk: int | None = None) -> None:
        self.buf = bytes(data)
        self.pos = 0
        self.chunk = chunk
        self.sent = bytearray()
        self.recv_into_calls = 0

    def recv_into(self, buffer) -> int:
        self.recv_into_calls += 1
        n = len(buffer)
        if self.chunk is not None:
            n = min(n, self.chunk)
        data = self.buf[self.pos : self.pos + n]
        buffer[: len(data)] = data
        self.pos += len(data)
        return len(data)

    def settimeout(self, _t) -> None:
        pass

    def sendall(self, data: bytes) -> None:
        self.sent += data


def _events(n: int, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    ev = np.empty(n, dtype=EVENT_DTYPE)
    ev["t"] = np.sort(rng.integers(0, 1_000_000, size=n).astype(np.uint32))
    ev["x"] = rng.integers(0, 320, size=n).astype(np.uint16)
    ev["y"] = rng.integers(0, 240, size=n).astype(np.uint16)
    ev["p"] = rng.integers(0, 2, size=n).astype(np.uint8)
    return ev


def _hello() -> Hello:
    return Hello(0, 320, 240, 10000, 277.1, 277.1, 159.5, 119.5, 0.0, 0.0, 12345)


# -- fixed sizes (R8.2) ----------------------------------------------------- #
def test_fixed_payload_sizes() -> None:
    assert len(_hello().encode()) == 44
    assert len(Cmd(0, 0, 0.1, -0.2).encode()) == 36
    assert len(Bye(0).encode()) == 4
    ev = _events(7)
    assert len(Obs(0, 0, 0, 100, ev).encode()) == 20 + 9 * 7
    ack = HelloAck("centroid", {"a": 1})
    meta_len = len(json.dumps(ack.meta).encode("utf-8"))
    assert len(ack.encode()) == 36 + meta_len


# -- round trips ------------------------------------------------------------ #
@pytest.mark.parametrize(
    "msg",
    [
        _hello(),
        HelloAck("hold", {"name": "hold", "os": "macos"}),
        Obs(1, 5, 1000, 2000, _events(50)),
        Cmd(1, 5, 0.12, -0.03, flags=P.FLAG_FAULT, t_rx_ns=111, t_tx_ns=222),
        Bye(3),
    ],
)
def test_round_trip(msg) -> None:
    sock = FakeSock(P.encode_message(msg))
    out = P.read_message(sock)
    assert type(out) is type(msg)
    if isinstance(msg, Obs):
        assert np.array_equal(out.events.view(np.uint8), msg.events.view(np.uint8))
        assert (out.episode, out.k, out.t_start_us, out.t_end_us) == (
            msg.episode,
            msg.k,
            msg.t_start_us,
            msg.t_end_us,
        )
    elif isinstance(msg, HelloAck):
        assert out.name == msg.name and out.meta == msg.meta
    elif isinstance(msg, Hello):
        # f32 fields lose precision; integer fields are exact.
        assert (out.episode, out.width, out.height, out.period_us, out.ctl_seed) == (
            msg.episode, msg.width, msg.height, msg.period_us, msg.ctl_seed
        )
        for attr in ("fx", "fy", "cx", "cy", "pan0", "tilt0"):
            assert getattr(out, attr) == pytest.approx(getattr(msg, attr), rel=1e-5)
    elif isinstance(msg, Cmd):
        assert (out.episode, out.k, out.flags, out.t_rx_ns, out.t_tx_ns) == (
            msg.episode, msg.k, msg.flags, msg.t_rx_ns, msg.t_tx_ns
        )
        assert out.pan == pytest.approx(msg.pan, rel=1e-5)
        assert out.tilt == pytest.approx(msg.tilt, rel=1e-5)
    else:
        assert out == msg


def test_event_array_bit_identical() -> None:
    ev = _events(1000, seed=3)
    out = Obs.decode(Obs(0, 0, 0, 0, ev).encode())
    assert out.events.dtype == EVENT_DTYPE
    assert np.array_equal(out.events.view(np.uint8), ev.view(np.uint8))


# -- commands are data (R8.9) ---------------------------------------------- #
@pytest.mark.parametrize("pan", [float("nan"), float("inf"), float("-inf"), 1.5])
@pytest.mark.parametrize("tilt", [float("nan"), float("inf"), float("-inf"), -0.5])
def test_non_finite_commands_survive_bit_for_bit(pan, tilt) -> None:
    cmd = Cmd(2, 9, pan, tilt)
    enc1 = cmd.encode()
    dec = Cmd.decode(enc1)  # must not raise
    enc2 = dec.encode()
    assert enc1 == enc2  # bit-for-bit through the round trip
    if math.isnan(pan):
        assert math.isnan(dec.pan)
    else:
        assert dec.pan == pan


# -- reserved flags (R8.11 / R8.5) ----------------------------------------- #
@pytest.mark.parametrize("flags", [0, 1, 2, 4, 7])
def test_valid_flags_accepted(flags) -> None:
    assert Cmd.decode(Cmd(0, 0, 0.0, 0.0, flags=flags).encode()).flags == flags


@pytest.mark.parametrize("flags", [8, 16, 1 << 31])
def test_reserved_flag_bits_rejected(flags) -> None:
    with pytest.raises(ProtocolError):
        Cmd(0, 0, 0.0, 0.0, flags=flags).encode()
    # and on decode of a crafted payload
    payload = struct.pack("<IIffIQQ", 0, 0, 0.0, 0.0, flags, 0, 0)
    with pytest.raises(ProtocolError):
        Cmd.decode(payload)


# -- HELLO_ACK metadata checks (R8.10) ------------------------------------- #
def test_metadata_oversized_rejected() -> None:
    big = {"x": "a" * (P.MAX_META + 10)}
    with pytest.raises(ProtocolError):
        HelloAck("hold", big).encode()


def test_metadata_not_utf8_rejected() -> None:
    payload = P._ACK_HEAD.pack(b"hold", 2) + b"\xff\xfe"
    with pytest.raises(ProtocolError):
        HelloAck.decode(payload)


def test_metadata_not_json_object_rejected() -> None:
    body = b"[1, 2, 3]"  # valid JSON, but an array not an object
    payload = P._ACK_HEAD.pack(b"hold", len(body)) + body
    with pytest.raises(ProtocolError):
        HelloAck.decode(payload)


# -- names (R8.7) ----------------------------------------------------------- #
@pytest.mark.parametrize("name", ["centroid", "hold", "A.b-1_2", "x" * 32])
def test_valid_names(name) -> None:
    assert P.validate_controller_name(name) == name


@pytest.mark.parametrize("name", ["", "bad name", "has!", "x" * 33, "two\nlines"])
def test_invalid_names_rejected(name) -> None:
    with pytest.raises(ProtocolError):
        P.validate_controller_name(name)
    with pytest.raises(ProtocolError):
        HelloAck(name, {}).encode()


# -- framing errors (R8.5) -------------------------------------------------- #
def test_bad_magic_raises() -> None:
    frame = P._HEADER.pack(b"XXXX", P.VERSION, P.MSG_BYE, 4) + Bye(0).encode()
    with pytest.raises(ProtocolError):
        P.read_message(FakeSock(frame))


def test_bad_version_raises() -> None:
    frame = P._HEADER.pack(P.MAGIC, 2, P.MSG_BYE, 4) + Bye(0).encode()
    with pytest.raises(ProtocolError):
        P.read_message(FakeSock(frame))


def test_bad_type_raises() -> None:
    frame = P._HEADER.pack(P.MAGIC, P.VERSION, 99, 4) + Bye(0).encode()
    with pytest.raises(ProtocolError):
        P.read_message(FakeSock(frame))


def test_bad_size_raises() -> None:
    with pytest.raises(ProtocolError):
        Hello.decode(b"too short")
    with pytest.raises(ProtocolError):
        Cmd.decode(b"\x00" * 10)


def test_payload_over_cap_raises_on_read() -> None:
    frame = P._HEADER.pack(P.MAGIC, P.VERSION, P.MSG_OBS, P.MAX_PAYLOAD + 1)
    with pytest.raises(ProtocolError):
        P.read_message(FakeSock(frame))


# -- partial delivery ------------------------------------------------------- #
def test_bytes_one_at_a_time_decode() -> None:
    msg = Obs(0, 2, 0, 100, _events(40))
    sock = FakeSock(P.encode_message(msg), chunk=1)
    out = P.read_message(sock)
    assert np.array_equal(out.events.view(np.uint8), msg.events.view(np.uint8))


def test_connection_closed_mid_message() -> None:
    with pytest.raises(P.ConnectionClosed):
        P.read_message(FakeSock(b"\x00\x00"))  # fewer than 12 header bytes


# -- oversized batch (R8.8) ------------------------------------------------- #
def test_oversized_batch_rejected() -> None:
    ev = np.zeros(P.MAX_EVENTS + 1, dtype=EVENT_DTYPE)
    with pytest.raises(ProtocolError):
        Obs(0, 0, 0, 0, ev).encode()


# -- size checks happen before the body is read (M5) ----------------------- #
def test_read_rejects_oversize_fixed_payload_before_reading() -> None:
    # A HELLO claiming 1000 bytes (HELLO is 44): rejected from the header, with
    # the payload never read (zero payload recvs).
    sock = FakeSock(P._HEADER.pack(P.MAGIC, P.VERSION, P.MSG_HELLO, 1000))
    with pytest.raises(ProtocolError):
        P.read_message(sock)
    assert sock.recv_into_calls == 1  # header only; payload not read


def test_read_rejects_ack_over_meta_cap_before_reading() -> None:
    sock = FakeSock(P._HEADER.pack(P.MAGIC, P.VERSION, P.MSG_HELLO_ACK, P.MAX_META + 1000))
    with pytest.raises(ProtocolError):
        P.read_message(sock)
    assert sock.recv_into_calls == 1


def test_read_rejects_bad_obs_length_before_reading() -> None:
    # OBS payload must be 20 + 9n; 25 is not, so reject before reading.
    sock = FakeSock(P._HEADER.pack(P.MAGIC, P.VERSION, P.MSG_OBS, 25))
    with pytest.raises(ProtocolError):
        P.read_message(sock)
    assert sock.recv_into_calls == 1


def test_deeply_nested_metadata_rejected_not_crash() -> None:
    raw = (b"[" * 60000)  # unbalanced; deep enough to raise RecursionError
    payload = P._ACK_HEAD.pack(b"ctl", len(raw)) + raw
    with pytest.raises(ProtocolError):
        HelloAck.decode(payload)


# -- more malformed-message detection (M6) --------------------------------- #
def test_obs_length_mismatch_rejected() -> None:
    body = P._OBS_HEAD.pack(0, 0, 0, 0, 5) + _events(2).tobytes()  # n=5, 2 events
    with pytest.raises(ProtocolError):
        Obs.decode(body)


def test_ack_meta_len_mismatch_rejected() -> None:
    body = P._ACK_HEAD.pack(b"hold", 100) + b"{}"  # meta_len=100, 2 bytes present
    with pytest.raises(ProtocolError):
        HelloAck.decode(body)


@pytest.mark.parametrize("plen", [0, 43, 45])
def test_read_hello_wrong_size_rejected(plen: int) -> None:
    sock = FakeSock(P._HEADER.pack(P.MAGIC, P.VERSION, P.MSG_HELLO, plen))
    with pytest.raises(ProtocolError):
        P.read_message(sock)
    assert sock.recv_into_calls == 1  # rejected from the header, payload not read


def test_metadata_over_cap_rejected_on_decode() -> None:
    # Decode-side 64 KiB cap (M6): meta_len is checked before the body.
    payload = P._ACK_HEAD.pack(b"ctl", P.MAX_META + 1)
    with pytest.raises(ProtocolError):
        HelloAck.decode(payload)


def test_name_non_nul_padding_rejected() -> None:
    # "hold\0garbage" must not be accepted as "hold" (M6).
    name_field = (b"hold\x00garbage").ljust(32, b"\x00")
    body = b"{}"
    payload = struct.pack("<32s", name_field) + struct.pack("<I", len(body)) + body
    with pytest.raises(ProtocolError):
        HelloAck.decode(payload)


# -- golden byte layout for the variable-size headers (M7) ----------------- #
def test_obs_header_golden() -> None:
    ev = _events(2)
    payload = Obs(3, 4, 100, 200, ev).encode()
    assert payload[:20] == struct.pack("<IIIII", 3, 4, 100, 200, 2)
    assert payload[20:] == ev.tobytes()


def test_hello_ack_header_golden() -> None:
    meta = __import__("json").dumps({"a": 1}).encode("utf-8")
    payload = HelloAck("hold", {"a": 1}).encode()
    assert payload[:36] == struct.pack("<32sI", b"hold", len(meta))
    assert payload[36:] == meta


# -- pin the wire layout (M7) ---------------------------------------------- #
def test_protocol_constants_pinned() -> None:
    assert P.MAGIC == b"JNSM" and P.VERSION == 1
    assert (P.MSG_HELLO, P.MSG_HELLO_ACK, P.MSG_OBS, P.MSG_CMD, P.MSG_BYE) == (1, 2, 3, 4, 5)
    assert (P.FLAG_FAULT, P.FLAG_DETECT, P.FLAG_RECOVER) == (1, 2, 4)
    assert P.HEADER_SIZE == 12 and P.MAX_PAYLOAD == 16 * 1024 * 1024


def test_event_dtype_layout_pinned() -> None:
    assert EVENT_DTYPE.itemsize == 9
    assert EVENT_DTYPE.names == ("t", "x", "y", "p")
    assert [EVENT_DTYPE.fields[n][1] for n in ("t", "x", "y", "p")] == [0, 4, 6, 8]


def test_hello_wire_layout_golden() -> None:
    h = Hello(1, 320, 240, 10000, 1.0, 2.0, 3.0, 4.0, 0.5, -0.5, 0xDEADBEEFCAFEBABE)
    assert h.encode() == struct.pack(
        "<IHHIffffffQ", 1, 320, 240, 10000, 1.0, 2.0, 3.0, 4.0, 0.5, -0.5, 0xDEADBEEFCAFEBABE
    )


def test_cmd_wire_layout_golden() -> None:
    c = Cmd(2, 7, 0.25, -0.75, 5, 111, 222)
    assert c.encode() == struct.pack("<IIffIQQ", 2, 7, 0.25, -0.75, 5, 111, 222)


def test_bye_and_framing_golden() -> None:
    assert Bye(9).encode() == struct.pack("<I", 9)
    frame = P.encode_message(Bye(9))
    assert frame[:12] == struct.pack("<4sHHI", b"JNSM", 1, P.MSG_BYE, 4)
    assert len(frame) == 16
