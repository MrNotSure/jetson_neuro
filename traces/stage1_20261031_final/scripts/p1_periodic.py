"""Stage 1 final (31 Oct 2026), Part 1.8: periodic loads in the INA228 idle trace, as in 30 Oct's P4_M2_periodic.txt.

  .venv/bin/python p1_periodic.py BIN CHUNKS MONO0 MONO1 [OUT.txt]

1 s means over the window (Mac arrival time selects conversions, as m2_analyze.py does), linear trend removed,
then the amplitude spectrum 2|FFT|/N (amplitude of a sinusoid, mW). Same on 0.1 s means, which reach periods
below 2 s. Reports the five strongest periods. Report only: no attribution.
"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402

binf, chk, m0, m1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
c = load(binf)
ch = np.loadtxt(chk, delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
k = np.clip(np.searchsorted(ch[:, 2], (c["conv_idx"] + 1) * 16), 0, len(ch) - 1)
sel = (ch[k, 0] >= m0) & (ch[k, 0] < m1) & c["cnvrf"]
sel[0] = False
t, P = c["t"][sel], c["P"][sel] * 1e3
L = [f"window {(m1 - m0) / 1e9:.1f} s, {sel.sum()} conversions, mean {P.mean():.1f} mW"]
for w in (1.0, 0.1):
    b = np.floor((t - t[0]) / w).astype(int)
    nb = b.max()
    m = b < nb
    x = np.bincount(b[m], P[m], nb) / np.maximum(np.bincount(b[m], minlength=nb), 1)
    tt = np.arange(nb) * w
    x = x - np.polyval(np.polyfit(tt, x, 1), tt)
    A = 2 * np.abs(np.fft.rfft(x)) / len(x)
    f = np.fft.rfftfreq(len(x), w)
    i = np.argsort(A[1:])[::-1][:5] + 1
    L.append(f"{w:g} s means (n {nb}): strongest periods (s) {np.round(1 / f[i], 2).tolist()} amplitudes {np.round(A[i], 1).tolist()} mW")
    for p0 in (5.3, 2.7):
        band = (1 / f[1:] > p0 * 0.95) & (1 / f[1:] < p0 * 1.05)
        if band.any():
            j = np.argmax(np.where(band, A[1:], 0)) + 1
            L.append(f"  near {p0} s: peak {A[j]:.1f} mW at {1 / f[j]:.2f} s; median amplitude of all bins {np.median(A[1:]):.1f} mW")
txt = "\n".join(L)
print(txt)
if len(sys.argv) > 5:
    open(sys.argv[5], "w").write(txt + "\n")
