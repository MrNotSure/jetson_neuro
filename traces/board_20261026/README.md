# Board session, 26 Oct 2026

Closed loop with the controller on the Jetson (spec_sim R14.6, passed) and
the reconnaissance for the Stage 0 measurement harness.

- Code on both machines: `main` at `8d91a6d`.
- `report.md` is the summary. Its paths are relative to this directory.
- `runs/` holds the simulator run directories from the session (`meta.json`,
  `periods.csv`, `summary.json`).
- `raw/` holds the measurement data and analyses; `raw/board/` is a copy of
  the board's `/tmp/jn_board/`, and `raw/scripts/` the scripts that ran.
- `commands.log` lists every command, including every `sudo` call.

Copied from the gitignored `runs/board_20261026/` on the Mac.
