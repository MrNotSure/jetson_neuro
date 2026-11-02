# T5 Jetson timing check, 2 Nov 2026

Controller A (`classical`) on the Jetson against the simulator on the Mac:
four 60 s realtime `track-sine-v1` runs, controller pinned to core 2, on the
quiet board (`docs/spec_ctl_a.md` T5, R7.1, R8.5). Results are in
`docs/ctl_a.md` §8.

- Code: `main` at `0c397e1` on both machines, `git_dirty` false. The board
  checkout was updated from a git bundle, since its radio is off.
- `raw/t5_result.txt` and `raw/t5_result.json` are the analysis
  (`scripts/t5_analyze.py`). `raw/sim_*.txt` are the simulator's terminal
  summaries, `raw/state_start.txt` the board state before the runs.
- `sim/` holds the simulator run directories (R1, R2, R3, D1 in time order).
- `raw/board/` is a copy of the board's `/tmp/jn_t5/`: controller logs, the
  10 Hz frequency logs (`freq_*.csv`) and D1's per-step board timing
  (`steps_D1.csv`, `steps_D1.csv.gc.csv`). The git bundle used to update the
  checkout is left out (109 MB).
- `scripts/`: `run_one.sh` (one run), `steplog_ctl.py` (the D1 wrapper),
  `freqlog.py`, `t5_analyze.py`. `commands.log` lists what ran, including the
  two `sudo` calls.
- `t5_analyze.py` resolves the run directories through the paths in
  `raw/sim_*.txt`, which point at the gitignored `runs/t5_20261102/`.

Copied from `runs/t5_20261102/` on the Mac.
