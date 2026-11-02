# Stage 1 first run, 29–30 Oct 2026: report for the planning agent

The session ran over two days:
- **Day 1 (29 Oct):** 17:51–18:40 UTC, raw data in `runs/stage1_20261029/`. It covered Parts 0–2, the VBUS jumper fix, and D4.
- **Day 2 (30 Oct):** 15:44–16:42 UTC, this folder. It covered D4 diagnosis and the pinmux investigation.

**Result in one line:** the meter works end to end, but the per-decision marker doesn't, because Jetson header pin 29 can't drive. Parts 3.4–6 (marker test M3, idle comparison, synthetic decisions, closed loop) weren't run.

> **Update, 30 Oct 17:26–17:50 UTC.** The fix session (`runs/stage1_20261030_fix/report.md`) restored the power mode with a warm reboot and moved the marker to pin 8 (UART1 TX), which passed M3. **Part 4 (M2) then ran in this folder: see "Part 4" at the end.** Points 2–3 below describe the state before those sessions.

The detailed marker problem statement is in **`pin29_problem.md`**. The user chose option C there, a persistent pinmux change; it needs your decision on permissions.

Tags: **V** = I ran it and saw the result. **V-user** = the user observed or reported it. **NV** = not verified. File paths are relative to this folder unless they start with `runs/`.

## Summary

1. **Part 1 confirmations.**
   - D1 and D2 held for the final layout; the 15 V reading was taken with the plug out of the Jetson; the plug was in the DC jack; the supply was off until asked; the marker wire was open at the Jetson end (all V-user, day 1).
   - **VIN+ to VBUS was 1.3 MΩ, so the jumper was open** (V-user). The first boot ran with power at an assumed 19 V.
   - The user then soldered the jumper closed, with the supply and the Pico unplugged: **0.01 Ω**. D1 and D2 were redone and held; the 19 V wires were still tight (V-user).
   - VBUS now reads 19.24 V at idle (V).
2. **Pin 29: it doesn't drive.** Details in `pin29_problem.md`.
   - `gpioset` high and low: rc 0 and the line shows as an output, but the pin reads **3–5 mV in both states** over three runs (V-user; board side V).
   - Released: **−6.9 mV** (V-user).
   - Method check: pin 1 reads 3.43 V (V-user).
   - **Cause:** the pad's output driver is disabled, `tristate=1` in pinctrl debugfs, released and while held (V). NVIDIA's `jetson-io` code classifies this state as "unused" (V, by reading).
   - **No header GPIO drives today;** only pin 8 (UART1 TX) does (V). The pin-to-pad table is from the devkit pinout (NV).
   - **`jetson-io` offers a `gpio` state for pin 29's group `extperiph3_clk`** (V by reading; not run).
   - **Not explained:** the released pin reads about 0 V although the pad's pull-up is on. Something on the carrier board sits between the pad and the header (NV). **Risk:** the pin may still not drive after a pinmux fix.
   - Toggle method and toggle cost: not reached.
3. **Idle power, INA228 against `VDD_IN`:** M2 wasn't run (no quiet board, no side-by-side sampler).
   - Spot values:
     - day 1: INA228 6.24–6.37 W (V);
     - day 2: **INA228 7.37–7.39 W and `VDD_IN` 5.62 W, both about 1.1 W above the earlier values,** because the power mode wasn't applied at today's boot (item 7) (V).
   - INA228 noise on day 2 (board not quiet: timers on, radio on, power mode not applied; a preview, not M2): sd of 10 ms / 1 s / 10 s means **149–154 / 104–112 / 49–67 mW** in the two quietest windows (V, `raw/C1_boot_summary.txt`).
   - The INA3221's last session, for comparison: 19 / 17 / 11.6 mW at 10 Hz on `VDD_IN`. That's a different boundary and a heavy low-pass filter, so the two aren't directly comparable.
4. **Synthetic decisions:** not run.
5. **Closed loop:** not run.
6. **Boot trace** (V):

   | | Day 1, boot 1 (jumper open, P at 19 V assumed) | Day 1, boot 2 | Day 2 |
   |---|---|---|---|
   | Peak conversion (1.08 ms) | 0.999 A at +28.8 s | 1.008 A at +29.8 s, VBUS 19.08 V | 1.008 A at **+5.8 s**, VBUS 18.72 V (min 18.63 V) |
   | Peak 10 ms / 1 s mean | 0.963 / 0.628 A | – | 0.950 / 0.636 A |
   | Above 2.5 A | never | never | never |
   | USB device / ssh | +29.6 s / +38.4 s | +29.3 s / +38.2 s | not timed (watcher bug, item 7); both up by +194 s |
   | Idle from about +40 s | 0.33 A, about 6.2 W | 0.33 A, 6.24–6.37 W | 0.38 A, 7.37 W (power mode not applied) |

