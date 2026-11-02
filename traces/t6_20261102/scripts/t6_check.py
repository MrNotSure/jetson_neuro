"""T6 (2 Nov 2026): integrity check of the closed-loop blocks of one capture (works on a live capture).
From traces/stage1_20261031_final/scripts/p2_check.py. Changes: A instead of C; blocks filtered by capture;
marker pulse widths (each fall to the next rise); the dummy's own pulse width; mark_ctl CSVs in raw/board/.

  .venv/bin/python scripts/t6_check.py raw/CAP.bin CAP [mc csv dir]

Falls split at gaps > 0.5 s; runs of length 1 are the dummies. For each H/A block of CAP in raw/blocks.json (in
order), compares falls with the mark_ctl rows and the OBS count in periods.csv, k and n_events, the dummy's lead,
edge intervals, pulse widths, the board's write() time, misses and send_lateness_us > 5 ms.
"""
import csv
import json
import os
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
binf, cap = sys.argv[1], sys.argv[2]
mcdir = sys.argv[3] if len(sys.argv) > 3 else os.path.join(RUN, "raw", "board")
c = load(binf)
fall, rise = c["fall"], c["rise"]
t = c["t"][1:]
iv = np.diff(t) * 1e6
T = np.median(iv)
missed = int(np.sum(np.round(iv[iv > 1.5 * T] / T) - 1))
print(f"{cap}: conversions {len(c['t'])}, missed {missed}, spurious ALRT {int((~c['cnvrf'][1:]).sum())}, seq16 gaps {c['seq_gaps']}, "
      f"falls {len(fall)}, rises {len(rise)}, fall/rise seq gaps {c['fall_seq_gaps']}/{c['rise_seq_gaps']}, "
      f"FIFO levels conv {sorted(set(c['level'].tolist()))}, fall levels {sorted(set(c.get('fall_level', np.zeros(0, int)).tolist()))}, "
      f"rise levels {sorted(set(c.get('rise_level', np.zeros(0, int)).tolist()))}")
j = np.searchsorted(rise, fall, side="right")
okw = j < len(rise)
width = np.full(len(fall), np.nan)
width[okw] = (rise[j[okw]] - fall[okw]) * 1e6
if len(fall):
    print(f"pulse widths (fall -> next rise) us: min {np.nanmin(width):.2f}, p50 {np.nanmedian(width):.2f}, max {np.nanmax(width):.2f}; "
          f"outside 8.5-8.9: {int(np.sum((width < 8.5) | (width > 8.9)))}; falls without a following rise: {int((~okw).sum())}")
runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 0.5)[0] + 1) if len(fall) else []
print(f"fall runs: {[len(r) for r in runs]}")
blocks = [b for b in json.load(open(os.path.join(RUN, "raw", "blocks.json"))) if b["cond"] in ("H", "A") and b["capture"] == cap]
big = [j for j, r in enumerate(runs) if len(r) > 1]
lone = [j for j, r in enumerate(runs) if len(r) == 1]
print(f"H/A blocks in {cap}: {len(blocks)}; fall runs > 1: {len(big)}; lone edges: {len(lone)}")
for i, b in enumerate(blocks):
    rows = list(csv.DictReader(open(os.path.join(mcdir, b["mc_csv"]))))
    per = list(csv.DictReader(open(os.path.join(RUN, "sim", b["sim_dir"], "periods.csv"))))
    if i >= len(big):
        print(f"{b['tag']}: no fall run"); continue
    j = big[i]
    fr = fall[runs[j]]
    lone_before = j > 0 and len(runs[j - 1]) == 1
    lead = fr[0] - fall[runs[j - 1][-1]] if lone_before else float("nan")
    dw = width[runs[j - 1][0]] if lone_before else float("nan")
    d = np.diff(fr) * 1e3
    wd = width[runs[j]]
    wr = np.array([int(x["t_after_ns"]) - int(x["t_before_ns"]) for x in rows]) / 1e3
    miss = sum(int(p["miss"]) for p in per)
    late = np.array([float(p["send_lateness_us"]) for p in per])
    ks = [int(x["k"]) for x in rows]
    pk = [int(p["k"]) for p in per]
    ne = sum(int(x["n_events"]) != int(p["n_events"]) for x, p in zip(rows, per))
    print(f"{b['tag']} ({b['cond']}, affinity {b.get('affinity')}): falls {len(fr)}, mark_ctl rows {len(rows)}, OBS (periods.csv rows) {len(per)}; "
          f"k match {ks == pk}; n_events mismatches {ne}; dummy lead {lead:.3f} s (lone dummy before: {lone_before}, width {dw:.2f} us)")
    print(f"   edge interval ms: median {np.median(d):.3f}, min {d.min():.3f}, max {d.max():.3f}, outside 8-15 ms {int(np.sum((d < 8) | (d > 15)))}; "
          f"pulse width us min/p50/max {np.nanmin(wd):.2f}/{np.nanmedian(wd):.2f}/{np.nanmax(wd):.2f}")
    print(f"   write() us: first {wr[0]:.1f}, p50 {np.median(wr):.1f}, p99 {np.percentile(wr, 99):.1f}, max {wr.max():.1f}")
    print(f"   misses {miss} at k {[int(p['k']) for p in per if int(p['miss'])][:10]}; send_lateness > 5 ms: {int(np.sum(late > 5000))} "
          f"at k {[int(p['k']) for p, l in zip(per, late) if l > 5000][:10]}; lateness p50/p99/max {np.median(late):.0f}/{np.percentile(late, 99):.0f}/{late.max():.0f} us")
    ctl = np.array([float(p["ctl_us"]) for p in per if p["ctl_us"] not in ("", "nan")])
    print(f"   ctl_us p50 {np.median(ctl):.1f}, p99 {np.percentile(ctl, 99):.1f}, max {ctl.max():.1f}; n_events mean {np.mean([int(x['n_events']) for x in rows]):.1f}")
