"""T6 (2 Nov 2026) diagnostic: where do the 10 Hz sampler's and freqlog's reads fall within the decision period?

  .venv/bin/python scripts/phase_diag.py CAP OUT.txt

Both loggers and mark_ctl stamp with the board's CLOCK_MONOTONIC, so each read's phase after the preceding marker
write is exact (no clock mapping). Per H/A block: the phase distribution of the sampler's reads (t0..t1) and of
freqlog's reads, and the INA228 excess folded on the sampler reads (board mono -> PIO time by a per-block fit of
marker write time to marker edge time, mark_ctl row j <-> edge j).
"""
import csv
import json
import os
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
cap, outf = sys.argv[1], sys.argv[2]
c = load(os.path.join(RUN, "raw", cap + ".bin"))
ok = c["cnvrf"].copy(); ok[0] = False
tc = c["t"][ok] - 540e-6
P = c["P"][ok]
fall = c["fall"]
runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 0.5)[0] + 1)
big = [r for r in runs if len(r) > 1]
blocks = [b for b in json.load(open(os.path.join(RUN, "raw", "blocks.json"))) if b["capture"] == cap and b["cond"] in ("H", "A")]
S = np.genfromtxt(os.path.join(RUN, "raw", "board", cap + "_ina3221_10hz.csv"), delimiter=",", names=True, dtype=np.int64)
F = np.genfromtxt(os.path.join(RUN, "raw", "board", cap + "_freq.csv"), delimiter=",", names=True, dtype=np.int64)
X = {}
for l in open(os.path.join(RUN, "raw", f"result_{cap}.txt")):
    if l.startswith("| R") and f"| {cap} |" in l:
        p = [x.strip() for x in l.split("|")]
        X[p[1]] = float(p[6])
L = []
L.append(f"{cap}: sampler {len(S)} reads, read duration t1-t0 p50 {np.median(S['t1_ns'] - S['t0_ns']) / 1e3:.0f} us; "
         f"sampler period p50 {np.median(np.diff(S['t0_ns'])) / 1e6:.4f} ms; freqlog period p50 {np.median(np.diff(F['mono_ns'])) / 1e6:.4f} ms")
L.append("| block | X [-1,4.5) uJ | sampler start phase after marker, ms: p10 / p50 / p90 | sampler end phase p50 | freqlog phase p50 | "
         "board-mono -> PIO fit resid us | INA228 excess around the sampler reads, uJ per read |")
L.append("|---|---|---|---|---|---|---|")
for b, r in zip(blocks, big):
    fr = fall[r]
    rows = list(csv.DictReader(open(os.path.join(RUN, "raw", "board", b["mc_csv"]))))
    tb = np.array([int(x["t_before_ns"]) for x in rows], dtype=np.int64)
    if len(tb) != len(fr):
        L.append(f"{b['tag']}: length mismatch"); continue
    cf = np.polyfit((tb - tb[0]) / 1e9, fr, 1)
    res = fr - np.polyval(cf, (tb - tb[0]) / 1e9)
    m = (S["t0_ns"] > tb[0] + 3e9) & (S["t0_ns"] < tb[-1] - 3e9)
    s0, s1 = S["t0_ns"][m], S["t1_ns"][m]
    j = np.searchsorted(tb, s0, side="right") - 1
    ph0 = (s0 - tb[j]) / 1e6
    ph1 = (s1 - tb[j]) / 1e6
    mf = (F["mono_ns"] > tb[0] + 3e9) & (F["mono_ns"] < tb[-1] - 3e9)
    jf = np.searchsorted(tb, F["mono_ns"][mf], side="right") - 1
    phf = (F["mono_ns"][mf] - tb[jf]) / 1e6
    # INA228 folded on the sampler reads: power vs time since read start, -20..+80 ms, baseline = the far part
    ts = np.polyval(cf, (s0 - tb[0]) / 1e9)
    edges = np.arange(-20, 80.001, 0.5) * 1e-3
    sel = (tc > ts[0] - 0.05) & (tc < ts[-1] + 0.1)
    tt, pp = tc[sel], P[sel]
    k = np.searchsorted(ts, tt + 0.02, side="right") - 1
    kk = np.clip(k, 0, len(ts) - 1)
    d = tt - ts[kk]
    v = (k >= 0) & (d >= -0.02) & (d < 0.08)
    bi = np.digitize(d[v], edges) - 1
    nb = len(edges) - 1
    prof = np.bincount(bi, pp[v], nb) / np.maximum(np.bincount(bi, minlength=nb), 1)
    ctr = (edges[:-1] + edges[1:]) / 2
    base = prof[(ctr >= 0.03) & (ctr < 0.08)].mean()
    ex = np.sum(prof[(ctr >= -0.002) & (ctr < 0.012)] - base) * 0.5e-3
    b["sampler_prof"] = (prof - base).tolist()
    L.append(f"| {b['tag']} | {X.get(b['tag'], float('nan')):.1f} | {np.percentile(ph0, 10):.2f} / {np.median(ph0):.2f} / {np.percentile(ph0, 90):.2f} | "
             f"{np.median(ph1):.2f} | {np.median(phf):.2f} | {res.std() * 1e6:.1f} | {ex * 1e6:+.0f} |")
prof_all = np.mean([b["sampler_prof"] for b in blocks if "sampler_prof" in b], axis=0)
seg = []
for a0, a1 in ((-5, 0), (0, 1), (1, 2), (2, 3), (3, 4), (4, 6), (6, 10), (10, 20)):
    mm = (ctr >= a0 * 1e-3) & (ctr < a1 * 1e-3)
    seg.append(f"[{a0},{a1}) {prof_all[mm].mean() * 1e3:+.1f}")
L.append("INA228 power around a sampler read, mean of blocks, ms after read start -> mW above [30, 80) ms: " + ", ".join(seg))
txt = "\n".join(L)
print(txt)
open(outf, "w").write(txt + "\n")
