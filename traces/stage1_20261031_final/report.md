# Stage 1 final session, 31 Oct 2026: quiet board, then the closed loop

Times are UTC. The session ran 12:49–13:55. Tags: **V** = I ran it and saw the result. **V-user** = the user did or reported it. **NV** = not verified. Paths are relative to this folder.

## Summary

1. **Service plan (§8.1) applied, and it survives a reboot (V).**
   - **Disabled, all 15 units:**
     - `docker.service`, `docker.socket`, `containerd`, `bluetooth`, `nvargus-daemon`, `iperf3`, `saned.socket`, `gnome-remote-desktop`, `ModemManager`;
     - the timers `apt-daily`, `apt-daily-upgrade`, `motd-news`, `update-notifier-download`, `update-notifier-motd`, `fwupd-refresh`.
   - **Also changed:** the default target is now `multi-user.target`, and the radio is off with no timed re-enable.
   - **Skipped:** none; every unit existed.
   - **After the warm reboot:**
     - no gdm, Xorg or gnome-shell is running;
     - every disabled unit is `inactive disabled`;
     - `systemctl --failed` is empty, both before and after;
     - running services went from 43 to 28.
   - **Idle, 5 min, before → after.** The days differ and the board was about 3–4 °C cooler today, so part of the saving may be temperature (NV).

     | | 30 Oct (Part 4) | 31 Oct, plan applied | Δ |
     |---|---|---|---|
     | INA228, 19 V input | 6362.3 mW | **6290.8 mW** | −71.5 mW |
     | INA3221 `VDD_IN` | 4541.9 mW | **4509.0 mW** | −32.9 mW |
     | sd of 10 ms / 100 ms / 1 s / 10 s means (INA228) | 114.3 / 89.9 / 34.8 / 8.3 mW | **100.4 / 80.8 / 33.5 / 7.4 mW** | |
2. **Closed loop, `centroid` (C) against `hold` (H), 4 interleaved rounds of 60 s (V).** The four rounds are paired. CIs are t with 3 df.

   | | Value | 95 % CI | Usable? |
   |---|---|---|---|
   | **(b) C − H**, window [−1, 4.5) ms | **+15.3 µJ** | [−42.2, +72.8] | Not resolved from 0 |
   | (b) C − H, window [−2, 4.5) ms | +10.9 µJ | [−41.4, +63.3] | Same |
   | (a) C − H, block means | +5.1 mW = **+51 µJ** per decision | [−50, +152] µJ | No, too wide |
   | (a) H − I, block means | +23.7 mW = **+237 µJ** per decision | [+182, +292] µJ | Yes; but I came first in every round |
   | `VDD_IN` (a) C − H | +1.8 mW = +18 µJ | [−43, +78] µJ | No; quantised (one code ≈ 40 mW) |

   Per round, (b) C − H was −37.9, +28.2, +28.3 and +42.7 µJ.
3. **X_H = 172.4 µJ [110.4, 234.4] (V),** about 3× Part 5's X_0 = 59.5 µJ. X_H fell steadily across the rounds: 228.5, 167.7, 152.8, 140.7 µJ. X_C stayed put: 187.7 µJ [177.0, 198.5], sd 6.8 µJ. The spread of X_H is what limits C − H. Its cause is NV (see "What broke").
4. **E_tot per decision (V):** block mean divided by the decision rate (100.000 Hz):
   - H: 63.11 mJ [63.03, 63.19];
   - C: 63.16 mJ [63.11, 63.21].

   The marked part of a decision is only about 0.3 % of that.
5. **The window [−1, 4.5) ms held up (V).** The pre-edge rise starts only about 0.5 ms before the marker edge (`raw/P2_result_profiles.png`). Over [−2, −1) ms the excess is +1.8 mW [−8.9, +12.5] for H and −3.3 mW [−9.1, +2.5] for C, both consistent with 0. Both windows are reported above.
6. **Precision (V, from the 4 rounds; all projections use z, NV).**
   - **Achieved:** the (b) C − H half-width is 57.5 µJ (t, 3 df), 375 % of the point estimate.
   - **±5 % / ±10 % of C − H:** about 5 × 10⁷ / 1.3 × 10⁷ decisions per condition. That isn't meaningful, because C − H isn't resolved from 0.
   - **Absolute targets** (round-to-round sd of C − H: 36 µJ):

     | Half-width | Rounds of 60 s | Decisions per condition |
     |---|---|---|
     | ±20 µJ | 13 | 7.5 × 10⁴ |
     | ±10 µJ | 50 | 3.0 × 10⁵ |
     | ±5 % of X_C (±9.4 µJ) | 57 | 3.4 × 10⁵ |
     | ±10 % of X_C (±18.8 µJ) | 14 | 8.6 × 10⁴ |
   - **One controller's X alone** (X_C, sd 6.8 µJ per block): ±5 % takes about 2 blocks.

   Details: `raw/P2_precision.txt`.

