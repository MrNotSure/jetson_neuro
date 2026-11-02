# Stage 1 fix session, 30 Oct 2026: power mode restored, marker on pin 8 works

The session ran 16:58–17:26 UTC and followed the planner's "Stage 1 fix session" with one change. **At the start the user chose option A, pin 8 (UART1 TX), as the marker instead of `jetson-io`.** So Part 3 (`jetson-io`, reboot #2, the `/boot` backup) wasn't run; nothing under `/boot` was written, and pin 29 is unchanged. Parts 0, 1 and 2 ran as planned. Fallback A ran as the marker path, with M3 at 100 Hz and 1 kHz, then Part 5.

Raw data is in `raw/` (running log `raw/notes.txt`, event marks `raw/marks.csv`), board files in `raw/board/`, scripts in `scripts/`, and every command in `commands.log`. Previous session: `runs/stage1_20261030/report.md` and `pin29_problem.md`.

Tags: **V** = I ran it and saw the result. **V-user** = the user measured or reported it. **NV** = not verified.

## Summary

1. **Pin 8 reaches the header: 3.43 V** at idle on a spare jumper against Pico GND (V-user). That's the same as pin 1's 3.3 V rail and under the 3.6 V limit. So a pad that the SoC drives does reach the 3.3 V header. The carrier blocks only pin 29, whose pad is tristated (previous session).
2. **Power mode: restored by the warm reboot #1.** nvpmodel didn't fail again (V):

   | | Before (boot of 30 Oct 16:04) | After reboot #1 | Expected |
   |---|---|---|---|
   | `nvpmodel.service` | failed, exit 234: "Reboot required for changing to this power mode: 1", then "bad input" | `Result=success` | success |
   | `nvpmodel -q` | 25W, 1 | 25W, 1 | 25W, 1 |
   | CPU `policy0`/`policy4` | schedutil, 729600 / **1728000** | schedutil, 729600 / **1344000** | 1344000 |
   | GPU devfreq | **performance**, max 1020 MHz, cur 1020 MHz | **nvhost_podgov**, max 918 MHz, cur 306 MHz | same |
   | GPU `tpc_pg_mask` / `fbp_pg_mask` | **0 / 0** (conf 240 / 2) | **240 / 2** | 240 / 2 |
   | bwmgr min / max | 204 M / 3199 M | 204 M / 3199 M | same |
   | cpuidle | all enabled | all enabled | all enabled |
   | INA228, 60 s mean | 7.42 W (1 s) | **6.376 W** (331.0 mA, 19.261 V) | 6.2–6.4 W |
   | `VDD_IN`, 60 s mean at 10 Hz | 5.62 W (spot) | **4.543 W** (sd 10.4 mW) | 4.5–4.6 W |
   | Board clock against the Mac | −0.14 s | **−31.3 s** after the reboot, then synced to −0.12 s | within 1 s |

   - **Probable reason a reboot was needed:** the GPU power-gating masks only take effect at boot. `nvpmodel -q --verbose` showed them as REAL 0 against CONF 240/2. The masks match the verbose output (V); that they're the reason for nvpmodel's prompt is NV.
   - **Why the earlier boot failed:** not known (NV).
3. **Boot menu: not observable** (V-user, V).
   - The user's console showed only the text of their earlier login session; no menu, no countdown (V-user).
   - The reason: `/dev/cu.usbmodem<jetson-serial>*` is the Linux USB gadget console (`ttyGS0`). It disappears during a reboot and doesn't exist before Linux starts. The boot menu goes to the debug UART (`console=ttyTCU0`) (V from the board's config).
   - So the countdown's real length stays unverified (NV).
   - **The USB console can't be used to pick a boot entry,** so any future `jetson-io` plan needs another recovery path.
4. **`jetson-io`: not run, by the user's choice.**
   - `extlinux.conf` is unchanged: `DEFAULT primary`, one `LABEL primary`, no `FDT`/`OVERLAYS`, mtime 15 Oct (V).
   - No overlay or backup was made, and pinconf wasn't touched.
