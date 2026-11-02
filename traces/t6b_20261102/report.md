# T6b confirmation session, 2 Nov 2026: controller A (`classical`) against `hold`, pre-registered

Times are UTC. The session ran 16:00–17:21. Tags: **V** = I ran it and saw the result. **V-user** = the user did or reported it. **NV** = not verified. Paths are relative to this folder. The design and analysis are in `raw/plan.txt`, written at 16:22 before the first block (md5s in `raw/plan_md5.txt`, unchanged at analysis time). Results: `raw/result.txt`, `raw/result.json`, `raw/result_profiles.png`.

## Summary

**Design as run (V):**
- 12 rounds of I, H and A in the pre-registered order (`raw/order.txt`), on `track-sine-v1`, realtime, 60 s blocks.
- Three captures: K1 16:26–16:41 (rounds 1–4), K2 16:41–16:56 (rounds 5–8), K3 16:56–17:11 (rounds 9–12).
- No 10 Hz logger ran at any time.
- **All 12 rounds passed the integrity rule.** Every H/A block had falls = rows = OBS = 6000, so nothing was excluded.

| Quantity | Value | 95 % CI | Tag |
|---|---|---|---|
| **E_dyn(A), primary: method (b), window [−1, 4.5) ms** | **+206.7 µJ** | **[+194.5, +218.9], ±5.9 %** (t, 11 df) | V |
| E_dyn(A), (b), window [−2, 4.5) ms | +215.5 µJ | [+194.6, +236.3] | V |
| E_dyn(A), (b), window [−2, 5.5) ms | +218.0 µJ | [+192.5, +243.4] | V |
| E_dyn(A), method (a), (P_A − P_H)/f | +210.6 µJ | [+162.0, +259.1] | V |
| X_H, [−1, 4.5) / [−2, 4.5) | 129.6 / 106.0 µJ | [122.6, 136.5] / [96.9, 115.1] | V |
| X_A, [−1, 4.5) / [−2, 4.5) | 336.3 / 321.4 µJ | [327.0, 345.7] / [303.4, 339.5] | V |
| **Harness (P_H − P_I)/f, per round** | **+207.7 µJ** (20.8 mW) | [+178.5, +237.0] | V |
| **E_tot(A) = P_A/f** | **63.625 mJ** | [63.591, 63.658] | V |
| … stack: idle floor P_I/f + harness + algorithm (a) | 63.206 mJ + 0.208 mJ + 0.211 mJ | floor [63.182, 63.231] | V |
| `n_events` per decision | H 404.4 (every block); A 157.6 [157.2, 158.0] | | V |
| A's `ctl_us` on the board (includes the marker write) | p50 489 (483–500), p99 581 (572–592), max 1128–4065 µs | per-block ranges | V |
| H's `ctl_us` | p50 15.6, p99 21.7 µs; max ≤ 61 µs except R1H 1547 and R2H 1659 µs | | V |
| A's tracking in the energy blocks | `rms_deg` 0.181° (0.179–0.184), `max_deg` 0.46–0.64°, in-FOV 1.000, 0 losses, 0–2 misses per block | | V |
| Pulses < 1 µs dropped | **0** (K1, K2, K3 and the smoke capture) | | V |
| Window check, excess over [−2, −1) / [4.5, 5.5) ms | H +0.1 / −1.0 mW; A +0.5 / −0.4 mW | all four CIs contain 0 | V |
| sd_D (primary) | 19.2 µJ | [13.6, 32.6] (χ², 11 df) | V |
| **Precision reached** | **±5.9 %** (primary) against the ±5 % target | ±5 % needs 16 rounds, ±10 % needs 6 | V |

