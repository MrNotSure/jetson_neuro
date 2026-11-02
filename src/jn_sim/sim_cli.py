"""The ``jn-sim run`` subcommand (spec T15).

Resolves the config from a scenario plus overrides (R12.4), builds the Link for
the endpoint (R9.2), sets up run logging (T13) and, with ``--view``, the live
viewer (T14, checked for availability before the run starts, R2.4), then runs
the loop and returns the exit status (R7.8).

Imported lazily by ``__main__`` only for ``run``; matplotlib is never imported
in this process (the viewer runs in a child).
"""

from __future__ import annotations

import sys
from typing import Any

from . import link as linkmod
from .config import ConfigError, resolve_config
from .host import Host, UnsupportedHostError
from .runlog import RunLogger
from .sim import Simulator


def main(args: Any) -> int:
    try:
        resolved = resolve_config(
            scenario=args.scenario,
            config_file=args.config,
            sets=args.set,
            trajectory=args.trajectory,
            seed=args.seed,
            duration=args.duration,
            episodes=args.episodes,
        )
    except (ConfigError, FileNotFoundError) as exc:
        print(f"jn-sim run: {exc}", file=sys.stderr)
        return 2

    cfg = resolved.config
    host = Host()
    try:
        host.check_supported()
        spec = linkmod.parse_endpoint(args.controller)
    except (UnsupportedHostError, linkmod.EndpointError) as exc:
        print(f"jn-sim run: {exc}", file=sys.stderr)
        return 2

    viewer = None
    if args.view:
        from . import viewer as viewermod

        try:
            backend = viewermod.check_available(host)
        except viewermod.ViewerUnavailable as exc:
            print(f"jn-sim run: {exc}", file=sys.stderr)
            return 2
        viewer = viewermod.Viewer(backend, cfg)
        viewer.start()

    link = linkmod.make_link(args.controller, connect_timeout=cfg.link.connect_timeout)
    logger = RunLogger(
        args.out or "runs",
        cfg,
        seed=cfg.run.seed,
        scenario=resolved.scenario,
        overrides=resolved.overrides,
        scenario_exact=resolved.scenario_exact,
        endpoint_type=spec.kind,
        warmup_s=cfg.run.warmup_s,
        success_in_fov=cfg.run.success_in_fov,
        save_events=args.save_events,
    )
    sim = Simulator(cfg, cfg.run.seed)
    try:
        result = sim.run(
            args.mode,
            link,
            episodes=cfg.run.episodes,
            duration_s=cfg.run.episode_length_s,
            host=host,
            logger=logger,
            viewer=viewer,
        )
    finally:
        if viewer is not None:
            viewer.close()

    if result.run_dir is not None:
        print(f"run directory: {result.run_dir}")
    line = f"status: {result.status}"
    if result.reason:
        line += f" ({result.reason})"
    print(line)
    if logger.summary is not None:
        _print_summary(logger.summary)
    return result.exit_code


def _fmt(x: Any) -> str:
    return "n/a" if x is None else (f"{x:.3g}" if isinstance(x, float) else str(x))


def _print_summary(summary: dict) -> None:
    """Print a compact form of summary.json to the terminal (R12.2, m3)."""
    o = summary["overall"]
    err, mis, tm = o["error"], o["mission"], o["timing"]
    hz = summary.get("achieved_hz")
    print(
        f"  periods={o['periods']} episodes={o['episodes']} misses={o['misses']}"
        + (f" achieved_hz={hz:.4f}" if hz is not None else "")
    )
    print(
        f"  error: rms_deg={_fmt(err['rms_deg'])} max_deg={_fmt(err['max_deg'])}"
        f"  in_view rms_px={_fmt(err['rms_px_in_view'])}"
        f" max_px={_fmt(err['max_px_in_view'])}"
    )
    print(
        f"  in_fov={_fmt(mis['in_fov_fraction'])} losses={mis['target_losses']}"
        f" unrecovered={mis['unrecovered_losses']} success_rate={_fmt(o['success_rate'])}"
    )
    print(
        f"  events/period p95={_fmt(o['events_per_period']['p95'])}"
        f"  sim_us p99={_fmt(tm['sim_us']['p99'])}  rtt_us p99={_fmt(tm['rtt_us']['p99'])}"
        f"  lateness_us p99={_fmt(tm['send_lateness_us']['p99'])}"
    )
    print(f"  cmd_invalid={o['cmd_invalid']} cmd_clamped={o['cmd_clamped']} flags={o['ctl_flags']}")