5. **D4 after a fix: not applicable.** Pin 29 is unchanged: line 105 unused input (V). The marker pin is pin 8, idle high at 3.43 V (item 1).
6. **M3 on pin 8: PASS.** One `0xFF` byte per event, written to `/dev/ttyTHS1` at 115200 8N1 on an absolute schedule; the Pico timestamps GP16 (V):

   | | 100 Hz, 60 s | 1 kHz, 10 s |
   |---|---|---|
   | Bytes sent / falls / rises captured | 6000 / 6000 / 6000 | 10000 / 10000 / 10000 |
   | Spurious pulses under 1 µs | 0 | 0 |
   | Pulse width (fall → rise), all 16 000 | 8.52–8.88 µs, p50 8.76 (1/115200 = 8.68) | (same set) |
   | Pico fall interval p50 / p99 / max | 10000.20 / 10006.8 / 10014.5 µs (min 9970.0) | 1000.08 / 1001.16 / 1013.0 µs (min 963.1) |
   | Jetson write-start interval p50 / p99 / max | 10000.0 / 10000.6 / 10001.1 µs | 1000.0 / 1000.4 / 1001.9 µs |
   | `write()` call p50 / p99 / max | 11.8 / 19.6 / 90.8 µs | 5.1 / 6.2 / 47.6 µs |
   | Write → edge jitter (residual of a linear fit), sd / p99 / max | 1.39 / 6.26 / 34.6 µs | 0.61 / 1.39 / 38.9 µs |
   | INA228 conversions missed during the run | 0 | 0 |

   - **Polarity is right:** idle high (GP16 reads 1); each event starts with a fall, and the line is low for one bit time (V).
   - **The largest latency in both runs is event 0,** the first write after opening the port: 35–39 µs. All other events stay under 12.2 µs (V).
   - **Clock rate:** Pico against Jetson `CLOCK_MONOTONIC` is +21.5 ppm, the same in both runs (V).
   - **Not measured:** the constant part of the write-to-edge delay. It needs a common reference.
   - **Pico load:** busy 54.1 % with markers, against 53.9 % without. Marker FIFOs never above level 1 (V).
7. **Unexpected:**
   - **The board clock was 31 s behind after the warm reboot** (V). It restores the time saved at shutdown, so a warm reboot loses its own length. SETUP_NOTES §7.5 says a warm reboot keeps the clock; that's not true here. I synced it and stopped the 12 timers right after (V).
   - **The first capture F1 stopped at 17:05:10 with SIGINT** (V). That terminal then held the user's `screen` login on the Jetson console, so the stop was most likely a Ctrl-C typed into it (NV). I restarted the capture as F2 and nothing was lost, apart from 3 minutes of idle trace.
   - **The planner's `pgrep -a 'apt|dpkg'` gives a false positive on this board:** it matches the kernel threads `[capture]` and `[capture-control]` (V). Use `pgrep -x` with exact names (`apt`, `apt-get`, `apt-helper`, `dpkg`).
   - **`apt-daily` ran at 17:03:35, before the timers were stopped** (V, `apt-helper` seen at 17:04). It had finished before the reboot (V).
   - **My reboot watcher started too late** to see the USB device drop: the reboot ran while the `sudo` prompt was still open. ssh answered at the first manual try (17:12:23), but the earliest ssh time isn't measured. The kernel came up at about 17:09:03 (from `/proc/uptime`).
   - Nothing unsafe was seen. Current peaked at 0.54 A, temperatures were 47.6–51.7 °C, and there was no over-current alarm (V).
