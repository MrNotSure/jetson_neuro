"""Stage 1 Part 5, board side: synthetic decisions at 100 Hz on an absolute schedule.

Per period: sleep until ~300 us before the slot, spin to the slot, write one 0xFF byte to
/dev/ttyTHS1 (header pin 8: one 8.7 us low pulse = decision start), spin on time.perf_counter_ns
for W after the write returns, then sleep to the next slot. No end byte (it would queue behind the
start byte's 87 us frame at W = 0); the board logs start and end of the busy work itself.
One dummy byte after opening the port (the first write is slow). Blocks are separated by GAP s
without markers. Standard library only.

  ~/venvs/jn/bin/python p5_decisions.py --order 0,1000,... --block-s 60 --gap-s 5 --out /tmp/jn_run1/P5.csv
CSV: block,w_us,i,t_sched_ns,t_wr0_ns,t_wr1_ns,t_end_ns   (CLOCK_MONOTONIC)
"""
import argparse
import json
import os
import signal
import termios
import time
import tty

stop = False


def _stop(s, f):
    global stop
    stop = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", required=True)
    ap.add_argument("--block-s", type=float, default=60)
    ap.add_argument("--gap-s", type=float, default=5)
    ap.add_argument("--hz", type=float, default=100)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    order = [int(x) for x in a.order.split(",")]
    period = int(round(1e9 / a.hz))
    n = int(round(a.block_s * a.hz))
    mono, pc = time.monotonic_ns, time.perf_counter_ns
    fd = os.open("/dev/ttyTHS1", os.O_WRONLY | os.O_NOCTTY)
    tty.setraw(fd)
    at = termios.tcgetattr(fd)
    at[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | termios.CRTSCTS)
    at[2] |= termios.CS8 | termios.CLOCAL
    at[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
    at[4] = at[5] = termios.B115200
    termios.tcsetattr(fd, termios.TCSANOW, at)
    w, byte = os.write, b"\xff"
    rows = []
    blocks = []
    try:
        t_dummy = mono()
        w(fd, byte)                                   # dummy byte, then idle
        termios.tcdrain(fd)
        t0 = mono() + int(a.gap_s * 1e9)
        for b, wus in enumerate(order):
            if stop:
                break
            wns = wus * 1000
            bstart = t0
            for i in range(n):
                if stop:
                    break
                ts = t0 + i * period
                while True:
                    d = ts - mono()
                    if d <= 0:
                        break
                    if d > 300_000:
                        time.sleep((d - 300_000) / 1e9)
                t1 = mono()
                w(fd, byte)
                t2 = mono()
                end = t2 + wns
                while pc() < end:
                    pass
                rows.append((b, wus, i, ts, t1, t2, mono()))
            blocks.append({"block": b, "w_us": wus, "t_start_ns": bstart, "t_end_ns": t0 + n * period})
            t0 = t0 + n * period + int(a.gap_s * 1e9)
        termios.tcdrain(fd)
    finally:
        os.close(fd)
    with open(a.out, "w") as f:
        f.write("block,w_us,i,t_sched_ns,t_wr0_ns,t_wr1_ns,t_end_ns\n")
        for r in rows:
            f.write("%d,%d,%d,%d,%d,%d,%d\n" % r)
    meta = {"order_us": order, "block_s": a.block_s, "gap_s": a.gap_s, "hz": a.hz, "decisions": len(rows),
            "stopped_early": stop, "t_dummy_ns": t_dummy, "blocks": blocks, "pid": os.getpid(),
            "utc_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(a.out + ".meta.json", "w") as f:
        json.dump(meta, f, indent=1)
    print(json.dumps({k: meta[k] for k in ("decisions", "stopped_early", "utc_end")}))


if __name__ == "__main__":
    main()
