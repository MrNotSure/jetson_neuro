"""T15: command line — the ctl import boundary and a run smoke (R1.3)."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from jn_sim import protocol
from jn_sim.protocol import EVENT_DTYPE

# Only these may be loaded while serving a controller (R1.3): the standard
# library, numpy, and the shared modules.
_SHARED = {
    "jn_sim", "jn_sim.__init__", "jn_sim.__main__", "jn_sim.ctl",
    "jn_sim.link", "jn_sim.protocol", "jn_sim.provenance", "jn_sim.testctl",
    "jn_sim.classical",  # controller A (spec_ctl_a.md R1.3)
}


def _some_events() -> np.ndarray:
    """A small moving-target-like batch, so a tracker has work to do."""
    ev = np.zeros(60, dtype=EVENT_DTYPE)
    ev["x"] = 200 + np.arange(60) % 6
    ev["y"] = 100 + np.arange(60) % 5
    ev["p"] = np.arange(60) % 2
    ev["t"] = np.arange(60) * 150
    return ev


@pytest.mark.parametrize("controller", ["centroid", "classical"])
def test_ctl_import_boundary_serving_an_episode(controller) -> None:
    # Serve one real episode through `python -m jn_sim ctl --once`, then check
    # that sys.modules holds only stdlib + numpy + the shared modules (R1.3,
    # T15). A subprocess with an allowlist, not a denylist (M6).
    repo = Path(__file__).resolve().parents[1]
    env = {
        **os.environ,
        "PYTHONPATH": "src",
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLBACKEND": "Agg",
    }
    code = (
        "import sys, json\n"
        "from jn_sim.__main__ import main\n"
        f"rc = main(['ctl', '--controller', {controller!r}, '--once', '--listen', '127.0.0.1:0'])\n"
        "mods = sorted(m for m in sys.modules\n"
        "              if m == 'jn_sim' or m.startswith('jn_sim.')\n"
        "              or m == 'matplotlib' or m.startswith('matplotlib.'))\n"
        "print('MODULES:' + json.dumps(mods), flush=True)\n"
        "sys.exit(rc)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code], cwd=str(repo), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        port = None
        while True:
            line = proc.stdout.readline()
            if not line:
                break
            if "listening on" in line:
                port = int(line.strip().rsplit(":", 1)[1])
                break
        assert port is not None, proc.stderr.read()

        conn = socket.create_connection(("127.0.0.1", port), timeout=10)
        protocol.send_message(
            conn, protocol.Hello(0, 320, 240, 10000, 277.1, 277.1, 159.5, 119.5, 0.0, 0.0, 1)
        )
        ack = protocol.read_message(conn)
        assert isinstance(ack, protocol.HelloAck)
        assert ack.name == controller
        protocol.send_message(conn, protocol.Obs(0, 0, 0, 10000, np.empty(0, dtype=EVENT_DTYPE)))
        assert isinstance(protocol.read_message(conn), protocol.Cmd)
        protocol.send_message(conn, protocol.Obs(0, 1, 10000, 20000, _some_events()))
        assert isinstance(protocol.read_message(conn), protocol.Cmd)
        protocol.send_message(conn, protocol.Bye(0))
        conn.close()
        out, err = proc.communicate(timeout=15)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.communicate()

    assert proc.returncode == 0, err
    mods_line = next(line for line in out.splitlines() if line.startswith("MODULES:"))
    loaded = json.loads(mods_line[len("MODULES:"):])
    forbidden = [m for m in loaded if m not in _SHARED]  # jn_sim.* outside shared, or matplotlib
    assert not forbidden, f"forbidden modules loaded while serving: {forbidden}\n{err}"
    # The registry imports controller A lazily (spec_ctl_a.md R1.2): only the
    # classical path loads it.
    assert ("jn_sim.classical" in loaded) == (controller == "classical")


def _run_args(**over):
    args = SimpleNamespace(
        scenario=None, config=None, set=[], controller="inproc:centroid",
        mode="lockstep", trajectory=None, duration=None, episodes=None, seed=None,
        view=False, save_events=False, out=None,
    )
    for k, v in over.items():
        setattr(args, k, v)
    return args


def test_run_cli_smoke(tmp_path) -> None:
    from jn_sim import sim_cli

    args = _run_args(set=["run.episode_length_s=0.3"], out=str(tmp_path))
    code = sim_cli.main(args)
    assert code == 0
    runs = list(tmp_path.iterdir())
    assert len(runs) == 1 and (runs[0] / "summary.json").exists()


def test_run_cli_rejects_not_built_endpoint(tmp_path) -> None:
    from jn_sim import sim_cli

    args = _run_args(controller="ssh://remote/5555", out=str(tmp_path))
    assert sim_cli.main(args) == 2  # ssh:// not built yet (T11)