7. **Unexpected:**
   - **`nvpmodel.service` failed at day 2's boot** (V). Its log: "Reboot required for changing to this power mode: 1", then "DO YOU WANT TO REBOOT NOW?", "bad input", exit 234.
     - `nvpmodel -q` still says 25W and `status` says `pmode:0001`, but the limits aren't applied:
       - CPU `scaling_max_freq` 1728000 (the 25 W conf has 1344000);
       - GPU `max_freq` 1020 MHz (conf 918 MHz);
       - **GPU governor `performance`, at 1020 MHz at idle.** On 26 Oct it was `nvhost_podgov` at 306 MHz.
     - That explains the +1.1 W. **The board isn't in its reference state, and no measurement should be taken until this is fixed.**
     - I changed no power or clock setting. The cause isn't known (NV). Day 1's boots can't be checked: only the current boot's journal exists. Day 1's lower idle suggests the mode applied then (NV).
     - **Possible link to the clock (NV):** day 2's boot came up at 1970, day 1's at 26 Oct. The `/etc/nvpmodel.conf` symlink has mtime 1970-01-01 01:16, from the 26 Oct session, which also ran with a 1970 clock.
   - **The INA3221's hwmon number changes between boots:** hwmon3, hwmon4, hwmon3 (V). The scratch sampler now resolves `/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*` and checks the name and labels (`scripts/sampler.py`; not yet run on the board).
   - **The board clock after a power cut** came up at 26 Oct (twice) and at 1970 (day 2) (V).
     - Syncing it starts catch-up jobs **in waves over at least 30 minutes**: 16:08:44 to after 16:39 on day 2, with apt-daily still running at the end. Waves: fwupd-refresh, apt-daily-upgrade, anacron, fstrim right after the sync; systemd-tmpfiles-clean 16:19:58; apt-daily-upgrade 16:27:38; anacron 16:30:15; apt-daily, apt-news, esm-cache from 16:33:24 (V).
     - **An empty `systemctl list-jobs` between waves doesn't mean the catch-up is over.**
   - **`logrotate.timer` doesn't exist on this board** (`not-found`, V), but it's on the brief's timer list.
   - **Spurious ALRT edges:** one at the supply plug-in (day 1), and two at about 16:16:21 on day 2, around when the user moved the live spare jumper from pin 1 to pin 29 (that timing link is NV). All three have CNVRF clear in DIAG_ALRT, so analyses can drop them; `capdec.py` now flags them. There was also one 0.12 µs GP16 pulse on the open marker wire at the day 1 plug-in (V).
   - **My boot watcher had a 15-minute limit counted from its start** and ended before the day 2 power-up, so that boot has no USB or ssh times (V). Fix: count the limit from power-up.
   - **One ssh "No route to host"** at 16:07:27, about 3 min after power-up. Ping and ssh worked 15–25 s later; cause not known (V).
   - Nothing unsafe was seen. No heat, smell or over-current was reported (V-user, nothing reported), and current never went above 2.5 A (V).
8. **Temp files and final state:** see "State at the end" below.

## Details

### The meter and capture path (V)
Scripts: `scripts/cap_pico.py`, `cap_host.py`, `capdec.py`, `capcheck.py`.
- **INA228:** as in the bench report §11 (400 kHz, ADCRANGE 0, SHUNT_CAL 4088, MODE 0xB 540/540 µs, AVG 1, DIAG_ALRT 0xC000). ENERGY and CHARGE are read once a second each.
- **One timebase for all three streams:**
  - three PIO state machines: ALRT falls, GP16 rises, GP16 falls;
  - one 25 MHz clock, 120 ns per count;
  - started in the same cycle;
  - the program layout makes the 515 s counter wrap clean.
  - Cross-check by injected `in x, 32`: 0–2 counts apart, at the start and end of every capture.
- **GP16 is never configured** (funcsel 31, OE 0, pad 0x56 before and after every capture).
- **Day 2 capture, 3148 s:**
  - 2 915 576 conversions, 0 missed, 0 sequence gaps, 0 framing errors;
  - Pico busy 53.9 %, longest handler 1039 µs;
  - **6 PIO wraps, each with normal intervals around it**;
  - **ENERGY register 14 828.28 J against summed P·dt 14 828.57 J** (−0.002 %).
