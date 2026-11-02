"""Throwaway (board session 2026-10-26): C1 analysis of sampler CSVs (Mac, numpy).

usage: .venv/bin/python c1_analyze.py CSV [CSV ...]
Per file: achieved rate, read cost per sample (t1-t0) and per read (/6), effective update
interval per column (median time between value changes), the fraction of samples where a
column changed, and how often the columns change together.
"""
import json
import sys

import numpy as np

COLS = ["in1", "curr1", "in2", "curr2", "in3", "curr3"]


def load(path):
    a = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.int64)
    return a[:, 0], a[:, 1], {c: a[:, 2 + i] for i, c in enumerate(COLS)}


for path in sys.argv[1:]:
    t0, t1, v = load(path)
    meta = json.load(open(path + ".meta.json"))
    dt = np.diff(t0) / 1e6
    cost = (t1 - t0) / 1e3
    print(f"=== {path.split('/')[-1]}  n={len(t0)} achieved={meta['achieved_hz']:.1f} Hz "
          f"cpu={meta['cpu_total_s']:.3f}s over {meta['wall_s']:.1f}s ({100*meta['cpu_fraction_of_one_core']:.1f}% of one core, "
          f"user {meta['cpu_user_s']:.3f} sys {meta['cpu_sys_s']:.3f})")
    print(f"  sample spacing ms: median={np.median(dt):.3f} p1={np.percentile(dt,1):.3f} p99={np.percentile(dt,99):.3f} max={dt.max():.3f}")
    print(f"  6-read cost us: median={np.median(cost):.0f} p99={np.percentile(cost,99):.0f} max={cost.max():.0f}  -> per read median={np.median(cost)/6:.0f} us")
    ch = {}
    for c in COLS:
        changed = np.flatnonzero(np.diff(v[c]) != 0) + 1
        ch[c] = set(changed.tolist())
        if len(changed) > 1:
            iv = np.diff(t0[changed]) / 1e6
            print(f"  {c:6s}: changes={len(changed):5d} ({100*len(changed)/(len(t0)-1):5.1f}% of samples)  "
                  f"interval ms median={np.median(iv):8.3f} p10={np.percentile(iv,10):8.3f} p90={np.percentile(iv,90):8.3f}  "
                  f"distinct values={len(np.unique(v[c]))} min={v[c].min()} max={v[c].max()}")
        else:
            print(f"  {c:6s}: changes={len(changed)} distinct={len(np.unique(v[c]))} value(s)={np.unique(v[c])[:5]}")
    # do channels change together? fraction of curr1 change samples where curr2/curr3 also changed
    for a, b in [("curr1", "curr2"), ("curr1", "curr3"), ("curr2", "curr3"), ("curr1", "in1")]:
        if ch[a]:
            both = len(ch[a] & ch[b])
            print(f"  co-change {a}&{b}: {both}/{len(ch[a])} of {a} changes ({100*both/len(ch[a]):.0f}%)")
    p = {i: v[f"in{i}"] * v[f"curr{i}"] / 1000.0 for i in (1, 2, 3)}
    print(f"  power mW mean: VDD_IN={p[1].mean():.0f} VDD_CPU_GPU_CV={p[2].mean():.0f} VDD_SOC={p[3].mean():.0f}")
    print(f"  LSBs: in steps {sorted(set(np.diff(np.unique(v['in1'])).tolist()))[:3]} mV; curr1 steps {sorted(set(np.diff(np.unique(v['curr1'])).tolist()))[:3]} mA; curr2 steps {sorted(set(np.diff(np.unique(v['curr2'])).tolist()))[:3]} mA")
