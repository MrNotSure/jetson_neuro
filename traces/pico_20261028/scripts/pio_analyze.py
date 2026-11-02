"""Analyse the PIO edge-capture CSV printed by pio_edges.py. Standard library only."""
import re
import statistics as st
import sys

runs = []
cur = None
for line in open(sys.argv[1]):
    line = line.strip()
    m = re.match(r"RUN period_us=(\d+) generated=(\d+) captured=(\d+) sysclk=(\d+) sm_freq=(\d+) cycles_per_count=(\d+)", line)
    if m:
        cur = dict(period_us=int(m[1]), gen=int(m[2]), cap=int(m[3]), sm_freq=int(m[5]), cpc=int(m[6]), pio=[], cpu=[])
        runs.append(cur)
    elif line.startswith("E,") and cur is not None:
        _, i, p, c = line.split(",")
        if int(p) >= 0:
            cur["pio"].append(int(p))
        if int(c) >= 0:
            cur["cpu"].append(int(c))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


for r in runs:
    ns_per_count = r["cpc"] * 1e9 / r["sm_freq"]
    # Down-counter: interval = previous - current (no wrap within a run: start 2**30-1).
    d = [a - b for a, b in zip(r["pio"], r["pio"][1:])]
    d_us = [x * ns_per_count / 1000 for x in d]
    cpu_d = [(b - a) & ((1 << 30) - 1) for a, b in zip(r["cpu"], r["cpu"][1:])]
    n = min(len(d), len(cpu_d))
    diff = [d_us[i] - cpu_d[i] for i in range(n)]
    # Cumulative: total PIO span vs CPU span (same clock source, so should agree to ~1 us).
    span_pio_us = (r["pio"][0] - r["pio"][-1]) * ns_per_count / 1000
    span_cpu_us = (r["cpu"][-1] - r["cpu"][0]) & ((1 << 30) - 1)
    print(f"== period {r['period_us']} us (~{1e6 / r['period_us']:.0f} Hz) ==")
    print(f"edges generated {r['gen']}, captured {r['cap']}, intervals {len(d)}")
    print(f"resolution: 1 count = {r['cpc']} SM cycles at {r['sm_freq'] / 1e6:.3f} MHz = {ns_per_count:.1f} ns")
    print(f"interval counts: median {st.median(d):.0f}, min {min(d)}, max {max(d)}, "
          f"p1 {pct(d, 0.01)}, p99 {pct(d, 0.99)}")
    print(f"interval us:     median {st.median(d_us):.3f}, min {min(d_us):.3f}, max {max(d_us):.3f}, "
          f"stdev {st.pstdev(d_us):.3f}")
    print(f"nominal period {r['period_us']} us; median - nominal = {st.median(d_us) - r['period_us']:+.3f} us")
    print(f"PIO interval - CPU ticks_us interval (us): median {st.median(diff):+.3f}, "
          f"min {min(diff):+.3f}, max {max(diff):+.3f}")
    print(f"total span: PIO {span_pio_us:.3f} us, CPU {span_cpu_us} us, diff {span_pio_us - span_cpu_us:+.3f} us")
    print(f"distinct interval values: {len(set(d))}")
    print()
