"""Step 8 analysis: CHARGE slope vs mean CURRENT/VSHUNT, ENERGY, flags. Standard library only.

  python3.12 accum_analyze.py <08_accum.txt>
"""
import statistics as st
import sys

CURRENT_LSB = 10.9 / (1 << 19)       # A
STEP_UA = 312.5e-9 / 0.015 * 1e6     # VSHUNT step in uA (ADCRANGE 0)
snaps, means = [], []
for line in open(sys.argv[1]):
    p = line.strip().split(",")
    if p[0] == "D" and p[1].startswith("t") and p[1][1:].isdigit():
        snaps.append((int(p[1][1:]), int(p[2]), int(p[3]), int(p[4]), int(p[5], 16), int(p[6]), int(p[7]), int(p[8]), int(p[9])))
    elif p[0] == "M":
        means.append((int(p[1]), int(p[2]), int(p[3]), int(p[4])))

t = [s[1] / 1e6 for s in snaps]
q = [s[3] for s in snaps]
e = [s[2] for s in snaps]
flags = sorted(set(s[4] for s in snaps))
mono = all(b <= a for a, b in zip(q, q[1:]))
dq = [b - a for a, b in zip(q, q[1:])]
mt, mq = st.fmean(t), st.fmean(q)
slope = sum((x - mt) * (y - mq) for x, y in zip(t, q)) / sum((x - mt) ** 2 for x in t)   # LSB per s
res = [y - (mq + slope * (x - mt)) for x, y in zip(t, q)]
i_charge = slope * CURRENT_LSB * 1e6          # uA
n = sum(m[1] for m in means)
i_current = sum(m[2] for m in means) / n * CURRENT_LSB * 1e6
i_vshunt = sum(m[3] for m in means) / n * STEP_UA
print(f"snapshots {len(snaps)} over {t[-1] - t[0]:.3f} s (Pico ticks_us)")
print(f"DIAG_ALRT values seen: {['0x%04X' % f for f in flags]}  (bit 11 ENERGYOF, 10 CHARGEOF, 9 MATHOF, 1 CNVRF, 0 MEMSTAT)")
print(f"ENERGY raw: min {min(e)}, max {max(e)}")
print(f"CHARGE raw: start {q[0]}, end {q[-1]}, change per second min {min(dq)} max {max(dq)}, monotonic: {mono}")
print(f"CHARGE slope {slope:.4f} LSB/s (fit residual sd {st.pstdev(res):.2f} LSB) -> {i_charge:.2f} uA")
print(f"mean CURRENT register over the same time (n={n}): {i_current:.2f} uA")
print(f"mean VSHUNT over the same time: {i_vshunt:.2f} uA ({sum(m[3] for m in means) / n:.3f} steps)")
print(f"CHARGE-derived / CURRENT-derived = {i_charge / i_current:.4f}")
print(f"POWER raw values: {sorted(set(s[5] for s in snaps))}; VBUS raw values: {sorted(set(s[6] for s in snaps))}")
print(f"DIETEMP: {min(s[8] for s in snaps) * 7.8125e-3:.2f}..{max(s[8] for s in snaps) * 7.8125e-3:.2f} C")
