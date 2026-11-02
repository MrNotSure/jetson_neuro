"""Throwaway (board session 2026-10-26): per-run stats and miss attribution.

usage: .venv/bin/python /private/tmp/jn_board_scripts/runstats.py RUN_DIR [RUN_DIR ...]
Prints one block per run: summary numbers plus, for every miss, the timing columns of the
periods around it, so a miss can be attributed to a Mac stall (send_lateness_us / sim_us spike)
or to the board / link (ctl_us / link_us spike).
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np

COLS = ["k", "miss", "send_lateness_us", "sim_us", "ctl_us", "rtt_us", "link_us", "n_events"]


def load(run):
    with open(run / "periods.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    data = {}
    for c in rows[0]:
        try:
            data[c] = np.array([float(r[c]) if r[c] != "" else np.nan for r in rows])
        except ValueError:
            pass
    return data


def pct(x, q):
    x = x[np.isfinite(x)]
    return float(np.percentile(x, q)) if x.size else float("nan")


def main():
    for arg in sys.argv[1:]:
        run = Path(arg)
        s = json.loads((run / "summary.json").read_text(encoding="utf-8"))
        m = json.loads((run / "meta.json").read_text(encoding="utf-8"))
        d = load(run)
        o = s["overall"]
        lat, ctl, rtt, link, sim = (d[c] for c in ("send_lateness_us", "ctl_us", "rtt_us", "link_us", "sim_us"))
        print(f"=== {run.name}")
        print(f"status={s['status']} periods={o['periods']} misses={o['misses']} achieved_hz={s['achieved_hz']:.4f}")
        print(f"controller={m['controller']['name']} sha={m['controller']['git_sha'][:12]} dirty={m['controller']['git_dirty']} "
              f"arch={m['controller']['arch']} py={m['controller']['python']} numpy={m['controller']['numpy']} endpoint={m['endpoint_type']}")
        print(f"lateness_us p50={pct(lat,50):.1f} p99={pct(lat,99):.1f} max={np.nanmax(lat):.1f} "
              f"n>500us={int(np.sum(lat>500))} n>1ms={int(np.sum(lat>1000))} n>5ms={int(np.sum(lat>5000))}")
        print(f"sim_us p50={pct(sim,50):.0f} p99={pct(sim,99):.0f} max={np.nanmax(sim):.0f}")
        print(f"ctl_us p50={pct(ctl,50):.1f} p99={pct(ctl,99):.1f} max={np.nanmax(ctl):.1f} mean={np.nanmean(ctl):.1f}")
        print(f"rtt_us p50={pct(rtt,50):.0f} p99={pct(rtt,99):.0f} max={np.nanmax(rtt):.0f}")
        print(f"link_us p50={pct(link,50):.0f} p99={pct(link,99):.0f} max={np.nanmax(link):.0f}")
        e = o["error"]
        print(f"rms_px_in_view={e['rms_px_in_view']:.2f} max_px_in_view={e['max_px_in_view']:.2f} rms_deg={e['rms_deg']:.3f} "
              f"in_fov_fraction={o['mission']['in_fov_fraction']} events_mean={o['events_per_period']['mean']:.1f}")
        print("top-5 lateness periods (k: lateness_us):",
              ", ".join(f"{int(d['k'][i])}:{lat[i]:.0f}" for i in np.argsort(-np.nan_to_num(lat))[:5]))
        print("top-5 ctl_us periods (k: ctl_us):",
              ", ".join(f"{int(d['k'][i])}:{ctl[i]:.0f}" for i in np.argsort(-np.nan_to_num(ctl))[:5]))
        print("top-5 link_us periods (k: link_us):",
              ", ".join(f"{int(d['k'][i])}:{link[i]:.0f}" for i in np.argsort(-np.nan_to_num(link))[:5]))
        for i in np.flatnonzero(d["miss"] > 0):
            print(f"  miss at k={int(d['k'][i])}; periods k-3..k+3:")
            print("    " + "  ".join(f"{c:>16}" for c in COLS))
            for j in range(max(0, i - 3), min(len(lat), i + 4)):
                print("    " + "  ".join(f"{d[c][j]:16.1f}" for c in COLS))
        print()


if __name__ == "__main__":
    main()
