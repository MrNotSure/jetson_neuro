#!/usr/bin/env python3
"""Evaluate a controller over scenarios x seeds (spec_ctl_a.md T4, R8.1).

Each (scenario, seed) is one lockstep run with the controller in-process,
wired like ``jn-sim run`` (sim_cli.py): ``resolve_config`` with the scenario,
seed and ``--set`` overrides, a ``RunLogger``, the ``Simulator`` and an
``InProcLink`` around a fresh controller built with the given parameters. The
run directories go under ``runs/eval_<UTC>[_<tag>]/``, next to ``eval.csv``
(the table printed at the end) and ``eval.json`` (the arguments and the
controller's effective parameters).

The table has one row per run, then per scenario a ``mean`` and a ``worst``
row over the seeds (worst: the largest error, losses and ctl_us, the smallest
in-FOV fraction and success).

Examples::

    .venv/bin/python scripts/eval_controllers.py centroid
    .venv/bin/python scripts/eval_controllers.py classical --param kp=0.2 \\
        --scenarios track-sine-v1 track-random-v1 --seeds 0 1 --jobs 4
    .venv/bin/python scripts/eval_controllers.py classical --set plant.omega_n=20
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import multiprocessing as mp
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "src"))  # run from the checkout, installed or not

from jn_sim import testctl  # noqa: E402
from jn_sim.config import ConfigError, resolve_config  # noqa: E402
from jn_sim.ctl import CtlUsageError, parse_params  # noqa: E402
from jn_sim.host import Host  # noqa: E402
from jn_sim.link import InProcLink  # noqa: E402
from jn_sim.runlog import RunLogger  # noqa: E402
from jn_sim.sim import Simulator  # noqa: E402

V1_SCENARIOS = ["track-static-v1", "track-sine-v1", "track-step-v1", "track-random-v1"]
COLUMNS = [
    "scenario", "seed", "rms_deg", "max_deg", "in_fov", "losses", "unrecovered",
    "success", "events_per_period", "ctl_us_p99", "status", "run_dir",
]


def run_one(controller: str, params: dict[str, Any], scenario: str, seed: int,
            sets: list[str], out_dir: str, duration: float | None = None) -> dict[str, Any]:
    """One lockstep in-process run; returns its table row."""
    resolved = resolve_config(scenario=scenario, sets=sets, seed=seed, duration=duration)
    cfg = resolved.config
    ctl = testctl.make_controller(controller, params)
    logger = RunLogger(
        out_dir, cfg, seed=cfg.run.seed, scenario=resolved.scenario,
        overrides=resolved.overrides, scenario_exact=resolved.scenario_exact,
        endpoint_type="inproc", warmup_s=cfg.run.warmup_s,
        success_in_fov=cfg.run.success_in_fov,
    )
    result = Simulator(cfg, cfg.run.seed).run(
        "lockstep", InProcLink(ctl), episodes=cfg.run.episodes,
        duration_s=cfg.run.episode_length_s, host=Host(), logger=logger,
    )
    o = logger.summary["overall"]
    err, mis = o["error"], o["mission"]
    return {
        "scenario": scenario,
        "seed": seed,
        "rms_deg": err["rms_deg"],
        "max_deg": err["max_deg"],
        "in_fov": mis["in_fov_fraction"],
        "losses": mis["target_losses"],
        "unrecovered": mis["unrecovered_losses"],
        "success": o["success_rate"],
        "events_per_period": o["events_per_period"]["mean"],
        "ctl_us_p99": o["timing"]["ctl_us"]["p99"],
        "status": result.status,
        "run_dir": str(Path(result.run_dir).relative_to(out_dir)) if result.run_dir else "",
    }


def _run_one_star(job: tuple) -> dict[str, Any]:
    return run_one(*job)


_WORST_MIN = {"in_fov", "success"}  # for these, worst is the smallest


def aggregate(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per scenario, a ``mean`` and a ``worst`` row over the seeds."""
    out = []
    for scenario in dict.fromkeys(r["scenario"] for r in rows):
        group = [r for r in rows if r["scenario"] == scenario]
        for label in ("mean", "worst"):
            agg: dict[str, Any] = {"scenario": scenario, "seed": label}
            for col in COLUMNS[2:10]:
                vals = [float(r[col]) for r in group if r[col] is not None]
                if not vals:
                    agg[col] = None
                elif label == "mean":
                    agg[col] = sum(vals) / len(vals)
                else:
                    agg[col] = min(vals) if col in _WORST_MIN else max(vals)
            agg["status"] = ",".join(sorted({r["status"] for r in group}))
            agg["run_dir"] = ""
            out.append(agg)
    return out


