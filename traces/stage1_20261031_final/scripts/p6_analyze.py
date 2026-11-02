"""Stage 1 final (31 Oct 2026), Part 2: closed loop, hold (H) against centroid (C), with idle (I) blocks.
Derived from traces/stage1_20261030/scripts/p5_analyze.py (Part 5, method (b) as it ran).

  .venv/bin/python scripts/p6_analyze.py raw/P2.bin raw/P2.chunks.csv raw/board/P2_ina3221_10hz.csv OUTPREFIX

Same definitions as Part 5: conversion time = ALRT edge - 540 us; 0.1 ms bins; baseline [5.5, 8.5) ms after
the edge; window [-PRE, 4.5) ms, PRE = 1 ms (and 2 ms, both reported).

Blocks: GP16 falls split at gaps > 0.5 s; runs of length 1 (the dummies) dropped. The remaining runs are the
H/C blocks of raw/P2_blocks.json in order (the smoke test S first). Falls must equal the mark_ctl rows,
else the block is excluded. Join: edge -> mark_ctl row (by order) -> periods.csv (by k).

Variable periods: a conversion less than PRE before the next edge gets a negative phase to that edge;
otherwise its phase is to the preceding edge. A conversion between edges j and j+1 is used only if
8 ms <= fr[j+1] - fr[j] <= 15 ms and neither decision j nor j+1 is flagged (miss, or send_lateness_us
> 5 ms). Conversions before the first or after the last edge are not used. So baseline samples lie more
than PRE (>= 1 ms) before the next edge.

(b) per block: profile p(phase), baseline b = mean p over [5.5, 8.5) ms, X = sum over the window of
    (p - b) x 0.1 ms. C - H per round = X_C - X_H; mean over rounds, t CI (n - 1 df).
(a) block means: H/C over [first fall + 3 s, last fall - 3 s]; I over [mark start + 4 s, mark end - 4 s]
    (Mac marks mapped to PIO time by a fit of conversion arrival time). C - H and H - I per round, as
    power and as energy per decision (/ decision rate). t CI over rounds (paired by round).
VDD_IN: the same windows, mapped to board time (board clock synced to the Mac), method (a).
"""
import csv
import json
import os
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042, 60: 2.000, 120: 1.980, 1e9: 1.96}
X0_P5 = 59.5e-6
RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def t975(df):
    ks = sorted(T975)
    for a, b in zip(ks, ks[1:]):
        if a <= df <= b:
            return T975[a] + (T975[b] - T975[a]) * (df - a) / (b - a)
    return 12.706


def tci(x):
    x = np.asarray(x, float)
    n = len(x)
    m = x.mean()
    if n < 2:
        return m, np.nan, np.nan, np.nan
    se = x.std(ddof=1) / np.sqrt(n)
    h = t975(n - 1) * se
    return m, m - h, m + h, se


binf, chkf, inaf, outp = sys.argv[1:5]
L = []
c = load(binf)
ok = c["cnvrf"].copy()
ok[0] = False
edge = c["t"][ok]
tc = edge - 540e-6
P = c["P"][ok]
fall = c["fall"]
iv = np.diff(c["t"][1:]) * 1e6
Tm = np.median(iv)
L.append(f"capture: {ok.sum()} valid conversions, missed {int(np.sum(np.round(iv[iv > 1.5 * Tm] / Tm) - 1))}, "
         f"spurious ALRT {int((~c['cnvrf'][1:]).sum())}, falls {len(fall)}, rises {len(c['rise'])}")