- **Day 1:** CHARGE against summed current 1.0001; ENERGY −0.005 %.
- **Zero current** (supply off): −0.04 mA, sd 0.19 mA.
- **Headroom:** at 926 conversions/s the Pico is 54 % busy, which leaves room for the marker streams. Marker handling under load is untested.

### Part 3 (V unless marked)
- **Clock:** `sudo date -u -s` from the Mac at a full second, both days. Afterwards board − Mac = −0.04 to −0.07 s, as close as ssh round trips can measure.
- **Board identity:**
  - checkout `8d91a6d`, clean;
  - `src/` and `scenarios/` are unchanged on the Mac's `main` since then (`git diff --stat 8d91a6d HEAD -- src scenarios` empty);
  - the Jetson's USB device: vendor 0x0955, product 0x7020 "Linux for Tegra", serial `<jetson-serial>`, tty `/dev/cu.usbmodem<jetson-serial>21`.
- **D4:**
  - 3 runs: day 1 60 s and 90 s per level; day 2 120 s (`raw/board_tmp_jn_run1/d4.log`, `runs/stage1_20261029/raw/board_tmp_jn_run1/`);
  - pinmux reads: `raw/C1_pinctrl_released.txt`, `raw/C1_pinconf_groups_held_high.txt`;
  - survey: `raw/C1_header_pin_survey.txt`;
  - `jetson-io` facts: `raw/C1_jetsonio_*.txt`, `raw/C2_*.txt`.
- **The `sudo` commands used, all announced and approved by the user:**
  - `date -u -s` (×2);
  - `systemctl poweroff` (×2, day 1);
  - `grep -r -i -A 20 "pq5" /sys/kernel/debug/pinctrl/` (read-only);
  - `cat /sys/kernel/debug/pinctrl/2430000.pinmux/pinconf-groups` (read-only).

### Not run
- **M3** (marker test), blocked by pin 29.
- **Parts 4–6.** These block-level measurements don't need the marker (`pin29_problem.md` §7), but they do need the power mode fixed first.

## Decisions for the planner
1. **Power mode.** How to restore the 25 W configuration after `nvpmodel.service` failed:
   - a warm reboot, which is what nvpmodel's own prompt asks for and which keeps the clock;
   - or `sudo nvpmodel -m 1`, answering its prompt.

   Both are outside this session's allowed commands. Also: should every session check, after boot, that `systemctl is-failed nvpmodel` isn't failed, plus the GPU governor and the CPU `scaling_max_freq`? And should someone find out why it failed?
2. **Pin 29, option C:** the permissions it needs (`sudo` under `/boot`, a reboot, running `jetson-io` interactively, the serial console as a recovery path) and the verification order (`pin29_problem.md` §5–§6). A reboot for C could also cover decision 1.
3. **Session protocol:**
   - the catch-up waves last more than 30 min, so stop the timers right after the clock sync rather than waiting for an empty `list-jobs`;
   - remove `logrotate.timer` from the brief's list;
   - the watcher fix;
   - the Jetson's USB identity (above) can go into SETUP_NOTES §9.
4. **Whether to run Parts 4, 5a and 6 at block level** before the marker is fixed.

