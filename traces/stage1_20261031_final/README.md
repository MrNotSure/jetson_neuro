# Stage 1 final session, 31 Oct 2026

Last session of the measurement setup: the service plan (SETUP_NOTES §8.1)
applied and verified after a reboot, 5 min quiet idle, then the closed loop
with the marker: 4 interleaved rounds of idle, `hold` and `centroid`, 60 s
each.

- Code: board checkout `main` at `8d91a6d`; Mac at `bb1b8a6` (same `src/`).
  The marked controller `scripts/mark_ctl.py` wraps the repo's controllers
  without changing them.
- `report.md` is the summary. `raw/` holds the measurement data and analyses
  (`P0_*` startup, `P1_*` service plan and idle, `P2_*` closed loop,
  `services_*.txt` the rollback list and diff), `raw/board/` a copy of the
  board's `/tmp/jn_final/`, `sim/` the simulator runs, `scripts/` the
  scripts that ran, `commands.log` every command, including every `sudo`
  call.
- Capture `P01` (startup and idle) has offset edge timestamps after the
  marker wire went on at 13:00; it's used for power only. `P2` is clean.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.

Copied from the gitignored `runs/stage1_20261031_final/` on the Mac.
