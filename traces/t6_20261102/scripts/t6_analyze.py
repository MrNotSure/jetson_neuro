"""T6 (2 Nov 2026): closed loop, hold (H) against classical (A), with idle (I) blocks at the session's ends.
Derived from traces/stage1_20261031_final/scripts/p6_analyze.py (31 Oct Part 2, method (b) as it ran).

  .venv/bin/python scripts/t6_analyze.py OUTPREFIX CAP [CAP ...]       (e.g. raw/result_C1 C1   or   raw/result C1 C2)

Inputs per capture CAP: raw/CAP.bin, raw/CAP.chunks.csv, raw/board/CAP_ina3221_10hz.csv(+.meta.json),
raw/board/CAP_freq.csv (or .csv.part while it runs), raw/blocks.json, raw/marks.csv, raw/order.txt,
raw/board/mc_<tag>.csv, sim/<dir>/{periods.csv,summary.json}. A live capture works; VDD_IN is skipped while the
sampler's meta.json doesn't exist yet.

Same definitions as 31 Oct: conversion time = ALRT edge - 540 us; 0.1 ms bins; baseline [5.5, 8.5) ms after the
edge; window [-PRE, END) ms with PRE = 1 and 2 ms, END = 4.5 ms (END = 5.5 ms also computed, as a sensitivity).
A conversion between edges j and j+1 is used only if 8 ms <= interval <= 15 ms and neither decision j nor j+1 is
flagged (miss, or send_lateness_us > 5 ms). A block whose falls != mark_ctl rows is excluded (and listed).

(b) X per block; per round D = X_A - X_H; E_dyn(A) = mean D over rounds, t CI (n - 1 df).
Window check on A's profile: excess over [-2, -1) ms before the edge and over [4.5, 5.5) ms after it.
(a) block means: H/A over [first fall + 3 s, last fall - 3 s]; I over [mark start + 4 s, mark end - 4 s] (Mac
marks mapped to PIO time by a fit of conversion arrival time, per capture). E_dyn(a) = (P_A - P_H)/f per round;
harness (mean P_H - mean P_I)/f, Welch CI; E_tot(A) = mean P_A / f as the stack floor + harness + algorithm.
VDD_IN: the same windows, mapped to board realtime (clock synced to the Mac), method (a).
Drift: X_H and X_A against round index, least-squares slope with t CI (n - 2 df).
Sizing: N = smallest number of rounds with t(N - 1) sd_D / sqrt(N) <= 5 % (10 %) of |mean D|.
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
        11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
        21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042,
        40: 2.021, 60: 2.000, 120: 1.980, 1e9: 1.96}
RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINDOWS = ((1, 4.5), (2, 4.5), (2, 5.5))          # (pre, end) in ms; the first is the primary
CTL = ("H", "A")
# Sensitivity only (T6_DEGLITCH=1): drop GP16 pulses < 1 us wide before splitting the falls into blocks. Added after
# the afternoon captures showed 0.12 us ringing pulses at marker rising edges (raw/glitch_summary.txt). The primary
# analysis keeps the brief's rule (a block with falls != rows is excluded).
DEGLITCH = os.environ.get("T6_DEGLITCH") == "1"
BOOT = {"S0": 1, "C1": 1, "C2": 2, "C2b": 2, "C3": 2}   # the Jetson was power-cycled between C1 and C2


def t975(df):
    if df < 1:
        return np.nan
    ks = sorted(T975)
    for a, b in zip(ks, ks[1:]):
        if a <= df <= b:
            return T975[a] + (T975[b] - T975[a]) * (df - a) / (b - a)
    return 1.96


def tci(x):
    x = np.asarray(x, float)
    n = len(x)
    if n == 0:
        return np.nan, np.nan, np.nan, np.nan
    m = x.mean()
    if n < 2:
        return m, np.nan, np.nan, np.nan
    se = x.std(ddof=1) / np.sqrt(n)
    h = t975(n - 1) * se
    return m, m - h, m + h, se


def welch(a, b):
    """mean(a) - mean(b), Welch CI. Returns m, lo, hi, se, df."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    se = np.sqrt(va + vb)
    df = (va + vb) ** 2 / (va ** 2 / (len(a) - 1) + vb ** 2 / (len(b) - 1))
    m = a.mean() - b.mean()
    h = t975(df) * se
    return m, m - h, m + h, se, df