- **The confirmation holds.** The pre-registered E_dyn(A) is +207 µJ [+195, +219]. T6's post-hoc logger-excluded figure was +200 µJ [+193, +207], so the two CIs overlap by most of their width. T6's primary was +217 µJ [+184, +250].
- **±5 % wasn't reached.** The half-width is ±5.9 %; 16 rounds would have reached ±5 %. The plan fixed 12 rounds, so no rounds were added.
- **What E_dyn contains** (as in T6): A's step plus every closed-loop difference from `hold`. That includes the smaller decode cost of 158 against 404 events per decision. E_dyn therefore understates A's own compute by that difference (size NV; T9 would remove it).
- **The window holds (V).** A's excess is back near 0 by about 2 ms after the edge (`raw/result_profiles.png`). The checks over [−2, −1) and [4.5, 5.5) ms are all consistent with 0. The wider windows give the same mean but a larger spread (sd_D 33 and 40 µJ against 19 µJ), because they add bins with no signal.
- **No drift (V).** Slopes against round index: X_H −0.28 µJ/round [−2.41, +1.85], X_A +2.00 [−0.51, +4.51], D +2.28 [−1.11, +5.66].
- **No capture effect (V).** By capture, D is K1 +194 [+155, +233], K2 +214 [+192, +236] and K3 +212 [+187, +237] µJ. The ANOVA F(2, 9) is 1.37, against a 5 % critical value of 4.26. For X_H F = 0.01, and for X_A F = 3.29.
- **Method (a) is noisier than (b) (V).** Its sd over rounds is 76 µJ against 19 µJ for (b). Block means wander by several mW from round to round (P_I 6316–6329 mW), a large fraction of A − H (21 mW). Method (b) subtracts each block's own baseline, so the wander cancels.
- **The harness is about as large as A's E_dyn.** The harness is H's whole closed-loop cost above idle: the link, `hold`'s step, the marker write and the decoding of 404 events per decision. It now has a usable CI (±14 %), from one I block per round.
- **The algorithm is 0.33 % of E_tot.** The idle floor is 99.3 % of it.

## Against T6

