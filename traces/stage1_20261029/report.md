# Stage 1 first run, 29 Oct 2026: Jetson through the INA228, boot trace, pin 29 doesn't drive

The session ran 17:51–18:40 UTC and had two power-ups:
- **18:11:** the VBUS jumper was open, so power was assumed at 19 V.
- **18:29:** you had soldered the jumper closed, so power was measured.

It stopped at D4: pin 29 didn't drive, and you chose to investigate tomorrow.

Not done: M3 and Parts 4–6. Part 7's restore had nothing to undo: no timer, radio or power setting was changed. Raw data is in `raw/` (running log in `raw/notes.txt`), the scripts in `scripts/` and every command in `commands.log`.

Tags: **V** = I ran it and saw the result. **V-user** = you observed or reported it. **NV** = not verified.

## Summary

1. **Part 1 confirmations.**
   - Before the first power-up: D1 and D2 still held for the final layout (V-user). The 15 V reading was taken with the plug out of the Jetson (V-user). The plug was in the DC jack, the supply was off until I asked, and the marker wire was open at the Jetson end (V-user).
   - **VIN+ to VBUS: 1.3 MΩ, the jumper open** (V-user). You soldered it closed between the power-ups, with the supply and the Pico unplugged. Afterwards **0.01 Ω**, D1 and D2 redone and holding, 19 V wires solid (all V-user).
   - VBUS then read 19.24 V at idle (V).
2. **Pin 29: it doesn't drive.**
   - `gpioset gpiochip0 105=1` and `=0` both returned 0, and `gpioinfo` showed line 105 as a `gpioset` output while held (V).
   - You measured **a constant 3 mV, high and low, over two runs** (60 s and 90 s per level), on a spare jumper on pin 29 against Pico GND (V-user).
   - After each run `gpioget` released the line, which read 0 and showed as unused input (V).
   - Toggle method and cost: not reached.
   - Likely cause: on this JetPack, header pins come up input-only until the pinmux is changed (`stage1_wiring.md`, "Not verified yet") (NV). A wrong header position isn't excluded yet (NV).
3. **Idle power:**
   - INA228: **6.37 W** (330.9 mA at 19.24 V), +120 to +480 s after the second power-up. That window includes the clock sync and D4 (V).
   - `VDD_IN`: a few readings at about +90 s after the first power-up gave about 4.5–4.7 W (V).
   - No side-by-side M2 and no noise table yet.
4. **Synthetic decisions:** not done.
5. **Closed loop:** not done.
6. **Boot trace,** second power-up (power measured; V):
   - **USB device** at +29.3 s, **ssh** at +38.2 s;
   - **peak current 1.008 A** for one 1.08 ms conversion at +29.8 s, while VBUS sagged to 19.08 V;
   - **never above 2.5 A;**
   - **idle about 0.33 A from about +40 s.**

   The first power-up looked the same: peak 0.999 A, USB +29.6 s, ssh +38.4 s, highest 1 s mean 0.63 A (at 19 V: 11.9 W). Plot: `raw/P2_boot_first3min.png`.
7. **Unexpected:**
   - Pin 29 doesn't drive (item 2).
   - **The INA3221's hwmon number changes between boots:** `hwmon3` on the first boot, `hwmon4` on the second (V). The sampler has to find it through `/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*`.
   - **The board clock came up at 26 Oct 16:06 and then 16:12 UTC,** 3.1 days behind, not 1970 (V).
   - **The supply plug-in disturbed both Pico inputs** (V):
     - one 0.12 µs pulse on the dangling GP16 marker wire;
     - one extra ALRT edge, 225 µs into a conversion cycle.

     The extra edge's record has DIAG_ALRT `0xC001`, with CNVRF clear, so CNVRF identifies such edges. Nothing else was spurious in 637 s.
   - **The Pico wasn't plugged in at the start** (V).
   - Nothing unsafe was seen (V-user, nothing reported).
8. **State at the end:**
   - **Jetson:** clean `sudo systemctl poweroff` at 18:39. The USB device was gone by 18:39:15 and current fell to 2.06 mA (40 mW) (V). The supply is still plugged in, with the board halted (V). Unplug it when convenient.
   - **Pin 29:** released to input before the shutdown (V).
   - **Pico:** `machine.reset()`, filesystem `[]`, GP16 in its reset state (funcsel 31, OE 0, pad 0x56) (V). Still plugged into the Mac.
   - **Marker wire:** open at the Jetson end (V-user).
   - **The spare jumper on pin 29:** remove it (V-user pending).
   - **Board settings:** timers, radio, power mode and clocks untouched. The only `sudo` used: two `systemctl poweroff` and one `date -u -s` (V).

