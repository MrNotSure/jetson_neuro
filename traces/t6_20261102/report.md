# T6 energy session, 2 Nov 2026: controller A (`classical`) against `hold`

Times are UTC. The session ran 11:15–15:10, with a lunch break from 12:33 to 14:00. Tags: **V** = I ran it and saw the result. **V-user** = the user did or reported it. **NV** = not verified. Paths are relative to this folder. Spec: `docs/spec_ctl_a.md` R9, task T6.

## Summary

**Design as run:** `track-sine-v1`, realtime, 60 s blocks. The order was idle I0, rounds 1–4 (capture C1), idle I50, rounds 5–20 (captures C2b and C3), and idle I99, with rounds in the 4-round cycle H A / A H / A H / H A (`raw/order.txt`). That is 20 rounds run. **18 rounds are usable under the brief's rule:** R9H and R18A each had one extra 0.12 µs edge on the marker line, so falls ≠ rows and both rounds are excluded. The Jetson was power-cycled during the lunch break, so rounds 1–4 ran on boot 1 and rounds 5–20 on boot 2.

### Main table (primary analysis: the brief's definitions; 18 rounds; t CI with 17 df)

| Quantity | Value | 95 % CI | Tag |
|---|---|---|---|
| **E_dyn(A), method (b), window [−1, 4.5) ms** | **+216.6 µJ** | [+183.5, +249.7] (±15.3 %) | V |
| E_dyn(A), (b), window [−2, 4.5) ms | +221.2 µJ | [+185.7, +256.8] | V |
| E_dyn(A), (b), window [−2, 5.5) ms (sensitivity) | +223.5 µJ | [+182.3, +264.7] | V |
| **E_dyn(A), method (a), (P_A − P_H)/f** | **+207.0 µJ** | [+180.5, +233.5] (±12.8 %) | V |
| X_H, [−1, 4.5) / [−2, 4.5) | 108.0 / 91.5 µJ | [86.8, 129.2] / [66.9, 116.1] | V |
| X_A, [−1, 4.5) / [−2, 4.5) | 324.6 / 312.7 µJ | [301.8, 347.5] / [291.1, 334.3] | V |
| Harness (P̄_H − P̄_I)/f | +181 µJ (18.1 mW) | [−30, +393], Welch df 2.5 | V; weak, see below |
| **E_tot(A) = P̄_A/f** | **63.823 mJ** | [63.790, 63.856] | V |
| … stack: idle floor P̄_I/f + harness + algorithm (a) | 63.435 mJ + 0.181 mJ + 0.207 mJ | | V |
| `VDD_IN` (a) E_dyn(A) | +318 µJ | [+278, +359] | V as measured; **not physical** (larger than at the input) |
| `VDD_IN` harness; E_tot(A) on `VDD_IN` | +50 µJ [−136, +236]; 45.80 mJ | | V |
| `n_events` per decision | H 404.4 (every block); A 157.5 (155.2–158.7) | | V |
| A's `ctl_us` on the board (includes the marker write, p50 12.7 µs) | p50 488 (479–496), p99 579 (565–588), max 1107–2721 µs | per-block ranges | V |
| H's `ctl_us` | p50 15.1, p99 22.8 µs | | V |
| A's tracking in the energy blocks | `rms_deg` 0.181° (0.175–0.184), in-FOV 1.000 in all 20 blocks, 0 losses, 0–4 misses per block | | V |
| Pinned core | `policy0` at 729.6 MHz in 99.5–100 % of 10 Hz samples, every block; tj 47.2–48.1 °C | | V |
| **Precision reached** | (b) ±15.3 %, (a) ±12.8 % | ±5 % would need 149 (b) / 105 (a) rounds; ±10 % 39 / 28 | V |

### The second figure: decisions overlapping a logger read excluded (chosen after seeing rounds 1–4)

The 10 Hz INA3221 sampler and `freqlog.py` cost about 0.47 mJ and 0.34 mJ per read, spread over about 5 ms. They aren't synchronised to the decisions, so each block's logger reads land at a random phase: sometimes inside the window, sometimes in the baseline. That's what spreads X from block to block (§ Drift). This variant drops every decision interval that overlaps an INA3221 read ([−1, +10) ms) or a `freqlog` read ([−2, +2) ms). That's 30–47 % of the intervals per block (mean 35 %); the board's monotonic clock was mapped to PIO time by a per-block fit, residual 44–62 µs. All other definitions are unchanged.

