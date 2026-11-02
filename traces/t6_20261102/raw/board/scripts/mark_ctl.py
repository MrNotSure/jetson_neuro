"""jn-sim controller (hold, centroid or classical) with a UART marker at the start of each step. Not tracked.
T6, 2 Nov 2026: copied from traces/stage1_20261031_final/scripts/mark_ctl.py; the only change is `classical`
added to the --controller choices (spec_ctl_a.md R9.2)."""
import argparse, os, sys, termios, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from jn_sim import ctl, provenance, testctl
from uart_marker import open_uart

class Marked:
    """Same controller, plus one 0xFF byte as the first action of each step."""
    def __init__(self, inner, fd, rows):
        self.inner, self.fd, self.rows = inner, fd, rows
        self.params = inner.params
    def reset(self, hello):
        return self.inner.reset(hello)          # name stays "hold" / "centroid"
    def step(self, obs):
        tb = time.monotonic_ns()
        os.write(self.fd, b"\xff")
        ta = time.monotonic_ns()
        self.rows.append((obs.episode, obs.k, tb, ta, int(obs.events.size)))
        return self.inner.step(obs)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--controller", required=True, choices=["hold", "centroid", "classical"])
    ap.add_argument("--listen", default="192.168.55.1:5555")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    host, port = ctl.parse_listen(a.listen)
    probe = testctl.make_controller(a.controller, {})
    meta = provenance.controller_metadata(a.controller, probe.params)   # unchanged metadata
    fd, _ = open_uart(115200)
    rows = []
    try:
        os.write(fd, b"\xff")                   # dummy: the first write is slow; a lone edge >= 1 s before the first decision
        termios.tcdrain(fd)
        time.sleep(1.0)
        ctl.serve(lambda: Marked(testctl.make_controller(a.controller, {}), fd, rows),
                  meta, host, port, once=True,
                  on_ready=lambda addr: print(f"listening {addr[0]}:{addr[1]}", flush=True))
    finally:
        termios.tcdrain(fd)
        os.close(fd)
        with open(a.out, "w") as f:
            f.write("episode,k,t_before_ns,t_after_ns,n_events\n")
            f.writelines("%d,%d,%d,%d,%d\n" % r for r in rows)

if __name__ == "__main__":
    main()
