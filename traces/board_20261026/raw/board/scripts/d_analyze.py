"""Throwaway (board session 2026-10-26): Part D summary (Mac, numpy).

usage: .venv/bin/python d_analyze.py RAW_BOARD_DIR RUN_mid RUN_low RUN_max
Per point: idle power per rail (30 s, drop first/last 3 s), rail bus voltages (in1..in3),
load-run power (sampler window inside the run), tegrastats frequency fields, run timing.
"""
import csv
import json
import re
import sys
from pathlib import Path

import numpy as np

raw = Path(sys.argv[1])
runs = dict(zip(("mid", "low", "max"), sys.argv[2:5]))
marks = {}
with open(raw / "marks.csv", newline="") as fh:
    for r in csv.DictReader(fh):
        marks.setdefault(r["tag"], {})[r["edge"]] = int(r["mono_ns"])


def rails(path, t_lo=None, t_hi=None, drop=3.0):
    a = np.loadtxt(path, delimiter=",", skiprows=1, dtype=np.int64)
    t = a[:, 0]
    if t_lo is None:
        sel = (t >= t[0] + drop * 1e9) & (t <= t[-1] - drop * 1e9)
    else:
        sel = (t >= t_lo + drop * 1e9) & (t <= t_hi - drop * 1e9)
    a = a[sel]
    p = [a[:, 2 * i] * a[:, 2 * i + 1] / 1000.0 for i in (1, 2, 3)]
    v = [a[:, 2 * i] for i in (1, 2, 3)]
    return [x.mean() for x in p], [x.mean() for x in v], int(sel.sum())


for lb in ("mid", "low", "max"):
    d = raw / "D"
    pi, vi, ni = rails(d / f"{lb}_idle_10hz.csv")
    m = marks.get(f"D_{lb}", {})
    pl, vl, nl = rails(d / f"{lb}_load_10hz.csv", m.get("start"), m.get("end"))
    print(f"=== point {lb}")
    print(f"  idle (n={ni}): VDD_IN={pi[0]:.0f} VDD_CPU_GPU_CV={pi[1]:.0f} VDD_SOC={pi[2]:.0f} mW; bus voltages in1/in2/in3 = {vi[0]:.0f}/{vi[1]:.0f}/{vi[2]:.0f} mV")
    print(f"  load (n={nl}, centroid run + tegrastats + freq logger running): VDD_IN={pl[0]:.0f} VDD_CPU_GPU_CV={pl[1]:.0f} VDD_SOC={pl[2]:.0f} mW; in1/in2/in3 = {vl[0]:.0f}/{vl[1]:.0f}/{vl[2]:.0f} mV")
    ts = (d / f"{lb}_load_tegrastats.txt").read_text().splitlines()
    cpu = set(); emc = set(); gr = set()
    for line in ts:
        cpu.update(re.findall(r"\d+%@(\d+)", line.split("EMC_FREQ")[0]))
        emc.update(re.findall(r"EMC_FREQ \d+%@(\d+)", line))
        gr.update(re.findall(r"GR3D_FREQ \d+%@\[(\d+)", line))
    print(f"  tegrastats ({len(ts)} lines): CPU MHz values {sorted(cpu, key=int)}  EMC MHz {sorted(emc)}  GR3D MHz {sorted(gr)}")
    rd = Path("/Users/<user>/Documents/code/jetson_neuro") / runs[lb]
    s = json.load(open(rd / "summary.json"))
    with open(rd / "periods.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    ctl = np.array([float(r["ctl_us"]) for r in rows if r["ctl_us"] not in ("", "nan")])
    big = ctl[np.array([int(r["n_events"]) for r in rows if r["ctl_us"] not in ("", "nan")]) >= 200]
    lat = np.array([float(r["send_lateness_us"]) for r in rows])
    link = np.array([float(r["link_us"]) for r in rows if r["link_us"] not in ("", "nan")])
    print(f"  run {rd.name}: status={s['status']} misses={s['overall']['misses']} ctl_us p50={np.median(ctl):.0f} p99={np.percentile(ctl,99):.0f} max={ctl.max():.0f} "
          f"(periods with >=200 events: p50={np.median(big):.0f} p99={np.percentile(big,99):.0f}); link_us p50={np.median(link):.0f} p99={np.percentile(link,99):.0f}; "
          f"lateness p99={np.percentile(lat,99):.0f} max={lat.max():.0f}; rms_px_in_view={s['overall']['error']['rms_px_in_view']:.2f}")