def slope_ci(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    n = len(x)
    if n < 3:
        return np.nan, np.nan, np.nan
    A = np.vstack([x, np.ones(n)]).T
    coef, res, *_ = np.linalg.lstsq(A, y, rcond=None)
    r = y - A @ coef
    s2 = r @ r / (n - 2)
    se = np.sqrt(s2 / np.sum((x - x.mean()) ** 2))
    h = t975(n - 2) * se
    return coef[0], coef[0] - h, coef[0] + h


def fmt(v, scale, unit, nd=2):
    m, lo, hi, se = tci(v)
    return f"{m * scale:+.{nd}f} {unit} [{lo * scale:+.{nd}f}, {hi * scale:+.{nd}f}] (se {se * scale:.{nd}f}, n {len(v)}, t {t975(len(v) - 1):.3f})"


def rounds_needed(sd, m, tgt):
    k = 2
    while t975(k - 1) * sd / np.sqrt(k) > tgt * abs(m) and k < 100000:
        k += 1
    return k


outp, caps = sys.argv[1], sys.argv[2:]
L = []
allblocks = json.load(open(os.path.join(RUN, "raw", "blocks.json")))
# Mac unix - Mac mono is taken per capture from its chunks.csv (the 31 Oct script used the median over all marks;
# the Mac's monotonic clock stops while it sleeps, and it slept during the lunch break, so marks from different
# captures carry different offsets).


SAMPLER_WIN = (-1e-3, 10e-3)     # around each INA3221 read start (the read takes 4.5 ms; its excess is gone by ~10 ms)
FREQ_WIN = (-2e-3, 2e-3)         # around each freqlog stamp (taken right after its four sysfs reads)


def contaminated(fr, tb_ns, reads):
    """Per edge interval j (fr[j], fr[j+1]): True if it overlaps any logger read window.
    tb_ns: mark_ctl's t_before_ns per edge (board CLOCK_MONOTONIC), mapped to PIO time by a linear fit;
    reads: list of (start_ns array, (w0, w1)) on the same board clock."""
    x = (tb_ns - tb_ns[0]) / 1e9
    cf = np.polyfit(x, fr, 1)
    resid = fr - np.polyval(cf, x)
    n = len(fr)
    excl = np.zeros(n - 1, bool)
    for s_ns, (w0, w1) in reads:
        s = np.polyval(cf, (s_ns - tb_ns[0]) / 1e9)
        s = s[(s > fr[0] - 0.05) & (s < fr[-1] + 0.05)]
        j0 = np.clip(np.searchsorted(fr, s + w0, side="right") - 1, 0, n - 2)
        j1 = np.clip(np.searchsorted(fr, s + w1, side="right") - 1, 0, n - 2)
        for a, b in zip(j0, j1):
            excl[a:b + 1] = True
    return excl, float(resid.std())


def method_b(tc, P, fr, flag, pre, excl=None):
    """Profile over [-pre, 8.5) ms by phase to the own edge; whole-fold profiles; window excesses.
    excl: optional bool per edge interval; True drops every conversion of that interval."""
    sel = (tc >= fr[0] - 0.002) & (tc <= fr[-1] + 0.016)
    tt, pp = tc[sel], P[sel]
    j = np.searchsorted(fr, tt, side="right") - 1          # preceding edge
    n = len(fr)
    valid = (j >= 0) & (j < n - 1)
    jc = np.clip(j, 0, n - 2)
    Lj = fr[jc + 1] - fr[jc]
    valid &= (Lj >= 0.008) & (Lj <= 0.015) & ~flag[jc] & ~flag[jc + 1]
    if excl is not None:
        valid &= ~excl[jc]
    to_next = fr[jc + 1] - tt
    neg = to_next < pre
    ph = np.where(neg, tt - fr[jc + 1], tt - fr[jc])
    after = tt - fr[jc]
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
    X = {}
    for end in (4.5, 5.5):
        win = (ctr >= -pre * 1e-3) & (ctr < end * 1e-3) & (cnt > 0)
        X[end] = np.sum(prof[win] - base) * 1e-4
    fa = np.arange(0, 15.0001, 0.1) * 1e-3
    fb = np.arange(-8.0, 0.0001, 0.1) * 1e-3
    ka = np.digitize(after[v], fa) - 1
    kb = np.digitize(before[v], fb) - 1
    ma, mb = (ka >= 0) & (ka < len(fa) - 1), (kb >= 0) & (kb < len(fb) - 1)
    na = np.bincount(ka[ma], minlength=len(fa) - 1)
    nbb = np.bincount(kb[mb], minlength=len(fb) - 1)
    pa = np.where(na > 0, np.bincount(ka[ma], pp[v][ma], len(fa) - 1) / np.maximum(na, 1), np.nan)
    pb = np.where(nbb > 0, np.bincount(kb[mb], pp[v][mb], len(fb) - 1) / np.maximum(nbb, 1), np.nan)
    pre21 = (before[v] >= -2e-3) & (before[v] < -1e-3)
    post45 = (after[v] >= 4.5e-3) & (after[v] < 5.5e-3)
    return {"X": X[4.5], "X55": X[5.5], "base": base, "prof": prof, "ctr": ctr, "cnt": cnt, "pa": pa, "pb": pb,
            "fa": fa, "fb": fb, "ex21": pp[v][pre21].mean() - base, "ex455": pp[v][post45].mean() - base,
            "n_used": int(v.sum()), "n_conv": int(len(tt))}


out_blocks, excluded = [], []
for cap in caps:
    c = load(os.path.join(RUN, "raw", cap + ".bin"))
    ok = c["cnvrf"].copy()
    ok[0] = False
    edge = c["t"][ok]
    tc = edge - 540e-6
    P = c["P"][ok]
    fall = c["fall"]
    iv = np.diff(c["t"][1:]) * 1e6
    Tm = np.median(iv)
    L.append(f"{cap}: {ok.sum()} valid conversions, missed {int(np.sum(np.round(iv[iv > 1.5 * Tm] / Tm) - 1))}, "
             f"spurious ALRT {int((~c['cnvrf'][1:]).sum())}, falls {len(fall)}, rises {len(c['rise'])}, trailer {c['trailer']}")
    if DEGLITCH and len(fall):
        rr = c["rise"]
        jj = np.searchsorted(rr, fall)
        wd = np.where(jj < len(rr), rr[np.minimum(jj, len(rr) - 1)] - fall, np.inf)
        keep = wd >= 1e-6
        L.append(f"  DEGLITCH: dropped {int((~keep).sum())} GP16 falls whose pulse is < 1 us wide (a marker start bit is 8.68 us)")
        fall = fall[keep]
    ch = np.loadtxt(os.path.join(RUN, "raw", cap + ".chunks.csv"), delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
    offs = ch[:, 1] - ch[:, 0]
    u_m = float(np.median(offs))
    L.append(f"  Mac unix - mono over the capture: spread {(offs.max() - offs.min()) / 1e6:.1f} ms"
             + ("  WARNING: the Mac slept during this capture" if offs.max() - offs.min() > 50e6 else ""))
    kk = np.clip(np.searchsorted(ch[:, 2], (c["conv_idx"] + 1) * 16), 0, len(ch) - 1)
    arr = ch[kk, 0][ok].astype(float)
    sub = slice(None, None, 97)
    cf = np.polyfit(arr[sub] / 1e9, edge[sub], 1)
    res = edge[sub] - np.polyval(cf, arr[sub] / 1e9)
    L.append(f"  PIO-vs-Mac-arrival fit: slope {cf[0]:.9f}, residual sd {res.std() * 1e3:.2f} ms")
    mono2pio = lambda m, cf=cf: np.polyval(cf, m / 1e9)
    pio2mono = lambda t, cf=cf: (t - cf[1]) / cf[0] * 1e9
    inaf = os.path.join(RUN, "raw", "board", cap + "_ina3221_10hz.csv")
    have_ina = os.path.exists(inaf + ".meta.json")
    if have_ina:
        meta = json.load(open(inaf + ".meta.json"))
        D = np.genfromtxt(inaf, delimiter=",", names=True, dtype=np.int64)
        tb = (D["t0_ns"] + D["t1_ns"]) / 2
        unix_b = (meta["start_realtime_ns"] + (tb - meta["start_mono_ns"])) / 1e9
        pin = D["in1"] * D["curr1"] / 1000.0
        L.append(f"  INA3221 sampler: {meta['samples']} samples, {meta['achieved_hz']:.3f} Hz, CPU {meta['cpu_fraction_of_one_core'] * 100:.2f} % of one core")
    else:
        L.append("  INA3221: no meta.json yet (sampler running?): VDD_IN skipped")
    fq = os.path.join(RUN, "raw", "board", cap + "_freq.csv")
    if not os.path.exists(fq):
        fq += ".part"
    F = np.genfromtxt(fq, delimiter=",", names=True, dtype=np.int64) if os.path.exists(fq) else None
    if F is not None:
        L.append(f"  freqlog: {len(F)} samples from {os.path.basename(fq)}")
    reads = []
    if os.path.exists(inaf):
        Sr = np.genfromtxt(inaf, delimiter=",", names=True, dtype=np.int64)
        reads.append((Sr["t0_ns"], SAMPLER_WIN))
    if F is not None:
        reads.append((F["mono_ns"], FREQ_WIN))
    L.append(f"  logger reads for the exclusion variant: {[len(r[0]) for r in reads]} (sampler, freqlog), windows "
             f"{SAMPLER_WIN[0] * 1e3:+g}..{SAMPLER_WIN[1] * 1e3:+g} ms / {FREQ_WIN[0] * 1e3:+g}..{FREQ_WIN[1] * 1e3:+g} ms")

    blocks = [b for b in allblocks if b["capture"] == cap]
    runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 0.5)[0] + 1) if len(fall) else []
    big = [r for r in runs if len(r) > 1]
    hc = [b for b in blocks if b["cond"] in CTL]
    L.append(f"  fall runs: {len(runs)} ({len(big)} of length > 1, {len(runs) - len(big)} lone); H/A blocks {len(hc)}")
    if len(big) != len(hc):
        L.append(f"  WARNING: {len(big)} fall runs of length > 1 against {len(hc)} H/A blocks")
    for b, r in zip(hc, big):
        b["fr"] = fall[r]
    for b in blocks:
        rec = {"capture": cap, "tag": b["tag"], "cond": b["cond"], "round": b["round"]}
        ms, me = b["mark_start_mono_ns"], b["mark_end_mono_ns"]
        if b["cond"] in CTL:
            if "fr" not in b:
                excluded.append(f"{b['tag']}: no fall run"); continue
            fr = b["fr"]
            rows = list(csv.DictReader(open(os.path.join(RUN, "raw", "board", b["mc_csv"]))))
            per = {int(p["k"]): p for p in csv.DictReader(open(os.path.join(RUN, "sim", b["sim_dir"], "periods.csv")))}
            if len(fr) != len(rows):
                excluded.append(f"{b['tag']}: {len(fr)} falls vs {len(rows)} mark_ctl rows"); continue
            summ = json.load(open(os.path.join(RUN, "sim", b["sim_dir"], "summary.json")))["overall"]
            ks = [int(x["k"]) for x in rows]
            pr = [per[k] for k in ks]
            miss = np.array([int(p["miss"]) == 1 for p in pr])
            late = np.array([float(p["send_lateness_us"]) for p in pr])
            flag = miss | (late > 5000)
            ctl = np.array([float(p["ctl_us"]) for p in pr])
            nev = np.array([int(x["n_events"]) for x in rows])
            d = np.diff(fr)
            rate = (len(fr) - 1) / (fr[-1] - fr[0])
            w0, w1 = fr[0] + 3, fr[-1] - 3
            rec.update({"n": len(fr), "obs": len(per), "rate": rate, "flagged": int(flag.sum()), "miss": int(miss.sum()),
                        "late5": int((late > 5000).sum()), "out_8_15": int(np.sum((d < 0.008) | (d > 0.015))),
                        "ctl_p50": float(np.nanmedian(ctl)), "ctl_p99": float(np.nanpercentile(ctl, 99)), "ctl_max": float(np.nanmax(ctl)),
                        "nev_mean": float(nev.mean()), "rms_deg": summ["error"]["rms_deg"], "max_deg": summ["error"]["max_deg"],
                        "in_fov": summ["mission"]["in_fov_fraction"], "losses": summ["mission"]["target_losses"],
                        "affinity": b.get("affinity"), "sim_dir": b["sim_dir"]})
            for pre in (1e-3, 2e-3):
                rec[f"b{int(pre * 1e3)}"] = method_b(tc, P, fr, flag, pre)
            if len(reads) == 2:
                tbn = np.array([int(x["t_before_ns"]) for x in rows], dtype=np.int64)
                excl, rres = contaminated(fr, tbn, reads)
                rec["excl_frac"], rec["tb_fit_resid_us"] = float(excl.mean()), rres * 1e6
                for pre in (1e-3, 2e-3):
                    rec[f"c{int(pre * 1e3)}"] = method_b(tc, P, fr, flag, pre, excl)
            f0, f1 = fr[0], fr[-1]
        else:
            w0, w1 = mono2pio(ms) + 4, mono2pio(me) - 4
            f0, f1 = w0, w1
        m = (tc >= w0) & (tc < w1)
        rec["Pa"] = P[m].mean()
        rec["win_s"] = w1 - w0
        u0, u1 = (pio2mono(w0) + u_m) / 1e9, (pio2mono(w1) + u_m) / 1e9
        if have_ina:
            mi = (unix_b >= u0) & (unix_b < u1)
            rec["vin"], rec["n_ina"] = pin[mi].mean(), int(mi.sum())
        if F is not None:
            g0, g1 = (pio2mono(f0) + u_m), (pio2mono(f1) + u_m)
            mf = (F["realtime_ns"] >= g0) & (F["realtime_ns"] < g1)
            p0 = F["cpu_policy0_khz"][mf]
            vals, cnts = np.unique(p0, return_counts=True)
            rec["p0_dist"] = {int(v): float(cn / max(len(p0), 1)) for v, cn in zip(vals, cnts)}
            rec["p0_729"] = float(np.mean(p0 == 729600)) if len(p0) else np.nan
            rec["p4_729"] = float(np.mean(F["cpu_policy4_khz"][mf] == 729600)) if len(p0) else np.nan
            rec["tj"] = float(F["tj_mC"][mf].mean() / 1000) if len(p0) else np.nan
            rec["n_freq"] = int(mf.sum())
        out_blocks.append(rec)