| | T6 primary (brief's analysis, loggers running) | T6 logger-excluded (post hoc) | **T6b (pre-registered, no loggers)** |
|---|---|---|---|
| E_dyn(A), (b) [−1, 4.5) | +216.6 [+183.5, +249.7] µJ, ±15.3 % | +199.8 [+192.7, +206.9] µJ, ±3.6 % | **+206.7 [+194.5, +218.9] µJ, ±5.9 %** |
| sd_D | 66.6 µJ | 14.3 µJ | 19.2 µJ [13.6, 32.6] |
| Rounds; N for ±5 % | 18; 149 | 18; 11 | 12; 16 |
| X_H / X_A, [−1, 4.5) | 108.0 / 324.6 µJ | 111.8 / 311.6 µJ | 129.6 / 336.3 µJ |
| E_dyn(A), (a) | +207.0 [+180.5, +233.5] µJ | – | +210.6 [+162.0, +259.1] µJ |
| Harness | +181 [−30, +393] µJ (Welch, 3 I blocks, df 2.5) | – | +207.7 [+178.5, +237.0] µJ (12 rounds) |
| E_tot(A) | 63.823 mJ | – | 63.625 mJ |
| Idle floor P_I/f | 63.435 mJ (loggers running) | – | 63.206 mJ |

- **The logger hypothesis holds (V).** The pre-registered rule says it's supported if the sd_D CI contains 14.3 µJ and excludes 66.6 µJ. The CI is [13.6, 32.6], so it is supported.
  - Without loggers, sd_D fell from T6's 66.6 µJ to 19.2 µJ, without excluding anything after the fact.
  - The point value is 1.34× T6's logger-excluded 14.3 µJ. What makes up the rest is NV; chance alone fits inside the CI.
- **The X levels moved; D didn't (V).** X_H and X_A are both about 20 µJ above T6's session figures. T6's own C1 (boot 1, morning) gave 134 and 342 µJ, close to today's 130 and 336 µJ (the analyzer check, below). So absolute X shifts between boots or sessions while the paired D stays put. Why X moves is NV.
- **The harness agrees with earlier sessions.** T6 had 181 µJ (CI wider than the value) and 31 Oct had 237 µJ [182, 292]. Today's 208 µJ [179, 237] lies between them.
- **The idle floor is 0.23 mJ lower than T6's.** About 80 µJ of that is T6's loggers, which ran in its I blocks (T6's estimate). The rest is NV; T6's I blocks themselves moved by 18 mW over its afternoon.

## Deviations from `raw/plan.txt`

**None.** The design ran as registered: 12 rounds, the order in `raw/order.txt`, captures K1–K3, no loggers, and snapshots only in the gaps. The analysis is `scripts/t6_analyze.py`, with the md5 recorded in the plan, run once as written: `t6_analyze.py raw/result K1 K2 K3`. Nothing was excluded, and no round was added or dropped.

**Recorded alongside, outside the plan:**
1. **Checklist deviation, before the plan was written (V-user):** the marker wire went onto GP16 with the Jetson running (16:05), after the user confirmed it was up. SETUP_NOTES §8.3 says it goes on before power-up. No capture was running, and S0 and K1–K3 then showed clean pulses (8.52–8.88 µs, 0 glitches). Also recorded in `raw/plan.txt` §4.
2. **`fake-hwclock-save` ran at 17:00:05.170–.178 on the board's clock** (`raw/fake_hwclock_1700.txt`). It isn't one of the six timers and stays running per SETUP_NOTES §8.3. Mapped onto the PIO clock, it ran 64 ms (±50 ms) after R9H's last decision edge. That is outside R9H's (a) window, and (b) uses no conversions after a block's last edge.
3. **One extra ALRT edge in K3,** 4.8 s into R12H, at the same PIO time as a marker rising edge (`raw/K3_spurious_alrt.txt`).
   - One conversion out of 839 107 got a timestamp 513 µs early; none was lost. Its effect on R12H's X is under 0.1 µJ (estimate, NV).
   - It's the same kind of event as T6's extra ALRT edges at marker edges (R6A, C3). Coupling from the marker wire onto GP17 is the likely cause (NV).
4. **Read-only diagnostics after the analysis** (not part of the results): `raw/ctl_max_diag.txt` (slowest steps per block), `raw/K3_spurious_alrt.txt` and `raw/fake_hwclock_1700.txt`.
5. **Analyzer check before the first block:** the new `t6_analyze.py` was run on T6's C1 (`T6B_RUN=runs/t6_20261102`). It reproduced T6's `raw/result_C1.txt` exactly: D +207.38 µJ, (a) +222.7 µJ, X_H 134.37 µJ and X_A 341.75 µJ. Output: `/private/tmp/jn_t6b/test_T6C1.*`.

## For the planner

**Block design for B–D: keep T6b's.**
- **No 10 Hz loggers during blocks.** Take a snapshot in each gap instead: temperatures, fan, both policies' and the GPU's frequency, one `VDD_IN` reading, `pgrep -x`.
- **One I block in every round,** with the order cycling through all six permutations of I, H and X.
- **The rest as T6b:**
  - a fresh pinned process per block, with the dummy byte;
  - one capture per 4 rounds;
  - pulses < 1 µs dropped before the falls are split, pre-registered;
  - integrity = falls = rows = OBS = 6000;
  - window [−1, 4.5) ms with baseline [5.5, 8.5) ms.
- **Cost:** a round of three blocks takes about 3.7 min, so 12 rounds take about 45 min.
- **Precision is about fixed in µJ, not in percent.** With sd_D ≈ 19 µJ, 12 rounds give about ±12 µJ.
  - ±5 % of a 200 µJ difference needs 16 rounds.
  - For a controller 50 µJ from `hold`, ±5 % needs about 240 rounds and ±10 % about 60.
  - So state the target in µJ for small differences. Whether B–D have the same sd_D is NV; a longer or more variable step could raise it.
- **Use (b) as the primary for B–D.** Method (a) is 4× noisier at this size (sd 76 µJ), so keep it as a cross-check only. The [−2, …) windows also add noise without changing the mean.
- **Check the window against each controller's profile.** A's excess is gone by about 2 ms. A step longer than about 3 ms (a GPU network, for example) needs a later baseline.
- **Always pair H and X within a round, and never compare X across sessions.** X_H moved by about 20 µJ between T6's two boots and today; D didn't.
- **The harness only needs re-measuring if the setup changes** (same H, link, scenario and board state). T6b's +208 µJ [179, 237] could then serve for B–D, and I blocks could drop to every second round. That's a planning choice, not tested here.

**What broke, or nearly did:**
1. **Nothing at the capture level (V).**
   - 0 missed conversions in 2.49 M; 0 glitch pulses; every block passed integrity.
   - The Mac stayed on AC with the lid open and `caffeinate` running, and nobody touched the charger.
   - The jumpers were pressed and the Pico wasn't re-plugged. That fits T6's guess that its 0.12 µs glitches came with the re-plug or the moved wiring (NV).
2. **A's slowest steps went past R7.1's 3 ms bound twice (V).**
   - R6A at k = 2706 took 4057 µs, and R10A at k = 1534 took 4065 µs: 2 of 72 000 steps. Neither caused a miss.
   - T5's maximum was 2301 µs.
   - Some slow steps recur at the same k in every fresh process. At k = 0 and k = 176, A took about 1.1 ms in all 12 A blocks (958–1176 µs). At k = 4369 it took about 2.5 ms in 6 of 12 (R1, R3–R6, R8A), and 0.35–0.39 ms in the other six.
   - A cost tied to the allocation count, such as garbage collection, would fit (NV). docs/ctl_a.md §8 attributes the slow steps to GC.
   - The two 4 ms steps don't recur at the same k. `gc.freeze()` after `reset` is the fix ctl_a §8 proposes (not applied).
3. **Simulator stalls on the Mac (V):** 3–52 sends per block were over 5 ms late, and 0–2 misses per block. They were flagged and dropped, as in T6; (b) used 98.7–99.9 % of each block's conversions.
4. **The board clock drifted.** It was −0.003 s after the step at 16:03 and −0.086 s at 17:14, about 19 ppm with no NTP (V). Nothing maps the board's clock except the fake-hwclock note above. For a long session, re-sync it every hour or so.
5. **`VDD_IN` snapshots (V as recorded, not analysed):** 4.58–4.70 W, plus one I-before reading of 5.36 W.

**Spec R9 points for the next revision** (in addition to T6's list):
- **R9.3:** replace the H/A rounds plus two I blocks with I/H/A rounds over the six permutations, with a fixed length.
- **R9.4:** replace the 10 Hz frequency logging with the gap snapshots. This means T6b has no in-block CPU frequency. In T6, `policy0` sat at 729.6 MHz 99.5–100 % of the time. The gap snapshots read 1.1–1.3 GHz, probably raised by the ssh snapshot itself (NV).
- **R7.1:** under the energy harness, the max bound failed twice in 72 000 steps.

## Details

- **Part 0** (V; `raw/state_start.txt`):
  - cold boot at 15:25:51 (board clock 2121 s behind); the six timers stopped first, then one relative step of +2121.462 s (−0.003 s after), with no catch-up jobs;
  - nvpmodel `Result=success`, CPU max 1344000 on `policy0` and `policy4`, GPU `nvhost_podgov` 918 MHz, REAL masks 240/2 (`raw/nvpmodel_verbose.txt`);
  - INA3221 at hwmon3; `dialout`; checkout `0c397e1`, clean; Python 3.12.3, numpy 2.5.4; radio `disabled`; `multi-user.target`;
  - the board's `src/` and `scenarios/` match the Mac's `main` by md5, 26 files.
- **Pico** (V): `/dev/cu.usbmodem1101` today; filesystem `[]`; GP16 funcsel 31, OE 0, pull-down; it read 0 before the wire went on and 1 after.
- **Answers (V-user):** jumpers firmly on GP16 and GP17; pin 30 → Pico GND, no series resistor, nothing else on the header; marker wire pin 8 → GP16 connected.
- **Smoke test S0** (V; `raw/S0_check.txt`, `raw/S0_meta_check.txt`):
  - falls = rows = OBS = 1000, with a lone dummy 3.17 s before the first decision;
  - 0 missed; widths 8.64–8.88 µs; `ctl_us` p50 509 µs; affinity 2;
  - `classical` with default parameters (identical to T6's), `git_sha 0c397e1`, `git_dirty false`.
- **Captures** (V; `raw/K*_capcheck.txt`, `raw/K*_check.txt`):

  | Capture | Time | Rounds | Conversions | Missed | Extra ALRT | Glitches < 1 µs | FDEBUG |
  |---|---|---|---|---|---|---|---|
  | K1 | 16:26:17–16:41:13 | 1–4 | 828 919 | 0 | 0 | 0 | 0 |
  | K2 | 16:41:29–16:56:20 | 5–8 | 824 291 | 0 | 0 | 0 | 0 |
  | K3 | 16:56:33–17:11:40 | 9–12 | 839 107 | 0 | 1 | 0 | 0 |

  Every H/A block had falls = rows = OBS = 6000, k matching, `n_events` agreeing, a lone dummy 1.35–1.77 s ahead, and affinity 2. Peak single-conversion current was 0.51 A, with no alarm; tj 47.2–47.9 °C.
- **Scripts** (`scripts/`): copied from `traces/t6_20261102/scripts/`, with paths changed to `/tmp/jn_t6b`, `/private/tmp/jn_t6b` and `runs/t6b_20261102`.
  - `t6_run.py`: I/H/A rounds, `R<n><cond>` tags, one `VDD_IN` reading in the snapshot.
  - `t6_check.py`: the deglitch rule and a PASS/FAIL line for 6000.
  - `t6_analyze.py`: rewritten for the plan, keeping T6's method (b), method (a) and I window code. T6's version is kept as `t6_analyze_T6copy.py`.
  - The other scripts are unchanged. Every command, including those inside board scripts (`board-script` lines) and every `sudo`, is in `commands.log`.
- **`sudo` used (all within the brief's list):**
  - `systemctl stop` of the six timers (16:02);
  - one `date -u -s '+2121.462 seconds'` (16:03);
  - `nvpmodel -q --verbose` (16:05);
  - `systemctl start` of the six timers (17:20, user asked).

  No reboot or poweroff.

## End state (V, 17:21)

- **Jetson:** running, up about 1 h 15 min; left on, at the user's choice (no poweroff).
  - nvpmodel success; `multi-user.target`; radio `disabled`; no jobs, no apt/dpkg, nothing of ours running, port 5555 closed; tj 47.7 °C;
  - board clock −0.086 s against the Mac at 17:14 (no NTP).
- **Timers:** at the user's request, the six maintenance timers were started again at 17:20:13 (`sudo systemctl start …`); all six are active. `fake-hwclock-save` is active too.
  - `anacron` and `systemd-tmpfiles-clean` fired straight away and finished (`Result=success`); no jobs left running at 17:20:32;
  - `/tmp/jn_t6b` still holds its 77 files;
  - `raw/state_end.txt`.
- **Pico:** `machine.reset()` at 17:15, on `/dev/cu.usbmodem1101`; filesystem `[]`; GP16 funcsel 31, OE 0, pull-down, reading 1 (`raw/pico_state_end.txt`).
- **Wiring (V-user):** marker wire on, Jetson pin 8 → Pico GP16; pin 30 → Pico GND; no series resistor. It comes off GP16 before the Pico is ever unplugged.
- **Mac:** on AC; `caffeinate` (pid 3704) stopped at 17:20.
- **Temp files, not deleted:**
  - board `/tmp/jn_t6b/` (5.7 MB, 77 files; copied to `raw/board/`; lost at the next reboot);
  - Mac `/private/tmp/jn_t6b/`: status and `.out` files, `stop_S0`, `stop_K1`–`stop_K3`, and the analyzer check `test_T6C1.*`.
- **No tracked files edited; no git writes** on either machine. `runs/` is gitignored.
- **Not yet copied to `traces/`.** `raw/` is 67 MB and the three `.bin` files are about 15 MB each, so they get gzipped (spec T6). That's the planner's step.