| Quantity | Value | 95 % CI | Tag |
|---|---|---|---|
| **E_dyn(A), (b, excl), [−1, 4.5) ms** | **+199.8 µJ** | [+192.7, +206.9] (**±3.6 %**) | V; post hoc |
| E_dyn(A), (b, excl), [−2, 4.5) / [−2, 5.5) ms | +201.2 / +201.9 µJ | [+183.5, +218.8] / [+179.3, +224.5] | V; post hoc |
| X_H / X_A, (b, excl), [−1, 4.5) | 111.8 / 311.6 µJ | [105.6, 117.9] / [305.5, 317.7] | V; post hoc |
| sd of D over rounds | 14.3 µJ (primary: 66.6 µJ) | | V |
| N for ±5 % / ±10 % | 11 / 5 rounds | | V |

**Sensitivity, deglitched** (`raw/result_deglitch.txt`): pulses under 1 µs are dropped before the falls are split into blocks. Each glitch is a single 0.12 µs pulse, and a marker byte's start bit is 8.68 µs. That keeps all 20 rounds:
- (b) +213.8 µJ [+184.1, +243.6];
- (a) +205.8 µJ [+181.8, +229.8];
- (b, excl) **+201.6 µJ [+194.7, +208.5] (±3.4 %)**.

**Per boot** (`raw/result_extra.txt`):

| | Boot 1 (rounds 1–4) | Boot 2 (14 rounds) |
|---|---|---|
| (b) | +207 µJ [+102, +313] | +219 µJ [+180, +259] |
| (b, excl) | +197 µJ [+178, +215] | +201 µJ [+192, +210] |
| (a) | +223 µJ [+119, +326] | +203 µJ [+173, +232] |

The boots agree.

**Reading the numbers.** Five figures all lie within 200–223 µJ: the primary (b), the primary (a), the logger-excluded (b), the deglitched set, and the per-boot values. The logger-excluded one is the most precise, at ±3.6 %. It wasn't pre-registered, so I report it next to the brief's figure, not in place of it.
- **What E_dyn contains.** It's A's step plus everything that differs between the two controllers in the closed loop. A gets 157 events per decision against `hold`'s 404 (R9.6), so its receive and decode cost is smaller. E_dyn understates A's own compute by that difference (size NV; T9 would remove it).
- **Against the rough expectation (NV in the brief): about 2× higher.** A's `ctl_us` is 473 µs longer than H's, so 200 µJ means about 420 mW above H while A computes. Part 5's busy core drew 249 mW. A's window profile peaks at about 390 mW against H's 185 mW (`raw/result_profiles.png`). Why the extra power isn't known (NV); numpy's memory traffic (EMC/DRAM) on top of the core is my leading guess.
- **The window holds (V).** A's excess is back near 0 by about 2 ms after the edge. The excess over [−2, −1) ms is −0.4 mW [−3.5, +2.8], and over [4.5, 5.5) ms +1.3 mW [−2.1, +4.7]; both are consistent with 0 (excluded variant: −1.0 [−2.2, +0.1] and −0.5 [−2.4, +1.3]). I didn't widen it. The [−2, 4.5) and [−2, 5.5) windows give the same answer within their CIs.
- **The harness CI is weak.** There are only 3 I blocks (6335.2, 6341.9 and 6353.4 mW) over two boots, so the Welch df is 2.5. The I blocks themselves move by 18 mW across the session, as much as the harness itself (18.1 mW). Per boot: boot 1 +174 µJ (one I block, no CI); boot 2 +166 µJ [−515, +846], df 1.1. The point value agrees with 31 Oct's 237 µJ [182, 292] to within that spread.
- **The idle floor includes the loggers.** They run in the I blocks too: at 10 reads/s each, about 4.7 mW (sampler) + 3.4 mW (`freqlog`), roughly 80 µJ of the 63.4 mJ (estimated from the folds in `raw/C1_logger_cost.txt`).
- **`VDD_IN` (V as measured, not usable for E_dyn).** A − H on `VDD_IN` is 31.8 mW against 20.7 mW at the 19 V input. `VDD_IN` is downstream of the input, so a ratio above 1 isn't physical. Boot 1 read 12.7–20.6 mW and boot 2 32.9–38.4 mW. One code is about 40 mW, and the INA3221's own sampling may alias with the 100 Hz load (cause NV). The 31 Oct session saw the same thing for H − I.

## Drift: did pinning fix X_H?

