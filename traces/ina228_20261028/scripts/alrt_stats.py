"""Step 7a statistics: conversion grid, glitches, and when ALRT rises within a DIAG_ALRT read.

  python3.12 alrt_stats.py <07a_alrt.txt>
"""
import statistics as st
import sys
from collections import defaultdict

NS = 24.0
BITS_2B_READ = 48          # S + addr/W + ptr + Sr + addr/R + 2 data bytes + P (in bit times, approx.)
FREQ = {"400k": 399_361, "100k": 100_000, "1M": 1_000_000}
edges, acts, syncs = defaultdict(list), defaultdict(list), {}
for line in open(sys.argv[1]):
    if not line.startswith("D,"):
        continue
    p = line.strip().split(",")
    if p[2] == "edge":
        edges[p[1]].append(int(p[4]))
    elif p[2] == "act":
        acts[p[1]].append((int(p[4]), int(p[5])))
    elif p[2] == "sync":
        syncs[p[1]] = (float(p[3]), int(p[4]))

summary = {}
for name in edges:
    if not name.startswith(("E4", "E5", "E6", "E7")):
        continue
    ta, xa = syncs[name]
    t = [(xa - x) * NS / 1000 for x in edges[name]]
    falls, rises = t[0::2], t[1::2]
    lows = [r - f for f, r in zip(falls, rises)]
    glitch = sum(1 for x in lows if x < 1.0)
    # Conversion grid: falls after the first one (the first is CNVR being enabled).
    cand = []
    for a_, b_ in zip(falls[1:], falls[2:]):
        n = round((b_ - a_) / 380)
        if n >= 1 and abs((b_ - a_) / n - 380) < 10:
            cand.append((b_ - a_) / n)
    T0 = st.median(cand)
    ref = falls[1]
    # Slot index of each fall, accumulated interval by interval so a small period
    # error cannot add up; only falls whose interval is a clean multiple count.
    ks, k = [0], 0
    pairs = [(0, falls[1])]
    for a_, b_ in zip(falls[1:], falls[2:]):
        n = (b_ - a_) / T0
        k += max(1, round(n))
        ks.append(k)
        pairs.append((k, b_))
    good = [(k_, f_) for (k_, f_), (kp, fp) in zip(pairs[1:], pairs[:-1])
            if abs((f_ - fp) - (k_ - kp) * T0) < 3.0]
    mk = st.fmean(k_ for k_, _ in good)
    mf = st.fmean(f_ for _, f_ in good)
    T = sum((k_ - mk) * (f_ - mf) for k_, f_ in good) / sum((k_ - mk) ** 2 for k_, _ in good)
    # Re-classify every fall against the fitted grid.
    on = []
    for f_ in falls[1:]:
        kk = round((f_ - mf) / T + mk)
        if abs(f_ - (mf + (kk - mk) * T)) < 3.0:
            on.append((kk, f_))
    res = [f_ - (mf + (k_ - mk) * T) for k_, f_ in on]
    ks = [k_ for k_, _ in on]
    off = len(falls) - 1 - len(on)
    slots = ks[-1] - ks[0] + 1
    missed = slots - len(set(k for k, _ in on))
    # Rise inside each action (CPU time mapped to PIO time with the start sync).
    a = [(s - ta, e - ta) for s, e in acts[name]]
    after_start, before_end = [], []
    for s, e in a:
        r = [x for x in rises if s - 20 <= x <= e + 20]
        if r:
            after_start.append(r[0] - s)
            before_end.append(e - r[0])
    dur = [e - s for s, e in a]
    summary[name] = (T, st.median(after_start), st.median(before_end), st.median(dur))
    print(f"== {name}")
    print(f"   falls {len(falls)} (first = CNVR enable), on-grid {len(on)}, off-grid {off}, "
          f"glitch pulses (<1 us low) {glitch}")
    print(f"   conversion period fit {T:.3f} us (expected 380), residual sd {st.pstdev(res) * 1000:.0f} ns, "
          f"max |res| {max(abs(x) for x in res) * 1000:.0f} ns")
    print(f"   grid slots {slots}, slots without a fall (conversion not seen) {missed}")
    print(f"   action (DIAG_ALRT read, CPU-timed) median {st.median(dur):.1f} us; ALRT rise: "
          f"{st.median(after_start):.1f} us after it starts (p10 {sorted(after_start)[len(after_start)//10]:.1f}, "
          f"p90 {sorted(after_start)[9*len(after_start)//10]:.1f}), "
          f"{st.median(before_end):.1f} us before it returns; {len(after_start)} of {len(a)} actions had a rise inside")

print()
print("Where in the read does ALRT rise? Model: (return - rise) = p + m * t_bit, with m the bit times")
print("between the rise and the end of the bus transaction and p the software time after it.")
# E4 (transparent, 400 kHz) is left out: its rises are mixed with glitches.
use = {"E7_transparent_diag_1M": "1M", "E5_latched_diag_400k": "400k", "E6_transparent_diag_100k": "100k"}
pts = sorted((1e6 / FREQ[key], summary[name][2], name) for name, key in use.items())
for tb, bef, name in pts:
    print(f"   {name:28s} t_bit {tb:5.2f} us: rise {bef:6.1f} us before the call returns")
xs = [p[0] for p in pts]
ys = [p[1] for p in pts]
mx, my = st.fmean(xs), st.fmean(ys)
m = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sum((x - mx) ** 2 for x in xs)
p = my - m * mx
print(f"   fit: m = {m:.1f} bit times before the end of the transaction, p = {p:.1f} us software overhead")
print(f"   i.e. ALRT rises at about bit {BITS_2B_READ - m:.0f} of the ~{BITS_2B_READ}-bit DIAG_ALRT read")