# Mac monotonic -> PIO time, from the arrival time of each conversion (lag of a few ms; fine for +-4 s margins)
ch = np.loadtxt(chkf, delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
kk = np.clip(np.searchsorted(ch[:, 2], (c["conv_idx"] + 1) * 16), 0, len(ch) - 1)
arr = ch[kk, 0][ok].astype(float)
sub = slice(None, None, 97)
cf = np.polyfit(arr[sub] / 1e9, edge[sub], 1)
res = edge[sub] - np.polyval(cf, arr[sub] / 1e9)
L.append(f"PIO-vs-Mac-arrival fit: slope {cf[0]:.9f}, residual sd {res.std() * 1e3:.2f} ms (arrival lag jitter)")
mono2pio = lambda m: np.polyval(cf, m / 1e9)
pio2mono = lambda t: (t - cf[1]) / cf[0] * 1e9
marks = list(csv.DictReader(open(os.path.join(RUN, "raw", "marks.csv"))))
u_m = np.median([int(r["mac_unix_ns"]) - int(r["mac_mono_ns"]) for r in marks])     # Mac unix - Mac mono
# INA3221 (board realtime ~ Mac unix)
meta = json.load(open(inaf + ".meta.json"))
D = np.genfromtxt(inaf, delimiter=",", names=True, dtype=np.int64)
tb = (D["t0_ns"] + D["t1_ns"]) / 2
unix_b = (meta["start_realtime_ns"] + (tb - meta["start_mono_ns"])) / 1e9     # s
pin = D["in1"] * D["curr1"] / 1000.0
pcg = D["in2"] * D["curr2"] / 1000.0

blocks = json.load(open(os.path.join(RUN, "raw", "P2_blocks.json")))
runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 0.5)[0] + 1) if len(fall) else []
L.append(f"fall runs (split at gaps > 0.5 s): {[len(r) for r in runs]}")
big = [r for r in runs if len(r) > 1]
hc = [b for b in blocks if b["cond"] in ("H", "C")]
if len(big) != len(hc):
    L.append(f"WARNING: {len(big)} fall runs of length > 1 against {len(hc)} H/C blocks")
for b, r in zip(hc, big):
    b["fr"] = fall[r]


def vdd_in(u0, u1):
    m = (unix_b >= u0) & (unix_b < u1)
    return pin[m].mean(), pcg[m].mean(), int(m.sum())


def method_b(fr, flag, pre):
    """Profile over [-pre, 15) ms after/before edges, X, baseline. flag: bool per edge."""
    sel = (tc >= fr[0] - 0.002) & (tc <= fr[-1] + 0.016)
    tt, pp = tc[sel], P[sel]
    j = np.searchsorted(fr, tt, side="right") - 1          # preceding edge
    n = len(fr)
    valid = (j >= 0) & (j < n - 1)
    jc = np.clip(j, 0, n - 2)
    Lj = fr[jc + 1] - fr[jc]
    valid &= (Lj >= 0.008) & (Lj <= 0.015) & ~flag[jc] & ~flag[jc + 1]
    to_next = fr[jc + 1] - tt
    neg = to_next < pre
    ph = np.where(neg, tt - fr[jc + 1], tt - fr[jc])
    owner = np.where(neg, jc + 1, jc)
    after = tt - fr[jc]                                     # for the whole-fold plot
    before = tt - fr[jc + 1]
    v = valid
    edges_ = np.round(np.arange(-pre * 1e3, 8.5001, 0.1), 4) * 1e-3
    nb = len(edges_) - 1
    k = np.digitize(ph[v], edges_) - 1
    m = (k >= 0) & (k < nb)
    cnt = np.bincount(k[m], minlength=nb)
    prof = np.bincount(k[m], pp[v][m], nb) / np.maximum(cnt, 1)
    ctr = (edges_[:-1] + edges_[1:]) / 2
    bsel = (ctr >= 5.5e-3) & (ctr < 8.5e-3) & (cnt > 0)
    base = prof[bsel].mean()
    win = (ctr >= -pre) & (ctr < 4.5e-3)
    X = np.sum(prof[win] - base) * 1e-4
    # whole fold, for the window check: after the preceding edge (0..15 ms) and before the next edge (-8..0 ms)
    fa = np.arange(0, 15.0001, 0.1) * 1e-3
    fb = np.arange(-8.0, 0.0001, 0.1) * 1e-3
    ka = np.digitize(after[v], fa) - 1
    kb = np.digitize(before[v], fb) - 1
    ma, mb = (ka >= 0) & (ka < len(fa) - 1), (kb >= 0) & (kb < len(fb) - 1)
    pa = np.bincount(ka[ma], pp[v][ma], len(fa) - 1) / np.maximum(np.bincount(ka[ma], minlength=len(fa) - 1), 1)
    pb = np.bincount(kb[mb], pp[v][mb], len(fb) - 1) / np.maximum(np.bincount(kb[mb], minlength=len(fb) - 1), 1)
    na = np.bincount(ka[ma], minlength=len(fa) - 1)
    pa = np.where(na > 0, pa, np.nan)
    nbb = np.bincount(kb[mb], minlength=len(fb) - 1)
    pb = np.where(nbb > 0, pb, np.nan)
    # pre-edge excess [-2, -1) ms (before-edge alignment), for the window check
    pre21 = (before[v] >= -2e-3) & (before[v] < -1e-3)
    ex21 = pp[v][pre21].mean() - base
    return {"X": X, "base": base, "prof": prof, "ctr": ctr, "cnt": cnt, "pa": pa, "pb": pb, "fa": fa, "fb": fb,
            "ex21": ex21, "n_used": int(v.sum()), "n_conv": int(len(tt)), "owners": len(np.unique(owner[v]))}


