"""Throwaway (board session 2026-10-26): C2 idle noise and C3 sampler-cost analysis (Mac, numpy).

usage: .venv/bin/python c23_analyze.py C23_DIR
"""
import json
import sys
from pathlib import Path

import numpy as np

RAILS = {1: "VDD_IN", 2: "VDD_CPU_GPU_CV", 3: "VDD_SOC"}


def load(path):
    a = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.int64)
    t = (a[:, 0] - a[0, 0]) / 1e9
    p = {i: a[:, 2 * i] * a[:, 2 * i + 1] / 1000.0 for i in (1, 2, 3)}  # mV*mA/1000 = mW
    return t, p, a


def blockmeans(t, x, w):
    k = np.floor(t / w).astype(int)
    n = k.max()  # drop the last, partial block
    return np.array([x[k == j].mean() for j in range(n) if np.any(k == j)])


d = Path(sys.argv[1])
f = d / "c2_idle_10hz_300s.csv"
t, p, a = load(f)
meta = json.load(open(str(f) + ".meta.json"))
print(f"=== C2 idle noise: {f.name} n={len(t)} span={t[-1]:.1f}s achieved={meta['achieved_hz']:.2f} Hz utc_end={meta['utc_end']}")
for i, name in RAILS.items():
    x = p[i]
    b1 = blockmeans(t, x, 1.0)
    b10 = blockmeans(t, x, 10.0)
    slope, icpt = np.polyfit(t, x, 1)
    # standard error of the slope (ordinary least squares, iid residuals: optimistic for correlated data)
    res = x - (slope * t + icpt)
    se = np.sqrt(np.sum(res**2) / (len(t) - 2) / np.sum((t - t.mean()) ** 2))
    print(f"  {name:15s} mean={x.mean():8.1f} mW sd={x.std(ddof=1):6.1f}  sd(1s means)={b1.std(ddof=1):6.1f} (n={len(b1)})  "
          f"sd(10s means)={b10.std(ddof=1):6.1f} (n={len(b10)})  drift={slope*60:+.2f} mW/min (OLS se {se*60:.2f})  "
          f"min={x.min():.0f} max={x.max():.0f}  first60s={x[t<60].mean():.1f} last60s={x[t>t[-1]-60].mean():.1f}")
    # largest 10 s excursion (to spot timer jobs)
    j = int(np.argmax(np.abs(b10 - np.median(b10))))
    print(f"      largest 10 s block deviation: block {j} (t={10*j}-{10*j+10}s) mean={b10[j]:.1f} vs median {np.median(b10):.1f}")
print("  raw current LSB 8 mA, voltage LSB 8 mV -> VDD_IN power LSB ~40 mW per sample")

print("\n=== C3 sampler cost: 10 Hz vs 1000 Hz requested, 60 s each, order 10,1000,10,1000")
rows = []
for f in sorted(d.glob("c3_*hz.csv")):
    t, p, a = load(f)
    meta = json.load(open(str(f) + ".meta.json"))
    sel = (t > 3) & (t < t[-1] - 3)  # drop the first/last 3 s, like the pilot blocks
    r = [f.name, meta["achieved_hz"], meta["cpu_fraction_of_one_core"]] + [p[i][sel].mean() for i in (1, 2, 3)]
    rows.append(r)
    print(f"  {f.name:16s} achieved={r[1]:7.1f} Hz cpu={100*r[2]:4.1f}% of one core  VDD_IN={r[3]:7.1f} VDD_CPU_GPU_CV={r[4]:6.1f} VDD_SOC={r[5]:6.1f} mW  (n={sel.sum()}, utc_end={meta['utc_end']})")
lo = [r for r in rows if "_10hz" in r[0]]
hi = [r for r in rows if "_1000hz" in r[0]]
for k, name in zip((3, 4, 5), RAILS.values()):
    dl = np.mean([r[k] for r in hi]) - np.mean([r[k] for r in lo])
    pairs = [h[k] - l[k] for l, h in zip(lo, hi)]
    print(f"  {name:15s} mean(1000Hz) - mean(10Hz) = {dl:+.1f} mW   per pair: {', '.join(f'{x:+.1f}' for x in pairs)}")
