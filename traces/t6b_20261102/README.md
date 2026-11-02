# T6b confirmation session, 2 Nov 2026: controller A against `hold`, pre-registered

Confirms T6 (`../t6_20261102/`) with the design and analysis fixed before the
first block (`raw/plan.txt`, md5 in `raw/plan_md5.txt`): 12 rounds of idle,
`hold` and A, the order cycling twice through all six permutations, no 10 Hz
loggers during the captures. `track-sine-v1`, realtime, 60 s blocks,
controller pinned to core 2. Results are in `docs/ctl_a.md` §9.

- Code: `main` at `0c397e1` on the board (`src/` identical to the Mac's
  `cbcae21`), `git_dirty` false.
- `report.md` is the summary. `raw/result.txt`, `raw/result.json` and
  `raw/result_profiles.png` are the pre-registered analysis
  (`scripts/t6_analyze.py`, run once as written).
- Captures: `S0` (smoke test), `K1` (rounds 1–4), `K2` (5–8), `K3` (9–12).
  Checks in `raw/*_capcheck.txt` and `raw/*_check.txt`.
- `sim/` holds the simulator run directories, `raw/board/` a copy of the
  board's `/tmp/jn_t6b/`, `scripts/` the scripts that ran, `commands.log`
  every command, including every `sudo` call.
- Files ending in `.gz` are `gzip -9` of the original (every file over 5 MiB); read
  them with `gzip -dc`.
- One edit against the original: the Mac's hostname in the `dhcpd` journal
  lines of `raw/fake_hwclock_1700.txt` reads `mac-hostname`.

Copied from the gitignored `runs/t6b_20261102/` on the Mac.