out_blocks = []
for b in blocks:
    rec = {"tag": b["tag"], "cond": b["cond"], "round": b["round"]}
    ms, me = b["mark_start_mono_ns"], b["mark_end_mono_ns"]
    if b["cond"] in ("H", "C"):
        if "fr" not in b:
            L.append(f"{b['tag']}: no fall run -> excluded")
            continue
        fr = b["fr"]
        rows = list(csv.DictReader(open(os.path.join(RUN, "raw", "board", b["mc_csv"]))))
        per = {int(p["k"]): p for p in csv.DictReader(open(os.path.join(RUN, "sim", b["sim_dir"], "periods.csv")))}
        if len(fr) != len(rows):
            L.append(f"{b['tag']}: {len(fr)} falls vs {len(rows)} mark_ctl rows -> EXCLUDED")
            continue
        ks = [int(x["k"]) for x in rows]
        pr = [per[k] for k in ks]
        miss = np.array([int(p["miss"]) == 1 for p in pr])
        late = np.array([float(p["send_lateness_us"]) for p in pr])
        flag = miss | (late > 5000)
        ctl = np.array([float(p["ctl_us"]) for p in pr])
        wr = np.array([int(x["t_after_ns"]) - int(x["t_before_ns"]) for x in rows]) / 1e3
        nev = np.array([int(x["n_events"]) for x in rows])
        d = np.diff(fr)
        rate = (len(fr) - 1) / (fr[-1] - fr[0])
        w0, w1 = fr[0] + 3, fr[-1] - 3
        mlead = fr[0] - mono2pio(ms)
        rec.update({"n": len(fr), "obs": len(per), "rate": rate, "flagged": int(flag.sum()), "miss": int(miss.sum()),
                    "late5": int((late > 5000).sum()), "out_8_15": int(np.sum((d < 0.008) | (d > 0.015))),
                    "ctl_p50": float(np.nanmedian(ctl)), "ctl_p99": float(np.nanpercentile(ctl, 99)),
                    "wr_p50": float(np.median(wr)), "wr_p99": float(np.percentile(wr, 99)),
                    "nev_mean": float(nev.mean()), "frac_ge200": float(np.mean(nev >= 200)), "mark_to_first_fall_s": mlead})
        for pre in (1e-3, 2e-3):
            rec[f"b{int(pre * 1e3)}"] = method_b(fr, flag, pre)
    else:
        w0, w1 = mono2pio(ms) + 4, mono2pio(me) - 4
    m = (tc >= w0) & (tc < w1)
    rec["Pa"] = P[m].mean()
    rec["win_s"] = w1 - w0
    u0, u1 = (pio2mono(w0) + u_m) / 1e9, (pio2mono(w1) + u_m) / 1e9
    rec["vin"], rec["vcg"], rec["n_ina"] = vdd_in(u0, u1)
    out_blocks.append(rec)
    s = f"{rec['tag']:4s} {rec['cond']} r{rec['round']}: block mean {rec['Pa'] * 1e3:7.1f} mW over {rec['win_s']:.1f} s; VDD_IN {rec['vin']:.1f} mW ({rec['n_ina']} samples)"
    if b["cond"] in ("H", "C"):
        s += (f"; decisions {rec['n']} (OBS {rec['obs']}), rate {rec['rate']:.3f} Hz, flagged {rec['flagged']} (miss {rec['miss']}, late>5ms {rec['late5']}), "
              f"intervals outside 8-15 ms {rec['out_8_15']}; ctl_us p50/p99 {rec['ctl_p50']:.1f}/{rec['ctl_p99']:.1f}; write p50/p99 {rec['wr_p50']:.1f}/{rec['wr_p99']:.1f} us; "
              f"events mean {rec['nev_mean']:.0f}, >= 200 in {rec['frac_ge200'] * 100:.1f} %; mark->first fall {rec['mark_to_first_fall_s']:.2f} s")
        for pre in (1, 2):
            q = rec[f"b{pre}"]
            s += f"\n      (b) window [-{pre}, 4.5) ms: X {q['X'] * 1e6:7.2f} uJ, baseline {q['base'] * 1e3:.1f} mW, pre-edge [-2,-1) ms excess {q['ex21'] * 1e3:+.1f} mW, conversions used {q['n_used']}/{q['n_conv']}"
        q = rec["b1"]
        seg = []
        for a0, a1 in ((-1, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4.5), (4.5, 5.5)):
            mm = (q["ctr"] >= a0 * 1e-3) & (q["ctr"] < a1 * 1e-3)
            seg.append(f"[{a0:g},{a1:g}) {np.mean(q['prof'][mm] - q['base']) * 1e3:+.0f}")
        fa = q["fa"][:-1] + 0.05e-3
        for a0, a1 in ((8.5, 9.5), (9.5, 10.5)):
            mm = (fa >= a0 * 1e-3) & (fa < a1 * 1e-3)
            seg.append(f"after-edge [{a0:g},{a1:g}) {np.nanmean(q['pa'][mm] - q['base']) * 1e3:+.0f}")
        s += "\n      excess by segment, ms -> mW: " + ", ".join(seg)
    L.append(s)

