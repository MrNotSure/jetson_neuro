"""T6b (2 Nov 2026): the pre-registered analysis of raw/plan.txt. From traces/t6_20261102/scripts/t6_analyze.py
(an unchanged copy is kept as t6_analyze_T6copy.py). Method (b), method (a) for H/A, the I window, the window check,
the slope and the sizing code are T6's, unchanged. T6b changes, all fixed in raw/plan.txt before the first block:
  - GP16 pulses < 1 us wide (fall -> next rise) are always dropped before the falls are split into blocks
    (T6's DEGLITCH option, now always on); the count is reported per capture;
  - marker integrity: every H/A block needs falls = mark_ctl rows = OBS (periods.csv rows) = 6000; a block that
    fails is excluded together with its whole round;
  - no logger-excluded variant and no VDD_IN analysis: no 10 Hz logger runs in T6b, and VDD_IN is kept only as the
    snapshot readings (raw/snapshots.txt), summarised here as recorded;
  - one I block per round: harness = (P_H - P_I)/f per round, t CI (T6: Welch over 3 session-level I blocks);
    E_tot(A) = P_A/f per round = P_I/f + (P_H - P_I)/f + (P_A - P_H)/f, each term with a t CI;
    f per round = mean of that round's H and A decision rates (T6's f for method (a));
  - X_H, X_A and D against round index (least-squares slope, t CI, n - 2 df) and by capture (mean and t CI per
    capture; one-way ANOVA F against its 5 % critical value);
  - logger hypothesis: sd_D against T6's 14.3 uJ (logger-excluded) and 66.6 uJ (primary); N for +-5 % and +-10 %.

  .venv/bin/python scripts/t6_analyze.py OUTPREFIX CAP [CAP ...]       (e.g. raw/result K1 K2 K3)

T6B_RUN=<run folder> reads another session's files (used once, to check this script against T6's C1).
"""
import csv
import json
import os
import re
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
F95_DF1_2 = {3: 9.552, 4: 6.944, 5: 5.786, 6: 5.143, 7: 4.737, 8: 4.459, 9: 4.256, 10: 4.103, 11: 3.982, 12: 3.885}
CHI2 = {2: (0.0506, 7.378), 3: (0.216, 9.348), 4: (0.484, 11.143), 5: (0.831, 12.833), 6: (1.237, 14.449),
        7: (1.690, 16.013), 8: (2.180, 17.535), 9: (2.700, 19.023), 10: (3.247, 20.483), 11: (3.816, 21.920)}   # (2.5 %, 97.5 %)
