"""Stage 1 Part 4 (M2): idle power, INA228 (board input, 19 V) against INA3221 VDD_IN, same window.

  .venv/bin/python m2_analyze.py raw/P4_m2.bin raw/P4_m2.chunks.csv raw/board/P4_ina3221_10hz.csv MONO0 MONO1 UNIX0 UNIX1 OUTPREFIX

Window: Mac monotonic MONO0..MONO1 (INA228, by arrival time of each record) and Mac unix UNIX0..UNIX1
(INA3221, board realtime = start_realtime_ns + (t0_ns - start_mono_ns); board clock within ~0.15 s
of the Mac, synced at the start of the session). Spurious ALRT records (CNVRF clear) are dropped.
Noise table: sd of non-overlapping block means over the window. Drift: OLS slope (samples treated
as independent, so its standard error is optimistic).
"""
import json
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

binf, chk, csvf = sys.argv[1:4]
m0, m1 = int(sys.argv[4]), int(sys.argv[5])
u0, u1 = float(sys.argv[6]), float(sys.argv[7])
outp = sys.argv[8]
L = []


def blocks(t, x, w):
    b = np.floor((t - t[0]) / w).astype(int)
    nb = b.max()                      # drop the last, partial block
    m = b < nb
    n = np.bincount(b[m], minlength=nb)
    s = np.bincount(b[m], x[m], minlength=nb)
    return s[n > 0] / n[n > 0]


def ols(t, x):
    A = np.vstack([np.ones_like(t), t]).T
    coef, *_ = np.linalg.lstsq(A, x, rcond=None)
    r = x - A @ coef
    se = np.sqrt(np.sum(r ** 2) / (len(x) - 2) / np.sum((t - t.mean()) ** 2))
    return coef[1], se


# INA228
c = load(binf)
ch = np.loadtxt(chk, delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
k = np.clip(np.searchsorted(ch[:, 2], (c["conv_idx"] + 1) * 16), 0, len(ch) - 1)
sel = (ch[k, 0] >= m0) & (ch[k, 0] < m1) & c["cnvrf"]
sel[0] = False
t = c["t"][sel]
P, V, I = c["P"][sel], c["V"][sel], c["I"][sel]
iv = np.diff(c["t"][1:][c["cnvrf"][1:]]) * 1e6
T = np.median(iv)
L.append(f"INA228: {sel.sum()} conversions over {t[-1] - t[0]:.2f} s (PIO); capture-wide missed "
         f"{int(np.sum(np.round(iv[iv > 1.5 * T] / T) - 1))}, spurious ALRT {int((~c['cnvrf'][1:]).sum())}, "
         f"GP16 rises/falls {len(c['rise'])}/{len(c['fall'])}")
L.append(f"INA228 board input: P {P.mean() * 1e3:.1f} mW, I {I.mean() * 1e3:.2f} mA, V {V.mean():.4f} V (sd {V.std() * 1e3:.1f} mV)")
row228 = {"per conversion (1.08 ms)": P.std() * 1e3}
for w, lab in ((0.01, "10 ms"), (0.1, "100 ms"), (1.0, "1 s"), (10.0, "10 s")):
    bm = blocks(t, P, w)
    row228[f"{lab} means"] = bm.std(ddof=1) * 1e3
    row228[f"n {lab}"] = len(bm)
s228, se228 = ols(t - t[0], P)
L.append(f"INA228 drift {s228 * 60e3:+.2f} mW/min (se {se228 * 60e3:.2f})")
# INA3221
meta = json.load(open(csvf + ".meta.json"))
D = np.genfromtxt(csvf, delimiter=",", names=True, dtype=np.int64)
tb = (D["t0_ns"] + D["t1_ns"]) / 2
unix = (meta["start_realtime_ns"] + (tb - meta["start_mono_ns"])) / 1e9
m = (unix >= u0) & (unix < u1)
ts = (tb[m] - tb[m][0]) / 1e9
pin = D["in1"][m] * D["curr1"][m] / 1000.0
pcg = D["in2"][m] * D["curr2"][m] / 1000.0
pso = D["in3"][m] * D["curr3"][m] / 1000.0
L.append(f"INA3221: {m.sum()} samples over {ts[-1]:.1f} s at {meta['achieved_hz']:.3f} Hz, sampler CPU "
         f"{meta['cpu_fraction_of_one_core'] * 100:.2f} % of one core, hwmon {meta['hwmon_resolved']}")
rows = {}
for name, x in (("VDD_IN", pin), ("VDD_CPU_GPU_CV", pcg), ("VDD_SOC", pso)):
    r = {"per sample (100 ms)": x.std(ddof=1)}
    for w, lab in ((1.0, "1 s"), (10.0, "10 s")):
        bm = blocks(ts, x, w)
        r[f"{lab} means"] = bm.std(ddof=1)
    sl, se = ols(ts, x)
    r["mean"] = x.mean()
    r["drift mW/min"] = (sl * 60, se * 60)
    r["codes"] = len(np.unique(x))
    rows[name] = r
    L.append(f"{name}: mean {x.mean():.1f} mW, sd/sample {r['per sample (100 ms)']:.1f}, sd 1 s {r['1 s means']:.1f}, "
             f"sd 10 s {r['10 s means']:.1f} mW, drift {sl * 60:+.2f} mW/min (se {se * 60:.2f}), distinct values {r['codes']}")
L.append("")
L.append("| | Mean (mW) | sd per sample | sd of 10 ms means | sd of 100 ms means | sd of 1 s means | sd of 10 s means |")
L.append("|---|---|---|---|---|---|---|")
L.append(f"| INA228, 19 V input | {P.mean() * 1e3:.1f} | {row228['per conversion (1.08 ms)']:.1f} (1.08 ms) | "
         f"{row228['10 ms means']:.1f} | {row228['100 ms means']:.1f} | {row228['1 s means']:.1f} | {row228['10 s means']:.1f} |")
r = rows["VDD_IN"]
L.append(f"| INA3221 VDD_IN, 5 V | {r['mean']:.1f} | {r['per sample (100 ms)']:.1f} (100 ms) | – | "
         f"{r['per sample (100 ms)']:.1f} | {r['1 s means']:.1f} | {r['10 s means']:.1f} |")
L.append("")
L.append(f"INA228 - VDD_IN = {P.mean() * 1e3 - r['mean']:.1f} mW; VDD_IN / INA228 = {r['mean'] / (P.mean() * 1e3):.4f}")
L.append(f"block counts INA228: 10 ms {row228['n 10 ms']}, 1 s {row228['n 1 s']}, 10 s {row228['n 10 s']}")
txt = "\n".join(L)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")
fig, ax = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
t1 = np.arange(len(blocks(t, P, 1.0))) + 0.5
ax[0].plot(t - t[0], P, lw=0.2, color="0.8", label="each conversion")
ax[0].plot(t1, blocks(t, P, 1.0), color="C3", label="1 s means")
ax[0].set_ylabel("INA228, W")
ax[0].legend(fontsize=8, loc="upper right")
ax[0].set_title("Part 4, idle: board input (INA228) and VDD_IN (INA3221), same window")
ax[1].plot(ts, pin / 1e3, lw=0.6, color="C0", label="VDD_IN, 10 Hz samples")
ax[1].plot(np.arange(len(blocks(ts, pin, 1.0))) + 0.5, blocks(ts, pin, 1.0) / 1e3, color="C3", label="1 s means")
ax[1].set_ylabel("VDD_IN, W")
ax[1].set_xlabel("time in window, s")
ax[1].legend(fontsize=8, loc="upper right")
fig.tight_layout()
fig.savefig(outp + ".png", dpi=120)
