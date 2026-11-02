"""T5: log both CPU clusters' and the GPU's current frequency, plus tj temperature.

10 Hz on an absolute schedule, standard library only, read-only sysfs.

  taskset -c 0 ~/venvs/jn/bin/python -u freqlog.py DURATION_S OUT.csv
"""
import glob
import sys
import time

dur, out = float(sys.argv[1]), sys.argv[2]
files = [
    "/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq",  # cpu0-3, incl. the pinned cpu2
    "/sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq",  # cpu4-5
    "/sys/class/devfreq/17000000.gpu/cur_freq",
]
tj = next(z for z in sorted(glob.glob("/sys/class/thermal/thermal_zone*"))
          if open(z + "/type").read().strip() == "tj-thermal") + "/temp"
files.append(tj)
rows = []
t_start = time.monotonic_ns()
n = int(round(dur * 10))
for i in range(n):
    t_next = t_start + i * 100_000_000
    d = t_next - time.monotonic_ns()
    if d > 0:
        time.sleep(d / 1e9)
    vals = []
    for p in files:
        with open(p) as f:
            vals.append(f.read().strip())
    rows.append((time.monotonic_ns(), time.time_ns(), *vals))
with open(out, "w") as f:
    f.write("mono_ns,realtime_ns,cpu_policy0_khz,cpu_policy4_khz,gpu_hz,tj_mC\n")
    f.writelines(",".join(map(str, r)) + "\n" for r in rows)
print(f"wrote {len(rows)} samples", flush=True)
