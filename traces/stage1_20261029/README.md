# Stage 1 first run, day 1: 29 Oct 2026

First power-up of the Jetson through the INA228: boot trace, the VBUS
jumper fix, and the first sign that header pin 29 doesn't drive.

- Code: board checkout `main` at `8d91a6d`; Mac at `78cf5f9` (same `src/`).
- `report.md` is the summary. `raw/` holds the measurement data and
  analyses, `raw/board_tmp_jn_run1/` a copy of the board's working
  directory, `scripts/` the scripts that ran, `commands.log` every command,
  including every `sudo` call.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.
- Day 2 is in `../stage1_20261030/`.

Copied from the gitignored `runs/stage1_20261029/` on the Mac. Paths in the
report that start with `runs/` refer to these copies under `traces/`.