L.append("")
L.append("excluded blocks: " + ("; ".join(excluded) if excluded else "none"))
L.append("\nper block:")
L.append("| block | cap | cond | P_a mW | VDD_IN mW | X [-1,4.5) uJ | X [-2,4.5) uJ | X [-2,5.5) uJ | baseline mW | pre [-2,-1) mW | post [4.5,5.5) mW | events | ctl_us p50/p99/max | rms_deg | in-FOV | losses | miss / late>5ms | policy0 at 729.6 MHz | policy0 freqs (kHz: frac) | tj C | affinity |")
L.append("|" + "---|" * 21)
for r in out_blocks:
    vin = f"{r['vin']:.1f}" if "vin" in r else "-"
    fd = ", ".join(f"{k}: {v:.3f}" for k, v in sorted(r.get("p0_dist", {}).items(), key=lambda kv: -kv[1])[:3]) if "p0_dist" in r else "-"
    p729 = f"{r['p0_729'] * 100:.1f} %" if "p0_729" in r else "-"
    tj = f"{r['tj']:.1f}" if "tj" in r else "-"
    if r["cond"] in CTL:
        b1, b2 = r["b1"], r["b2"]
        L.append(f"| {r['tag']} | {r['capture']} | {r['cond']} | {r['Pa'] * 1e3:.1f} | {vin} | {b1['X'] * 1e6:.2f} | {b2['X'] * 1e6:.2f} | {b2['X55'] * 1e6:.2f} | "
                 f"{b1['base'] * 1e3:.1f} | {b1['ex21'] * 1e3:+.1f} | {b1['ex455'] * 1e3:+.1f} | {r['nev_mean']:.1f} | {r['ctl_p50']:.0f}/{r['ctl_p99']:.0f}/{r['ctl_max']:.0f} | "
                 f"{r['rms_deg']:.3f} | {r['in_fov']:.3f} | {r['losses']} | {r['miss']} / {r['late5']} | {p729} | {fd} | {tj} | {r['affinity']} |")
    else:
        L.append(f"| {r['tag']} | {r['capture']} | I | {r['Pa'] * 1e3:.1f} | {vin} | - | - | - | - | - | - | - | - | - | - | - | - | {p729} | {fd} | {tj} | - |")