8. **State at the end** (17:26 UTC):
   - **Jetson:**
     - running in the restored 25 W configuration (final check identical to the table's "after" column, V);
     - clock −0.15 s against the Mac;
     - **timers started again**, all 12 active;
     - no jobs, and no marker or sampler process;
     - pin 29 untouched;
     - `/dev/ttyTHS1` at 115200;
     - radio enabled, untouched;
     - checkout `8d91a6d`, clean;
     - **`extlinux.conf` `DEFAULT primary`, unchanged**;
     - **`<user>` is now in `dialout`.** That's permanent; undo with `sudo gpasswd -d <user> dialout`.
   - **Pico:** `machine.reset()` at 17:25. Filesystem `[]`; GP16 funcsel 31, OE 0, pad 0x56, reading 1 because the marker wire is high (V).
   - **Wiring:**
     - **the marker wire is connected, Jetson pin 8 → Pico GP16** (V-user), with no series resistor reported;
     - the spare jumper is off pin 8 (V-user);
     - the pin 30 ground wire is in place (V-user).
     - **Pin 8 is high whenever the Jetson runs, so the wire comes off GP16 before the Pico is ever unplugged.**
   - **Serial console:** the user can close it (`Ctrl-A` `d`, or `Ctrl-A` `k`).
   - **Temp files, not deleted:**
     - Mac `/private/tmp/jn_fix/`: `F1/F2/F3.status.json`, `reboot1_mark.txt`, `stop_F2`, `stop_F3`;
     - board `/tmp/jn_fix/`: the health sampler CSV, M3 CSVs, the smoke-test CSV, `scripts/` (copied to `raw/board/`).

## Details

### Part 0 (V)
- The Jetson was up 54 min. Board − Mac was −0.14 s, so no sync was needed at that point. No apt or dpkg was running, no jobs, line 105 `PQ.05` unused.
- **Snapshot in `raw/state_before/`:**
  - `systemctl status` and `show`;
  - the nvpmodel journal (via `sudo`);
  - `nvpmodel -q --verbose`;
  - `status` (`pmode:0001`, mtime 26 Oct);
  - `ls` of `/etc/nvpmodel*` and `/var/lib/nvpmodel/`;
  - cpufreq, devfreq, bwmgr, cpuidle and temperatures.
- **REAL against CONF in `nvpmodel -q --verbose`:**
  - FBP_PG_MASK 0 / 2, TPC_PG_MASK 0 / 240;
  - GPU `power/control` auto / on;
  - CPU max 1728000 / 1344000 on all 6 cores;
  - GPU max 1020 / 918 MHz;
  - EMC max equal to the conf.
- **The user confirmed** the Pico was plugged in, the spare jumper touched nothing, the marker wire was unconnected, the pin 30 ground wire was in place, and the serial console was open (V-user).
- **Captures:**
  - F1, 17:00:19–17:05:10;
  - F2, 17:08:14–17:19:13, which covers reboot #1;
  - F3, 17:22:03–17:23:56, covering M3.

  0 missed conversions in all three (V).

### Part 2 (V)
- **Reboot command:** `mark` 17:08:42, `sudo systemctl reboot` approved and run before 17:09:22. The kernel came up at about 17:09:03, judging from uptime 199.9 s at 17:12:23.
- **Health check from 17:12:47:** `raw/state_after_reboot1/`.
- **Clock and timers:** `sudo date -u -s` at 17:14:47; the timer stop at 17:16:29. Between them, update-notifier-download started at 17:13:47.
- **60 s window 17:16:50–17:17:50:**
  - INA228 from F2 by Mac arrival time (`scripts/winmean.py`);
  - `VDD_IN` from `sampler.py`, 10 Hz, 601 samples, 0.5 % of a core;
  - the sampler resolved hwmon3 through the I²C path (V).

### Fallback A (V)
- **`dialout`:** `sudo usermod -aG dialout <user>` at 17:04, then `ssh -O exit`. A fresh session lists `20(dialout)`, and `/dev/ttyTHS1` (`root:dialout 0660`) is writable.
- **`scripts/uart_marker.py`:**
  - standard library only (`os`, `termios`, `tty`);
  - port set raw, 115200, CS8, no parity, 1 stop bit, CLOCAL, no flow control;
  - one `os.write(fd, b"\xff")` per event, with `time.monotonic_ns()` before and after;
  - sleeps to 300 µs before each scheduled time, then spins;
  - 1 s idle before and after each run;
  - `tcdrain` and `close` in `finally`.
- **Smoke test** before the wire was connected: 2 s at 100 Hz, `write()` p50 6.5 µs.
- **Analysis:** `scripts/m3_analyze.py`, output in `raw/M3_analysis.txt`.

## For the planner
- **Marker for Parts 5–6:**
  - one `write()` per event, about 5–12 µs per call at p50, with a fall at the start bit;
  - write a dummy byte after opening the port, so the slow first write isn't a decision;
  - start and end of a step can be told apart by pulse width, since each byte's low time follows its bit pattern: for example, `0xFF` gives one bit low (8.7 µs) and `0x00` gives nine (78 µs). That's an idea, not tested (NV).
- **Boot and session protocol:**
  - after every boot, check `nvpmodel` `Result`, the CPU max, the GPU governor and the TPC/FBP masks before measuring;
  - after every reboot, warm or cold, check and sync the clock;
  - the USB console shows no boot menu.
- **Docs to update** (tracked, not edited by me):
  - `stage1_wiring.md`: the marker is pin 8 (UART1 TX, idle high), not pin 29;
  - SETUP_NOTES §7.5: a warm reboot loses its own length;
  - SETUP_NOTES §7.2: the USB console doesn't show the boot menu;
  - SETUP_NOTES §9: the `dialout` membership and the Jetson's USB identity.
