"""Stage 1 run: decode a cap_pico.py stream (.bin) into numpy arrays on one unwrapped timebase.

  from capdec import load; c = load("raw/X.bin")

Time: PIO counts of 120 ns since the SMs started. Each state machine counts X down from
0xFFFFFFFF; elapsed counts = (0xFFFFFFFF - X) mod 2**32. The conversion stream (one record per
~9000 counts) is unwrapped by consecutive differences; the marker streams, which can be idle
for longer than a wrap, are unwrapped against the nearest preceding conversion record in
arrival order (they are serviced within a few ms of the edge, far less than 2**31 counts).
"""
import struct
import numpy as np

COUNT_S = 120e-9
WRAP = 1 << 32
STEP_A = 312.5e-9 / 0.015          # A per VSHUNT step (ADCRANGE 0, 15 mOhm)
STEP_V = 195.3125e-6               # V per VBUS step
OFFSET_A = -111e-6                 # zero-current offset from the bench test (not subtracted)


def s20(b0, b1, b2):
    v = ((b0.astype(np.int64) << 16) | (b1.astype(np.int64) << 8) | b2.astype(np.int64)) >> 4
    return np.where(v & 0x80000, v - (1 << 20), v)


def _unwrap_seq(c):
    c = c.astype(np.int64)
    d = np.diff(c)
    d = np.where(d < -(1 << 31), d + WRAP, d)
    d = np.where(d > (1 << 31), d - WRAP, d)
    return np.concatenate([c[:1], c[:1] + np.cumsum(d)])


def load(path):
    raw = open(path, "rb").read()
    n = len(raw) // 16
    a = np.frombuffer(raw[: n * 16], dtype=np.uint8).reshape(n, 16)
    typ = a[:, 0]
    end = np.nonzero(typ == 0x5A)[0]
    if len(end):
        a = a[: end[0]]
        typ = a[:, 0]
    bad = ~np.isin(typ, [0xA5, 0xB6, 0xB7, 0xC7, 0xD8])
    x = a[:, 4:8].copy().view("<u4").ravel().astype(np.int64)
    cnt = (0xFFFFFFFF - x) % WRAP
    out = {"n_records": len(a), "bad_framing": int(bad.sum()), "trailer": bool(len(end))}
    ia = np.nonzero(typ == 0xA5)[0]
    ta = _unwrap_seq(cnt[ia])
    out["conv_idx"] = ia
    out["t"] = ta * COUNT_S
    out["level"] = a[ia, 1].astype(int)
    seq = a[ia, 2].astype(np.int64) | (a[ia, 3].astype(np.int64) << 8)
    out["seq16"] = seq
    out["seq_gaps"] = int(np.sum((np.diff(seq) % 65536) != 1))
    out["vsh"] = s20(a[ia, 8], a[ia, 9], a[ia, 10])
    out["vbus"] = s20(a[ia, 11], a[ia, 12], a[ia, 13])
    out["diag"] = (a[ia, 14].astype(int) << 8) | a[ia, 15]
    out["I"] = out["vsh"] * STEP_A
    out["V"] = out["vbus"] * STEP_V
    out["P"] = out["I"] * out["V"]
    # reference conversion count for every record (nearest preceding conversion, else following)
    pos = np.searchsorted(ia, np.arange(len(a)), side="right") - 1
    pos = np.clip(pos, 0, max(len(ia) - 1, 0))
    for name, code in (("rise", 0xB6), ("fall", 0xB7)):
        im = np.nonzero(typ == code)[0]
        if len(ia) and len(im):
            ref = ta[pos[im]]
            d = (cnt[im] - ref) % WRAP
            d = np.where(d >= (1 << 31), d - WRAP, d)
            out[name] = (ref + d) * COUNT_S
            out[name + "_level"] = a[im, 1].astype(int)
            s = a[im, 2].astype(np.int64) | (a[im, 3].astype(np.int64) << 8)
            out[name + "_seq_gaps"] = int(np.sum((np.diff(s) % 65536) != 1))
        else:
            out[name] = np.zeros(0)
            out[name + "_seq_gaps"] = 0
    ic = np.nonzero(typ == 0xC7)[0]
    acc = []
    for i in ic:
        reg = int(a[i, 1])
        s = int(a[i, 2]) | (int(a[i, 3]) << 8)
        tk = struct.unpack_from("<I", a[i].tobytes(), 4)[0]
        v = int.from_bytes(a[i, 8:13].tobytes(), "big")
        if reg == 0x0A and v & (1 << 39):
            v -= 1 << 40
        acc.append((int(pos[i]), reg, s, tk, v))
    out["acc"] = acc
    sy = []
    for i in np.nonzero(typ == 0xD8)[0]:
        b = a[i].tobytes()
        a1, xr, xf = struct.unpack_from("<III", b, 4)
        sy.append({"phase": b[1], "a1_minus_a2": b[2] | (b[3] << 8), "xa": a1, "xr": xr, "xf": xf})
    out["sync"] = sy
    return out


def accum_series(c):
    """ENERGY (J) and CHARGE (C) samples with the time of the preceding conversion."""
    t = c["t"]
    ia = c["conv_idx"]
    E, Q = [], []
    for pos, reg, s, tk, v in c["acc"]:
        tt = t[pos] if len(t) else np.nan            # pos = index of the preceding conversion
        if reg == 0x09:
            E.append((tt, v * 16 * 3.2 * (10.9 / (1 << 19))))
        else:
            Q.append((tt, v * (10.9 / (1 << 19))))
    return np.array(E).reshape(-1, 2), np.array(Q).reshape(-1, 2)