def evaluate(controller: str, params: dict[str, Any], scenarios: list[str], seeds: list[int],
             sets: list[str], out_base: str = "runs", tag: str | None = None, jobs: int = 1,
             duration: float | None = None) -> tuple[Path, list[dict[str, Any]]]:
    """Run every (scenario, seed); write eval.csv and eval.json; return the
    output directory and the table (per-run rows, then the aggregates)."""
    probe = testctl.make_controller(controller, params)  # fail fast on bad params
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"eval_{stamp}" + (f"_{tag}" if tag else "")
    out_dir = Path(out_base) / name
    n = 1
    while True:
        try:
            out_dir.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            n += 1
            out_dir = Path(out_base) / f"{name}_{n}"
    jobs_list = [(controller, params, sc, sd, sets, str(out_dir), duration)
                 for sc in scenarios for sd in seeds]
    if jobs > 1:
        with ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn")) as ex:
            rows = list(ex.map(_run_one_star, jobs_list))
    else:
        rows = [_run_one_star(j) for j in jobs_list]
    table = rows + aggregate(rows)
    with (out_dir / "eval.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in table:
            w.writerow({k: _cell(r[k]) for k in COLUMNS})
    with (out_dir / "eval.json").open("w", encoding="utf-8") as fh:
        json.dump({
            "controller": controller, "params_given": params, "params": probe.params,
            "scenarios": scenarios, "seeds": seeds, "sets": sets, "duration": duration,
            "mode": "lockstep", "endpoint_type": "inproc", "start_utc": stamp,
        }, fh, indent=2)
        fh.write("\n")
    return out_dir, table


def _cell(x: Any) -> str:
    if x is None:
        return ""
    if isinstance(x, float):
        return "nan" if math.isnan(x) else f"{x:.6g}"
    return str(x)


def format_table(table: list[dict[str, Any]]) -> str:
    head = ["scenario", "seed", "rms_deg", "max_deg", "in_fov", "losses", "unrec",
            "success", "ev/period", "ctl_us_p99", "status"]
    keys = ["scenario", "seed", "rms_deg", "max_deg", "in_fov", "losses", "unrecovered",
            "success", "events_per_period", "ctl_us_p99", "status"]
    fmt = {"rms_deg": "{:.3f}", "max_deg": "{:.3f}", "in_fov": "{:.4f}", "success": "{:.2f}",
           "events_per_period": "{:.0f}", "ctl_us_p99": "{:.0f}", "losses": "{:.4g}",
           "unrecovered": "{:.4g}"}
    lines = [[str(h) for h in head]]
    for r in table:
        cells = []
        for k in keys:
            v = r[k]
            cells.append("n/a" if v is None else (fmt[k].format(v) if k in fmt else str(v)))
        lines.append(cells)
    widths = [max(len(row[i]) for row in lines) for i in range(len(head))]
    return "\n".join("  ".join(c.rjust(w) if i > 1 else c.ljust(w)
                               for i, (c, w) in enumerate(zip(row, widths))) for row in lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("controller", help="hold | centroid | classical")
    ap.add_argument("--param", action="append", default=[], metavar="KEY=VALUE",
                    help="controller parameter (as jn-sim ctl --param)")
    ap.add_argument("--scenarios", nargs="+", default=V1_SCENARIOS)
    ap.add_argument("--seeds", nargs="+", type=int, default=[0, 1, 2, 3, 4])
    ap.add_argument("--set", action="append", default=[], metavar="SECTION.KEY=VALUE",
                    help="config override on top of each scenario (sim R12.4)")
    ap.add_argument("--duration", type=float, help="episode length in s (default: the scenario's)")
    ap.add_argument("--out", default=str(_REPO / "runs"), help="base directory (default runs/)")
    ap.add_argument("--tag", help="suffix for the eval directory name")
    ap.add_argument("--jobs", type=int, default=1, help="parallel runs (lockstep results "
                    "don't depend on it; ctl_us does)")
    args = ap.parse_args(argv)
    try:
        params = parse_params(args.param)
        out_dir, table = evaluate(args.controller, params, args.scenarios, args.seeds, args.set,
                                  args.out, args.tag, max(1, args.jobs), args.duration)
    except (CtlUsageError, ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"eval_controllers: {exc}", file=sys.stderr)
        return 2
    print(f"controller: {args.controller} {json.dumps(params) if params else '(defaults)'}"
          + (f"  overrides: {' '.join(args.set)}" if args.set else ""))
    print(format_table(table))
    print(f"written: {out_dir / 'eval.csv'}")
    return 0 if all(r["status"] == "completed" for r in table) else 1


if __name__ == "__main__":
    sys.exit(main())
