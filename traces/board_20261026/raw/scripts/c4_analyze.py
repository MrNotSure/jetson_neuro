"""Throwaway (board session 2026-10-26): C4 pilot analysis (Mac, numpy).

usage: .venv/bin/python c4_analyze.py SAMPLER_CSV MARKS_CSV PILOT_JSON [TAG_PREFIX]
Per block: mean power per rail over [start+3 s, end-3 s] (board monotonic marks), misses and
ctl_us p50 from the run directory. Per condition: mean +- sd over repeats. Differences H-I and
C-H with 95 % CIs (Welch t; Student t quantiles from a table). E_dyn and E_tot for centroid at
100 Hz, and the repeats per condition needed for a CI half-width of +-10 % of (C - H).
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

RAILS = {1: "VDD_IN", 2: "VDD_CPU_GPU_CV", 3: "VDD_SOC"}
F = 100.0  # control rate, Hz
DROP = 3.0  # s dropped at each block edge
# two-sided 95 % Student t quantiles t_{0.975, df}
TQ = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
      11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086,
      22: 2.074, 24: 2.064, 26: 2.056, 28: 2.048, 30: 2.042, 40: 2.021, 60: 2.000, 120: 1.980, 10**9: 1.960}


def tq(df):
    ks = sorted(TQ)
    if df <= ks[0]:
        return TQ[ks[0]]
    for lo, hi in zip(ks, ks[1:]):
        if lo <= df <= hi:
            return TQ[lo] + (TQ[hi] - TQ[lo]) * (df - lo) / (hi - lo)
    return 1.96


def welch(a, b):
    """CI for mean(a) - mean(b)."""
    a, b = np.asarray(a), np.asarray(b)
    va, vb = a.var(ddof=1) / len(a), b.var(ddof=1) / len(b)
    se = np.sqrt(va + vb)
    df = (va + vb) ** 2 / (va**2 / (len(a) - 1) + vb**2 / (len(b) - 1)) if se > 0 else 10**9
    d = a.mean() - b.mean()
    h = tq(df) * se
    return d, h, df, se


def n_needed(sa, sb, delta, target=0.10):
    for n in range(2, 10000):
        df = 2 * n - 2  # equal n, pooled-ish df
        h = tq(df) * np.sqrt(sa**2 / n + sb**2 / n)
        if h <= target * abs(delta):
            return n
    return None


def main():
    samp, marks, pj = sys.argv[1], sys.argv[2], sys.argv[3]
    prefix = sys.argv[4] if len(sys.argv) > 4 else "C4"
    a = np.loadtxt(samp, delimiter=",", skiprows=1, dtype=np.int64)
    t = a[:, 0]
    p = {i: a[:, 2 * i] * a[:, 2 * i + 1] / 1000.0 for i in (1, 2, 3)}
    mk = {}
    with open(marks, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["tag"].startswith(prefix + "_"):
                mk.setdefault(r["tag"], {})[r["edge"]] = int(r["mono_ns"])
    blocks = json.load(open(pj))
    per = []
    print(f"{'block':10s} {'cond':4s} {'win_s':>6s} {'n':>5s} " + " ".join(f"{n:>15s}" for n in RAILS.values()) +
          f" {'misses':>6s} {'ctl_p50':>8s} {'lat_max':>8s} {'run_first_rx_vs_start_s':>24s} {'run_last_rx_vs_end_s':>21s}")
    for b in blocks:
        tag = b["tag"]
        if tag not in mk or "start" not in mk[tag] or "end" not in mk[tag]:
            continue
        s, e = mk[tag]["start"], mk[tag]["end"]
        sel = (t >= s + DROP * 1e9) & (t <= e - DROP * 1e9)
        vals = [p[i][sel].mean() for i in (1, 2, 3)]
        misses = ctl50 = latmax = first = last = float("nan")
        if b.get("run_dir"):
            rd = Path("/Users/<user>/Documents/code/jetson_neuro") / b["run_dir"]
            s_ = json.load(open(rd / "summary.json"))
            misses = s_["overall"]["misses"]
            with open(rd / "periods.csv", newline="", encoding="utf-8") as fh:
                rows = list(csv.DictReader(fh))
            ctl = np.array([float(r["ctl_us"]) for r in rows if r["ctl_us"] not in ("", "nan")])
            lat = np.array([float(r["send_lateness_us"]) for r in rows])
            rx = [int(float(r["ctl_rx_ns"])) for r in rows if r["ctl_rx_ns"] not in ("", "nan")]
            ctl50, latmax = np.median(ctl), np.nanmax(lat)
            first, last = (rx[0] - s) / 1e9, (rx[-1] - e) / 1e9
        per.append((tag, b["cond"], vals, misses, ctl50))
        print(f"{tag:10s} {b['cond']:4s} {(e-s)/1e9:6.1f} {sel.sum():5d} " + " ".join(f"{v:15.1f}" for v in vals) +
              f" {misses:6} {ctl50:8.1f} {latmax:8.0f} {first:24.2f} {last:21.2f}")
    print()
    res = {}
    for cond in ("I", "H", "C"):
        xs = np.array([v for _, c, v, _, _ in per if c == cond])
        if len(xs):
            res[cond] = xs
            print(f"condition {cond}: n={len(xs)}  " + "  ".join(
                f"{n}={xs[:, k].mean():.1f}+-{xs[:, k].std(ddof=1) if len(xs) > 1 else float('nan'):.1f}" for k, n in enumerate(RAILS.values())))
    print()
    for (A, Bc) in (("H", "I"), ("C", "H"), ("C", "I")):
        if A in res and Bc in res and len(res[A]) > 1 and len(res[Bc]) > 1:
            for k, n in enumerate(RAILS.values()):
                d, h, df, se = welch(res[A][:, k], res[Bc][:, k])
                print(f"P_{A} - P_{Bc} {n:15s}: {d:+7.1f} mW  95% CI [{d-h:+7.1f}, {d+h:+7.1f}] (Welch df={df:.1f}, se={se:.1f})")
            print()
    if "C" in res and "H" in res:
        print(f"E per decision at f = {F:.0f} Hz:")
        for k, n in enumerate(RAILS.values()):
            d, h, df, se = welch(res["C"][:, k], res["H"][:, k])
            ec = res["C"][:, k].mean() / F
            nn = n_needed(res["C"][:, k].std(ddof=1), res["H"][:, k].std(ddof=1), d)
            print(f"  {n:15s} E_dyn = (P_C-P_H)/f = {d/F:+.3f} mJ  95% CI [{(d-h)/F:+.3f}, {(d+h)/F:+.3f}]   "
                  f"E_tot = P_C/f = {ec:.2f} mJ   repeats/condition for CI half-width <= 10% of (P_C-P_H): {nn}")


if __name__ == "__main__":
    main()
