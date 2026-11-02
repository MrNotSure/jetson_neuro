"""Stage 1 Part 5: synthetic decisions, energy per decision above W = 0, two ways.

  .venv/bin/python p5_analyze.py raw/P5.bin raw/board_P5/P5.csv OUTPREFIX

Pico: INA228 conversions (CNVRF-valid) and GP16 falls (decision starts: start bit of one 0xFF on
header pin 8), one PIO clock. Falls are matched to board rows by order: a lone dummy fall, then 12
blocks separated by 5 s gaps. Each conversion represents its 1.08 ms cycle, centred 540 us before
its ALRT edge (where in the cycle VSHUNT is integrated isn't known: +-0.54 ms on the profile's time axis).

(a) Block means: mean P over [first fall + 3 s, last fall - 3 s] of each block; dE(W) = (P_W - P_0) / 100 Hz.
(b) Decision-aligned: phase of each conversion after its preceding fall, folded into [-1, 9) ms.
    Per block: aligned profile p(phase); baseline b = mean p over [5.5, 8.5] ms (the same block's quiet
    part, which cancels block-to-block drift); X = integral of (p - b) over [-1, 4.5] ms.
    dE(W) = X_W - mean(X_0): the excess over W = 0, so the marker write's own cost cancels.
CIs: Welch t over the 3 + 3 block values (t quantiles from a table).
"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228,
        12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042, 1e9: 1.96}


def t975(df):
    ks = sorted(T975)
    for a, b in zip(ks, ks[1:]):
        if a <= df <= b:
            return T975[a] + (T975[b] - T975[a]) * (df - a) / (b - a)
    return 12.706


def welch(x, y):
    x, y = np.asarray(x, float), np.asarray(y, float)
    vx, vy = x.var(ddof=1) / len(x), y.var(ddof=1) / len(y)
    d = x.mean() - y.mean()
    se = np.sqrt(vx + vy)
    df = (vx + vy) ** 2 / (vx ** 2 / (len(x) - 1) + vy ** 2 / (len(y) - 1)) if se > 0 else 1e9
    h = t975(df) * se
    return d, d - h, d + h, df


binf, csvf, outp = sys.argv[1:4]
L = []
c = load(binf)
ok = c["cnvrf"].copy()
ok[0] = False
edge = c["t"][ok]
tc = edge - 540e-6
P = c["P"][ok]
fall = c["fall"]
B = np.genfromtxt(csvf, delimiter=",", names=True, dtype=np.int64)
nblk = int(B["block"].max()) + 1
L.append(f"capture: {ok.sum()} valid conversions, {len(fall)} falls, {len(c['rise'])} rises; board rows {len(B)} in {nblk} blocks")
runs = np.split(np.arange(len(fall)), np.nonzero(np.diff(fall) > 2.0)[0] + 1)
L.append(f"fall runs (split at gaps > 2 s): {[len(r) for r in runs]}")
if len(runs[0]) == 1:
    runs = runs[1:]                         # the dummy byte
blocks = []
for b in range(nblk):
    rb = B[B["block"] == b]
    fr = fall[runs[b]]
    if len(fr) != len(rb):
        L.append(f"block {b}: {len(fr)} falls vs {len(rb)} board rows -> MISMATCH")
    w_us = int(rb["w_us"][0])
    busy = (rb["t_end_ns"] - rb["t_wr1_ns"]) / 1e3
    wr = (rb["t_wr1_ns"] - rb["t_wr0_ns"]) / 1e3
    late = (rb["t_wr0_ns"] - rb["t_sched_ns"]) / 1e3
    # (a)
    m = (tc >= fr[0] + 3) & (tc <= fr[-1] - 3)
    Pa = P[m].mean()
    # (b)
    sel = (tc >= fr[0] - 0.009) & (tc <= fr[-1] + 0.0095)
    tt, pp = tc[sel], P[sel]
    j = np.searchsorted(fr, tt, side="right") - 1
    jn = np.clip(j + 1, 0, len(fr) - 1)
    ph = np.where(j >= 0, tt - fr[np.clip(j, 0, None)], -1.0)
    ph = np.where((ph >= 0.009) & (j + 1 < len(fr)), tt - fr[jn], ph)   # fold [9, 10) ms to [-1, 0)
    good = (ph >= -0.001) & (ph < 0.009)
    ph, pp, jj = ph[good], pp[good], np.where(ph[good] < 0, jn[good], np.clip(j[good], 0, None))
    edges_ = np.arange(-1.0, 9.0001, 0.1) * 1e-3
    k = np.clip(np.digitize(ph, edges_) - 1, 0, len(edges_) - 2)
    prof = np.bincount(k, pp, len(edges_) - 1) / np.maximum(np.bincount(k, minlength=len(edges_) - 1), 1)
    ctr = (edges_[:-1] + edges_[1:]) / 2
    base = prof[(ctr >= 5.5e-3) & (ctr < 8.5e-3)].mean()
    win = (ctr >= -1e-3) & (ctr < 4.5e-3)
    X = np.sum(prof[win] - base) * 1e-4                 # J (0.1 ms bins)
    # per-decision values (for the decisions-needed estimate): sum (P - base) * 1.08 ms over the window
    inw = (ph >= -1e-3) & (ph < 4.5e-3)
    per = np.bincount(jj[inw], (pp[inw] - base) * 1.07964e-3, len(fr))
    # same with each decision's own quiet part [5.5, 8.5) ms as its baseline (removes slow board activity)
    inb = (ph >= 5.5e-3) & (ph < 8.5e-3)
    nw_ = np.bincount(jj[inw], minlength=len(fr))
    sw_ = np.bincount(jj[inw], pp[inw], len(fr))
    nb_ = np.bincount(jj[inb], minlength=len(fr))
    sb_ = np.bincount(jj[inb], pp[inb], len(fr))
    okb = nb_ > 0
    per_local = ((sw_ - sb_ / np.maximum(nb_, 1) * nw_) * 1.07964e-3)[okb]
    blocks.append({"b": b, "w": w_us, "n": len(fr), "Pa": Pa, "X": X, "base": base, "prof": prof, "per": per,
                   "per_local": per_local,
                   "busy_p50": np.median(busy), "busy_p99": np.percentile(busy, 99), "wr_p50": np.median(wr),
                   "late_p99": np.percentile(late, 99), "late_max": late.max()})
    L.append(f"block {b:2d} W {w_us:4d} us: decisions {len(fr)}, block mean {Pa * 1e3:.1f} mW, baseline {base * 1e3:.1f} mW, "
             f"window excess X {X * 1e6:7.2f} uJ; busy p50/p99 {np.median(busy):.1f}/{np.percentile(busy, 99):.1f} us, "
             f"write p50 {np.median(wr):.1f} us, lateness p99/max {np.percentile(late, 99):.1f}/{late.max():.1f} us")
ctr = (np.arange(-1.0, 9.0, 0.1) + 0.05) * 1e-3
Ws = sorted(set(x["w"] for x in blocks))
by = {w: [x for x in blocks if x["w"] == w] for w in Ws}
L.append("")
L.append("| W | (a) block means: dE per decision, 95 % CI | (b) decision-aligned: dE per decision, 95 % CI | P_block mean |")
L.append("|---|---|---|---|")
res = {}
for w in Ws:
    Pa = [x["Pa"] for x in by[w]]
    Xb = [x["X"] for x in by[w]]
    if w == 0:
        L.append(f"| 0 (reference) | – | X_0 = {np.mean(Xb) * 1e6:.2f} uJ (marker write + its window; sd {np.std(Xb, ddof=1) * 1e6:.2f}) | {np.mean(Pa) * 1e3:.1f} mW |")
        continue
    da = welch(Pa, [x["Pa"] for x in by[0]])
    db = welch(Xb, [x["X"] for x in by[0]])
    res[w] = (da, db)
    L.append(f"| {w / 1000:.1f} ms | {da[0] / 100 * 1e6:+.1f} uJ [{da[1] / 100 * 1e6:+.1f}, {da[2] / 100 * 1e6:+.1f}] (df {da[3]:.1f}) | "
             f"{db[0] * 1e6:+.2f} uJ [{db[1] * 1e6:+.2f}, {db[2] * 1e6:+.2f}] (df {db[3]:.1f}) | {np.mean(Pa) * 1e3:.1f} mW |")
# active power from the slope
for lab, idx, scale in (("(a)", 0, 1 / 100), ("(b)", 1, 1.0)):
    xs = np.array([w * 1e-6 for w in Ws])
    ys = np.array([0.0] + [res[w][idx][0] * scale for w in Ws if w != 0])
    A = np.vstack([np.ones_like(xs), xs]).T
    coef, *_ = np.linalg.lstsq(A, ys, rcond=None)
    L.append(f"slope {lab}: dE = {coef[0] * 1e6:+.2f} uJ + {coef[1]:.3f} W x W  -> active power above idle ~ {coef[1] * 1e3:.0f} mW")
# decisions needed at W = 0.1 ms for +-5 % (method b, per-decision values, treated as independent: optimistic)
if 100 in res:
    per0 = np.concatenate([x["per"] for x in by[0]])
    per1 = np.concatenate([x["per"] for x in by[100]])
    d = res[100][1][0]
    s2 = per0.var(ddof=1) + per1.var(ddof=1)
    n = (1.96 * np.sqrt(s2) / (0.05 * abs(d))) ** 2 if d != 0 else np.inf
    L.append(f"per-decision window excess: sd {per0.std(ddof=1) * 1e6:.1f} uJ (W 0), {per1.std(ddof=1) * 1e6:.1f} uJ (W 0.1 ms); "
             f"mean {per0.mean() * 1e6:.2f} / {per1.mean() * 1e6:.2f} uJ")
    L.append(f"  with the block baseline (slow activity left in): N = {n:.3g} per condition ({n / 100 / 60:.1f} min) if decisions were independent")
    q0 = np.concatenate([x["per_local"] for x in by[0]])
    q1 = np.concatenate([x["per_local"] for x in by[100]])
    dl = q1.mean() - q0.mean()
    nl = (1.96 * np.sqrt(q0.var(ddof=1) + q1.var(ddof=1)) / (0.05 * abs(dl))) ** 2
    L.append(f"  with each decision's own baseline: sd {q0.std(ddof=1) * 1e6:.1f} / {q1.std(ddof=1) * 1e6:.1f} uJ, dE {dl * 1e6:.2f} uJ, "
             f"N = {nl:.3g} per condition ({nl / 100 / 60:.1f} min at 100 Hz), decisions treated as independent")
    s_blk = np.sqrt(np.var([x["X"] for x in by[0]], ddof=1) / 3 + np.var([x["X"] for x in by[100]], ddof=1) / 3)
    nb = 18000 * (s_blk / (0.05 * abs(d) / 1.96)) ** 2
    L.append(f"  from the block spread (3 + 3 blocks of 6000): SE of dE {s_blk * 1e6:.2f} uJ -> N = {nb:.3g} per condition "
             f"({nb / 100 / 60:.1f} min); block sds rest on 2 df each, so this is uncertain by a factor of several")
txt = "\n".join(L)
print(txt)
open(outp + ".txt", "w").write(txt + "\n")
fig, ax = plt.subplots(figsize=(10, 5.5))
for i, w in enumerate(Ws):
    pr = np.mean([x["prof"] - x["base"] for x in by[w]], axis=0)
    ax.plot(ctr * 1e3, pr * 1e3, color=f"C{i}", label=f"W = {w / 1000:g} ms")
    if w:
        ax.axvspan(0, w / 1000, color=f"C{i}", alpha=0.08)
ax.axhline(0, color="0.5", lw=0.5)
ax.axvspan(-1, 4.5, color="0.9", alpha=0.3, zorder=-1)
ax.set_xlabel("time after the decision's marker edge (start bit on pin 8), ms  (conversion centres; +-0.54 ms)")
ax.set_ylabel("power above the block's quiet baseline, mW")
ax.set_title("Part 5: decision-aligned power profiles, 3 blocks x 6000 decisions per W (INA228, 19 V input)")
ax.legend()
fig.tight_layout()
fig.savefig(outp + "_profiles.png", dpi=120)
