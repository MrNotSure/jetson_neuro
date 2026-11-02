# T6 energy session, 2 Nov 2026: controller A against `hold`

Energy per control decision of controller A (`classical`) on the board,
`docs/spec_ctl_a.md` R9 and T6. `track-sine-v1`, realtime, 60 s blocks,
controller pinned to core 2: one idle block, 20 rounds of `hold`/A in a
counterbalanced cycle, two more idle blocks.

- Code: `main` at `0c397e1` on the board (`src/` identical to the Mac's
  `cbcae21`), `git_dirty` false.
- `report.md` is the summary. `raw/result.txt` and `raw/result.json` are the
  final analysis (`scripts/t6_analyze.py`); `raw/result_deglitch.*` the
  sensitivity run with sub-µs marker pulses dropped; `raw/result_C1.*`,
  `raw/result_r8.*`, `raw/result_r16.*` the interim analyses.
- Captures: `S0` (smoke test), `C1` (rounds 1–4), `C2` (damaged by the Mac's
  sleep, no blocks, not used), `C2b` (rounds 5–12; ended without a trailer
  when the charger was plugged back in, data up to then decode cleanly),
  `C3` (rounds 13–20). Checks in `raw/*_capcheck.txt` and `raw/*_check.txt`.
- The Jetson was power-cycled during the lunch break: rounds 1–4 ran on boot
  1, rounds 5–20 on boot 2.
- `sim/` holds the simulator run directories, `raw/board/` a copy of the
  board's `/tmp/jn_t6/`, `scripts/` the scripts that ran, `commands.log`
  every command, including every `sudo` call.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.

Copied from the gitignored `runs/t6_20261102/` on the Mac.
