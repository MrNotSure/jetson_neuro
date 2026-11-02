"""Throwaway (board session 2026-10-26): Mac-side orchestrator for the C4 pilot.

usage: .venv/bin/python pilot.py ORDER_FILE OUT_JSON [--duration-set ...]
Reads the block order (one condition per line: I/H/C), then per block:
  ssh begin (snapshot, fresh --once controller for H/C, start mark)
  -> 30 s realtime run (H/C) or 30.5 s sleep (I)
  -> ssh end (end mark, wait for controller exit, snapshot)
  -> 10 s gap.
Aborts (and leaves the board idle) if any thermal zone in a snapshot is >= 85 C.
Only light work happens on the Mac while a block runs.
"""
import json
import re
import subprocess
import sys
import time

B = "/private/tmp/jn_board_scripts/b"
ROOT = "/Users/<user>/Documents/code/jetson_neuro"
OUTRUNS = "runs/board_20261026/runs"
TEMP_LIMIT = 85000


def board(cmd):
    r = subprocess.run([B, cmd], capture_output=True, text=True, timeout=60)
    return r.stdout + r.stderr


def max_temp(text):
    temps = [int(x) for x in re.findall(r"(?:cpu|gpu|soc\d|tj)-thermal=(\d+)", text)]
    return max(temps) if temps else None


def main():
    order = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
    out = sys.argv[2]
    extra = sys.argv[3:]  # e.g. pilot variants; empty for C4
    tag_prefix = "C4"
    if extra and extra[0].startswith("--tag="):
        tag_prefix = extra.pop(0).split("=", 1)[1]
    blocks = []
    for i, cond in enumerate(order, 1):
        tag = f"{tag_prefix}_{i:02d}_{cond}"
        rec = {"i": i, "tag": tag, "cond": cond}
        txt = board(f"bash /tmp/jn_board/scripts/blk.sh begin {tag} {cond}")
        rec["begin"] = txt.strip()
        rec["tmax_pre"] = max_temp(txt)
        if rec["tmax_pre"] is not None and rec["tmax_pre"] >= TEMP_LIMIT:
            rec["abort"] = "temperature limit before block"
            blocks.append(rec)
            break
        if cond != "I" and "NOT LISTENING" in txt:
            rec["abort"] = "controller not listening"
            blocks.append(rec)
            break
        t0 = time.time()
        if cond == "I":
            time.sleep(30.5)
        else:
            r = subprocess.run(
                [f"{ROOT}/.venv/bin/jn-sim", "run", "--scenario", "track-sine-v1",
                 "--controller", "tcp://192.168.55.1:5555", "--mode", "realtime",
                 "--out", OUTRUNS, *extra],
                cwd=ROOT, capture_output=True, text=True, timeout=120)
            rec["run_rc"] = r.returncode
            m = re.search(r"run directory: (\S+)", r.stdout)
            rec["run_dir"] = m.group(1) if m else None
            rec["run_out"] = r.stdout[-800:] + r.stderr[-400:]
        rec["mac_block_s"] = time.time() - t0
        txt = board(f"bash /tmp/jn_board/scripts/blk.sh end {tag} {cond}")
        rec["end"] = txt.strip()
        rec["tmax_post"] = max_temp(txt)
        blocks.append(rec)
        print(f"{tag}: rc={rec.get('run_rc')} dir={rec.get('run_dir')} tmax_pre={rec['tmax_pre']} tmax_post={rec['tmax_post']} "
              f"mac_block_s={rec['mac_block_s']:.1f}", flush=True)
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(blocks, fh, indent=1)
        if rec["tmax_post"] is not None and rec["tmax_post"] >= TEMP_LIMIT:
            rec["abort"] = "temperature limit after block"
            break
        time.sleep(10)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(blocks, fh, indent=1)


if __name__ == "__main__":
    main()
