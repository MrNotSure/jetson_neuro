"""Step 5 analysis: zero-current VSHUNT noise per setting. Standard library only.

  python3.12 noise_analyze.py <05_noise.txt>
"""
import re
import statistics as st
import sys
from collections import defaultdict

R = 0.015
STEP_NV = {0: 312.5, 1: 78.125}
# Datasheet Table 8-2 noise-free ENOB (peak-to-peak based) for the settings used.
ENOB = {("ct50_avg1", 0): 12.4, ("ct280_avg1", 0): 13.8, ("ct1052_avg1", 0): 14.5,
        ("ct280_avg1_range1", 1): 11.8}

meta = {}
data = defaultdict(list)
for line in open(sys.argv[1]):
    m = re.match(r"SETTING (\S+) ADCRANGE=(\d) VSHCT=(\d+)us AVG=(\d+) .*expected_cycle_us=(\d+) .*us_per_sample=([\d.]+)", line)
    if m:
        meta[m[1]] = dict(rng=int(m[2]), ct=int(m[3]), avg=int(m[4]), cyc=int(m[5]), per=float(m[6]))
    elif line.startswith("D,"):
        _, label, i, v = line.strip().split(",")
        data[label].append(int(v))

print("%-18s %5s %5s %4s %6s %8s %7s %6s %6s %6s %9s %9s %10s %s" % (
    "setting", "range", "VSHCT", "AVG", "n", "mean", "sd", "min", "max", "p-p",
    "mean uA", "sd uA", "sd nV", "datasheet noise-free p-p (steps)"))
for label, vals in data.items():
    md = meta[label]
    step_ua = STEP_NV[md["rng"]] * 1e-9 / R * 1e6
    mean, sd = st.fmean(vals), st.pstdev(vals)
    pp = max(vals) - min(vals)
    ds = ENOB.get((label, md["rng"]))
    ds_txt = "%.0f (ENOB %.1f)" % (2 ** (20 - ds), ds) if ds else "-"
    print("%-18s %5d %5d %4d %6d %8.3f %7.3f %6d %6d %6d %9.2f %9.2f %10.1f %s" % (
        label, md["rng"], md["ct"], md["avg"], len(vals), mean, sd, min(vals), max(vals), pp,
        mean * step_ua, sd * step_ua, sd * STEP_NV[md["rng"]], ds_txt))
print()
print("standard error of the mean (steps) = sd/sqrt(n), assuming independent samples:")
for label, vals in data.items():
    sd = st.pstdev(vals)
    n = len(vals)
    # lag-1 autocorrelation, to check the independence assumption
    m = st.fmean(vals)
    num = sum((vals[i] - m) * (vals[i + 1] - m) for i in range(n - 1))
    den = sum((v - m) ** 2 for v in vals)
    print("  %-18s sem %.3f steps; lag-1 autocorrelation %+.3f; first half mean %.3f, second half mean %.3f"
          % (label, sd / n ** 0.5, num / den, st.fmean(vals[: n // 2]), st.fmean(vals[n // 2:])))
print()
print("sample spacing vs expected conversion cycle:")
for label, md in meta.items():
    print("  %-18s expected cycle %6d us, measured %9.1f us per sample (%+.3f %% if every cycle was read)"
          % (label, md["cyc"], md["per"], (md["per"] / md["cyc"] - 1) * 100))
