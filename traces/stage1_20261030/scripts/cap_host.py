"""Stage 1 run, Mac side: run cap_pico.py on the Pico and stream it to disk. Standard library only.

  .venv/bin/python cap_host.py NAME [--max-s 4000]

Writes raw/NAME.bin (records as received), raw/NAME.chunks.csv (Mac arrival time of each read:
monotonic ns, unix ns, total bytes), raw/NAME.txt (Pico STATS line and host summary), and keeps
/private/tmp/jn_run1/NAME.status.json updated twice a second (live current and power).
Stop: create /private/tmp/jn_run1/stop_NAME, or SIGTERM/SIGINT; the host then sends 'q' and
waits for the trailer. Over-current alarm (every 10 ms mean above ALARM_A for a whole second):
the host logs it and says it aloud; the supply still has to be unplugged by hand.
"""
import json
import os
import select
import signal
import struct
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import picolink  # noqa: E402

SCRATCH = "/private/tmp/jn_run1"
STEP_A = 312.5e-9 / 0.015
STEP_V = 195.3125e-6
ALARM_A = 2.5
LOG = os.path.join(RUN, "commands.log")
VALID = {0xA5, 0xB6, 0xB7, 0xC7, 0xD8, 0x5A}

stop_req = False


def _sig(signum, frame):
    global stop_req
    stop_req = True


def s20(b):
    v = ((b[0] << 16) | (b[1] << 8) | b[2]) >> 4
    return v - (1 << 20) if v & 0x80000 else v


def main():
    name = sys.argv[1]
    max_s = 4000
    if "--max-s" in sys.argv:
        max_s = int(sys.argv[sys.argv.index("--max-s") + 1])
    with open(LOG, "a") as f:
        f.write("%s\tmac\t%s\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), " ".join(sys.argv)))
    signal.signal(signal.SIGTERM, _sig)
    signal.signal(signal.SIGINT, _sig)
    stop_file = os.path.join(SCRATCH, "stop_" + name)
    status_path = os.path.join(SCRATCH, name + ".status.json")
    if os.path.exists(stop_file):
        sys.exit(f"stale stop file {stop_file}; move it aside first")
    code = (open(os.path.join(HERE, "ina_common.py")).read() + f"\nMAX_S = {max_s}\n"
            + open(os.path.join(HERE, "cap_pico.py")).read())
    raw_dir = os.path.join(RUN, "raw")
    fbin = open(os.path.join(raw_dir, name + ".bin"), "wb")
    fchk = open(os.path.join(raw_dir, name + ".chunks.csv"), "w")
    fchk.write("mac_mono_ns,mac_unix_ns,bytes_total\n")
    path, port, repl = picolink.open_repl()
    t_start_unix = time.time()
    counts = {k: 0 for k in VALID}
    bad = 0
    pending = bytearray()
    total = 0
    win = []                 # (t_mac, I, P, V) per conversion, last ~2 s
    peak_i = None
    peak_i_t = None
    over_since = None
    alarm = False
    sent_q = False
    trailer = False
    last_status = 0
    last_data = time.monotonic()
    tail = b""
    sync = []
    first_conv_skipped = False
    try:
        repl.start(code)
        if port.buf:
            pending += port.buf
            port.buf.clear()
        while True:
            if (stop_req or os.path.exists(stop_file)) and not sent_q:
                port.write(b"q")
                sent_q = True
            r, _, _ = select.select([port.fd], [], [], 0.2)
            chunk = b""
            if r:
                try:
                    chunk = os.read(port.fd, 1 << 16)
                except BlockingIOError:
                    chunk = b""
            now = time.monotonic()
            if chunk:
                last_data = now
                pending += chunk
            # consume complete records
            nrec = len(pending) // 16
            out = bytearray()
            for i in range(nrec):
                rec = pending[16 * i:16 * i + 16]
                t = rec[0]
                if t not in VALID:
                    bad += 1
                    raise RuntimeError(f"framing lost after {sum(counts.values())} records: {bytes(rec)!r}")
                if t == 0x5A:
                    trailer = True
                    tail = bytes(pending[16 * (i + 1):])
                    out += rec
                    break
                counts[t] += 1
                out += rec
                if t == 0xA5:
                    if not first_conv_skipped:
                        first_conv_skipped = True
                        continue
                    I = s20(rec[8:11]) * STEP_A
                    V = s20(rec[11:14]) * STEP_V
                    win.append((now, I, I * V, V))
                    if peak_i is None or I > peak_i:
                        peak_i, peak_i_t = I, time.time() - t_start_unix
                elif t == 0xD8:
                    sync.append(bytes(rec).hex())
            if out:
                fbin.write(out)
                total += len(out)
                fchk.write("%d,%d,%d\n" % (time.monotonic_ns(), time.time_ns(), total))
            if trailer:
                pending = bytearray()
                break
            pending = pending[16 * nrec:]
            # over-current watch on 10 ms means of the last second
            cut = now - 2.0
            while win and win[0][0] < cut:
                win.pop(0)
            if now - last_status > 0.5:
                last_status = now
                w1 = [x for x in win if x[0] >= now - 1.0]
                st = {"utc": time.strftime("%H:%M:%S", time.gmtime()), "elapsed_s": round(time.time() - t_start_unix, 1),
                      "conversions": counts[0xA5], "rises": counts[0xB6], "falls": counts[0xB7], "acc": counts[0xC7],
                      "n_last_1s": len(w1)}
                if w1:
                    st["I_1s_A"] = round(sum(x[1] for x in w1) / len(w1), 4)
                    st["P_1s_W"] = round(sum(x[2] for x in w1) / len(w1), 3)
                    st["V_1s"] = round(sum(x[3] for x in w1) / len(w1), 3)
                    st["I_max_1s_A"] = round(max(x[1] for x in w1), 4)
                    # 10 ms means (about 9 conversions each)
                    m10 = [sum(x[1] for x in w1[j:j + 9]) / len(w1[j:j + 9]) for j in range(0, len(w1), 9)]
                    if len(w1) > 800 and min(m10) > ALARM_A:
                        if not alarm:
                            alarm = True
                            subprocess.Popen(["say", "Over current. Unplug the supply."])
                        st["ALARM"] = "current above %.1f A for 1 s" % ALARM_A
                st["peak_I_A"] = None if peak_i is None else round(peak_i, 4)
                st["peak_I_at_s"] = None if peak_i_t is None else round(peak_i_t, 2)
                st["alarm_ever"] = alarm
                with open(status_path + ".tmp", "w") as f:
                    json.dump(st, f)
                os.replace(status_path + ".tmp", status_path)
            if now - last_data > 10:
                raise TimeoutError("stream stalled for 10 s")
        port.buf += tail
        o, e = repl.finish(timeout=20)
        repl.exit()
    finally:
        port.close()
        fbin.close()
        fchk.close()
    stats = o.decode(errors="replace").strip()
    lines = [f"port {path}", f"started unix {t_start_unix:.3f} ({time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(t_start_unix))})",
             f"ended unix {time.time():.3f}", f"records by type {{{', '.join('0x%02X: %d' % (k, v) for k, v in sorted(counts.items()))}}}",
             f"bytes {total}; bad framing {bad}; trailer {trailer}; stop sent by host {sent_q}",
             f"sync records {sync}", f"peak single-conversion current {peak_i} A at {peak_i_t} s; alarm {alarm}",
             f"Pico stdout: {stats}", f"Pico stderr: {e!r}"]
    open(os.path.join(raw_dir, name + ".txt"), "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
