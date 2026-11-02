"""Stage 1 fix session: INA228 mean power between two Mac monotonic times (e.g. from marks.csv).

  .venv/bin/python winmean.py raw/F2.bin raw/F2.chunks.csv MONO_START_NS MONO_END_NS

Each conversion gets the Mac arrival time of the read that delivered it (arrival lags the
conversion by a few ms, irrelevant for windows of seconds). Spurious ALRT records (CNVRF clear)
are dropped. Works on a capture that is still being written (uses the complete records so far).
"""
import sys
import numpy as np
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from capdec import load  # noqa: E402

binf, chk, m0, m1 = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
c = load(binf)
ch = np.loadtxt(chk, delimiter=",", skiprows=1, dtype=np.int64).reshape(-1, 3)
endb = (c["conv_idx"] + 1) * 16
k = np.clip(np.searchsorted(ch[:, 2], endb), 0, len(ch) - 1)
arr = ch[k, 0]
sel = (arr >= m0) & (arr < m1) & c["cnvrf"]
sel[0] = False
P, V, I = c["P"][sel], c["V"][sel], c["I"][sel]
t = c["t"][sel]
print(f"window {(m1 - m0) / 1e9:.1f} s: {sel.sum()} conversions over {t[-1] - t[0]:.2f} s (PIO), "
      f"P mean {P.mean() * 1e3:.1f} mW, I {I.mean() * 1e3:.2f} mA, V {V.mean():.4f} V, sd(P per conv) {P.std() * 1e3:.1f} mW")
