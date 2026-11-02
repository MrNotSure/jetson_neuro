"""Stage 1 run: boot trace from capture P2_boot. Power assumes 19.0 V (VBUS jumper open, VBUS reads ~0).

  .venv/bin/python boot_analyze.py raw/P2_boot.bin raw/P2_boot.chunks.csv raw/P2_boot_events.txt OUT_PREFIX
"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load, accum_series  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

V_ASSUMED = 19.0
binf, chunks, events, outp = sys.argv[1:5]
c = load(binf)
t, I, V = c["t"][1:], c["I"][1:], c["V"][1:]
# Mac unix time of each conversion: map by bytes received (records arrive <= ~10 ms after the edge)
ch = np.loadtxt(chunks, delimiter=",", skiprows=1)
rec_end_bytes = (c["conv_idx"][1:] + 1) * 16
k = np.searchsorted(ch[:, 2], rec_end_bytes)
k = np.clip(k, 0, len(ch) - 1)
mac_unix = ch[k, 1] / 1e9
# fit unix = a + b*t on the earliest arrivals (lower envelope) per 1 s bin
bins = np.floor(t).astype(int)
sel = [np.argmin(mac_unix[bins == b] - t[bins == b]) + np.nonzero(bins == b)[0][0] for b in np.unique(bins)]
A = np.vstack([np.ones(len(sel)), t[sel]]).T
coef, *_ = np.linalg.lstsq(A, mac_unix[sel], rcond=None)
unix = coef[0] + coef[1] * t
ev = {}
for line in open(events):
    p = line.rstrip("\n").split("\t")
    for key in ("POWER-UP", "USB:", "TTY:", "SSH:"):
        if p[2].startswith(key) and key not in ev:
            ev[key] = float(p[0])
on = np.nonzero(I > 0.05)[0]
i_on = on[0]
t_on = t[i_on]
rel = t - t_on
P = I * V_ASSUMED
lines = []
lines.append(f"conversions {len(t)}, span {t[-1] - t[0]:.1f} s, missed check: max interval {np.diff(t).max() * 1e6:.1f} us, "
             f"bad framing {c['bad_framing']}, seq gaps {c['seq_gaps']}")
lines.append(f"Mac clock fit: unix = {coef[0]:.3f} + {coef[1]:.9f} * t_pio  (rate vs Mac {(coef[1] - 1) * 1e6:+.1f} ppm)")
lines.append(f"current first > 50 mA at t_pio {t_on:.4f} s = unix {unix[i_on]:.3f} "
             f"({np.datetime64(int(unix[i_on] * 1000), 'ms')} UTC)")
pre = I[:max(i_on - 1000, 1)]
lines.append(f"before power-up: I mean {pre.mean() * 1e3:.3f} mA, sd {pre.std() * 1e3:.3f} mA (n {len(pre)}); VBUS mean {V[:i_on].mean() * 1e3:.2f} mV")
for key in ("USB:", "TTY:", "SSH:"):
    if key in ev:
        lines.append(f"{key} seen at +{ev[key] - unix[i_on]:.1f} s after power-up (watcher polls every ~0.5-1 s)")
ip = np.argmax(I)
lines.append(f"peak single conversion: {I[ip]:.4f} A at +{rel[ip]:.3f} s ({I[ip] * V_ASSUMED:.2f} W at 19 V)")
# 10 ms and 1 s means
def means(x, tt, w):
    b = np.floor((tt - tt[0]) / w).astype(int)
    n = np.bincount(b)
    m = np.bincount(b, x) / np.maximum(n, 1)
    return (np.arange(len(m)) + 0.5) * w + tt[0], m, n
t10, m10, n10 = means(I[i_on:], rel[i_on:], 0.010)
t1, m1, n1 = means(I[i_on:], rel[i_on:], 1.0)
j = np.argmax(m10)
lines.append(f"peak 10 ms mean: {m10[j]:.4f} A at +{t10[j]:.2f} s; peak 1 s mean: {m1.max():.4f} A at +{t1[np.argmax(m1)]:.1f} s")
lines.append(f"any 10 ms mean above 2.5 A: {bool((m10 > 2.5).any())}; samples above 2.5 A: {int((I > 2.5).sum())}")
lines.append(f"inrush: first 50 ms after power-up, max conversion {I[i_on:i_on + 50].max():.4f} A; "
             f"first 10 conversions {np.round(I[i_on - 2:i_on + 10], 4).tolist()} A")
for a, b in ((0, 10), (10, 20), (20, 30), (30, 40), (40, 60), (60, 90), (90, 120), (120, 150), (150, 180), (180, 1e9)):
    m = (rel >= a) & (rel < b)
    if m.any():
        lines.append(f"  +{a:>4}..{min(b, rel[-1]):6.1f} s: I mean {I[m].mean() * 1e3:7.1f} mA, sd {I[m].std() * 1e3:6.1f}, "
                     f"max {I[m].max() * 1e3:7.1f}; P(19 V) {I[m].mean() * V_ASSUMED:6.3f} W")
# time to idle: first time after which the 10 s rolling mean stays within 5 % of the final 30 s mean
fin = I[rel > rel[-1] - 30].mean()
roll = np.array([I[(rel >= s) & (rel < s + 10)].mean() for s in np.arange(0, rel[-1] - 10, 1.0)])
ok = np.abs(roll - fin) < 0.05 * fin
first = None
for s in range(len(ok)):
    if ok[s:].all():
        first = s
        break
lines.append(f"final 30 s mean {fin * 1e3:.1f} mA ({fin * V_ASSUMED:.3f} W at 19 V); 10 s means stay within 5 % from +{first} s")
lines.append(f"VBUS during the whole capture: mean {V.mean() * 1e3:.2f} mV, max {V.max() * 1e3:.2f} mV (jumper open)")
E, Q = accum_series(c)
if len(Q) > 2:
    qd = Q[-1, 1] - Q[0, 1]
    m = (t >= Q[0, 0]) & (t <= Q[-1, 0])
    lines.append(f"CHARGE {Q[0, 0]:.1f}..{Q[-1, 0]:.1f} s: {qd:.4f} C -> mean {qd / (Q[-1, 0] - Q[0, 0]) * 1e3:.2f} mA; "
                 f"sampled CURRENT mean over the same span {I[m].mean() * 1e3:.2f} mA (ratio {qd / (Q[-1, 0] - Q[0, 0]) / I[m].mean():.4f})")
if len(E) > 2:
    lines.append(f"ENERGY register {E[0, 1]:.4f} -> {E[-1, 1]:.4f} J (POWER uses VBUS ~0, so ~0 expected)")
txt = "\n".join(lines)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")
fig, ax = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True)
ax[0].plot(rel, I, lw=0.3, color="0.7", label="each conversion (1.08 ms)")
ax[0].plot(t10, m10, lw=0.6, color="C0", label="10 ms means")
ax[0].plot(t1, m1, lw=1.5, color="C3", label="1 s means")
for key, col in (("USB:", "C2"), ("SSH:", "C1")):
    if key in ev:
        x = ev[key] - unix[i_on]
        for a_ in ax:
            a_.axvline(x, color=col, ls="--", lw=1)
        ax[0].text(x, ax[0].get_ylim()[1] * 0.95 if False else 0.95, " " + key.rstrip(":"), color=col, va="top")
ax[0].set_ylabel("current, A")
ax[0].legend(loc="upper right", fontsize=8)
ax[0].set_title("Jetson boot through the INA228, 29 Oct 2026 (19 V input, high side)")
ax[1].plot(t1, m1 * V_ASSUMED, color="C3")
ax[1].set_ylabel("power at 19 V assumed, W")
ax[1].set_xlabel("time since power-up, s")
ax[0].set_xlim(-5, rel[-1])
fig.tight_layout()
fig.savefig(outp + ".png", dpi=120)
