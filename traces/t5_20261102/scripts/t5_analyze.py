"""T5 analysis: Jetson timing of `classical` (spec_ctl_a R7.1, R8.5, T5).

  .venv/bin/python runs/t5_20261102/scripts/t5_analyze.py

Per run: ctl_us p50/p99/max over received CMDs, periods over 1 and 3 ms, misses
with their neighbourhood, tracking metrics, CPU frequency. For the diagnostic
run D1: the board-side step time of every period, including missed ones, with
context switches, page faults and GC collections around the slow steps.
"""
import csv
import glob
import json
import os
import sys

import numpy as np

S = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
RUNS = ["R1", "R2", "R3", "D1"]
L = []


def q(x, p):
    return float(np.percentile(x, p)) if len(x) else float("nan")


def sim_dir(label):
    txt = open(f"{S}/raw/sim_{label}.txt").read()
    line = next(l for l in txt.splitlines() if l.startswith("run directory:"))
    return os.path.join(S, "..", "..", line.split(":", 1)[1].strip())


def load_periods(d):
    rows = list(csv.DictReader(open(f"{d}/periods.csv")))
    f = lambda c: np.array([float(r[c]) for r in rows])
    return {c: f(c) for c in ("k", "ctl_us", "miss", "send_lateness_us", "n_events", "sim_us", "rtt_us")}


summary = {}
for lab in RUNS:
    d = sim_dir(lab)
    sm = json.load(open(f"{d}/summary.json"))
    meta = json.load(open(f"{d}/meta.json"))
    p = load_periods(d)
    ok = p["miss"] == 0
    c = p["ctl_us"][ok]
    miss_k = p["k"][~ok].astype(int).tolist()
    fr = list(csv.DictReader(open(f"{S}/raw/board/freq_{lab}.csv")))
    f0 = np.array([int(r["cpu_policy0_khz"]) for r in fr])
    f4 = np.array([int(r["cpu_policy4_khz"]) for r in fr])
    tj = np.array([int(r["tj_mC"]) for r in fr]) / 1000
    o = sm["overall"]
    rec = {
        "ctl_us_p50": q(c, 50), "ctl_us_p99": q(c, 99), "ctl_us_max": float(c.max()),
        "over_1ms": int((c > 1000).sum()), "over_3ms": int((c > 3000).sum()),
        "misses": len(miss_k), "miss_k": miss_k,
        "rms_deg": o["error"]["rms_deg"], "max_deg": o["error"]["max_deg"],
        "in_fov": o["mission"]["in_fov_fraction"], "losses": o["mission"]["target_losses"],
        "events_mean": o["events_per_period"]["mean"], "achieved_hz": sm.get("achieved_hz"),
        "lateness_p99_us": q(p["send_lateness_us"], 99), "lateness_max_us": float(np.nanmax(p["send_lateness_us"])),
        "link_us_p99": q((p["rtt_us"] - p["ctl_us"])[ok], 99),
        "cpu_policy0_khz": sorted({int(x) for x in f0}), "cpu_policy4_khz": sorted({int(x) for x in f4}),
        "cpu_policy0_share_max": float((f0 == f0.max()).mean()),
        "tj_degC": [float(tj.min()), float(tj.max())],
        "git_sha": meta["controller"]["git_sha"][:7], "git_dirty": meta["controller"]["git_dirty"],
    }
    summary[lab] = rec
    L.append(f"{lab}: ctl_us p50/p99/max {rec['ctl_us_p50']:.0f} / {rec['ctl_us_p99']:.0f} / {rec['ctl_us_max']:.0f} us; "
             f">1 ms {rec['over_1ms']}, >3 ms {rec['over_3ms']}; misses {rec['misses']} {miss_k}; "
             f"rms/max {rec['rms_deg']:.3f}/{rec['max_deg']:.3f} deg, in-FOV {rec['in_fov']}, losses {rec['losses']}; "
             f"events {rec['events_mean']:.0f}/period; lateness p99/max {rec['lateness_p99_us']:.0f}/{rec['lateness_max_us']:.0f} us; "
             f"link p99 {rec['link_us_p99']:.0f} us; cpu0 kHz {rec['cpu_policy0_khz']} "
             f"(at max {100 * rec['cpu_policy0_share_max']:.0f} %), cpu4 kHz {rec['cpu_policy4_khz']}; tj {rec['tj_degC']}; "
             f"code {rec['git_sha']} dirty {rec['git_dirty']}")
    for mk in miss_k:
        i = int(np.nonzero(p["k"] == mk)[0][0])
        ctx = []
        for j in range(max(0, i - 2), min(len(p["k"]), i + 3)):
            ctx.append(f"k={int(p['k'][j])} miss={int(p['miss'][j])} ctl_us={p['ctl_us'][j]:.0f} "
                       f"lateness={p['send_lateness_us'][j]:.0f} sim_us={p['sim_us'][j]:.0f} n={int(p['n_events'][j])}")
        L.append("   around miss: " + " | ".join(ctx))

# --- pooled R1-R3 -------------------------------------------------------------
pool = []
for lab in ("R1", "R2", "R3"):
    p = load_periods(sim_dir(lab))
    pool.append(p["ctl_us"][p["miss"] == 0])