## For the planner

### SETUP_NOTES edits needed
- **§8.1:**
  - "Not applied yet" becomes "Applied 31 Oct 2026, verified after a reboot"; §9's "Apply the service plan" can be ticked.
  - Move `udisks2`, `upower`, `colord` and `power-profiles-daemon` from "always on" to "with the desktop". They don't run under `multi-user.target`; `udisks2` and `power-profiles-daemon` are wanted by `graphical.target`.
  - Also gone with the desktop: `accounts-daemon`, `packagekit`, `switcheroo-control`, and gdm's user session `user@121`.
  - New: `getty@tty1`.
  - `rtkit`, the NVIDIA helpers and the rest of the always-on list still run.
- **§8.3, step 1:** the list becomes the six maintenance timers only: `anacron`, `man-db`, `fstrim`, `e2scrub_all`, `dpkg-db-backup`, `systemd-tmpfiles-clean`. The other six are disabled. "Start the same list again at the end" means those six; a `start` of the disabled ones would run them until the next boot.
- **§8.3, "During measurements":** the radio is now off permanently, so drop "with a timed re-enable armed first". When internet is needed: `sudo nmcli radio wifi on`, then off again.
- **§7.5:**
  - this cold boot came up at **1970** again: fake-hwclock still doesn't hold (§9 open item);
  - the warm reboot came back **34.06 s behind** (30 Oct: 31 s).
- **§7.7 / §9:** this cold boot started at 1970 and `nvpmodel` gave **`Result=success`**. A 1970 start alone doesn't make nvpmodel fail.
- **Boot times, new data:**
  - cold boot: ssh up 37 s after power-up;
  - warm reboot: ssh up 49 s after the command (30 Oct, with the desktop: about 3 min). That it's faster because of `multi-user.target` is plausible, NV.
- **§8.2 or `docs/stage1_wiring.md`:** connect the marker wire before the Jetson powers up. If it goes on while a capture is running, restart the capture afterwards. The contact bounce overflows the PIO edge FIFOs and offsets every later edge timestamp in that capture (see "What broke").
- **Rescue path:** there's no Ethernet cable at the bench, and HDMI wasn't confirmed. Part 1 ran without a fallback, with the user's agreement.

### Block design for controller A
- **Interleaved 60 s blocks:**
  - A against a reference (`hold` or `centroid`), with a fresh controller process per block, one dummy byte, then one marker byte per decision;
  - **counterbalance the order** (for example ABBA / BAAB, so each condition is first equally often) instead of a free permutation;
  - **one I block per round is optional:** H − I is now known (237 µJ [182, 292]), and it costs a third of the time.
- **Pin the controller to one core** (`taskset -c N`; `ctl_start.sh` already has `CTL_TASKSET`). Log the core and both clusters' `scaling_cur_freq` per block. My leading guess for X_H's drift is unpinned core placement (NV).
- **Analysis: method (b), as in `scripts/p6_analyze.py`:**
  - window [−1, 4.5) ms, baseline [5.5, 8.5) ms;
  - use periods of 8–15 ms only, and drop flagged ones (≤ 0.4 % of decisions here).
  - If A's step lasts longer than about 3 ms, move the window end and the baseline. At 10 ms periods, a step over about 4 ms leaves no room for a baseline.
- **Size:**
  - with today's spread, about 13 rounds per condition for ±20 µJ, or 50 for ±10 µJ;
  - if pinning brings H's spread down to C's (sd 6.8 µJ), a few rounds would do (NV);
  - run 4 rounds first, then size the rest from the measured spread.
- **Closed-loop confound:** the event count depends on the controller. `hold` doesn't track, so its OBS carry 404 events on average, against 262 for `centroid`. C − H therefore mixes compute with receive/decode differences. Report `n_events` with the energy, or decide whether A should also be measured open-loop on replayed OBS.
- **`ctl_us` now includes the marker write,** for both controllers:

  | | H | C |
  |---|---|---|
  | `ctl_us` p50 | 22–30 µs | 108–115 µs |
  | marker `write()` p50 | 14.5–19 µs | 14.5–19 µs |
  | first decision's `write()` | 34–62 µs | 34–62 µs |

  The write is slower than the 5–12 µs in `docs/stage1_wiring.md`. The first write after the dummy is still slow.