R = [x for x in out_blocks if x["round"] > 0]
rounds = sorted(set(x["round"] for x in R))
by = {(x["round"], x["cond"]): x for x in R}
full = [r for r in rounds if all((r, cnd) in by for cnd in "IHC")]
L.append(f"\nrounds complete (I, H, C all present and valid): {full}")
L.append("\n| round | order | P_I mW | P_H mW | P_C mW | (a) C-H mW | (a) H-I mW | rate H / C Hz | (b) X_H uJ | (b) X_C uJ | (b) C-H uJ | (b) C-H uJ, [-2,4.5) | VDD_IN C-H mW |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
order = {int(l.split()[0][5:]): " ".join(l.split()[1:]) for l in open(os.path.join(RUN, "raw", "order.txt")) if l.startswith("round")}
A_CH, A_HI, E_CH, E_HI, B_CH, B_CH2, XH, XC, XH2, XC2, V_CH, V_HI, VE_CH, ETH, ETC = ([] for _ in range(15))
for r in full:
    I, H, C = by[(r, "I")], by[(r, "H")], by[(r, "C")]
    rt = (H["rate"] + C["rate"]) / 2
    A_CH.append(C["Pa"] - H["Pa"]); A_HI.append(H["Pa"] - I["Pa"])
    E_CH.append((C["Pa"] - H["Pa"]) / rt); E_HI.append((H["Pa"] - I["Pa"]) / H["rate"])
    B_CH.append(C["b1"]["X"] - H["b1"]["X"]); B_CH2.append(C["b2"]["X"] - H["b2"]["X"])
    XH.append(H["b1"]["X"]); XC.append(C["b1"]["X"]); XH2.append(H["b2"]["X"]); XC2.append(C["b2"]["X"])
    V_CH.append(C["vin"] - H["vin"]); V_HI.append(H["vin"] - I["vin"]); VE_CH.append((C["vin"] - H["vin"]) / 1e3 / rt)
    ETH.append(H["Pa"] / H["rate"]); ETC.append(C["Pa"] / C["rate"])
    L.append(f"| {r} | {order.get(r, '')} | {I['Pa'] * 1e3:.1f} | {H['Pa'] * 1e3:.1f} | {C['Pa'] * 1e3:.1f} | {A_CH[-1] * 1e3:+.1f} | {A_HI[-1] * 1e3:+.1f} | "
             f"{H['rate']:.3f} / {C['rate']:.3f} | {XH[-1] * 1e6:.2f} | {XC[-1] * 1e6:.2f} | {B_CH[-1] * 1e6:+.2f} | {B_CH2[-1] * 1e6:+.2f} | {V_CH[-1]:+.1f} |")


def fmt(v, scale, unit, nd=2):
    m, lo, hi, se = tci(v)
    return f"{m * scale:+.{nd}f} {unit} [{lo * scale:+.{nd}f}, {hi * scale:+.{nd}f}] (se {se * scale:.{nd}f}, n {len(v)}, t {t975(len(v) - 1):.3f})"


n = len(full)
L.append("")
L.append(f"(b) C - H, window [-1, 4.5) ms: {fmt(B_CH, 1e6, 'uJ')}")
L.append(f"(b) C - H, window [-2, 4.5) ms: {fmt(B_CH2, 1e6, 'uJ')}")
L.append(f"(b) X_H, window [-1, 4.5) ms: {fmt(XH, 1e6, 'uJ')}   (Part 5 X_0 = {X0_P5 * 1e6:.1f} uJ)")
L.append(f"(b) X_C, window [-1, 4.5) ms: {fmt(XC, 1e6, 'uJ')}")
L.append(f"(b) X_H, window [-2, 4.5) ms: {fmt(XH2, 1e6, 'uJ')};  X_C {fmt(XC2, 1e6, 'uJ')}")
L.append(f"(a) C - H: {fmt(A_CH, 1e3, 'mW', 1)}  ->  per decision {fmt(E_CH, 1e6, 'uJ', 1)}")
L.append(f"(a) H - I: {fmt(A_HI, 1e3, 'mW', 1)}  ->  per decision {fmt(E_HI, 1e6, 'uJ', 1)}")
L.append(f"VDD_IN (a) C - H: {fmt(V_CH, 1, 'mW', 1)}  ->  per decision {fmt(VE_CH, 1e6, 'uJ', 1)};  H - I: {fmt(V_HI, 1, 'mW', 1)}")
L.append(f"E_tot per decision (block mean / decision rate): H {fmt(ETH, 1e3, 'mJ', 2)};  C {fmt(ETC, 1e3, 'mJ', 2)}")
# window check
for cnd in "HC":
    e = [by[(r, cnd)]["b1"]["ex21"] for r in full]
    L.append(f"window check {cnd}: mean excess over [-2, -1) ms before the edge, relative to the block baseline: {fmt(e, 1e3, 'mW', 1)}")
# decisions needed (method b, C - H, window [-1, 4.5)), from the round-to-round spread
if n >= 2:
    m, lo, hi, se = tci(B_CH)
    nd = np.mean([by[(r, c_)]["n"] for r in full for c_ in "HC"])
    Ncur = n * nd
    L.append(f"\nachieved (b) C - H half-width: {(hi - m) * 1e6:.2f} uJ (t, {n - 1} df) = {(hi - m) / abs(m) * 100:.1f} % of |C - H|; "
             f"with z instead of t: {1.96 * se * 1e6:.2f} uJ ({1.96 * se / abs(m) * 100:.1f} %)")
    for tgt in (0.05, 0.10):
        Nz = Ncur * (1.96 * se / (tgt * abs(m))) ** 2
        sd_r = se * np.sqrt(n)
        k = 2
        while t975(k - 1) * sd_r / np.sqrt(k) > tgt * abs(m) and k < 10000:
            k += 1
        L.append(f"  +-{tgt * 100:.0f} %: about {Nz:.3g} decisions per condition (z, {Nz / 6000:.2f} blocks of 60 s); "
                 f"with t over 60 s rounds: {k} rounds ({k * nd:.3g} decisions per condition)")
    for lab, v in (("(a) C - H", E_CH), ("VDD_IN C - H", VE_CH)):
        m2, lo2, hi2, se2 = tci(v)
        L.append(f"  {lab}: half-width {(hi2 - m2) * 1e6:.1f} uJ (t) = {(hi2 - m2) / abs(m2) * 100 if m2 else np.inf:.0f} % of |C - H|")
txt = "\n".join(L)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")

# plots: whole fold (after the preceding edge, before the next edge) and the window profile, H and C
fig, ax = plt.subplots(1, 3, figsize=(16, 5), gridspec_kw={"width_ratios": [1, 1.6, 1.2]})
for cnd, col in (("H", "C0"), ("C", "C3")):
    bl = [by[(r, cnd)]["b1"] for r in full]
    if not bl:
        continue
    fb = bl[0]["fb"]
    fa = bl[0]["fa"]
    pb = np.nanmean([q["pb"] - q["base"] for q in bl], axis=0)
    pa = np.nanmean([q["pa"] - q["base"] for q in bl], axis=0)
    ax[0].plot((fb[:-1] + 0.05e-3) * 1e3, pb * 1e3, color=col, label=f"{cnd}, aligned on the next edge")
    ax[1].plot((fa[:-1] + 0.05e-3) * 1e3, pa * 1e3, color=col, label=f"{cnd}, aligned on the preceding edge")
    pr = np.mean([q["prof"] - q["base"] for q in bl], axis=0)
    ax[2].plot(bl[0]["ctr"] * 1e3, pr * 1e3, color=col, label=f"{cnd}: X = {np.mean([q['X'] for q in bl]) * 1e6:.1f} uJ")
for a in ax:
    a.axhline(0, color="0.5", lw=0.5)
    a.legend(fontsize=8)
    a.set_xlabel("ms")
ax[0].axvspan(-1, 0, color="0.85", alpha=0.5)
ax[0].axvline(-2, color="0.6", ls=":")
ax[0].set_title("before the next edge (window start -1 / -2 ms)")
ax[1].axvspan(5.5, 8.5, color="0.85", alpha=0.5)
ax[1].set_title("after the preceding edge (baseline 5.5-8.5 ms shaded)")
ax[2].axvspan(-1, 4.5, color="0.9", alpha=0.4)
ax[2].set_title("window profile [-1, 4.5) ms, phase to own edge")
ax[0].set_ylabel("INA228 power above the block baseline, mW (mean of rounds)")
fig.suptitle("Part 2: closed loop, hold vs centroid, marker-aligned (19 V input; conversion centres, +-0.54 ms)")
fig.tight_layout()
fig.savefig(outp + "_profiles.png", dpi=110)
