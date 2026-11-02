"""Stage 1 run: quick integrity summary of one capture.  .venv/bin/python capcheck.py raw/NAME.bin"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load, accum_series, COUNT_S  # noqa: E402


def main():
    c = load(sys.argv[1])
    t = c["t"][1:]                      # record 0 is the CNVR-enable edge
    iv = np.diff(t) * 1e6
    T = np.median(iv)
    missed = int(np.sum(np.round(iv[iv > 1.5 * T] / T) - 1))
    steps = int(np.sum((iv - T > 8.5) & (iv - T < 11.5)))
    irregular = int(np.sum((np.abs(iv - T) > 1.0) & (np.abs(iv - T - 10) > 1.5) & (iv < 1.5 * T)))
    print(f"records {c['n_records']}, bad framing {c['bad_framing']}, trailer {c['trailer']}")
    print(f"conversions {len(c['t'])}, seq16 gaps {c['seq_gaps']}, FIFO levels {sorted(set(c['level'].tolist()))}")
    sp = np.nonzero(~c["cnvrf"][1:])[0]
    print(f"records without CNVRF (spurious ALRT edges): {len(sp)} at t = {np.round(c['t'][1:][sp], 4).tolist()[:10]} s")
    pr = c["rise"]
    if len(pr) and len(c["fall"]):
        print(f"GP16 rises {len(pr)}, falls {len(c['fall'])}")
    print(f"span {t[-1] - t[0]:.3f} s, interval median {T:.3f} us, min {iv.min():.3f}, max {iv.max():.3f}, "
          f"missed {missed}, +10us steps {steps}, irregular {irregular}")
    wraps = int((t[-1] / COUNT_S) // (1 << 32))
    print(f"PIO wraps crossed: {wraps} (one every {(1 << 32) * COUNT_S:.1f} s)")
    for k in range(1, wraps + 1):
        tw = k * (1 << 32) * COUNT_S
        j = np.searchsorted(t, tw)
        if 2 <= j < len(t) - 2:
            print(f"  around wrap {k} at {tw:.3f} s: intervals {np.round(iv[j - 3:j + 2], 3).tolist()} us")
    I, V, P = c["I"][1:], c["V"][1:], c["P"][1:]
    print(f"I mean {I.mean() * 1e3:.3f} mA sd {I.std() * 1e3:.3f} mA, min {I.min() * 1e3:.2f}, max {I.max() * 1e3:.2f}; "
          f"V mean {V.mean():.4f} V sd {V.std() * 1e3:.2f} mV; P mean {P.mean() * 1e3:.1f} mW")
    for nm in ("rise", "fall"):
        print(f"{nm}: {len(c[nm])} edges, seq gaps {c[nm + '_seq_gaps']}")
    E, Q = accum_series(c)
    if len(E) > 2:
        print(f"ENERGY samples {len(E)}: {E[0, 1]:.4f} -> {E[-1, 1]:.4f} J over {E[-1, 0] - E[0, 0]:.1f} s")
    if len(Q) > 2:
        print(f"CHARGE samples {len(Q)}: {Q[0, 1]:.6f} -> {Q[-1, 1]:.6f} C over {Q[-1, 0] - Q[0, 0]:.1f} s")
    for s in c["sync"]:
        print(f"sync phase {s['phase']}: SM0-SM1 {s['xa'] - s['xr']} counts, SM0-SM2 {s['xa'] - s['xf']} counts, "
              f"SM0 moved {s['a1_minus_a2']} counts during the spin")


if __name__ == "__main__":
    main()
