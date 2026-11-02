"""Stage 1 run: board clock offset against the Mac, by ssh round trips (no sudo).

  .venv/bin/python clockcheck.py [n]     -> offset = board_utc - Mac_utc at the midpoint, per exchange
"""
import subprocess
import sys
import time

n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
LOG = __file__.rsplit("/", 2)[0] + "/commands.log"
with open(LOG, "a") as f:
    f.write("%s\tboard\tssh jetson-usb 'date -u +%%s.%%N' x%d (clockcheck.py)\n" % (time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), n))
rows = []
for i in range(n):
    t0 = time.time()
    out = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "jetson-usb", "date -u +%s.%N"],
                         capture_output=True, text=True, timeout=20).stdout.strip()
    t1 = time.time()
    b = float(out)
    rows.append((t1 - t0, b - (t0 + t1) / 2))
    time.sleep(0.2)
for rtt, off in rows:
    print(f"rtt {rtt * 1e3:7.1f} ms   board - mac {off:+.3f} s")
best = min(rows)
print(f"best (shortest rtt {best[0] * 1e3:.1f} ms): board - mac = {best[1]:+.3f} s = {best[1] / 86400:+.4f} d; "
      f"mac utc {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}")