**The session-long fall is gone; the block-to-block spread isn't (V).**
- Every controller ran on core 2 (`taskset -cp` in every block, `raw/snapshots.txt`). `policy0` stayed at 729.6 MHz.
- X_H against round index: slope −3.1 µJ/round [−6.5, +0.4] (16 df). X_A: +0.4 [−3.6, +4.5]. D: +3.5 [−2.1, +9.1].
- On 31 Oct, unpinned, X_H fell 228 → 141 µJ over 4 rounds, about −29 µJ per round. Nothing like that today.
- **But X_H still ranged 33–189 µJ between blocks** (sd 42.6 µJ), against 112 µJ ± 12.4 µJ sd with the logger reads excluded.
- **The cause of the spread is the 10 Hz loggers (V).** With them excluded, the slopes are −0.49 [−1.56, +0.59] (X_H), −0.03 [−1.12, +1.06] (X_A) and +0.46 [−0.79, +1.70] µJ/round (D). The sd per block drops from 42.6 to 12.4 (X_H), from 46.0 to 12.3 (X_A) and from 66.6 to 14.3 µJ (D). `raw/C1_phase_diag.txt` shows the sampler's read phase within the period differing from block to block (0.5–9.5 ms), because each `jn-sim` run starts at an arbitrary time.
- Whether the same mechanism also explains 31 Oct's drift is NV. The sampler ran then too, but a monotonic fall over 4 rounds would need a slowly moving phase, not a random one.
- So pinning can't be credited on its own. The 31 Oct drift didn't recur, and pinning removes one candidate cause (NV).

## For the planner

**Is ±5 % realistic?** Not with the loggers running during blocks. Under the brief's analysis, sd_D is 67 µJ, so ±5 % of 217 µJ takes about 150 rounds (about 6 h). Without the logger noise, sd_D is 14 µJ, so about 11 rounds (about 27 min) give ±5 % on a 200 µJ difference. N scales as (sd_D / 0.05 m)², so a controller that differs from `hold` by 50 µJ would need about 16× more.

**Block design for B–D:**
- **Don't run the 10 Hz INA3221 sampler or `freqlog` during H/X blocks.** Take a `freq` and `VDD_IN` snapshot before and after each block instead (`t6_run.py` already does). Alternatively, pre-register the logger exclusion used here. Either way, `VDD_IN` method (a) would then need its own blocks, and today it wasn't usable for differences this size anyway.
- **Keep everything else:** fresh pinned process per block, dummy byte, counterbalanced 4-round cycle, window [−1, 4.5) ms with baseline [5.5, 8.5) ms. Check the window against each new controller's profile; a step longer than about 3 ms needs a later baseline.
- **I blocks:** if the harness matters, put one I block in every round, or every second round. Two or three per session give a CI wider than the value, and I drifted 18 mW over the afternoon.
- **One capture per 4-round chunk.** A capture that dies (C2b) then costs at most a chunk. `cap_host.py` aborts on the first framing error.
- **Mac:** on AC, lid open, `caffeinate -ims` running, and nobody touches the charger during a capture. Both of today's capture-level problems came from the Mac's power.
- **Marker integrity:** `t6_check.py` now reports pulse widths. A rule that drops pulses under 1 µs should be pre-registered, or the cause of the 0.12 µs pulses fixed (§ What broke 6).

**Spec R9 points that turned out wrong or incomplete:**
- **R9.4** asks for the CPU frequency "at 10 Hz (in the INA3221 sampler)", and R9.1 for `VDD_IN` alongside. Logging at 10 Hz during the blocks is what limits the precision. A frequency check before and after each block would have been enough: `policy0` sat at 729.6 MHz 99.5–100 % of the time.
- **R9.6's `VDD_IN` comparison** doesn't work at the 20 mW level: the result is larger than at the input.
- **R9.3's cap** (40 min) can't reach ±5 % with today's spread. It would with the logger noise removed.
- **The brief's expected E_dyn** (about 110 µJ from 249 mW × 0.45 ms) is low by about 2×. Part 5's busy-loop power per core doesn't transfer to numpy work.
- **R9.6 asks for E_tot as a stack.** The harness part of that stack can't get a useful CI from two or three I blocks.

## What broke

1. **The first clock sync was off by 0.77 s (V).**
   - `sudo date -u -s @T` with T taken on the Mac ran about 0.8 s later, because of ssh plus sudo latency.
   - A relative step (`date -u -s '+0.785 seconds'`, `scripts/clocksync.py`) fixed it. Board − Mac was −0.015 s at 11:48 and −0.003 s after the second boot.
   - Most of the morning's −1.004 s was probably the T5 sync itself (NV).
