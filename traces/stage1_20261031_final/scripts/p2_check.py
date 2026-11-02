"""Stage 1 final (31 Oct 2026), Part 2: integrity check of the closed-loop blocks so far (works on a live capture).

  .venv/bin/python scripts/p2_check.py raw/P2.bin [mc csv dir]

Falls split at gaps > 0.5 s; runs of length 1 are the dummies. For each H/C block in raw/P2_blocks.json (in
order), compares falls with the mark_ctl rows and the OBS count in periods.csv, the dummy's lead, edge
intervals, the board's write() time, misses and send_lateness_us > 5 ms.
"""
import csv
import json
import os
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
binf = sys.argv[1]
mcdir = sys.argv[2] if len(sys.argv) > 2 else os.path.join(RUN, "raw", "board")
c = load(binf)
fall = c["fall"]
t = c["t"][1:]
iv = np.diff(t) * 1e6
T = np.median(iv)
print(f"conversions {len(c['t'])}, missed {int(np.sum(np.round(iv[iv > 1.5 * T] / T) - 1))}, spurious ALRT {int((~c['cnvrf'][1:]).sum())}, "
      f"falls {len(fall)}, rises {len(c['rise'])}, FIFO levels conv {sorted(set(c['level'].tolist()))}, "
      f"fall levels {sorted(set(c.get('fall_level', np.zeros(0, int)).tolist()))}")
runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 0.5)[0] + 1) if len(fall) else []
print(f"fall runs: {[len(r) for r in runs]}")
blocks = [b for b in json.load(open(os.path.join(RUN, "raw", "P2_blocks.json"))) if b["cond"] in ("H", "C")]
big = [j for j, r in enumerate(runs) if len(r) > 1]
for i, b in enumerate(blocks):
    rows = list(csv.DictReader(open(os.path.join(mcdir, b["mc_csv"]))))
    per = list(csv.DictReader(open(os.path.join(RUN, "sim", b["sim_dir"], "periods.csv"))))
    if i >= len(big):
        print(f"{b['tag']}: no fall run"); continue
    j = big[i]
    fr = fall[runs[j]]
    lead = fr[0] - fall[runs[j - 1][-1]] if j > 0 and len(runs[j - 1]) == 1 else float("nan")
    d = np.diff(fr) * 1e3
    wr = np.array([int(x["t_after_ns"]) - int(x["t_before_ns"]) for x in rows]) / 1e3
    miss = sum(int(p["miss"]) for p in per)
    late = np.array([float(p["send_lateness_us"]) for p in per])
    ks = [int(x["k"]) for x in rows]
    pk = [int(p["k"]) for p in per]
    ne = sum(int(x["n_events"]) != int(p["n_events"]) for x, p in zip(rows, per))
    print(f"{b['tag']} ({b['cond']}): falls {len(fr)}, mark_ctl rows {len(rows)}, OBS (periods.csv rows) {len(per)}; "
          f"k match {ks == pk}; n_events mismatches {ne}; dummy lead {lead:.3f} s (lone dummy before: {j > 0 and len(runs[j - 1]) == 1})")
    print(f"   edge interval ms: median {np.median(d):.3f}, min {d.min():.3f}, max {d.max():.3f}, outside 8-15 ms {int(np.sum((d < 8) | (d > 15)))}")
    print(f"   write() us: first {wr[0]:.1f}, p50 {np.median(wr):.1f}, p99 {np.percentile(wr, 99):.1f}, max {wr.max():.1f}")
    print(f"   misses {miss} at k {[int(p['k']) for p in per if int(p['miss'])][:10]}; send_lateness > 5 ms: {int(np.sum(late > 5000))} "
          f"at k {[int(p['k']) for p, l in zip(per, late) if l > 5000][:10]}; lateness p50/p99/max {np.median(late):.0f}/{np.percentile(late, 99):.0f}/{late.max():.0f} us")
    ctl = np.array([float(p["ctl_us"]) for p in per if p["ctl_us"] not in ("", "nan")])
    print(f"   ctl_us p50 {np.median(ctl):.1f}, p99 {np.percentile(ctl, 99):.1f}; n_events mean {np.mean([int(x['n_events']) for x in rows]):.0f}")