for r in out_blocks:
    if r["cond"] in CTL:
        q = r["b1"]
        seg = []
        for a0, a1 in ((-1, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4.5), (4.5, 5.5)):
            mm = (q["ctr"] >= a0 * 1e-3) & (q["ctr"] < a1 * 1e-3)
            seg.append(f"[{a0:g},{a1:g}) {np.mean(q['prof'][mm] - q['base']) * 1e3:+.0f}")
        L.append(f"  {r['tag']}: excess by segment, ms -> mW: " + ", ".join(seg) + f"; conversions used {q['n_used']}/{q['n_conv']}; "
                 f"decisions {r['n']} (OBS {r['obs']}), rate {r['rate']:.4f} Hz, flagged {r['flagged']}, intervals outside 8-15 ms {r['out_8_15']}")

R = [x for x in out_blocks if x["cond"] in CTL]
by = {(x["round"], x["cond"]): x for x in R}
rounds = sorted(set(x["round"] for x in R if x["round"] > 0))
full = [r for r in rounds if (r, "H") in by and (r, "A") in by]
Is = [x for x in out_blocks if x["cond"] == "I"]
order = {}
for l in open(os.path.join(RUN, "raw", "order.txt")):
    if l.startswith("round"):
        order[int(l.split()[0][5:])] = " ".join(l.split()[1:])