## State at the end (16:42 UTC, day 2)
- **Jetson:**
  - running and idle, still in the failed-nvpmodel state;
  - clock synced;
  - apt-daily and esm-cache catch-up jobs still running;
  - pin 29 released (unused input);
  - no `gpioset`, sampler, `d4.sh` or controller running;
  - timers untouched, all active (`logrotate.timer` doesn't exist);
  - radio untouched: enabled, Wi-Fi disconnected;
  - no tracked file changed; checkout `8d91a6d`, clean (V).

  Whether to shut it down is the user's decision, asked separately.
- **Pico:** `machine.reset()` at 16:38:05. Filesystem `[]`; GP16 funcsel 31, OE 0, pad 0x56, the reset state; plugged into the Mac (V).
- **Wiring:**
  - the marker wire is open at the Jetson end (V-user);
  - **the spare jumper is still on pin 29**, to be removed with the Jetson off (V-user);
  - the VBUS jumper is closed (V-user).
- **Repo:** no tracked file edited on the Mac. `git status` shows only the edits that were already there (V).
- **Temp files, not deleted:**
  - Mac `/private/tmp/jn_run1/`: `C1_boot.status.json`, `C1_snap.bin` (a 19.5 MB partial copy), `stop_C1_boot`, `pycache_mac/` (moved out of `scripts/`).
  - Board `/tmp/jn_run1/`: `d4.log`, `d4.out`, `hdr40_p3767.dts`, `scripts/d4.sh`. Copied to `raw/board_tmp_jn_run1/`.
  - Day 1's Mac scratch is gone: the Mac's `/private/tmp` was cleaned between the days, and it held only status files and copies.
  - `scripts/__pycache__/` was recreated by the last analysis; harmless.

## Part 4: quiet board, idle comparison (M2), 30 Oct 17:36–17:50 UTC

This ran after the fix session: 25 W restored, marker on pin 8, nothing writing to it. Files: `raw/P4_*`, `raw/board_P4/`, `scripts/m2_analyze.py`.

### Setup (V)
- **Pre-check:** nvpmodel `Result=success`, CPU max 1344000, GPU `nvhost_podgov` (918 MHz max, 306 MHz at idle), TPC/FBP masks 240/2, board clock −0.16 s against the Mac, no jobs, no apt/dpkg.
- **Quiet board:**
  - **12 maintenance timers stopped** at 17:39:13;
  - **Wi-Fi re-enable armed** at 17:39:15 (`run-r8b7802d6f42347ee8083f6cf65ea98c2.timer`, fires 19:09:15 UTC);
  - **radio off** at 17:39:16.

  The only timer left before 18:00 UTC was `fake-hwclock-save`, at 18:00:00.
- **Meters:**
  - INA228 capture `P4_m2` from 17:39:29;
  - INA3221 sampler at 10 Hz from 17:39:37 for 480 s. It found the sensor through `/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*` (hwmon3 this boot) and used 0.47 % of one core.
- **Window:** 5 min, 17:40:40.25 to 17:45:40.49 UTC, set by Mac marks (`raw/marks.csv`).
  - The INA228 data is selected by Mac arrival time, the INA3221 data by board realtime, which was within 0.16 s of the Mac.
  - No service or timer started in the window (journal).
  - Temperatures 49.2 → 48.5 °C, fan PWM 66 throughout.
  - INA228: 0 missed conversions, 0 spurious ALRT edges.

### Results (V)

| | Mean | sd per sample | sd of 10 ms means | sd of 100 ms means | sd of 1 s means | sd of 10 s means |
|---|---|---|---|---|---|---|
| **INA228**, board input at 19.26 V | **6362.3 mW** (330.32 mA) | 129.9 mW (1.08 ms) | 114.3 mW | 89.9 mW | 34.8 mW | 8.3 mW (5.6 detrended) |
| **INA3221 `VDD_IN`**, module input at 5.02 V | **4541.9 mW** | 3.0 mW (100 ms) | – | 3.0 mW | 1.5 mW | 0.5 mW |
| INA3221 last session (26 Oct, less quiet board) | 4546.5 mW | 19.0 mW | – | – | 17.1 mW | 11.6 mW |

- **Board input against `VDD_IN`:** INA228 − `VDD_IN` = **1820 mW**, and `VDD_IN` / INA228 = **0.714**. The 1.8 W is what the carrier board and its 19 V → 5 V conversion use outside the module's input (NV what it consists of).
- **The INA228's spread is the board's own activity, not meter noise.** The meter floor from the bench is 0.19 mA per conversion, which is 3.6 mW at 19.26 V and 0.12 mW for 1 s means. The measured sd is 130 mW per conversion and 35 mW for 1 s means.
- **Periodic load in the INA228 trace:** the 1 s means have their strongest periods at 5.3 s and 2.7 s, about 15 mW each. The journal shows two candidates, though the link is NV:
  - `dhcpd` renews the Mac's lease on the USB link every 6 s, since the lease is 15 s;
  - `systemd-resolved` retries DNS server 8.8.8.8 every 5 s, because there's no internet.
- **Drift:** −4.2 mW/min. The first minute averaged 6375 mW and the last 6355 mW. The board was still cooling slightly (NV as the cause).
- **The INA3221's small sd isn't low noise; it's blindness.**
  - `VDD_IN` read exactly 5024 mV × 904 mA in 2986 of 3003 samples, and 896 or 912 mA in the other 17. Its resolution is one 8 mA code, about 40 mW, and it low-passes over about 0.6 s, so it can't see the fluctuations the INA228 shows.
  - Last session's 19 / 17 / 11.6 mW came from a busier board (catch-up jobs, man-db), where the reading toggled between codes.
  - There are one-code blips about every 60 s in the window, at 29.5 s, 89.5 s and so on. The cause isn't found (NV).
  - `VDD_CPU_GPU_CV` read 442.2 mW, almost always one code. `VDD_SOC` read 1382.2 mW, toggling between two codes (272 and 280 mA).
- **Plot:** `raw/P4_M2.png`. Folded and spectral checks: `raw/P4_M2_extra.txt`, `raw/P4_M2_periodic.txt`.

### Implication for Part 5 (estimate, NV)
- The board's own activity is **114 mW sd in 10 ms means**, about 1.1 mJ per 10 ms window.
- A ±5 % CI on a 0.15 mJ decision (±7.5 µJ) by plain averaging of 10 ms windows would need about (1.96 × 1.14 mJ / 7.5 µJ)² ≈ 9 × 10⁴ decisions, against a baseline measured equally well. That's roughly 15 minutes or more per condition at 100 Hz.
- Shorter windows around the decision, and the periodic loads above, change this. Part 5 measures it.

### State after Part 4 (V)
- **Kept in the quiet state, for Parts 5–6 if they follow:**
  - **the 12 timers are still stopped;**
  - **the radio is still off,** and comes back on by itself at 19:09:15 UTC.
- **Nothing of mine running on the board.**
- **Pico:** `machine.reset()`, filesystem `[]`, GP16 reset state, reading 1 because the marker wire on pin 8 is high.
- **Board scratch** `/tmp/jn_run1/`: the sampler CSV, meta, log and pid, plus `scripts/`. Copied to `raw/board_P4/`.
- **Mac scratch** `/private/tmp/jn_run1/`: `P4_m2.status.json`, `stop_P4_m2`, and the earlier files.

## Part 5: synthetic decisions, 30 Oct 17:59–18:24 UTC

The planner's adapted brief for the pin 8 marker wasn't available yet. With the user's agreement I ran Part 5 as below, inside a 30-minute slot. Files: `raw/P5_*`, `raw/board_P5/`, `scripts/p5_decisions.py`, `scripts/p5_analyze.py`.

### Design (V)
- **Board script** (`p5_decisions.py`, standard library only), 100 Hz on an absolute `CLOCK_MONOTONIC` schedule:
  - sleep until about 300 µs before each slot, then spin to it;
  - write one `0xFF` to `/dev/ttyTHS1`: the falling edge of the start bit on pin 8 marks the decision start;
  - spin on `perf_counter_ns` for W;
  - sleep to the next slot.
- **Markers:**
  - no end byte, since at W = 0 it would queue behind the start byte's 87 µs frame. The board logs the start and end of its busy work instead;
  - one dummy byte after opening the port;
  - 5 s without markers between blocks.
- **Conditions:** W = 0, 0.1, 0.3 and 1 ms, 3 blocks of 60 s each (6000 decisions per block).
- **Order,** written before the start (`raw/P5_order.txt`): `PCG64(20261030).permutation`, giving W (µs) = **0, 0, 0, 300, 300, 300, 100, 1000, 1000, 1000, 100, 100**.

  This order isn't well mixed: all three W = 0 blocks come first and the 1 ms blocks are contiguous. A fixed seed was the rule, but drift therefore aliases into method (a).
- **Board state:** quiet, as in Part 4 (timers stopped, radio off). `fake-hwclock-save` ran at 18:00:10, before the first block, and nothing started during the run (journal).
- **Run:** 18:00:20–18:13:20 UTC; capture `P5` 17:59:22–18:13:31.

### Integrity (V)
- **Markers:**
  - 72 000 decisions written, **72 001 falls and 72 001 rises** captured (the decisions plus the dummy);
  - fall runs split as 1 + 12 × 6000;
  - 0 spurious ALRT edges, 0 missed conversions;
  - Pico busy 54.1 %, marker FIFO level 1 throughout.
- **Board timing:**
  - busy time p50 = W + 0.6 µs;
  - `write()` p50 6.0–6.3 µs (11.3 µs in block 11);
  - schedule lateness p99 1.0–1.3 µs, max 2.8–99.6 µs.

### Results (V, from `raw/P5_result.txt`)

Energy per decision above W = 0, 95 % CI (Welch, 3 + 3 blocks):

| W | (a) block means, (P_W − P_0) / 100 Hz | (b) decision-aligned |
|---|---|---|
| 0.1 ms | +71 µJ [−1, +144] | **+28.1 µJ [+22.5, +33.8]** |
| 0.3 ms | +26 µJ [−60, +112] | **+77.8 µJ [+75.2, +80.5]** |
| 1.0 ms | +330 µJ [+264, +396] | **+250.4 µJ [+241.6, +259.1]** |
| **Slope: active power above idle** | 320 mW (intercept −5 µJ) | **249 mW** (intercept +2.0 µJ) |

- **Method (b):**
  - each conversion is placed at its cycle centre and folded onto the time since the preceding marker edge;
  - per block: excess over the block's own quiet part (5.5–8.5 ms after the edge), integrated over −1 to +4.5 ms;
  - minus the mean of the W = 0 blocks.
- **Method (b) is about 25× tighter than (a) here.** The block means carry the board's slow drift. Block baselines range over 6353–6371 mW, about ±90 µJ per decision, and the unmixed order aliases it. Method (b) cancels the drift through each block's own baseline.
- **(b) is linear in W:** 0.1 ms × 249 mW + 2 µJ = 27 µJ predicted against 28.1 µJ measured. The 249 mW is one A78 core spinning, above the board's idle. The CPU frequency during the spin wasn't logged (schedutil; NV).
- **Plot:** `raw/P5_result_profiles.png`. The excess rises at the marker edge, plateaus at about 250–270 mW for W = 0.3 and 1 ms, and lasts W plus about 0.6 ms (the conversion's 1.08 ms cycle smears it). There's a small dip of about −15 mW at 1.7–2 ms and 3.8–4 ms in all conditions (NV why).
- **The W = 0 decision itself costs X_0 = 59.5 µJ** (sd 1.2 over 3 blocks) in the window, above the quiet baseline. It peaks at about 140 mW in the first 0.3 ms.

  That's the wake-up, the roughly 300 µs spin to the slot and the marker write. It cancels in the differences above, but it's part of what a real harness pays per decision.

### Decisions needed for ±5 % at W = 0.1 ms (method b)

| Basis | Per condition | At 100 Hz | |
|---|---|---|---|
| Block spread: SE of ΔE 1.68 µJ from 3 + 3 blocks of 6000 | **about 1 × 10⁵** | **about 16 min** | V; rests on 2 df per side, so uncertain by a factor of several |
| Per-decision sd (386 µJ with each decision's own baseline), decisions treated as independent | 5.8 × 10⁵ | 97 min | V, but pessimistic: the observed block-to-block spread is 6× smaller than independence predicts, so neighbouring decisions' values aren't independent (NV why) |

- **For the spec:** plan on the order of 10⁵ decisions per condition (15–20 min at 100 Hz) for ±5 % on a decision of about 28 µJ. That's 0.1 ms of one busy core.
- **A `centroid` decision** (about 90 µs of compute, but 0.15 mJ on `VDD_IN` in the pilot) would have a larger excess, so it needs fewer decisions (NV until Part 6).

### Not done
- Part 6, the closed loop.
- Repeats beyond 3 per condition.
- A better-mixed block order (for example a balanced Latin square), which would make method (a) usable.

## End of today's session (V, 18:24 UTC)
- **Restored:**
  - **timers started again,** all 12 active;
  - **radio on.** The transient `run-r8b7802d6f42347ee8083f6cf65ea98c2.timer` will still fire at 19:09:15 UTC and run `nmcli radio wifi on` again, which is harmless;
  - nothing of mine running on the board;
  - nvpmodel `Result=success`.
- **Pico:** `machine.reset()`, filesystem `[]`, GP16 funcsel 31, OE 0, reading 1 (the marker wire on pin 8 is high).
- **Wiring:** **the marker wire is connected, Jetson pin 8 → Pico GP16.** Take it off GP16 before the Pico is ever unplugged.
- **Jetson:** left running.
- **Temp files, not deleted:**
  - board `/tmp/jn_run1/`: Part 4 and 5 CSVs, logs and pids, `scripts/` (copied to `raw/board_P4/`, `raw/board_P5/`);
  - Mac `/private/tmp/jn_run1/`: status files, `stop_*` flags, `C1_snap.bin`, `P5_snap.bin` (partial copies), `pycache_mac/`.

### Shutdown (V, 18:25 UTC)
- **Before:** no apt/dpkg, no jobs (18:25:33).
- **`sudo systemctl poweroff`** at 18:25:38. The Jetson's USB device was gone by 18:25:40 and ssh no longer answers. The user then unplugs the supply.
- **Pico:** still enumerated and reset (filesystem `[]`). The marker wire from pin 8 to GP16 is still connected; it comes off GP16 before the Pico is unplugged.
