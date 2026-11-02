"""Throwaway (board session 2026-10-26): compare the non-timing columns of two periods.csv files.

usage: .venv/bin/python cmpcsv.py RUN_A RUN_B
Timing columns per spec R2.3 / R12.2: sim_us, ctl_us, rtt_us, link_us, ctl_rx_ns, ctl_tx_ns,
send_lateness_us. Everything else is compared as exact strings (byte-identical values).
"""
import csv
import sys
from pathlib import Path

TIMING = {"sim_us", "ctl_us", "rtt_us", "link_us", "ctl_rx_ns", "ctl_tx_ns", "send_lateness_us"}


def rows(run):
    with open(Path(run) / "periods.csv", newline="", encoding="utf-8") as fh:
        r = csv.reader(fh)
        header = next(r)
        return header, list(r)


ha, ra = rows(sys.argv[1])
hb, rb = rows(sys.argv[2])
assert ha == hb, "headers differ"
cols = [i for i, c in enumerate(ha) if c not in TIMING]
print(f"A={sys.argv[1]}\nB={sys.argv[2]}")
print(f"rows A={len(ra)} B={len(rb)}; compared columns ({len(cols)}): {', '.join(ha[i] for i in cols)}")
first = None
ndiff = 0
for k, (x, y) in enumerate(zip(ra, rb)):
    for i in cols:
        if x[i] != y[i]:
            ndiff += 1
            if first is None:
                first = (k, ha[i], x[i], y[i])
if len(ra) != len(rb):
    print("row counts differ")
if first is None and len(ra) == len(rb):
    print("IDENTICAL: all non-timing columns match exactly in every row")
else:
    print(f"first difference: row {first[0]} (k={ra[first[0]][1]}), column {first[1]}: A={first[2]} B={first[3]}; total differing cells={ndiff}")