## Details

### Part 0 (V)
- The Jetson was off: no console device, no NVIDIA USB device, and ssh timed out.
- Repo `HEAD` is `78cf5f9`. `git diff --stat 8d91a6d HEAD -- src scenarios` is empty, and the board checkout is `8d91a6d` and clean.
- No tracked file was edited on either machine. The pre-existing edits are listed in `raw/P0_state.txt`.

### Capture path (V)
`cap_pico.py`, `cap_host.py` and `capdec.py`.
- **INA228 settings:** as in the bench report §11.
- **Accumulators:** ENERGY and CHARGE once a second each, half a second apart.
- **One PIO counter for all three streams:**
  - three state machines in PIO0: ALRT falls, GP16 rises, GP16 falls;
  - 25 MHz (divider 5), 3 cycles per count on every path, so 120 ns per count;
  - started in the same cycle by one CTRL write that also restarts the clock dividers;
  - X counts down from 0xFFFFFFFF, and the program layout makes the fall-through at X = 0 equal the jump target, so the wrap gives no false edge or lost count.
  - Check: `in x, 32` injected into all three by consecutive viper stores. Differences were 0–2 counts at the start and end of every capture.
- **GP16 is never configured.** Before and after every capture: funcsel 31, OE 0, pad 0x56.
- **P2b_boot**, 637 s:
  - 589 968 conversions, 0 missed, 0 sequence gaps, 0 framing errors, FIFO backlog 0;
  - Pico busy 53.9 %, longest handler 1043 µs.
  - **It crossed one PIO wrap at 515.4 s, and the intervals around it are normal (1079.64 / 1079.76 µs). The unwrap is checked.**
  - **ENERGY register 3832.41 J against summed P·dt 3832.59 J** (−0.005 %).
- **P2_boot**, 427 s, first power-up: 0 missed. CHARGE against summed current: ratio 1.0001.

### Parts 2–3 (V unless marked)
- **Clock:** 18:31:27 `sudo date -u -s` at a full Mac second. Afterwards board − Mac = −0.04 s, as close as ssh round trips can measure. `systemctl list-jobs` was empty right after the sync, and again at 18:39. Catch-up jobs weren't observed in those 8 minutes (NV whether they ran).
- **The Jetson's USB identity:** vendor 0x0955, product 0x7020 "Linux for Tegra", serial `<jetson-serial>`, tty `/dev/cu.usbmodem<jetson-serial>21`.
- **Before power-up:** VBUS read 0.39–0.69 V on the floating VIN+ node. Current −0.04 mA, sd 0.19 mA.
- **Per-conversion power at idle:** sd 261 mW (real board activity, not meter noise; the meter floor is 0.19 mA × 19 V ≈ 4 mW).
- Files: `raw/P2b_boot_check.txt`, `raw/P2b_boot_extra.txt`, `raw/P2b_boot_events.txt`, `raw/P3b_clock_*.txt`, `raw/P3b_D4_board.txt`, `raw/board_tmp_jn_run1/` (copy of the board's `/tmp/jn_run1/`).

## For the next session: pin 29

Each item needs your decision where marked.
1. **Rule out the probing.** Put the spare jumper on pin 1 (3.3 V) and read it against Pico GND: that checks the method. Then recount pin 29: odd row, directly beside pin 30, the 6th pair from the end opposite pin 1.
2. **Read the pinmux state.** `sudo cat` of the pinctrl debugfs entry for PQ.05. That's read-only, but it's a `sudo` not on this session's list, so it needs your OK.
3. **Options if the pad is input-only:**
   - `jetson-io`: a device-tree overlay and a reboot; forbidden this session, so it needs your decision;
   - pin 8, UART1 TX, as the marker: one byte per decision, no board configuration change (`stage1_wiring.md`).
4. **Then resume** at M3 and continue with Parts 4–6. Clock sync and boot at the start of every session, as today.

## Files
- **Mac scratch** `/private/tmp/jn_run1/`:
  - `*.status.json`;
  - `P2_boot_3min.*`, `P2b_snap.bin` (early copies);
  - `stop_P2_boot`, `stop_P2b_boot` (stop flags; they only block reuse of those capture names);
  - an empty `build/`.
- **Board scratch** `/tmp/jn_run1/`: `d4.log`, `d4_run1.log`, `d4.out`, `scripts/d4.sh`. Copied to `raw/board_tmp_jn_run1/`. Not deleted.