L.append(f"\nrounds complete (H and A valid): {full}; I blocks: {[x['tag'] for x in Is]}")
L.append("\n| round | order | P_H mW | P_A mW | (a) A-H mW | rate H / A Hz | X_H uJ | X_A uJ | D (b) uJ | D [-2,4.5) uJ | D [-2,5.5) uJ | VDD_IN A-H mW |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
S = {k: [] for k in ("D1", "D2", "D55", "XH", "XA", "XH2", "XA2", "Ea", "Va", "EtA", "rt",
                     "Dc1", "Dc2", "Dc55", "XHc", "XAc", "XHc2", "XAc2")}
for r in full:
    H, A = by[(r, "H")], by[(r, "A")]
    rt = (H["rate"] + A["rate"]) / 2
    S["rt"].append(rt)
    if "c1" in H and "c1" in A:
        S["Dc1"].append(A["c1"]["X"] - H["c1"]["X"])
        S["Dc2"].append(A["c2"]["X"] - H["c2"]["X"])
        S["Dc55"].append(A["c2"]["X55"] - H["c2"]["X55"])
        S["XHc"].append(H["c1"]["X"]); S["XAc"].append(A["c1"]["X"]); S["XHc2"].append(H["c2"]["X"]); S["XAc2"].append(A["c2"]["X"])
    S["D1"].append(A["b1"]["X"] - H["b1"]["X"])
    S["D2"].append(A["b2"]["X"] - H["b2"]["X"])
    S["D55"].append(A["b2"]["X55"] - H["b2"]["X55"])
    S["XH"].append(H["b1"]["X"]); S["XA"].append(A["b1"]["X"]); S["XH2"].append(H["b2"]["X"]); S["XA2"].append(A["b2"]["X"])
    S["Ea"].append((A["Pa"] - H["Pa"]) / rt)
    S["EtA"].append(A["Pa"] / A["rate"])
    va = (A["vin"] - H["vin"]) if ("vin" in A and "vin" in H) else np.nan
    if "vin" in A and "vin" in H:
        S["Va"].append(va / 1e3 / rt)
    L.append(f"| {r} | {order.get(r, '')} | {H['Pa'] * 1e3:.1f} | {A['Pa'] * 1e3:.1f} | {(A['Pa'] - H['Pa']) * 1e3:+.1f} | {H['rate']:.3f} / {A['rate']:.3f} | "
             f"{S['XH'][-1] * 1e6:.2f} | {S['XA'][-1] * 1e6:.2f} | {S['D1'][-1] * 1e6:+.2f} | {S['D2'][-1] * 1e6:+.2f} | {S['D55'][-1] * 1e6:+.2f} | {va:+.1f} |")

res = {"rounds": full, "per_round": {k: [float(v) for v in S[k]] for k in S}}
n = len(full)
L.append("")
L.append(f"(b) E_dyn(A) = X_A - X_H, window [-1, 4.5) ms: {fmt(S['D1'], 1e6, 'uJ')}")
L.append(f"(b) E_dyn(A), window [-2, 4.5) ms: {fmt(S['D2'], 1e6, 'uJ')}")
L.append(f"(b) E_dyn(A), window [-2, 5.5) ms (sensitivity): {fmt(S['D55'], 1e6, 'uJ')}")
L.append(f"(b) X_H [-1, 4.5): {fmt(S['XH'], 1e6, 'uJ')};  X_A {fmt(S['XA'], 1e6, 'uJ')}")
L.append(f"(b) X_H [-2, 4.5): {fmt(S['XH2'], 1e6, 'uJ')};  X_A {fmt(S['XA2'], 1e6, 'uJ')}")
if S["Dc1"]:
    L.append("\nlogger-excluded variant (decision intervals overlapping an INA3221 read [-1, +10) ms or a freqlog read [-2, +2) ms dropped):")
    L.append("| round | X_H excl uJ | X_A excl uJ | D excl [-1,4.5) uJ | D excl [-2,4.5) uJ | D excl [-2,5.5) uJ | dropped intervals H / A |")
    L.append("|---|---|---|---|---|---|---|")
    for i, r in enumerate(full):
        L.append(f"| {r} | {S['XHc'][i] * 1e6:.2f} | {S['XAc'][i] * 1e6:.2f} | {S['Dc1'][i] * 1e6:+.2f} | {S['Dc2'][i] * 1e6:+.2f} | {S['Dc55'][i] * 1e6:+.2f} | "
                 f"{by[(r, 'H')]['excl_frac'] * 100:.1f} % / {by[(r, 'A')]['excl_frac'] * 100:.1f} % |")
    L.append(f"(b, excl) E_dyn(A), window [-1, 4.5) ms: {fmt(S['Dc1'], 1e6, 'uJ')}")
    L.append(f"(b, excl) E_dyn(A), window [-2, 4.5) ms: {fmt(S['Dc2'], 1e6, 'uJ')}")
    L.append(f"(b, excl) E_dyn(A), window [-2, 5.5) ms (sensitivity): {fmt(S['Dc55'], 1e6, 'uJ')}")
    L.append(f"(b, excl) X_H [-1, 4.5): {fmt(S['XHc'], 1e6, 'uJ')};  X_A {fmt(S['XAc'], 1e6, 'uJ')}")
    L.append(f"(b, excl) X_H [-2, 4.5): {fmt(S['XHc2'], 1e6, 'uJ')};  X_A {fmt(S['XAc2'], 1e6, 'uJ')}")
    for cnd in CTL:
        e21 = [by[(r, cnd)]["c1"]["ex21"] for r in full]
        e45 = [by[(r, cnd)]["c1"]["ex455"] for r in full]
        L.append(f"(b, excl) window check {cnd}: excess over [-2, -1) ms {fmt(e21, 1e3, 'mW', 1)}; over [4.5, 5.5) ms {fmt(e45, 1e3, 'mW', 1)}")
    L.append(f"marker-write -> edge fit residual (board mono to PIO), us: {[round(by[(r, c_)]['tb_fit_resid_us'], 1) for r in full for c_ in CTL]}")
    L.append("")
L.append(f"(a) E_dyn(A) = (P_A - P_H)/f per round: {fmt(S['Ea'], 1e6, 'uJ', 1)}")
if S["Va"]:
    L.append(f"VDD_IN (a) E_dyn(A): {fmt(S['Va'], 1e6, 'uJ', 1)}")
f = np.mean(S["rt"]) if S["rt"] else 100.0
PH = [x["Pa"] for x in R if x["cond"] == "H" and x["round"] in full]
PA = [x["Pa"] for x in R if x["cond"] == "A" and x["round"] in full]
PI = [x["Pa"] for x in Is]
L.append(f"decision rate f (mean of rounds): {f:.4f} Hz")
L.append(f"block means: P_H {fmt(PH, 1e3, 'mW', 1)}; P_A {fmt(PA, 1e3, 'mW', 1)}; P_I {[round(p * 1e3, 1) for p in PI]} mW")
if len(PI) >= 2 and len(PH) >= 2:
    m, lo, hi, se, df = welch(PH, PI)
    L.append(f"(a) harness (mean P_H - mean P_I)/f: {m / f * 1e6:+.1f} uJ [{lo / f * 1e6:+.1f}, {hi / f * 1e6:+.1f}] (Welch se {se / f * 1e6:.1f}, df {df:.2f}, t {t975(df):.3f}); "
             f"= {m * 1e3:+.1f} mW; the I side has {len(PI)} blocks, so its variance has {len(PI) - 1} df")
    res["harness"] = [m / f, lo / f, hi / f, df]
    # stack
    mA, loA, hiA, seA = tci(np.array(PA) / f)
    mI = np.mean(PI) / f
    mH = np.mean(PH) / f
    L.append(f"E_tot(A) = mean P_A / f: {mA * 1e3:.3f} mJ [{loA * 1e3:.3f}, {hiA * 1e3:.3f}] = idle floor {mI * 1e3:.3f} mJ + harness {(mH - mI) * 1e6:+.1f} uJ + algorithm (a) {(mA - mH) * 1e6:+.1f} uJ")
    for bt in sorted(set(BOOT[x["capture"]] for x in out_blocks)):
        ph = [x["Pa"] for x in R if x["cond"] == "H" and x["round"] in full and BOOT[x["capture"]] == bt]
        pa_ = [x["Pa"] for x in R if x["cond"] == "A" and x["round"] in full and BOOT[x["capture"]] == bt]
        pi = [x["Pa"] for x in Is if BOOT[x["capture"]] == bt]
        if ph and pi:
            s = f"boot {bt}: I blocks {[x['tag'] for x in Is if BOOT[x['capture']] == bt]} P_I {np.mean(pi) * 1e3:.1f} mW; H blocks {len(ph)} P_H {np.mean(ph) * 1e3:.1f} mW; A blocks {len(pa_)} P_A {np.mean(pa_) * 1e3:.1f} mW; harness (P_H - P_I)/f {(np.mean(ph) - np.mean(pi)) / f * 1e6:+.1f} uJ"
            if len(pi) >= 2 and len(ph) >= 2:
                m3, lo3, hi3, se3, df3 = welch(ph, pi)
                s += f" [{lo3 / f * 1e6:+.1f}, {hi3 / f * 1e6:+.1f}] (Welch df {df3:.2f})"
            else:
                s += " (one I block: no CI)"
            L.append(s)
    if all("vin" in x for x in Is) and all("vin" in x for x in R):
        VH = [x["vin"] / 1e3 for x in R if x["cond"] == "H" and x["round"] in full]
        VA = [x["vin"] / 1e3 for x in R if x["cond"] == "A" and x["round"] in full]
        VI = [x["vin"] / 1e3 for x in Is]
        m2, lo2, hi2, se2, df2 = welch(VH, VI)
        L.append(f"VDD_IN: P_H {np.mean(VH) * 1e3:.1f} mW, P_A {np.mean(VA) * 1e3:.1f} mW, P_I {[round(v * 1e3, 1) for v in VI]} mW; "
                 f"harness {m2 / f * 1e6:+.1f} uJ [{lo2 / f * 1e6:+.1f}, {hi2 / f * 1e6:+.1f}] (Welch df {df2:.2f}); E_tot(A) on VDD_IN {np.mean(VA) / f * 1e3:.3f} mJ")
for cnd in CTL:
    e21 = [by[(r, cnd)]["b1"]["ex21"] for r in full]
    e45 = [by[(r, cnd)]["b1"]["ex455"] for r in full]
    L.append(f"window check {cnd}: excess over [-2, -1) ms before the edge {fmt(e21, 1e3, 'mW', 1)}; over [4.5, 5.5) ms after the edge {fmt(e45, 1e3, 'mW', 1)}")
    e21e = [x * 1e-3 for x in e21]
for cnd in CTL:
    for key in ("ctl_p50", "ctl_p99", "nev_mean", "rms_deg", "in_fov"):
        v = [by[(r, cnd)][key] for r in full]
        L.append(f"{cnd} {key}: mean {np.mean(v):.4g}, range {np.min(v):.4g}-{np.max(v):.4g}" if v else f"{cnd} {key}: -")
    v = [by[(r, cnd)]["ctl_max"] for r in full]
    L.append(f"{cnd} ctl_max per block: {[round(x) for x in v]}; misses per block {[by[(r, cnd)]['miss'] for r in full]}; losses {[by[(r, cnd)]['losses'] for r in full]}")
    if "p0_729" in by.get((full[0], cnd), {}) if full else False:
        L.append(f"{cnd} policy0 at 729.6 MHz per block: {[round(by[(r, cnd)]['p0_729'] * 100, 1) for r in full]} %; tj {[round(by[(r, cnd)]['tj'], 1) for r in full]} C")
# drift
if n >= 3:
    for key, lab in (("XH", "X_H"), ("XA", "X_A"), ("D1", "D"), ("XHc", "X_H excl"), ("XAc", "X_A excl"), ("Dc1", "D excl")):
        if len(S[key]) != n:
            continue
        s, lo, hi = slope_ci(full, S[key])
        L.append(f"drift {lab} against round: slope {s * 1e6:+.3f} uJ/round [{lo * 1e6:+.3f}, {hi * 1e6:+.3f}] (t, {n - 2} df); "
                 f"sd {np.std(S[key], ddof=1) * 1e6:.2f} uJ, range {min(S[key]) * 1e6:.1f}-{max(S[key]) * 1e6:.1f}")
# sizing
if n >= 2:
    for lab, key in (("(b) [-1,4.5)", "D1"), ("(b) [-2,4.5)", "D2"), ("(a)", "Ea"), ("(b, excl) [-1,4.5)", "Dc1"), ("(b, excl) [-2,4.5)", "Dc2")):
        if len(S[key]) != n:
            continue
        m, lo, hi, se = tci(S[key])
        sd = se * np.sqrt(n)
        L.append(f"sizing {lab}: mean {m * 1e6:+.2f} uJ, sd_D {sd * 1e6:.2f} uJ, half-width now {(hi - m) * 1e6:.2f} uJ = {(hi - m) / abs(m) * 100:.1f} % "
                 f"(t, {n - 1} df); N for +-5 %: {rounds_needed(sd, m, 0.05)} rounds, for +-10 %: {rounds_needed(sd, m, 0.10)} rounds")
        res[f"sizing_{key}"] = {"mean": m, "sd": sd, "half": hi - m, "n": n, "N5": rounds_needed(sd, m, 0.05), "N10": rounds_needed(sd, m, 0.10)}
txt = "\n".join(L)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")
json.dump({"blocks": [{k: v for k, v in r.items() if k not in ("b1", "b2", "c1", "c2")} | {f"{b}_{k}": float(r[b][k]) for b in ("b1", "b2", "c1", "c2") if b in r
                                                                              for k in ("X", "X55", "base", "ex21", "ex455")}
                      for r in out_blocks], "summary": res}, open(outp + ".json", "w"), indent=1, default=float)

fig, ax = plt.subplots(1, 3, figsize=(16, 5), gridspec_kw={"width_ratios": [1, 1.6, 1.2]})
for cnd, col in (("H", "C0"), ("A", "C3")):
    bl = [by[(r, cnd)]["b1"] for r in full]
    if not bl:
        continue
    fb, fa = bl[0]["fb"], bl[0]["fa"]
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
ax[1].axvline(4.5, color="0.6", ls=":")
ax[1].set_title("after the preceding edge (baseline 5.5-8.5 ms shaded, window end 4.5 ms dotted)")
ax[2].axvspan(-1, 4.5, color="0.9", alpha=0.4)
ax[2].set_title("window profile [-1, 4.5) ms, phase to own edge")
ax[0].set_ylabel("INA228 power above the block baseline, mW (mean of rounds)")
fig.suptitle(f"T6: closed loop, hold vs classical, marker-aligned ({', '.join(caps)}; rounds {full[0] if full else '-'}-{full[-1] if full else '-'})")
fig.tight_layout()
fig.savefig(outp + "_profiles.png", dpi=110)