RUN = os.path.abspath(os.environ.get("T6B_RUN") or os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CTL = ("H", "A")
N_EXP = 6000                      # decisions per 60 s H/A block
GLITCH_S = 1e-6                   # pulses shorter than this are dropped (a start bit is 8.68 us)
T6_SD_D = {"T6 logger-excluded": 14.3e-6, "T6 primary": 66.6e-6}


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


def has0(v):
    m, lo, hi, se = tci(v)
    return "consistent with 0" if lo <= 0 <= hi else "NOT consistent with 0"


def rounds_needed(sd, m, tgt):
    k = 2
    while t975(k - 1) * sd / np.sqrt(k) > tgt * abs(m) and k < 100000:
        k += 1
    return k


def anova(groups):
    """One-way ANOVA F over groups (lists). Returns F, df1, df2, 5 % critical value (df1 = 2 only) or nan."""
    gs = [np.asarray(g, float) for g in groups if len(g)]
    if len(gs) < 2:
        return np.nan, 0, 0, np.nan
    allv = np.concatenate(gs)
    m = allv.mean()
    ssb = sum(len(g) * (g.mean() - m) ** 2 for g in gs)
    ssw = sum(((g - g.mean()) ** 2).sum() for g in gs)
    df1, df2 = len(gs) - 1, len(allv) - len(gs)
    if df2 < 1 or ssw == 0:
        return np.nan, df1, df2, np.nan
    F = (ssb / df1) / (ssw / df2)
    return F, df1, df2, (F95_DF1_2.get(df2, np.nan) if df1 == 2 else np.nan)


def method_b(tc, P, fr, flag, pre, excl=None):
    """T6's method (b), unchanged. Profile over [-pre, 8.5) ms by phase to the own edge; whole-fold profiles; window
    excesses. excl (never used in T6b): optional bool per edge interval; True drops every conversion of that interval."""
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


def snapshots():
    """Per tag: {'before'|'after': {vin_mW, tj_C, p0, p4, gpu, fan_pwm, apt_clean, no_jobs}} from raw/snapshots.txt."""
    path = os.path.join(RUN, "raw", "snapshots.txt")
    out = {}
    if not os.path.exists(path):
        return out
    cur = None
    for line in open(path):
        mh = re.match(r"== (\S+) .*?(before|after)\s*$", line) or re.match(r"== (\S+) (before|after)\s*$", line)
        if line.startswith("== "):
            cur = (mh.group(1), mh.group(2)) if mh else None
            if cur:
                out.setdefault(cur[0], {})[cur[1]] = {"apt_clean": False, "no_jobs": False}
            continue
        if not cur:
            continue
        d = out[cur[0]][cur[1]]
        if (m := re.search(r"vdd_in mV=(\d+) mA=(\d+)", line)):
            d["vin_mW"] = int(m.group(1)) * int(m.group(2)) / 1000
        if (m := re.search(r"tj-thermal=(-?\d+)", line)):
            d["tj_C"] = int(m.group(1)) / 1000
        if (m := re.search(r"cpu_cur policy0=(\d+) policy4=(\d+) gpu_cur=(\d+)", line)):
            d["p0"], d["p4"], d["gpu"] = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if (m := re.search(r"fan_pwm=(\d+)", line)):
            d["fan_pwm"] = int(m.group(1))
        if "no apt/dpkg" in line:
            d["apt_clean"] = True
        if "No jobs running." in line:
            d["no_jobs"] = True
    return out


outp, caps = sys.argv[1], sys.argv[2:]
L = [f"T6b pre-registered analysis (raw/plan.txt); run folder {RUN}; captures {caps}"]
allblocks = json.load(open(os.path.join(RUN, "raw", "blocks.json")))
order = {}
for l in open(os.path.join(RUN, "raw", "order.txt")):
    if l.startswith("round"):
        order[int(l.split()[0][5:])] = " ".join(l.split()[1:])

out_blocks, excluded, bad_rounds, dropped = [], [], set(), {}
for cap in caps:
    c = load(os.path.join(RUN, "raw", cap + ".bin"))
    ok = c["cnvrf"].copy()
    ok[0] = False
    edge = c["t"][ok]
    tc = edge - 540e-6
    P = c["P"][ok]
    fall, rise = c["fall"], c["rise"]
    iv = np.diff(c["t"][1:]) * 1e6
    Tm = np.median(iv)
    L.append(f"{cap}: {ok.sum()} valid conversions, missed {int(np.sum(np.round(iv[iv > 1.5 * Tm] / Tm) - 1))}, "
             f"spurious ALRT {int((~c['cnvrf'][1:]).sum())}, falls {len(fall)}, rises {len(rise)}, trailer {c['trailer']}")
    # pre-registered deglitch: width = next rise after the fall; no following rise counts as wide (kept)
    if len(fall) and len(rise):
        jj = np.searchsorted(rise, fall, side="right")
        wd = np.where(jj < len(rise), rise[np.minimum(jj, len(rise) - 1)] - fall, np.inf)
    else:
        wd = np.full(len(fall), np.inf)
    short = wd < GLITCH_S
    dropped[cap] = int(short.sum())
    L.append(f"  DEGLITCH (pre-registered): dropped {dropped[cap]} GP16 pulses < 1 us wide"
             + (f" at t = {np.round(fall[short], 6).tolist()[:20]} s, widths {np.round(wd[short] * 1e6, 3).tolist()[:20]} us" if dropped[cap] else ""))
    fall = fall[~short]
    ch = np.loadtxt(os.path.join(RUN, "raw", cap + ".chunks.csv"), delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
    offs = ch[:, 1] - ch[:, 0]
    L.append(f"  Mac unix - mono over the capture: spread {(offs.max() - offs.min()) / 1e6:.1f} ms"
             + ("  WARNING: the Mac slept during this capture" if offs.max() - offs.min() > 50e6 else ""))
    kk = np.clip(np.searchsorted(ch[:, 2], (c["conv_idx"] + 1) * 16), 0, len(ch) - 1)
    arr = ch[kk, 0][ok].astype(float)
    sub = slice(None, None, 97)
    cf = np.polyfit(arr[sub] / 1e9, edge[sub], 1)
    res = edge[sub] - np.polyval(cf, arr[sub] / 1e9)
    L.append(f"  PIO-vs-Mac-arrival fit: slope {cf[0]:.9f}, residual sd {res.std() * 1e3:.2f} ms")
    mono2pio = lambda m, cf=cf: np.polyval(cf, m / 1e9)

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
                excluded.append(f"{b['tag']}: no fall run")
                bad_rounds.add(b["round"])
                continue
            fr = b["fr"]
            rows = list(csv.DictReader(open(os.path.join(RUN, "raw", "board", b["mc_csv"]))))
            per = {int(p["k"]): p for p in csv.DictReader(open(os.path.join(RUN, "sim", b["sim_dir"], "periods.csv")))}
            if not (len(fr) == len(rows) == len(per) == N_EXP):
                excluded.append(f"{b['tag']}: falls {len(fr)}, mark_ctl rows {len(rows)}, OBS {len(per)} (need {N_EXP} each)")
                bad_rounds.add(b["round"])
                continue
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
        else:
            w0, w1 = mono2pio(ms) + 4, mono2pio(me) - 4
        m = (tc >= w0) & (tc < w1)
        rec["Pa"] = P[m].mean()
        rec["win_s"] = w1 - w0
        rec["n_conv_a"] = int(m.sum())
        out_blocks.append(rec)

L.append("")
L.append("excluded blocks (each takes its whole round): " + ("; ".join(excluded) if excluded else "none"))
L.append(f"pulses < 1 us dropped, per capture: {dropped}; total {sum(dropped.values())}")
L.append("\nper block:")
L.append("| block | cap | cond | P_a mW | window s | X [-1,4.5) uJ | X [-2,4.5) uJ | X [-2,5.5) uJ | baseline mW | pre [-2,-1) mW | post [4.5,5.5) mW | events | ctl_us p50/p99/max | rms_deg | max_deg | in-FOV | losses | miss / late>5ms | out 8-15 ms | conv used | affinity |")
L.append("|" + "---|" * 21)
for r in out_blocks:
    if r["cond"] in CTL:
        b1, b2 = r["b1"], r["b2"]
        L.append(f"| {r['tag']} | {r['capture']} | {r['cond']} | {r['Pa'] * 1e3:.1f} | {r['win_s']:.1f} | {b1['X'] * 1e6:.2f} | {b2['X'] * 1e6:.2f} | {b2['X55'] * 1e6:.2f} | "
                 f"{b1['base'] * 1e3:.1f} | {b1['ex21'] * 1e3:+.1f} | {b1['ex455'] * 1e3:+.1f} | {r['nev_mean']:.1f} | {r['ctl_p50']:.0f}/{r['ctl_p99']:.0f}/{r['ctl_max']:.0f} | "
                 f"{r['rms_deg']:.3f} | {r['max_deg']:.3f} | {r['in_fov']:.3f} | {r['losses']} | {r['miss']} / {r['late5']} | {r['out_8_15']} | {b1['n_used']}/{b1['n_conv']} | {r['affinity']} |")
    else:
        L.append(f"| {r['tag']} | {r['capture']} | I | {r['Pa'] * 1e3:.1f} | {r['win_s']:.1f} | - | - | - | - | - | - | - | - | - | - | - | - | - | - | {r['n_conv_a']} | - |")
for r in out_blocks:
    if r["cond"] in CTL:
        q = r["b1"]
        seg = []
        for a0, a1 in ((-1, 0), (0, 0.5), (0.5, 1), (1, 2), (2, 3), (3, 4.5), (4.5, 5.5)):
            mm = (q["ctr"] >= a0 * 1e-3) & (q["ctr"] < a1 * 1e-3)
            seg.append(f"[{a0:g},{a1:g}) {np.mean(q['prof'][mm] - q['base']) * 1e3:+.0f}")
        L.append(f"  {r['tag']}: excess by segment, ms -> mW: " + ", ".join(seg) + f"; decisions {r['n']} (OBS {r['obs']}), "
                 f"rate {r['rate']:.4f} Hz, flagged {r['flagged']}")

by = {(x["round"], x["cond"]): x for x in out_blocks}
cand = sorted(set(x["round"] for x in out_blocks if x["round"] > 0) | {r for r in bad_rounds if r > 0})
full = [r for r in cand if r not in bad_rounds and (r, "H") in by and (r, "A") in by]
fullI = [r for r in full if (r, "I") in by]
L.append(f"\nrounds kept (H and A valid): {full}; with a valid I block too: {fullI}; rounds excluded: {sorted(bad_rounds)}")

S = {k: [] for k in ("D1", "D2", "D55", "XH", "XA", "XH2", "XA2", "Ea", "f", "PH", "PA")}
SI = {k: [] for k in ("harness", "floor", "Etot", "algo", "PI")}
L.append("\n| round | cap | order | P_I mW | P_H mW | P_A mW | f Hz | X_H uJ | X_A uJ | D (b) uJ | D [-2,4.5) uJ | D [-2,5.5) uJ | (a) uJ | harness uJ | E_tot(A) mJ |")
L.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
for r in full:
    H, A = by[(r, "H")], by[(r, "A")]
    f = (H["rate"] + A["rate"]) / 2
    S["f"].append(f)
    S["PH"].append(H["Pa"]); S["PA"].append(A["Pa"])
    S["D1"].append(A["b1"]["X"] - H["b1"]["X"])
    S["D2"].append(A["b2"]["X"] - H["b2"]["X"])
    S["D55"].append(A["b2"]["X55"] - H["b2"]["X55"])
    S["XH"].append(H["b1"]["X"]); S["XA"].append(A["b1"]["X"]); S["XH2"].append(H["b2"]["X"]); S["XA2"].append(A["b2"]["X"])
    S["Ea"].append((A["Pa"] - H["Pa"]) / f)
    pi, hs, et = "-", "-", "-"
    if r in fullI:
        I = by[(r, "I")]
        SI["PI"].append(I["Pa"])
        SI["harness"].append((H["Pa"] - I["Pa"]) / f)
        SI["floor"].append(I["Pa"] / f)
        SI["algo"].append((A["Pa"] - H["Pa"]) / f)
        SI["Etot"].append(A["Pa"] / f)
        pi, hs, et = f"{I['Pa'] * 1e3:.1f}", f"{SI['harness'][-1] * 1e6:+.1f}", f"{SI['Etot'][-1] * 1e3:.4f}"
    L.append(f"| {r} | {H['capture']} | {order.get(r, '')} | {pi} | {H['Pa'] * 1e3:.1f} | {A['Pa'] * 1e3:.1f} | {f:.4f} | "
             f"{S['XH'][-1] * 1e6:.2f} | {S['XA'][-1] * 1e6:.2f} | {S['D1'][-1] * 1e6:+.2f} | {S['D2'][-1] * 1e6:+.2f} | {S['D55'][-1] * 1e6:+.2f} | "
             f"{S['Ea'][-1] * 1e6:+.1f} | {hs} | {et} |")

n = len(full)
res = {"rounds": full, "rounds_with_I": fullI, "excluded": excluded, "pulses_dropped": dropped,
       "per_round": {k: [float(v) for v in S[k]] for k in S} | {k: [float(v) for v in SI[k]] for k in SI}}


def put(key, v, scale=1.0):
    m, lo, hi, se = tci(v)
    res[key] = {"mean": m * scale, "lo": lo * scale, "hi": hi * scale, "se": se * scale, "n": len(v)}


L.append("\nPRIMARY")
L.append(f"(b) E_dyn(A) = mean D = X_A - X_H, window [-1, 4.5) ms: {fmt(S['D1'], 1e6, 'uJ')}")
put("Edyn_b_primary_uJ", S["D1"], 1e6)
L.append("\nSECONDARY")
L.append(f"(b) E_dyn(A), window [-2, 4.5) ms: {fmt(S['D2'], 1e6, 'uJ')}")
L.append(f"(b) E_dyn(A), window [-2, 5.5) ms: {fmt(S['D55'], 1e6, 'uJ')}")
L.append(f"(a) E_dyn(A) = (P_A - P_H)/f per round: {fmt(S['Ea'], 1e6, 'uJ', 1)}")
L.append(f"(b) X_H [-1, 4.5): {fmt(S['XH'], 1e6, 'uJ')};  X_A {fmt(S['XA'], 1e6, 'uJ')}")
L.append(f"(b) X_H [-2, 4.5): {fmt(S['XH2'], 1e6, 'uJ')};  X_A {fmt(S['XA2'], 1e6, 'uJ')}")
put("Edyn_b_m2_45_uJ", S["D2"], 1e6); put("Edyn_b_m2_55_uJ", S["D55"], 1e6); put("Edyn_a_uJ", S["Ea"], 1e6)
put("XH_uJ", S["XH"], 1e6); put("XA_uJ", S["XA"], 1e6); put("XH2_uJ", S["XH2"], 1e6); put("XA2_uJ", S["XA2"], 1e6)
L.append(f"decision rate f per round: mean {np.mean(S['f']):.4f} Hz, range {min(S['f']):.4f}-{max(S['f']):.4f}" if S["f"] else "no rounds")
L.append(f"block means: P_H {fmt(S['PH'], 1e3, 'mW', 1)}; P_A {fmt(S['PA'], 1e3, 'mW', 1)}; P_I {fmt(SI['PI'], 1e3, 'mW', 1)}")
if SI["harness"]:
    L.append(f"harness (P_H - P_I)/f per round: {fmt(SI['harness'], 1e6, 'uJ', 1)}")
    L.append(f"E_tot(A) = P_A/f per round: {fmt(SI['Etot'], 1e3, 'mJ', 4)}")
    L.append(f"  stack: idle floor P_I/f {fmt(SI['floor'], 1e3, 'mJ', 4)}")
    L.append(f"       + harness       {fmt(SI['harness'], 1e6, 'uJ', 1)}")
    L.append(f"       + algorithm (a) {fmt(SI['algo'], 1e6, 'uJ', 1)}")
    put("harness_uJ", SI["harness"], 1e6); put("Etot_mJ", SI["Etot"], 1e3); put("floor_mJ", SI["floor"], 1e3); put("algo_uJ", SI["algo"], 1e6)
    put("PI_mW", SI["PI"], 1e3)
put("PH_mW", S["PH"], 1e3); put("PA_mW", S["PA"], 1e3)

L.append("\nWINDOW CHECK (excess over the block baseline, per round, t CI; method (b) with pre = 1 ms)")
for cnd in CTL:
    e21 = [by[(r, cnd)]["b1"]["ex21"] for r in full]
    e45 = [by[(r, cnd)]["b1"]["ex455"] for r in full]
    L.append(f"{cnd}: [-2, -1) ms before the edge {fmt(e21, 1e3, 'mW', 1)} -> {has0(e21)}; "
             f"[4.5, 5.5) ms after the edge {fmt(e45, 1e3, 'mW', 1)} -> {has0(e45)}")
    put(f"win_{cnd}_pre21_mW", e21, 1e3); put(f"win_{cnd}_post455_mW", e45, 1e3)

L.append("\nDRIFT: against round index (least squares, t CI, n - 2 df)")
for key, lab in (("XH", "X_H"), ("XA", "X_A"), ("D1", "D")):
    if n >= 3:
        s, lo, hi = slope_ci(full, S[key])
        L.append(f"{lab}: slope {s * 1e6:+.3f} uJ/round [{lo * 1e6:+.3f}, {hi * 1e6:+.3f}] -> {'consistent with 0' if lo <= 0 <= hi else 'NOT consistent with 0'}; "
                 f"sd {np.std(S[key], ddof=1) * 1e6:.2f} uJ, range {min(S[key]) * 1e6:.1f}-{max(S[key]) * 1e6:.1f}")
        res[f"slope_{key}_uJ_per_round"] = [s * 1e6, lo * 1e6, hi * 1e6]
L.append("by capture (mean, t CI over that capture's rounds; one-way ANOVA F across captures)")
capof = {r: by[(r, "H")]["capture"] for r in full}
for key, lab in (("XH", "X_H"), ("XA", "X_A"), ("D1", "D")):
    parts, groups = [], []
    for cp in caps:
        g = [v for r, v in zip(full, S[key]) if capof[r] == cp]
        groups.append(g)
        parts.append(f"{cp} {fmt(g, 1e6, 'uJ', 1)}" if g else f"{cp} -")
    F, d1, d2, crit = anova(groups)
    L.append(f"{lab}: " + "; ".join(parts) + f"; ANOVA F({d1}, {d2}) = {F:.2f}, 5 % critical {crit:.3f} -> "
             + ("differ" if F > crit else "no difference at 5 %" if np.isfinite(crit) else "no critical value tabled"))
    res[f"anova_{key}"] = [F, d1, d2, crit]

L.append("\nLOGGER HYPOTHESIS AND PRECISION")
if n >= 2:
    for lab, key in (("(b) [-1,4.5) primary", "D1"), ("(b) [-2,4.5)", "D2"), ("(b) [-2,5.5)", "D55"), ("(a)", "Ea")):
        m, lo, hi, se = tci(S[key])
        sd = se * np.sqrt(n)
        L.append(f"{lab}: mean {m * 1e6:+.2f} uJ, sd_D {sd * 1e6:.2f} uJ, half-width {(hi - m) * 1e6:.2f} uJ = {(hi - m) / abs(m) * 100:.1f} % "
                 f"(t, {n - 1} df); N for +-5 %: {rounds_needed(sd, m, 0.05)} rounds, for +-10 %: {rounds_needed(sd, m, 0.10)} rounds")
        res[f"sizing_{key}"] = {"mean": m, "sd": sd, "half": hi - m, "half_pct": (hi - m) / abs(m) * 100, "n": n,
                                "N5": rounds_needed(sd, m, 0.05), "N10": rounds_needed(sd, m, 0.10)}
    if SI["harness"] and len(SI["harness"]) >= 2:
        m, lo, hi, se = tci(SI["harness"])
        L.append(f"harness: mean {m * 1e6:+.1f} uJ, sd {se * np.sqrt(len(SI['harness'])) * 1e6:.1f} uJ, half-width {(hi - m) * 1e6:.1f} uJ")
    sdD = np.std(S["D1"], ddof=1)
    L.append(f"sd_D (primary) = {sdD * 1e6:.2f} uJ; T6: {T6_SD_D['T6 logger-excluded'] * 1e6:.1f} uJ logger-excluded, "
             f"{T6_SD_D['T6 primary'] * 1e6:.1f} uJ primary; ratio to each {sdD / T6_SD_D['T6 logger-excluded']:.2f} / {sdD / T6_SD_D['T6 primary']:.2f}")
    res["sd_D_uJ"] = sdD * 1e6
    dfs = n - 1
    if dfs in CHI2:
        lo_c, hi_c = CHI2[dfs]
        slo, shi = sdD * np.sqrt(dfs / hi_c), sdD * np.sqrt(dfs / lo_c)
        inside = {k: slo <= v <= shi for k, v in T6_SD_D.items()}
        verdict = ("supported" if inside["T6 logger-excluded"] and not inside["T6 primary"] else
                   "rejected" if inside["T6 primary"] and not inside["T6 logger-excluded"] else "not decided")
        L.append(f"sd_D 95 % CI (chi-square, {dfs} df): [{slo * 1e6:.2f}, {shi * 1e6:.2f}] uJ; contains 14.3: {inside['T6 logger-excluded']}, "
                 f"contains 66.6: {inside['T6 primary']} -> logger hypothesis {verdict} (pre-registered rule: supported if the CI contains "
                 f"14.3 and excludes 66.6; rejected if the reverse; otherwise not decided)")
        res["sd_D_ci_uJ"] = [slo * 1e6, shi * 1e6]
        res["logger_hypothesis"] = verdict

L.append("\nCONTROLLERS, TRACKING AND EVENTS (per block, rounds kept)")
for cnd in CTL:
    for key in ("ctl_p50", "ctl_p99", "ctl_max", "nev_mean", "rms_deg", "max_deg", "in_fov"):
        v = [by[(r, cnd)][key] for r in full]
        L.append(f"{cnd} {key}: mean {np.mean(v):.4g}, range {np.min(v):.4g}-{np.max(v):.4g}" if v else f"{cnd} {key}: -")
        if v:
            res[f"{cnd}_{key}"] = [float(np.mean(v)), float(np.min(v)), float(np.max(v))]
    L.append(f"{cnd} misses per block {[by[(r, cnd)]['miss'] for r in full]}; late > 5 ms {[by[(r, cnd)]['late5'] for r in full]}; "
             f"losses {[by[(r, cnd)]['losses'] for r in full]}; affinity {sorted(set(str(by[(r, cnd)]['affinity']) for r in full))}")
    v = [by[(r, cnd)]["nev_mean"] for r in full]
    if v:
        L.append(f"{cnd} n_events per decision: {fmt(v, 1, 'events', 1)}")

L.append("\nSNAPSHOTS (raw/snapshots.txt, in the gaps; VDD_IN as recorded, not analysed for differences)")
sn = snapshots()
for cnd in ("I", "H", "A"):
    tags = [by[(r, cnd)]["tag"] for r in full if (r, cnd) in by]
    for when in ("before", "after"):
        ds = [sn[t][when] for t in tags if t in sn and when in sn[t]]
        if not ds:
            continue
        vin = [d["vin_mW"] for d in ds if "vin_mW" in d]
        tj = [d["tj_C"] for d in ds if "tj_C" in d]
        p0 = sorted(set(d.get("p0") for d in ds))
        p4 = sorted(set(d.get("p4") for d in ds))
        gp = sorted(set(d.get("gpu") for d in ds))
        fan = sorted(set(d.get("fan_pwm") for d in ds))
        L.append(f"{cnd} {when}: {len(ds)} snapshots; VDD_IN mW " + (f"{min(vin):.0f}-{max(vin):.0f} (mean {np.mean(vin):.0f})" if vin else "-")
                 + (f"; tj {min(tj):.1f}-{max(tj):.1f} C" if tj else "") + f"; policy0 kHz {p0}; policy4 kHz {p4}; gpu Hz {gp}; fan_pwm {fan}; "
                 f"apt/dpkg clean {all(d['apt_clean'] for d in ds)}; no jobs {all(d['no_jobs'] for d in ds)}")
alltj = [d["tj_C"] for t in sn for d in sn[t].values() if "tj_C" in d]
if alltj:
    L.append(f"all snapshots: tj {min(alltj):.1f}-{max(alltj):.1f} C (stop limit 80 C)")

txt = "\n".join(L)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")
json.dump({"blocks": [{k: v for k, v in r.items() if k not in ("b1", "b2")} | {f"{b}_{k}": float(r[b][k]) for b in ("b1", "b2") if b in r
                                                                          for k in ("X", "X55", "base", "ex21", "ex455", "n_used", "n_conv")}
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
fig.suptitle(f"T6b: closed loop, hold vs classical, marker-aligned, no 10 Hz loggers ({', '.join(caps)}; rounds {full[0] if full else '-'}-{full[-1] if full else '-'})")
fig.tight_layout()
fig.savefig(outp + "_profiles.png", dpi=110)
