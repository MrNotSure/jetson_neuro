# Stage 1 first run, day 2: 30 Oct 2026

Two parts, on either side of the fix session (`../stage1_20261030_fix/`):

- **15:44–16:42 UTC:** diagnosis of the pin 29 marker (pad tristated in the
  pinmux) and of the power mode that didn't apply at the cold boot.
- **17:36–18:30 UTC, after the fix:** Part 4, quiet-board idle, INA228
  against `VDD_IN`; Part 5, synthetic decisions of known length (W = 0, 0.1,
  0.3, 1 ms, 3 × 60 s each) with the marker on pin 8; then restore and
  poweroff. Results are at the end of `report.md`.

- Code: board checkout `main` at `8d91a6d`; Mac at `78cf5f9` (same `src/`).
- `report.md` covers both days; `pin29_problem.md` is the pinmux analysis
  and the options. `raw/` holds the measurement data and analyses
  (`raw/P4_*`, `raw/P5_*`, running log `raw/notes.txt`, Mac marks
  `raw/marks.csv`), `raw/board_tmp_jn_run1/`, `raw/board_P4/` and
  `raw/board_P5/` copies of the board's working directory, `scripts/` the
  scripts that ran, `commands.log` every command, including every `sudo`
  call.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.
- One edit against the original: the Mac's hostname in the `dhcpd` journal
  lines of `raw/P4_M2_periodic.txt` reads `mac-hostname`.
- Day 1 is in `../stage1_20261029/`.

Copied from the gitignored `runs/stage1_20261030/` on the Mac. Paths in the
report that start with `runs/` refer to these copies under `traces/`.