2. **The Mac slept during the lunch break, and capture C2 lost about 110 600 conversions (V).**
   - The lid was closed on battery: clamshell sleep at 12:31:32, maintenance sleep at 12:32:56, about 60 s each, matching the two conversion gaps (`raw/C2_lunch_capture.txt`).
   - No block ran on C2, and it isn't used.
   - Fix: `caffeinate -ims -t 10800` from 13:56 to 15:06, with the lid open.
3. **The Jetson was power-cycled by pulling the supply during lunch (V-user).**
   - It came back about 13:50:01 with the clock 3012 s behind.
   - I stopped the six timers first, then stepped the clock, in one ssh call. The user had removed the sudo prompt and asked me to set the board up again.
   - anacron had started at boot and ran `cron.daily` and `cron.weekly` at 13:55:12 (1 s, before any block).
   - The board's `/tmp/jn_t6` was gone. C1's files had been copied before lunch; C2's sampler and `freqlog` files and the board log after 12:24 were lost.
   - **The Pico was re-plugged with the marker wire on GP16 while the Jetson was off (V-user).** It came back as `/dev/cu.usbmodem101`, having been `…1101`. Rule 5 says the wire comes off GP16 before the Pico is ever unplugged. Pin 8 wasn't driving at re-plug. Whether the Jetson was still on when the Pico was unplugged is NV.
4. **The charger came out at 14:24:40, during R11A (V; V-user that it was unplugged).**
   - At 14:24:37: 4 extra ALRT edges and a Pico FIFO backlog of up to 4.
   - A grid check (`raw/C2b_gridcheck.txt`) shows **0 conversions missed**; the extra edges lie 142–183 µs after a slot.
   - I paused after round 12 and asked. The user reconnected it.
5. **The charger going back in, at 14:39:23, ended C2b (V).**
   - 10 glitch edges on GP16 and an exception in the Pico script: the host saw `INA228 reset` and the start of a traceback, so it stopped on "framing lost".
   - The traceback text wasn't saved (`raw/C2b_host_crash.txt`). The cause is probably a USB or ground transient (NV).
   - No block was running. C2b has no trailer, but its data up to that point decode cleanly. Rounds 13–20 and I99 ran in a new capture, **C3**.
6. **Two 0.12 µs GP16 pulses ended two blocks under the falls = rows rule (V).**
   - R9H at 14:19:34 and R18A at 14:55:54. Each came 8.76 µs after a real marker fall, so exactly at that pulse's rising edge.
   - Also, two single extra ALRT edges arrived at marker edges: R6A at a fall (14:10:02), and C3 at a rise (14:43:54).
   - **None in the morning** (S0, C1: 0 of 49 009 edges). **All in the afternoon**, after the Pico was re-plugged into another socket. My guess is ringing or crosstalk on the unterminated marker wire next to GP17, perhaps after the wiring moved (NV).
   - The glitch list is in `raw/glitch_summary.txt`; the deglitched sensitivity is above.
7. **The 10 Hz loggers limit the precision** (§ Drift). This is a design issue, not a failure.
8. **Time:** each of the two morning sudo prompts took 13–15 min to be approved, and the 1.5 h box was extended by the user (V-user).
9. **jn-sim:** 0–4 misses and a few sends over 5 ms late per block; they were flagged and excluded, as on 31 Oct. The analysis uses 99 %+ of the conversions in each block.

## Details

### Part 0 (V; `raw/state_start.txt`, `raw/state_reboot.txt`)
- **Boot 1** (cold boot 09:27, handed over):
  - 25 W mode: `Result=success`, CPU max 1344000 on all cores, GPU `nvhost_podgov` 918 MHz, TPC/FBP masks 240/2 (REAL = CONF, `raw/nvpmodel_verbose.txt`);
  - six timers inactive, radio `disabled`, `multi-user.target`, `pgrep -x` clean, no jobs;
  - `dialout` in `id`; checkout `0c397e1`, clean; Python 3.12.3, numpy 2.5.4.
  - The board's `src/` and `scenarios/` match the Mac's `main` (`cbcae21`) by md5, 26 files.
- **Boot 2:** the same checks pass again (`raw/nvpmodel_verbose_reboot.txt`). The INA3221 is now at hwmon4.
- **Answers (V-user):**
  - marker wire on GP16 (pin 8) and pin 30 on Pico GND; no series resistor; nothing else on the header;
  - Mac apps closed except Kiro;
  - serial console closed. `lsof` showed no process with the console port open (V).

