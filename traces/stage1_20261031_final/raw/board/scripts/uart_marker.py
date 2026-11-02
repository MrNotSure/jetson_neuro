"""Stage 1 fix session, board side: per-event marker on header pin 8 (UART1 TX, /dev/ttyTHS1).
Standard library only. One 0xFF byte per event = one start bit = one low pulse of 1/baud (8.68 us
at 115200) on an idle-high line. Events follow an absolute schedule on CLOCK_MONOTONIC.

  ~/venvs/jn/bin/python uart_marker.py --hz 100 --duration 60 --out /tmp/jn_fix/m3_100hz.csv

CSV rows: i, t_sched_ns, t_before_ns, t_after_ns  (time.monotonic_ns() around os.write).
Also writes OUT.meta.json. Idle 1 s before the first event and after the last (block boundaries).
SIGINT/SIGTERM stop the schedule early; the port is drained and closed in every case.
"""
import argparse
import json
import os
import signal
import termios
import time
import tty

DEV = "/dev/ttyTHS1"
stop = False


def _stop(signum, frame):
    global stop
    stop = True


def open_uart(baud):
    fd = os.open(DEV, os.O_WRONLY | os.O_NOCTTY)
    tty.setraw(fd)
    a = termios.tcgetattr(fd)
    a[2] &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB | termios.CRTSCTS)
    a[2] |= termios.CS8 | termios.CLOCAL
    a[0] &= ~(termios.IXON | termios.IXOFF | termios.IXANY)
    speed = getattr(termios, f"B{baud}")
    a[4] = a[5] = speed
    termios.tcsetattr(fd, termios.TCSANOW, a)
    return fd, termios.tcgetattr(fd)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hz", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--baud", type=int, default=115200)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    period = int(round(1e9 / a.hz))
    n = int(round(a.duration * a.hz))
    mono = time.monotonic_ns
    rows = []
    fd, attrs = open_uart(a.baud)
    byte = b"\xff"
    try:
        t0 = mono() + 1_000_000_000          # 1 s idle before the first event
        for i in range(n):
            if stop:
                break
            ts = t0 + i * period
            while True:                      # sleep to ~300 us before, then spin
                d = ts - mono()
                if d <= 0:
                    break
                if d > 300_000:
                    time.sleep((d - 300_000) / 1e9)
            tb = mono()
            os.write(fd, byte)
            ta = mono()
            rows.append((i, ts, tb, ta))
        termios.tcdrain(fd)
        time.sleep(1.0)                      # 1 s idle after the last event
    finally:
        os.close(fd)
    with open(a.out, "w") as f:
        f.write("i,t_sched_ns,t_before_ns,t_after_ns\n")
        for r in rows:
            f.write("%d,%d,%d,%d\n" % r)
    late = sorted(r[2] - r[1] for r in rows)
    wd = sorted(r[3] - r[2] for r in rows)
    q = lambda s, p: s[min(len(s) - 1, int(p * (len(s) - 1)))] / 1000 if s else None
    meta = {"dev": DEV, "baud": a.baud, "byte": "0xff", "hz": a.hz, "period_ns": period, "events_planned": n,
            "events_sent": len(rows), "stopped_early": stop, "first_sched_ns": rows[0][1] if rows else None,
            "lateness_us_p50_p99_max": [q(late, .5), q(late, .99), q(late, 1.0)],
            "write_us_p50_p99_max": [q(wd, .5), q(wd, .99), q(wd, 1.0)],
            "cflag": attrs[2], "ispeed": attrs[4], "utc_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "pid": os.getpid()}
    with open(a.out + ".meta.json", "w") as f:
        json.dump(meta, f, indent=1)
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
