"""Stage 1 fix session: marker test M3 on pin 8 (UART1 TX, one 0xFF byte per event).

  .venv/bin/python m3_analyze.py raw/F3.bin raw/board/m3_100hz.csv raw/board/m3_1khz.csv

Pico side: GP16 falls (start bit) and rises (end of start bit) from capture F3, on the PIO clock.
Runs are separated by the 1 s idle before and after each run (gaps > 0.5 s). Edges are matched to
the Jetson's writes by order; a linear fit maps Jetson CLOCK_MONOTONIC to the Pico clock, and the
residuals give the jitter of write-to-edge latency (its constant part isn't observable this way).
"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402


def q(x, ps=(0.5, 0.99, 1.0)):
    x = np.sort(np.asarray(x))
    return [float(x[min(len(x) - 1, int(p * (len(x) - 1)))]) for p in ps]


def runs_of(t):
    if len(t) == 0:
        return []
    cut = np.nonzero(np.diff(t) > 0.5)[0] + 1
    return np.split(t, cut)


c = load(sys.argv[1])
fall, rise = c["fall"], c["rise"]
print(f"capture: {len(c['t'])} conversions, falls {len(fall)}, rises {len(rise)}, "
      f"seq gaps rise/fall {c['rise_seq_gaps']}/{c['fall_seq_gaps']}, bad framing {c['bad_framing']}")
# conversions while markers ran: missed?
tt = c["t"][1:][c["cnvrf"][1:]]
iv = np.diff(tt) * 1e6
T = np.median(iv)
print(f"conversions: missed {int(np.sum(np.round(iv[iv > 1.5 * T] / T) - 1))}, spurious ALRT {int((~c['cnvrf'][1:]).sum())}, "
      f"FIFO levels {sorted(set(c['level'].tolist()))}, marker FIFO levels rise {sorted(set(c.get('rise_level', np.array([])).tolist()))} "
      f"fall {sorted(set(c.get('fall_level', np.array([])).tolist()))}")
# pair each fall with the next rise
j = np.searchsorted(rise, fall, side="right")
okp = j < len(rise)
width = (rise[j[okp]] - fall[okp]) * 1e6
print(f"pulse width (fall -> next rise): n {len(width)}, p0 {width.min():.3f}, p50 {np.median(width):.3f}, max {width.max():.3f} us "
      f"(1/115200 = 8.681 us); widths < 1 us: {int((width < 1).sum())}; first edge overall is a "
      f"{'fall' if (len(fall) and (not len(rise) or fall[0] < rise[0])) else 'rise'}")
fr = runs_of(fall)
rr = runs_of(rise)
print(f"fall runs: {[len(r) for r in fr]}; rise runs: {[len(r) for r in rr]}")
for path, label in ((sys.argv[2], "100 Hz"), (sys.argv[3], "1 kHz")):
    J = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.int64)
    n = len(J)
    cand = [r for r in fr if abs(len(r) - n) <= max(5, n // 100)]
    if not cand:
        print(f"{label}: no matching run of falls for {n} writes"); continue
    pf = cand[0]
    cr = [r for r in rr if abs(len(r) - n) <= max(5, n // 100)]
    print(f"\n== {label}: writes {n}, falls captured {len(pf)}, rises captured {len(cr[0]) if cr else 0}")
    jb = (J[:, 2] - J[0, 2]) / 1e9                  # write start, Jetson clock, s
    wd = (J[:, 3] - J[:, 2]) / 1e3                  # write() duration, us
    late = (J[:, 2] - J[:, 1]) / 1e3
    period = (J[1, 1] - J[0, 1]) / 1e9
    pi = np.diff(pf) * 1e6
    ji = np.diff(jb) * 1e6
    print(f"Pico fall intervals (us): p50/p99/max {np.round(q(pi), 3)}, min {pi.min():.3f}; nominal {period * 1e6:.0f}")
    print(f"Jetson write-start intervals (us): p50/p99/max {np.round(q(ji), 3)}, min {ji.min():.3f}")
    print(f"|interval - nominal| p50/p99/max: Pico {np.round(q(np.abs(pi - period * 1e6)), 3)}, "
          f"Jetson {np.round(q(np.abs(ji - period * 1e6)), 3)} us")
    print(f"write() duration (us) p50/p99/max {np.round(q(wd), 3)}; schedule lateness p50/p99/max {np.round(q(late), 3)}")
    if len(pf) == n:
        A = np.vstack([np.ones(n), jb]).T
        coef, *_ = np.linalg.lstsq(A, pf, rcond=None)
        res = (pf - A @ coef) * 1e6
        print(f"fit Pico = a + b * Jetson: b - 1 = {(coef[1] - 1) * 1e6:+.2f} ppm; residual (write start -> edge jitter) "
              f"sd {res.std():.3f} us, p1 {np.percentile(res, 1):.3f}, p50 {np.median(res):.3f}, p99 {np.percentile(res, 99):.3f}, "
              f"min {res.min():.3f}, max {res.max():.3f} us")
        # same against write end
        ja = (J[:, 3] - J[0, 2]) / 1e9
        coef2, *_ = np.linalg.lstsq(np.vstack([np.ones(n), ja]).T, pf, rcond=None)
        res2 = (pf - np.vstack([np.ones(n), ja]).T @ coef2) * 1e6
        print(f"  against write end: residual sd {res2.std():.3f} us, p1 {np.percentile(res2, 1):.3f}, p99 {np.percentile(res2, 99):.3f}")
        big = np.argsort(np.abs(res))[-3:]
        print(f"  largest residuals at events {big.tolist()}: {np.round(res[big], 2).tolist()} us; write() there {np.round(wd[big], 1).tolist()} us")
