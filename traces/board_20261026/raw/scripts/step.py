"""Throwaway (board session 2026-10-26): CPU load steps with known monotonic timestamps, to see
how fast the INA3221 readings respond (C1 update-interval check).

usage: ~/venvs/jn/bin/python step.py OUT_CSV
Six forked workers busy-loop together for each burst; the parent writes start/end monotonic_ns.
Schedule (seconds after start): 2.0 for 1000 ms, 4.5 for 300 ms, 6.0 for 100 ms, 7.5 for 30 ms, 9.0 for 10 ms.
"""
import os
import sys
import time

BURSTS = [(2.0, 1.000), (4.5, 0.300), (6.0, 0.100), (7.5, 0.030), (9.0, 0.010)]
NW = 6


def spin_until(t_ns):
    x = 0
    while time.monotonic_ns() < t_ns:
        x += 1
    return x


def main():
    out = sys.argv[1]
    t0 = time.monotonic_ns() + 200_000_000
    sched = [(t0 + int(s * 1e9), t0 + int((s + d) * 1e9)) for s, d in BURSTS]
    kids = []
    for w in range(NW):
        pid = os.fork()
        if pid == 0:
            os.sched_setaffinity(0, {w})
            for a, b in sched:
                now = time.monotonic_ns()
                if a > now:
                    time.sleep((a - now) / 1e9)
                spin_until(b)
            os._exit(0)
        kids.append(pid)
    for pid in kids:
        os.waitpid(pid, 0)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("start_ns,end_ns,duration_s\n")
        for (a, b), (s, d) in zip(sched, BURSTS):
            fh.write(f"{a},{b},{d}\n")


if __name__ == "__main__":
    main()
