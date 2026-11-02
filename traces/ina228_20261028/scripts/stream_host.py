"""Step 9, Mac side: receive the Pico's binary INA228 stream. Standard library only.

  python3.12 stream_host.py <pico_script.py> <out.bin> <report.txt>

Reuses picolink.py from the Pico bring-up (port lookup by USB vendor 0x2e8a and the
Pico's serial, raw REPL over os.open/termios). The Pico script is prepended with
ina_common.py and sent through the raw REPL; nothing is written to the Pico's flash.
"""
import os
import select
import statistics as st
import struct
import sys
import time

REPO = os.path.expanduser("~/Documents/code/jetson_neuro")
sys.path.insert(0, os.path.join(REPO, "traces/pico_20261028/scripts"))
import picolink  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REC = 16
COUNT_US = 0.12          # 3 cycles at 25 MHz
STEP_UA = 312.5e-9 / 0.015 * 1e6
VBUS_MV = 0.1953125


def s20(b):
    v = ((b[0] << 16) | (b[1] << 8) | b[2]) >> 4
    return v - (1 << 20) if v & 0x80000 else v


def main():
    pico_script, out_bin, out_txt = sys.argv[1:4]
    code = open(os.path.join(HERE, "ina_common.py")).read() + "\n" + open(pico_script).read()
    path, port, repl = picolink.open_repl()
    data = bytearray()
    chunks = []                                   # (mac monotonic ns, bytes so far)
    try:
        repl.start(code)
        data += port.buf
        port.buf.clear()
        t_first = None
        pos = 0
        last = time.monotonic()
        while True:
            r, _, _ = select.select([port.fd], [], [], 0.5)
            if r:
                try:
                    c = os.read(port.fd, 1 << 16)
                except BlockingIOError:
                    c = b""
                if c:
                    now = time.monotonic_ns()
                    if t_first is None:
                        t_first = now
                    data += c
                    chunks.append((now, len(data)))
                    last = time.monotonic()
            # Check each new complete record; the trailer starts with 0x5A.
            found = False
            while (pos + 1) * REC <= len(data):
                first = data[pos * REC]
                pos += 1
                if first == 0x5A:
                    found = True
                    break
                if first != 0xA5:
                    raise RuntimeError(f"framing lost at record {pos - 1}: {bytes(data[(pos - 1) * REC:pos * REC])!r}")
            if found:
                break
            if time.monotonic() - last > 10:
                raise TimeoutError("stream stalled")
        nrec = pos                                # records including the trailer
        tail = bytes(data[nrec * REC:])
        port.buf += tail
        out, err = repl.finish(timeout=15)
        repl.exit()
    finally:
        port.close()
    body = bytes(data[: (nrec - 1) * REC])
    open(out_bin, "wb").write(body)

    recs = [body[i:i + REC] for i in range(0, len(body), REC)]
    bad_magic = sum(1 for r in recs if r[0] != 0xA5)
    seqs = [struct.unpack_from("<I", r, 2)[0] for r in recs]
    seq_gaps = [(a, b) for a, b in zip(seqs, seqs[1:]) if b != a + 1]
    lvl = [r[1] for r in recs]
    ts = [struct.unpack_from("<I", r, 6)[0] * COUNT_US for r in recs]
    vsh = [s20(r[10:13]) for r in recs]
    vb = [s20(r[13:16]) for r in recs]
    # Drop record 0: its edge is CNVR being enabled, not a conversion end.
    iv = [b - a for a, b in zip(ts[1:], ts[2:])]
    T = st.median(iv)
    missed = sum(round(x / T) - 1 for x in iv if x > 1.5 * T)
    irregular = [round(x, 2) for x in iv if abs(x - T) > 1.0 and abs(x - T - 10) > 1.5 and x < 1.5 * T]
    steps = sum(1 for x in iv if 8.5 < x - T < 11.5)
    span_s = (ts[-1] - ts[1]) / 1e6
    mac_s = (chunks[-1][0] - t_first) / 1e9
    lines = [
        f"port {path}",
        f"Pico stdout after the binary stream: {out.decode(errors='replace').strip()}",
        f"Pico stderr: {err!r}",
        f"bytes received {len(body)} in {nrec - 1} records of {REC} bytes (+ trailer); bad magic {bad_magic}",
        f"sequence: first {seqs[0]}, last {seqs[-1]}, gaps {len(seq_gaps)} {seq_gaps[:5]}",
        f"records with FIFO backlog (level > 1 when serviced): {sum(1 for x in lvl if x > 1)}; levels seen {sorted(set(lvl))}",
        f"conversion interval (PIO): median {T:.3f} us, min {min(iv):.3f}, max {max(iv):.3f}; "
        f"+10 us grid steps {steps}; irregular {len(irregular)} {irregular[:5]}",
        f"missed conversions (intervals > 1.5 T): {missed}",
        f"PIO time span {span_s:.3f} s; records/s {(len(recs) - 1) / span_s:.1f}; "
        f"bytes/s {len(body) / mac_s:.0f} (Mac arrival span {mac_s:.3f} s)",
        f"VSHUNT: mean {st.fmean(vsh):.3f} steps = {st.fmean(vsh) * STEP_UA:.1f} uA, sd {st.pstdev(vsh):.2f} steps = {st.pstdev(vsh) * STEP_UA:.1f} uA",
        f"VBUS: mean {st.fmean(vb):.2f} steps = {st.fmean(vb) * VBUS_MV:.3f} mV, sd {st.pstdev(vb):.2f} steps, max {max(vb)} steps",
        f"Mac read chunks: {len(chunks)}, median chunk {st.median([b - a for (_, a), (_, b) in zip(chunks, chunks[1:])]):.0f} bytes",
    ]
    text = "\n".join(lines)
    print(text)
    open(out_txt, "w").write(text + "\n")


if __name__ == "__main__":
    main()
