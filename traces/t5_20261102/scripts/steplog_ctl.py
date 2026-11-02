"""T5 diagnostic (spec_ctl_a T5): jn-sim ctl for `classical`, logging every step.

Not for energy blocks. Serves one connection like `jn-sim ctl --controller
classical --once`, with unchanged controller metadata, and records per step:
episode, k, step start/end on CLOCK_MONOTONIC, the event count, and the
thread's context-switch and page-fault deltas over the step (getrusage around
the timed region, not inside it). Steps whose CMD arrives late at the simulator
are logged too, so misses can be attributed. GC collections are logged with
their times. Rows stay in memory and are written when the connection closes.

  cd ~/jetson_neuro && PYTHONPATH=src taskset -c 2 ~/venvs/jn/bin/python -u \
      steplog_ctl.py --out /tmp/jn_t5/steps.csv --listen 192.168.55.1:5555
"""
import argparse
import gc
import resource
import time

from jn_sim import ctl, provenance, testctl

WHO = getattr(resource, "RUSAGE_THREAD", resource.RUSAGE_SELF)
mono = time.monotonic_ns


class Timed:
    """The same controller; times each step and records rusage deltas."""

    def __init__(self, inner, rows):
        self.inner, self.rows = inner, rows
        self.params = inner.params

    def reset(self, hello):
        return self.inner.reset(hello)  # name stays "classical"

    def step(self, obs):
        r0 = resource.getrusage(WHO)
        t0 = mono()
        out = self.inner.step(obs)
        t1 = mono()
        r1 = resource.getrusage(WHO)
        self.rows.append((obs.episode, obs.k, t0, t1, int(obs.events.size),
                          r1.ru_nvcsw - r0.ru_nvcsw, r1.ru_nivcsw - r0.ru_nivcsw,
                          r1.ru_minflt - r0.ru_minflt))
        return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listen", default="192.168.55.1:5555")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    host, port = ctl.parse_listen(a.listen)
    probe = testctl.make_controller("classical", {})
    meta = provenance.controller_metadata("classical", probe.params)  # unchanged metadata
    rows, gcrows = [], []
    gc.callbacks.append(lambda phase, info: gcrows.append((phase, info["generation"], mono())))
    try:
        ctl.serve(lambda: Timed(testctl.make_controller("classical", {}), rows),
                  meta, host, port, once=True,
                  on_ready=lambda addr: print(f"listening {addr[0]}:{addr[1]}", flush=True))
    finally:
        with open(a.out, "w") as f:
            f.write("episode,k,t0_ns,t1_ns,n_events,d_nvcsw,d_nivcsw,d_minflt\n")
            f.writelines("%d,%d,%d,%d,%d,%d,%d,%d\n" % r for r in rows)
        with open(a.out + ".gc.csv", "w") as f:
            f.write("phase,generation,t_ns\n")
            f.writelines("%s,%d,%d\n" % r for r in gcrows)
        print(f"wrote {len(rows)} steps, {len(gcrows)} gc callbacks", flush=True)


if __name__ == "__main__":
    main()
