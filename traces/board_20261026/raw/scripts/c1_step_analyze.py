"""Throwaway (board session 2026-10-26): step response of the INA3221 readings.

usage: .venv/bin/python c1_step_analyze.py SAMPLER_CSV MARKS_CSV
For each burst: baseline (mean over the 300 ms before), level during the burst, and the time from
burst start (and end) until curr2 (VDD_CPU_GPU_CV) first crosses half-way. Also prints the curr2
trace around the 1000 ms burst edges, so the rise shape (one jump vs ramp) is visible.
"""
import sys

import numpy as np

a = np.loadtxt(sys.argv[1], delimiter=",", skiprows=1, dtype=np.int64)
m = np.loadtxt(sys.argv[2], delimiter=",", skiprows=1)
t = a[:, 0]
cols = {"in1": a[:, 2], "curr1": a[:, 3], "in2": a[:, 4], "curr2": a[:, 5], "in3": a[:, 6], "curr3": a[:, 7]}
p2 = cols["in2"] * cols["curr2"] / 1000.0
p1 = cols["in1"] * cols["curr1"] / 1000.0
print(f"samples={len(t)} spacing median={np.median(np.diff(t))/1e6:.3f} ms")
for s, e, d in m:
    s, e = int(s), int(e)
    base = (t > s - 300e6) & (t < s)
    during = (t >= s) & (t < e)
    b2 = p2[base].mean()
    print(f"burst {d*1000:.0f} ms: VDD_CPU_GPU_CV base={b2:.0f} mW, during mean={p2[during].mean() if during.any() else float('nan'):.0f} max={p2[during].max() if during.any() else float('nan'):.0f}; "
          f"VDD_IN base={p1[base].mean():.0f} during mean={p1[during].mean() if during.any() else float('nan'):.0f}")
    after = (t >= s) & (t < e + 600e6)
    peak = p2[after].max()
    half = b2 + 0.5 * (peak - b2)
    idx = np.flatnonzero(after & (p2 >= half))
    if idx.size:
        print(f"   peak within burst+600ms={peak:.0f} mW; first sample >= half-way at +{(t[idx[0]]-s)/1e6:.1f} ms after start; "
              f"last >= half-way at +{(t[idx[-1]]-e)/1e6:.1f} ms after end")
s, e = int(m[0, 0]), int(m[0, 1])
for label, edge in (("rise", s), ("fall", e)):
    w = (t >= edge - 30e6) & (t < edge + 60e6)
    print(f"{label} edge of the 1000 ms burst, curr2 [mA] at (ms rel. edge):")
    print("   " + " ".join(f"{(ti-edge)/1e6:+.0f}:{ci}" for ti, ci in zip(t[w], cols["curr2"][w])))
    print("   curr1: " + " ".join(f"{(ti-edge)/1e6:+.0f}:{ci}" for ti, ci in zip(t[w], cols["curr1"][w])))
