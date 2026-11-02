"""Throwaway (board session 2026-10-26): INA3221 rail sampler. READ-ONLY on the power monitor.

Opens each rail's bus-voltage and current file once and re-reads them with os.pread(fd, 64, 0)
per sample; every sample is stamped with time.monotonic_ns() before and after the six reads.

usage: ~/venvs/jn/bin/python sampler.py --rate HZ --duration S --out CSV
  --rate 0  -> as fast as possible
  --duration 0 -> run until SIGINT/SIGTERM
Rows: t0_ns,t1_ns,in1,curr1,in2,curr2,in3,curr3   (mV, mA; 1=VDD_IN 2=VDD_CPU_GPU_CV 3=VDD_SOC)
A trailer file CSV.meta.json records rate, sample count, wall time and getrusage CPU time.
Rows are flushed about once per second, so a long run loses at most ~1 s on a crash.
"""
import argparse
import json
import os
import resource
import signal
import time

import glob

# The hwmon number changes between boots (hwmon3 on 29 Oct boot 1, hwmon4 on boot 2): it follows
# driver probe order, not anything on the Mac side. Find the INA3221 by its I2C address instead,
# and refuse to run unless exactly one match has name "ina3221" and the expected channel labels.
_I2C_DEV = "/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*"
_LABELS = {"in1_label": "VDD_IN", "in2_label": "VDD_CPU_GPU_CV", "in3_label": "VDD_SOC"}


def find_ina3221():
    hits = sorted(glob.glob(_I2C_DEV))
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one INA3221 hwmon under {_I2C_DEV}; found {hits}")
    hw = hits[0]
    name = open(f"{hw}/name").read().strip()
    labels = {k: open(f"{hw}/{k}").read().strip() for k in _LABELS}
    if name != "ina3221" or labels != _LABELS:
        raise SystemExit(f"{hw}: name {name!r}, labels {labels}; refusing")
    return hw


HW = find_ina3221()
FILES = ["in1_input", "curr1_input", "in2_input", "curr2_input", "in3_input", "curr3_input"]

stop = False


def _stop(signum, frame):
    global stop
    stop = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rate", type=float, required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    fds = [os.open(f"{HW}/{f}", os.O_RDONLY) for f in FILES]
    pread = os.pread
    mono = time.monotonic_ns
    period = int(1e9 / a.rate) if a.rate > 0 else 0
    out = open(a.out, "w", encoding="utf-8", buffering=1 << 20)
    out.write("t0_ns,t1_ns," + ",".join(f.replace("_input", "") for f in FILES) + "\n")
    ru0 = resource.getrusage(resource.RUSAGE_SELF)
    start_rt = time.time_ns()
    start = mono()
    end = start + int(a.duration * 1e9) if a.duration > 0 else None
    nxt = start
    n = 0
    buf = []
    last_flush = start
    while not stop:
        if period:
            now = mono()
            if nxt > now:
                time.sleep((nxt - now) / 1e9)
            nxt += period
        t0 = mono()
        vals = [pread(fd, 64, 0) for fd in fds]
        t1 = mono()
        buf.append(f"{t0},{t1}," + ",".join(v.strip().decode() for v in vals) + "\n")
        n += 1
        if t1 - last_flush > 1_000_000_000:
            out.write("".join(buf))
            out.flush()
            buf.clear()
            last_flush = t1
        if end is not None and t1 >= end:
            break
    stop_ns = mono()
    ru1 = resource.getrusage(resource.RUSAGE_SELF)
    out.write("".join(buf))
    out.close()
    for fd in fds:
        os.close(fd)
    wall = (stop_ns - start) / 1e9
    cpu = (ru1.ru_utime - ru0.ru_utime) + (ru1.ru_stime - ru0.ru_stime)
    meta = {
        "rate_hz_requested": a.rate, "duration_s_requested": a.duration, "samples": n,
        "wall_s": wall, "achieved_hz": n / wall if wall else None,
        "cpu_user_s": ru1.ru_utime - ru0.ru_utime, "cpu_sys_s": ru1.ru_stime - ru0.ru_stime,
        "cpu_total_s": cpu, "cpu_fraction_of_one_core": cpu / wall if wall else None,
        "start_mono_ns": start, "start_realtime_ns": start_rt, "stop_mono_ns": stop_ns, "hwmon": HW,
        "hwmon_resolved": os.path.realpath(HW), "files": [f"{HW}/{f}" for f in FILES],
        "pid": os.getpid(), "utc_end": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    with open(a.out + ".meta.json", "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=1)


if __name__ == "__main__":
    main()
