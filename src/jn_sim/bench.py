"""``jn-sim bench`` — render/event performance (spec T17, R13.1, R13.3).

Runs the real loop (inproc ``centroid``, lockstep) for each trajectory and
reports the per-period simulator compute ``sim_us`` (p50/p99/max) and events
per period. R13.1 targets the default sine scenario at ``sim_us`` p99 <= 4 ms;
R13.3 reports step and random without a hard target. R13.4 (the stage-2
rendering budget) is the optional T24.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .config import Config
from .host import Host
from .link import InProcLink
from .sim import Simulator
from .testctl import make_controller


class _Collector:
    run_dir = None

    def __init__(self) -> None:
        self.sim_us: list[int] = []
        self.n_events: list[int] = []

    def start(self, *a) -> None:
        pass

    def set_ctl_seed(self, *a) -> None:
        pass

    def set_achieved_hz(self, *a) -> None:
        pass

    def log_period(self, row, events) -> None:
        self.sim_us.append(row["sim_us"])
        self.n_events.append(row["n_events"])

    def finalize(self, *a) -> None:
        pass


def _measure(trajectory: str, duration: float, seed: int = 0):
    cfg = Config()
    cfg.target.trajectory = trajectory
    sim = Simulator(cfg, seed)
    coll = _Collector()
    sim.run("lockstep", InProcLink(make_controller("centroid")),
            episodes=1, duration_s=duration, host=Host(), logger=coll)
    return np.asarray(coll.sim_us, dtype=float), np.asarray(coll.n_events, dtype=float)


def main(args: Any) -> int:
    duration = getattr(args, "duration", None) or 10.0
    print(f"jn-sim bench: {Config().camera.width}x{Config().camera.height}, "
          f"lockstep inproc centroid, {duration:.0f}s per trajectory\n")
    print(f"{'trajectory':>9}  {'sim_us p50':>10} {'p99':>8} {'max':>8}  "
          f"{'events p50':>10} {'p99':>8} {'max':>8}")
    results = {}
    for traj in ("sine", "step", "random"):
        sim_us, nev = _measure(traj, duration)
        s50, s99, smax = np.percentile(sim_us, [50, 99, 100])
        e50, e99, emax = np.percentile(nev, [50, 99, 100])
        results[traj] = (s99, smax)
        print(f"{traj:>9}  {s50:>10.0f} {s99:>8.0f} {smax:>8.0f}  "
              f"{e50:>10.0f} {e99:>8.0f} {emax:>8.0f}")
    sine_p99 = results["sine"][0]
    ok = sine_p99 <= 4000.0
    print(f"\nR13.1 (sine sim_us p99 <= 4 ms): {sine_p99/1000:.2f} ms  "
          f"-> {'PASS' if ok else 'FAIL'}")
    print("R13.3 (step, random): reported above, no hard target.")
    return 0 if ok else 1
