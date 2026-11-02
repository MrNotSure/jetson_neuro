# Stage 1 fix session, 30 Oct 2026

Power mode restored by a warm reboot; the marker moved to header pin 8
(UART1 TX) and passed M3 at 100 Hz and 1 kHz.

- Code: board checkout `main` at `8d91a6d`; Mac at `78cf5f9` (same `src/`).
- `report.md` is the summary. `raw/` holds the measurement data and
  analyses (running log `raw/notes.txt`, event marks `raw/marks.csv`),
  `raw/state_*` the board snapshots before, after the reboot and at the end,
  `raw/board/` a copy of the board's `/tmp/jn_fix/`, `scripts/` the scripts
  that ran, `commands.log` every command, including every `sudo` call.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.

Copied from the gitignored `runs/stage1_20261030_fix/` on the Mac. Paths in
the report that start with `runs/` refer to these copies under `traces/`.