pool = np.concatenate(pool)
L.append(f"pooled R1-R3: n {len(pool)}, ctl_us p50/p99/p99.9/max {q(pool, 50):.0f} / {q(pool, 99):.0f} / "
         f"{q(pool, 99.9):.0f} / {pool.max():.0f} us; >1 ms {(pool > 1000).sum()}, >3 ms {(pool > 3000).sum()}")
summary["pooled_R1_R3"] = {"n": int(len(pool)), "p50": q(pool, 50), "p99": q(pool, 99), "p999": q(pool, 99.9),
                           "max": float(pool.max()), "over_1ms": int((pool > 1000).sum()), "over_3ms": int((pool > 3000).sum())}

# --- D1: board-side step times --------------------------------------------------
st = list(csv.DictReader(open(f"{S}/raw/board/steps_D1.csv")))
k = np.array([int(r["k"]) for r in st])
dur = np.array([(int(r["t1_ns"]) - int(r["t0_ns"])) / 1000 for r in st])
t0 = np.array([int(r["t0_ns"]) for r in st])
t1 = np.array([int(r["t1_ns"]) for r in st])
nev = np.array([int(r["n_events"]) for r in st])
nvcsw = np.array([int(r["d_nvcsw"]) for r in st])
nivcsw = np.array([int(r["d_nivcsw"]) for r in st])
minflt = np.array([int(r["d_minflt"]) for r in st])
gcr = list(csv.DictReader(open(f"{S}/raw/board/steps_D1.csv.gc.csv")))
gstart = [int(r["t_ns"]) for r in gcr if r["phase"] == "start"]
gstop = [int(r["t_ns"]) for r in gcr if r["phase"] == "stop"]
gc_ms = [(b - a) / 1e6 for a, b in zip(gstart, gstop)]
in_gc = np.zeros(len(st), bool)
for a, b in zip(gstart, gstop):
    in_gc |= (t0 <= b) & (t1 >= a)
p = load_periods(sim_dir("D1"))
L.append("")
L.append(f"D1 board-side step time (step() only, all {len(st)} steps incl. missed): p50/p99/max "
         f"{q(dur, 50):.0f} / {q(dur, 99):.0f} / {dur.max():.0f} us; >1 ms {(dur > 1000).sum()}, >3 ms {(dur > 3000).sum()}")
L.append(f"   k covers 0..{k.max()} with {len(np.unique(k))} unique (sim periods {len(p['k'])})")
L.append(f"   GC collections: {len(gc_ms)}, durations ms {[round(x, 3) for x in gc_ms]}; steps overlapping a collection: {int(in_gc.sum())}")
slow = np.argsort(dur)[::-1][:12]
L.append("   slowest steps (k, us, events, voluntary/involuntary ctx switches, minor faults, in GC):")
for i in slow:
    L.append(f"     k={k[i]} {dur[i]:.0f} us n={nev[i]} nvcsw={nvcsw[i]} nivcsw={nivcsw[i]} minflt={minflt[i]} gc={bool(in_gc[i])}")
cs = (nvcsw + nivcsw) > 0
L.append(f"   steps with a context switch: {int(cs.sum())}; their p50/max {q(dur[cs], 50):.0f} / "
         f"{(dur[cs].max() if cs.any() else float('nan')):.0f} us; without: p99/max {q(dur[~cs], 99):.0f} / {dur[~cs].max():.0f} us")
# board step time vs sim ctl_us for received CMDs: the wrapper adds getrusage overhead
ok = p["miss"] == 0
ctlmap = dict(zip(p["k"][ok].astype(int), p["ctl_us"][ok]))
d = np.array([ctlmap[kk] - dd for kk, dd in zip(k, dur) if kk in ctlmap])
L.append(f"   ctl_us - board step time (wrapper overhead): p50 {q(d, 50):.1f} us, p99 {q(d, 99):.1f} us")
for mk in summary["D1"]["miss_k"]:
    i = int(np.nonzero(k == mk)[0][0])
    j = int(np.nonzero(p["k"] == mk)[0][0])
    L.append(f"   missed k={mk}: board step {dur[i]:.0f} us (n={nev[i]}, ctx {nvcsw[i]}/{nivcsw[i]}, gc {bool(in_gc[i])}); "
             f"sim rtt for it n/a, send lateness k-1..k+1 "
             f"{[round(float(x)) for x in p['send_lateness_us'][max(0, j - 1):j + 2]]} us; next ctl_us {p['ctl_us'][j + 1]:.0f}")
summary["D1_board"] = {"p50": q(dur, 50), "p99": q(dur, 99), "max": float(dur.max()),
                       "over_1ms": int((dur > 1000).sum()), "over_3ms": int((dur > 3000).sum()),
                       "gc_collections": len(gc_ms), "gc_ms": gc_ms}

txt = "\n".join(L)
print(txt)
open(f"{S}/raw/t5_result.txt", "w").write(txt + "\n")
json.dump(summary, open(f"{S}/raw/t5_result.json", "w"), indent=1)