### What broke
1. **The marker wire went on after power-up.** The plan said before, and I missed it in Part 0 step 2.
   - It went on at 13:00 with the Jetson running and GP16 an input. That's safe, and the 30 Oct fix session did the same.
   - In capture `P01`, the contact bounce (206 rises, 203 falls) **stalled PIO SM1/SM2 on full FIFOs** (FDEBUG 0x06; edge counters 15.3 / 14.2 ms behind at the end). Every later edge timestamp in `P01` is offset.
   - `P01` was used only for power, so no result is affected. `P2` is clean: FDEBUG 0, sync offsets 0/1 counts, marker FIFO level 1.
2. **The fixed seed gave a poorly mixed order:** `PCG64(20261031)` produced I H C, I H C, I C H, I H C. I is first in every round, and H precedes C in three of four.
   - This aliases position-in-round into (a) H − I. The I means show no trend (6287.6, 6282.7, 6284.7, 6294.7 mW), so the bias is probably small (NV).
   - I kept the order, as the rule says.
3. **X_H drifted downward over the session; X_C didn't.** The peak segment [0, 0.5) ms fell from 255 to 227 mW, and the quiet part [1, 4.5) ms went from about +8 to −9 mW against the baseline.
   - It isn't the OBS content: the scenario is deterministic and `n_events` is identical in every H block.
   - It isn't temperature: `tj` 45.8–46.7 °C and fan PWM 55–60 across all block snapshots.
   - Not checked: which core each fresh process ran on, and the CPU frequency during the block (only snapshots between blocks). NV.
4. **The post-reboot clock sync waited about 10 min for approval** (13:10 → 13:20). The timers ran unstopped for that time. Only `anacron.timer` fired, at boot (13:09:15), and nothing ran during the idle window apart from `dhcpd` and `systemd-resolved` (journal).
5. **The INA3221 can't resolve these differences.** I blocks read one code (4508.7 mW) in 3 of 4 rounds. `VDD_IN` H − I came out at +33.3 mW, more than the INA228's +23.7 mW at the input, which isn't physical. That's quantisation.
6. **jn-sim:** 0–5 misses and 5–18 sends over 5 ms late per 60 s block, in bursts (for example k 4231–4237). These are on the Mac side. They were flagged and excluded.

## Details

### Part 0 (V)
- **Pico:** the only Pico port is `/dev/cu.usbmodem1101`. Filesystem `[]`; GP16 funcsel 31, OE 0, pull-down, read 0 with the Jetson off (`raw/P0_pico_state.txt`).
- **Answers (V-user):**
  - the marker wire was off GP16 and GND was connected;
  - no Ethernet cable;
  - wiring as documented, with nothing else stated;
  - serial console closed;
  - series resistor: **none** (user, after the session: none available). The wire is a direct connection, so the two rules in `docs/stage1_wiring.md` ("Marker wire") carry the protection.
- **Cold boot:** capture `P01` started first, with the over-current alarm at 1.5 A. Peak 1.006 A; ssh up 37 s after power-up (`raw/P0_boot_watch.txt`).
- **Before the sync** (`raw/P0_before_sync.txt`): board `1970-01-01 00:01:20 UTC`, `uptime -s` 1970-01-01 01:00:18 (local), `nvpmodel` `Result=success`.
- **Clock and timers:** sync at 12:56:44; the 12 timers were stopped 2 s later. `dpkg-db-backup` and `e2scrub_all` had already started in those 2 s and finished on their own. Board − Mac = −0.018 s.
- **Power mode passes, both boots** (`raw/P0_power_mode_check.txt`, `raw/P1_after_reboot_check.txt`):
  - `Result=success`;
  - CPU max 1344000 on `policy0` and `policy4`;
  - GPU `nvhost_podgov`, 918 MHz max;
  - TPC/FBP 240/2, both REAL and CONF.
- **Board checks:**
  - INA3221 on hwmon4 (hwmon3 after the reboot);
  - `dialout` in `id`;
  - `~/jetson_neuro` at `8d91a6d`, clean;
  - Python 3.12.3, numpy 2.5.4;
  - the board's `jn_sim` `ctl/testctl/protocol/provenance` match the Mac's (md5).

### Part 1 (V)
- **Rollback list:** `raw/services_before.txt`. After-state: `raw/services_after.txt`. Diff: `raw/services_diff.txt`. Command output: `raw/P1_apply.txt`.
- **Boot path:** `ssh`, `nv-l4t-usb-device-mode`, `nvpmodel`, `nvfancontrol` and `NetworkManager` are all `WantedBy=multi-user.target` (`raw/P1_bootpath_check.txt`).
- **Reboot** (`raw/P1_reboot_watch.txt`): USB gone at +5.9 s, back at +39.4 s, ssh at +48.7 s.
- **Idle window 13:23:55.6–13:28:55.6** (`raw/P1_M2.txt`, `raw/P1_M2.png`):
  - 277 904 conversions, 0 missed, 0 spurious;
  - V 19.2496 V;
  - drift −2.2 mW/min;
  - INA228 − `VDD_IN` = 1781.8 mW (30 Oct: 1820);
  - `VDD_IN` read 2 distinct values; sampler CPU 0.48 % of one core;
  - temperatures about 45.6–46.1 °C, fan PWM 55.
