"""Step 7a analysis: ALRT edge sequences per experiment. Standard library only.

  python3.12 alrt_analyze.py <07a_alrt.txt> [experiment_prefix] [n_events]
"""
import statistics as st
import sys
from collections import defaultdict

NS = 24.0  # ns per PIO count (3 cycles at 125 MHz)
edges = defaultdict(list)
acts = defaultdict(list)
syncs = {}
for line in open(sys.argv[1]):
    if not line.startswith("D,"):
        continue
    p = line.strip().split(",")
    if p[2] == "edge":
        edges[p[1]].append(int(p[4]))
    elif p[2] == "act":
        acts[p[1]].append((int(p[4]), int(p[5])))
    elif p[2] == "sync":
        syncs[p[1]] = (float(p[3]), int(p[4]), float(p[5]), int(p[6]))

want = sys.argv[2] if len(sys.argv) > 2 else ""
nshow = int(sys.argv[3]) if len(sys.argv) > 3 else 30
for name, e in edges.items():
    if not name.startswith(want):
        continue
    ta, xa, tb, xb = syncs[name]
    t = [(xa - x) * NS / 1000 for x in e]        # us since the start sync, PIO clock
    falls, rises = t[0::2], t[1::2]
    lows = [r - f for f, r in zip(falls, rises)]
    highs = [f - r for r, f in zip(rises, falls[1:])]
    ivals = [b - a for a, b in zip(falls, falls[1:])]
    a = acts.get(name, [])
    dur = [b - a_ for a_, b in a]
    # Map CPU action times into the PIO time base with the start sync (+-half sync window).
    a_rel = [(a_ - ta, b - ta) for a_, b in a]
    print(f"== {name}: {len(e)} edges, {len(a)} actions")
    if lows:
        print(f"   low widths us: median {st.median(lows):.2f}, min {min(lows):.2f}, max {max(lows):.2f}; "
              f"<1 us: {sum(1 for x in lows if x < 1)}")
    if ivals:
        print(f"   fall intervals us: median {st.median(ivals):.2f}, min {min(ivals):.2f}, max {max(ivals):.2f}")
    if dur:
        print(f"   action duration (CPU ticks) us: median {st.median(dur):.0f}, min {min(dur)}, max {max(dur)}")
    print("   first events (us since start sync; f=fall r=rise; A=action start..end in CPU time):")
    ev = [(x, "f" if i % 2 == 0 else "r") for i, x in enumerate(t)]
    ev += [(s, "A[") for s, _ in a_rel] + [(b, "]A") for _, b in a_rel]
    ev.sort()
    t0 = falls[0] if falls else 0
    print("   " + "  ".join(f"{k}{x - t0:.1f}" for x, k in ev[:nshow]))