### Part 1 (V)
- **`mark_ctl.py`:** `classical` added to `--controller`; nothing else changed (the diff is two lines).
- **The smoke block's metadata** reads `classical`, the default parameters, `git_sha 0c397e1`, `git_dirty false` (`raw/S0_meta_check.txt`).
- **Smoke test S, capture S0** (`raw/S0_check.txt`):
  - falls = rows = OBS = 1000, plus a lone dummy 2.54 s before the first decision;
  - 0 missed conversions; pulse widths 8.64–8.88 µs;
  - `ctl_us` p50 487 µs; affinity 2.

### Parts 2–3 (V)
- **Captures:**

  | Capture | Time | Content | Conversions | Missed | Extra ALRT | FDEBUG |
  |---|---|---|---|---|---|---|
  | C1 | 12:12–12:24 | I0, rounds 1–4 | 694 623 | 0 | 0 | 0 |
  | C2b | 14:05–14:39 | I50, rounds 5–12 | 1 899 255 | 0 | 5 | no trailer |
  | C3 | 14:42–15:04 | rounds 13–20, I99 | 1 199 387 | 0 | 1 | 0 |

  Checks: `raw/*_capcheck.txt`, `raw/*_check.txt`.
- **Every usable block:** falls = rows = OBS = 6000; k matches; `n_events` agrees; each dummy is a lone edge 1.3–2.5 s before its block; affinity 2.
- **Loggers:** the INA3221 sampler (10.000 Hz, 0.6 % of one core) and `freqlog.py` ran on core 5 throughout each capture, I blocks included.
- **Sizing:** recomputed after rounds 4, 8 and 16: N for ±5 % was 161, 94 and 134 rounds. So all 16 extra rounds ran, about 39 min of blocks including gaps.
- **Analysis:**
  - `scripts/t6_analyze.py` → `raw/result.txt`, `raw/result.json` and `raw/result_profiles.png`;
  - the deglitched run → `raw/result_deglitch.*`;
  - interim analyses → `raw/result_C1.*`, `raw/result_r8.*` and `raw/result_r16.*`.
  - Mac unix − monotonic is taken per capture from its `chunks.csv`, because the Mac's monotonic clock stopped during the lunch sleep.

### Scripts (`scripts/`)
- **Copied from `traces/stage1_20261031_final/scripts/`,** with paths adapted:
  - `cap_*`, `capdec`, `capcheck`, `picolink`, `pico_state`, `sampler`, `mark`, `uart_marker`, `ina_common`, `clockcheck`, `b`, `log`;
  - `mark_ctl.py`, with `classical` added;
  - `mc_start.sh`, now with `taskset -c 2` and the affinity reported; `mc_wait.sh`.
- **`freqlog.py`** (from T5): stops on SIGTERM and flushes a `.part` file.
- **New:**
  - `t6_run.py`, from `p2_run.py`: affinity check, safety checks, capture tags;
  - `t6_check.py`, from `p2_check.py`: pulse widths;
  - `t6_analyze.py`, from `p6_analyze.py`: logger-excluded variant, drift, sizing, per-boot harness, deglitch option;
  - `clocksync.py`, `phase_diag.py`.
- Every command, including those inside board scripts (`board-script` lines) and every `sudo`, is in `commands.log`.

## End state (V, 15:06)
- **Jetson:** running on boot 2, up 1 h 15 min; left on (no poweroff asked).
  - `multi-user.target`; radio `disabled`; `nvpmodel` success; tj 48.3 °C;
  - **the six maintenance timers are still stopped** (inactive) until the user decides; `fake-hwclock-save` active; the six disabled timers inactive and disabled;
  - no jobs, no apt/dpkg, nothing of ours running, port 5555 closed.
- **Pico:** `machine.reset()` at 15:05, on `/dev/cu.usbmodem101`. Filesystem `[]`; GP16 funcsel 31, OE 0, pull-down, reading 1 (pin 8 high) (`raw/pico_state_end.txt`).
- **Wiring (V-user):**
  - **marker wire connected, Jetson pin 8 → Pico GP16;** pin 30 → Pico GND; no series resistor;
  - take the wire off GP16 before the Pico is ever unplugged.
- **Mac:** on AC; `caffeinate` stopped at 15:06.
- **Temp files, not deleted:**
  - board `/tmp/jn_t6/` (14 MB, 114 files; copied to `raw/board/`; lost at the next reboot);
  - Mac `/private/tmp/jn_t6/`: status and `.out` files, `stop_*`, md5 lists, and an analyzer dry run (`test_S0.*`).
- **No tracked files edited; no git writes.** `git status` is clean on both machines, and `runs/` is gitignored.
- **Not yet copied to `traces/`** (spec T6: gzip above 5 MB). That's the planner's step.