- **Periodic loads: still there** (`raw/P1_M2_periodic.txt`, same method as 30 Oct; reported, not investigated):

  | Period | 31 Oct | 30 Oct |
  |---|---|---|
  | 5.36 s | 18.0 mW | 15.9 mW (at 5.26 s) |
  | 2.70 s | 10.4 mW | 12.9 mW (at 2.65 s) |

  The median spectral bin is 2.4 mW.

### Part 2 (V)
- **Integrity** (`raw/P2_check.txt`, `raw/P2_capcheck.txt`):
  - capture `P2`, 970 s: 898 366 conversions, 0 missed, 0 spurious, FDEBUG 0;
  - falls = rises = 49 009 = 1001 (smoke test) + 8 × 6001. For every block, falls = `mark_ctl` rows = OBS = 6000, k matches, and `n_events` agrees;
  - each dummy is a lone edge 1.40–1.74 s before its first decision;
  - excluded blocks: none.
- **Smoke test S,** 10 s `hold`: 1000 / 1000 / 1000, 0 missed conversions, 1 sim miss.
- **Order:** `raw/order.txt`, written at 13:29:10 before the first block.
- **Runs:**
  - blocks 13:32:29–13:46:48: `raw/P2_blocks.json` and `raw/P2_snapshots.txt` (temperature, fan, frequencies and `pgrep` before and after each block);
  - sim runs in `sim/`;
  - one 10 Hz sampler over all of it (9648 samples).
- **Results:** `raw/P2_result.txt` (per block, with excess by segment), `raw/P2_result_profiles.png`.
  - The profile peaks at about 270 mW (H) and 295 mW (C) about 0.25 ms after the edge, and is back near the baseline by about 1.5 ms. C has a small extra tail at 1–1.5 ms.
  - Edge intervals were 8–15 ms for all but 14–76 per block. Conversions used: 99.0–99.7 %.
- **Method (b)** as in Part 5, plus the variable-period rules from the brief. A conversion between two edges is used only if that interval is 8–15 ms and neither edge is flagged. Block means in (a):
  - H/C: [first fall + 3 s, last fall − 3 s];
  - I: [mark + 4 s, mark − 4 s], mapped to PIO time by a fit of arrival time (residual 2.8 ms).

### Scripts (`scripts/`)
- Copied from the 30 Oct sessions:
  - `cap_*`, `capdec`, `capcheck`, `picolink`, `pico_state`, `sampler`, `mark`, `m2_analyze`, `p5_analyze`, `clockcheck`, `winmean`, `uart_marker`, `watch_*`, `ctl_*`;
  - changes: scratch path, alarm at 1.5 A, and the boot watcher's limit now counts from power-up.
- New:
  - `mark_ctl.py` (the planner's, verbatim);
  - `mc_start.sh`, `mc_wait.sh`, `p2_run.py`, `p2_check.py`, `p6_analyze.py`, `p1_periodic.py`.
- Commands run inside board scripts are appended to `commands.log` as `board-script` lines.

## End state (V, 13:50)
- **Jetson:** running, uptime 40 min, left on (no poweroff asked).
  - `multi-user.target`; radio `disabled`;
  - six maintenance timers and `fake-hwclock-save` active; six refresh timers inactive and disabled;
  - `nvpmodel` success; no jobs, no apt/dpkg;
  - nothing of mine running; port 5555 closed.
- **Pico:** `machine.reset()` at 13:49:47. Filesystem `[]`; GP16 funcsel 31, OE 0, reading 1 (pin 8 is high).
- **Wiring:** **marker wire connected, Jetson pin 8 → Pico GP16;** pin 30 → Pico GND. Take the wire off GP16 before the Pico is ever unplugged. **No series resistor** (V-user: none available), so that rule and "GP16 is never an output" are the only protection.
- **Temp files, not deleted:**
  - board `/tmp/jn_final/` (copied to `raw/board/`; lost at the next reboot);
  - Mac `/private/tmp/jn_final/`: status files, `stop_P01`, `stop_P2`, `*.out`.
- **No tracked files edited.** The only git commands were the read-only `rev-parse` / `status` on the board from the Part 0 checklist.
