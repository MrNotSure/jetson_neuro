"""Stage 1 fix session: record one event with the Mac's monotonic and wall clock, to raw/marks.csv
and commands.log. The capture's chunks.csv carries the same monotonic clock, so events can be
placed on the PIO trace.   usage: .venv/bin/python mark.py 'label'
"""
import os
import sys
import time

RUN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
mono, unix = time.monotonic_ns(), time.time_ns()
label = " ".join(sys.argv[1:]).replace(",", ";")
path = os.path.join(RUN, "raw", "marks.csv")
new = not os.path.exists(path)
with open(path, "a") as f:
    if new:
        f.write("mac_mono_ns,mac_unix_ns,utc,label\n")
    utc = time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(unix / 1e9)) + ".%03dZ" % (unix // 1_000_000 % 1000)
    f.write(f"{mono},{unix},{utc},{label}\n")
with open(os.path.join(RUN, "commands.log"), "a") as f:
    f.write(f"{utc}\tmark\t{label} (mac_mono_ns {mono})\n")
print(f"{utc} mono {mono} {label}")
