"""T6, 2 Nov 2026: measure board - Mac and print the relative step for `sudo date -u -s '<step> seconds'`.

  STEP=$(.venv/bin/python clocksync.py) && ssh jetson-usb "sudo date -u -s '$STEP seconds'"

Offset as clockcheck.py: midpoint of the shortest of 5 ssh round trips. Prints the step (-offset, with sign)
on stdout and exits 0 only if |offset| > 0.1 s, so the sudo runs only when the pre-agreed rule allows it.
GNU date evaluates a relative time when it runs, so the step is right however long ssh and sudo take
(an absolute `date -s @T` left the board 0.77 s behind at 11:35, from ssh + sudo latency).
The sudo itself stays in the visible ssh command, not in this script.
"""
import subprocess
import sys
import time

LOG = __file__.rsplit("/", 2)[0] + "/commands.log"
with open(LOG, "a") as f:
    f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\tboard\tssh jetson-usb 'date -u +%s.%N' x5 (clocksync.py)\n")
rows = []
for _ in range(5):
    t0 = time.time()
    out = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "jetson-usb", "date -u +%s.%N"],
                         capture_output=True, text=True, timeout=20).stdout.strip()
    t1 = time.time()
    rows.append((t1 - t0, float(out) - (t0 + t1) / 2))
    time.sleep(0.2)
rtt, off = min(rows)
print(" ".join(f"{o:+.3f}@{r * 1e3:.0f}ms" for r, o in rows), file=sys.stderr)
print(f"board - mac = {off:+.3f} s (rtt {rtt * 1e3:.1f} ms)", file=sys.stderr)
if abs(off) <= 0.1:
    print("within 0.1 s: no step", file=sys.stderr)
    sys.exit(1)
print(f"{-off:+.3f}")
