"""Command-line entry point for ``jn-sim`` (spec T15).

Subcommand modules are imported lazily, inside the branch that handles them,
so that ``jn-sim ctl`` never loads the simulator, ``host.py`` or matplotlib
(spec R1.3, T15). Only the standard library and numpy may be imported at module
scope here.
"""

from __future__ import annotations

import argparse
import sys

from . import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jn-sim",
        description="Event-vision closed-loop simulator (jetson_neuro).",
    )
    parser.add_argument("--version", action="version", version=f"jn-sim {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    # run ---------------------------------------------------------------
    p_run = sub.add_parser("run", help="run the closed loop")
    p_run.add_argument("--scenario")
    p_run.add_argument("--config")
    p_run.add_argument("--set", action="append", default=[], metavar="KEY=VALUE")
    p_run.add_argument("--controller", default="inproc:centroid")
    p_run.add_argument("--mode", choices=("lockstep", "realtime"), default="lockstep")
    p_run.add_argument(
        "--trajectory", choices=("static", "sine", "step", "random")
    )
    p_run.add_argument("--duration", type=float)
    p_run.add_argument("--episodes", type=int)
    p_run.add_argument("--seed", type=int)
    p_run.add_argument("--view", action="store_true")
    p_run.add_argument("--save-events", action="store_true")
    p_run.add_argument("--out")

    # ctl ---------------------------------------------------------------
    p_ctl = sub.add_parser("ctl", help="run a controller server")
    p_ctl.add_argument("--controller", required=True, metavar="hold|centroid")
    p_ctl.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    p_ctl.add_argument("--listen", metavar="HOST:PORT")
    p_ctl.add_argument("--once", action="store_true")
    p_ctl.add_argument(
        "--idle-timeout",
        type=float,
        default=30.0,
        help="drop a connection that goes silent mid-run for this many seconds",
    )

    # bench -------------------------------------------------------------
    sub.add_parser("bench", help="measure render/event performance")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 2

    if args.command == "ctl":
        from . import ctl

        return ctl.main(args)

    if args.command == "run":
        from . import sim_cli

        return sim_cli.main(args)

    if args.command == "bench":
        from . import bench

        return bench.main(args)

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
