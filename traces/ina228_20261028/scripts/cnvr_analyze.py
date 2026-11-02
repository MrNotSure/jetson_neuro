"""Step 7b analysis: conversion-ready intervals and whether every conversion was read.

  python3.12 cnvr_analyze.py <07b_cnvr.txt>
"""
import re
import statistics as st
import sys
from collections import defaultdict

NS = 24.0
edges, acts, syncs, meta = defaultdict(list), defaultdict(list), {}, {}
for line in open(sys.argv[1]):
    m = re.match(r"RUN (\S+) .*expected_cycle_us=(\d+)", line)
    if m:
        meta[m[1]] = int(m[2])
    if not line.startswith("D,"):
        continue
    p = line.strip().split(",")
    if p[2] == "edge":
        edges[p[1]].append(int(p[4]))
    elif p[2] == "act":
        acts[p[1]].append(tuple(int(x) for x in p[4:8]))
    elif p[2] == "sync":
        syncs[p[1]] = (float(p[3]), int(p[4]))


def pct(xs, q):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(q * (len(xs) - 1) + 0.5))]


for name, e in edges.items():
    Texp = meta[name]
    ta, xa = syncs[name]
    t = [(xa - x) * NS / 1000 for x in e]
    falls, rises = t[0::2], t[1::2]
    lows = [r - f for f, r in zip(falls, rises)]
    glitches = sum(1 for x in lows if x < 1.0)
    conv = falls[1:]                       # the first fall is CNVR being enabled
    # Slot numbers from the expected period, refined by a least-squares fit.
    T = Texp
    for _ in range(3):
        ks = [round((f - conv[0]) / T) for f in conv]
        mk, mf = st.fmean(ks), st.fmean(conv)
        T = sum((k - mk) * (f - mf) for k, f in zip(ks, conv)) / sum((k - mk) ** 2 for k in ks)
    res = [f - (mf + (k - mk) * T) for k, f in zip(ks, conv)]
    on = [abs(r) < 3.0 for r in res]
    ivals = [b - a for a, b, k1, k2 in zip(conv, conv[1:], ks, ks[1:]) if k2 - k1 == 1]
    slots = ks[-1] - ks[0] + 1
    missed = slots - len(set(ks))
    print(f"== {name}  (expected cycle {Texp} us)")
    print(f"   conversions seen {len(conv)} of {slots} slots; missed {missed}; off-grid falls {on.count(False)}; "
          f"glitch pulses <1 us {glitches}")
    print(f"   interval (consecutive slots, n={len(ivals)}): median {st.median(ivals):.3f} us, "
          f"min {min(ivals):.3f}, max {max(ivals):.3f}, sd {st.pstdev(ivals) * 1000:.0f} ns, "
          f"p1..p99 {pct(ivals, .01):.3f}..{pct(ivals, .99):.3f}")
    print(f"   fitted period {T:.4f} us = expected {(T / Texp - 1) * 100:+.4f} %; "
          f"jitter about the fit sd {st.pstdev(res) * 1000:.0f} ns, max |res| {max(abs(r) for r in res) * 1000:.0f} ns")
    a = acts.get(name, [])
    if not a:
        continue
    # Phase steps: intervals that are not a whole number of periods.
    steps = []
    for (k1, f1), (k2, f2) in zip(zip(ks, conv), zip(ks[1:], conv[1:])):
        d = (f2 - f1) - (k2 - k1) * st.median(ivals)
        if abs(d) > 1.0:
            steps.append((round(f1 - conv[0]), round(d, 2)))
    print(f"   phase steps of the conversion grid (>1 us): {steps[:10]}")
    # CPU timing relative to the fall that triggered each action. Action i follows
    # falls[i] (falls[0] = CNVR enable). Start-sync mapping, +-17 us.
    pairs = list(zip(a, falls[: len(a)]))[1:]
    react = [s - ta - f for (s, m_, b, v), f in pairs]
    if a[0][1] != a[0][0]:
        vsh_done = [m_ - ta - f for (s, m_, b, v), f in pairs]
    else:
        vsh_done = None
    diag_done = [b - ta - f for (s, m_, b, v), f in pairs]
    print(f"   handler start after the fall: median {st.median(react):.0f} us, p99 {pct(react, .99):.0f}, max {max(react):.0f}")
    if vsh_done:
        late = sum(1 for x in vsh_done if x > T - 50)
        print(f"   VSHUNT read done after the fall: median {st.median(vsh_done):.0f} us, p99 {pct(vsh_done, .99):.0f}, "
              f"max {max(vsh_done):.0f}; later than T-50 us (risk of reading the next result): {late}")
        vs = [v for (s, m_, b, v) in a]
        print(f"   VSHUNT values: mean {st.fmean(vs):.2f} steps, sd {st.pstdev(vs):.2f}")
    print(f"   DIAG_ALRT read done (ALRT re-armed) after the fall: median {st.median(diag_done):.0f} us, "
          f"p99 {pct(diag_done, .99):.0f}, max {max(diag_done):.0f}; margin to next conversion "
          f"min {T - max(diag_done):.0f} us")
