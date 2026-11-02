# Pico bring-up, 28 Oct 2026

Raspberry Pi Pico (RP2040, SC0916) on the Mac's USB, nothing wired to it.
Work ran 16:20–16:38 UTC, plus a different-port check at 16:46. Raw outputs are in `raw/`, the scripts I used in
`scripts/` (copies of the files in `/private/tmp/jn_pico/`).

Tags: **V** = I ran it and saw the result. **V-user** = you observed it and
told me. **NV** = not verified.

## 1. Software

| Item | Result | |
|---|---|---|
| Firmware | `firmware/RPI_PICO-20260824-v1.29.0.uf2`, 680 960 bytes, fetched over HTTPS from `micropython.org/resources/firmware/` (HTTP 200) | V |
| SHA-256 | `e1160e602e277d85920adb5fe741435edccba9ba6ecadc85fdab75252eeff4e9` | V |
| Published checksum | Not cross-checked. The download page builds its file list with JavaScript, so the fetch showed no file names, and I know of no published hash. The SHA-256 is a record of what was flashed, not proof it's authentic | NV |
| UF2 block 0 | magicStart0 `0x0A324655` ✓, magicStart1 `0x9E5D5157` ✓, magicEnd `0x0AB16F30` ✓, flags `0x00002000` (family ID present), family `0xE48BFF56` = RP2040 ✓, target `0x10000000` | V (`raw/01_uf2check.txt`) |
| UF2 whole file | 1330 blocks, numbering contiguous, only family `0xE48BFF56`, addresses `0x10000000–0x10053200` (inside XIP flash); payload contains "Raspberry Pi Pico with RP2040" and not "Pico W", "Pico2" or "RP2350" | V |
| mpremote | 1.29.0, installed with `~/.local/bin/uv tool install mpremote==1.29.0` into `~/.local/share/uv/tools/mpremote`. Dependencies resolved: **pyserial 3.5**, **platformdirs 4.13.7** | V (`raw/02_mpremote_install.txt`) |
| Tool interpreter | uv picked its own CPython 3.11.11, not Homebrew's | V |
| Project untouched | `mpremote` isn't in `.venv`; `git status` is the same as at the start (README.md and exploration.md were already modified and the stage1_wiring files already untracked before I began) | V |

To remove: `~/.local/bin/uv tool uninstall mpremote`.

## 2. USB identity and port

| | BOOTSEL (before) | MicroPython (after) | |
|---|---|---|---|
| VID:PID | `2e8a:0003` "RP2 Boot" | `2e8a:0005`, vendor "MicroPython", product "Board in FS mode" | V |
| Serial | `E0C9125B0D9B` | `<pico-serial>` | V |
| Port | none | `/dev/cu.usbmodem2101` (and `tty.usbmodem2101`) | V |
| `mpremote connect list` | — | `/dev/cu.usbmodem2101 <pico-serial> 2e8a:0005 MicroPython Board in FS mode` | V |

- **Timing.** `cp -X` returned exit 0 at 16:21:59. By 16:22:03 the volume was gone, and the port appeared at 16:22:09. V
- **Product ID.** The brief named no PID for MicroPython mode. 0x0005 is the one MicroPython uses on rp2, so I continued. V for the value; that it's MicroPython's assigned PID is NV.
- **Accessory dialog.** macOS showed "Allow accessory to connect?" before flashing and after flashing (once per new USB identity), and you clicked Allow. V-user. It did not show up again after the replug into the same port, nor after you moved it to a different Mac USB port (both V-user). No dialog was reported after my `machine.reset()` calls either; the port came back each time without anyone clicking (V).
- **BOOTSEL serial.** `E0C9125B0D9B` doesn't identify the board. It isn't the flash ID, and the same string shows up in other people's logs ([Dr. Klipper wiki](https://drklipper.de/doku.php?id=klipper_faq:rp2040_input_shaper_hardware)). A Raspberry Pi forum thread contrasts the 12-digit BOOTSEL serial with the 16-digit runtime one ([forum](https://forums.raspberrypi.com/viewtopic.php?t=349189)). V for this board; the general claim is from those sources.

**Name stability.**

| Event | Port | Evidence | |
|---|---|---|---|
| `mpremote soft-reset` | `cu.usbmodem2101` | `ticks_ms` 60 407 afterwards, so no reboot | V |
| `mpremote reset` | `cu.usbmodem2101` | `ticks_ms` 3 230 afterwards, so it rebooted | V |
| Your unplug/replug, same Mac port | `cu.usbmodem2101` | `ticks_ms` 50 665 at 16:27:47 | V |
| After every later `machine.reset()` | `cu.usbmodem2101` | | V |
| You moved it to a different Mac USB port | **`cu.usbmodem1101`** | locationID `0x01100000` (was `0x02100000`); same VID:PID and serial; `ticks_ms` 27 835 at 16:46:27; filesystem still `[]` | V (`raw/15_other_usb_port.txt`) |

The brief calls `mpremote reset` a soft reset. In mpremote, `reset` is `machine.reset()` (a hard reset) and `soft-reset` is Ctrl-D, so I ran both.

**The name follows the physical port, not the device.** The suffix is the first two hex digits of the IOKit locationID plus `01`: `0x021…` gave `2101`, `0x011…` gave `1101` (V for these two ports). Resets and replugs into the same port keep the name; moving the cable changes it. A hub would presumably give a longer suffix (NV).

**Telling it from the Jetson's console.**

| | Pico (today) | Jetson console |
|---|---|---|
| USB vendor | `0x2e8a` (V) | `0x0955` per the brief (NV today) |
| Serial | `<pico-serial>`, equal to `machine.unique_id()` (V) | NV |
| Name | `cu.usbmodem2101` or `cu.usbmodem1101` depending on the Mac port (V) | `cu.usbmodem<jetson-serial>21` / `…23` per SETUP_NOTES and `traces/board_20261026/report.md` (NV today) |

Match on vendor ID plus serial number, read from IOKit. The name pattern isn't reliable: both are `cu.usbmodem*`.

## 3. Board

| | | |
|---|---|---|
| `sys.implementation` | `(name='micropython', version=(1, 29, 0, ''), _machine='Raspberry Pi Pico with RP2040', _mpy=4870, _build='RPI_PICO', _thread='unsafe')` | V |
| `os.uname()` | `sysname='rp2', release='1.29.0', version='v1.29.0 on 2026-08-24 (GNU 16.1.0 MinSizeRel)', machine='Raspberry Pi Pico with RP2040'` | V |
| `machine.freq()` | 125 000 000 | V |
| `machine.unique_id()` | `<pico-serial>`, matches the USB serial | V |
| `gc.mem_free()` | 228 656 bytes (5 072 allocated) | V |
| Filesystem | `[]`, 1 441 792 bytes total; 8 192 bytes used is filesystem metadata | V |

## 4. Tests (steps 5–10)

### LED (GP25)

| Run | Pattern | Seen? |
|---|---|---|
| First | 5 blinks, 0.5 s on / 0.5 s off, 2 s after start | Not seen (V-user) |
| Retry | 10 s countdown, then 5 blinks, 1 s on / 1 s off | Seen (V-user) |

The code ran correctly both times: the pin read back 1 at every "on" (V). Why the first run was missed isn't known (NV). Each run ended with `machine.reset()`.

### Internal temperature (ADC 4)

64 samples. `read_u16` min/median/max were 14003 / 14019 / 14083, giving a mean of 0.7060 V (V).

Using the datasheet formula T = 27 − (V − 0.706) / 0.001721, with V = raw × 3.3 / 65535, that's **27.0 °C**. Single samples range 25.2–27.5 °C (V).

Plausible for a board at room temperature. The absolute accuracy depends on the 3.3 V reference and the sensor's spread (NV).

### PIO edge capture (GP16)

GP16 was confirmed free (V-user).

How the test worked:
- The CPU drove GP16 as a plain output. State machine 0 watched the same pad through its JMP pin, running at sysclk with divider 1.
- Every path through the 7-instruction program costs **3 cycles per decrement** of a down-counter X. On each rising edge it does `in x, 32` with autopush. So 1 count = 3 / 125 MHz = **24 ns**, which is the timestamp resolution (V).
- The CPU recorded `ticks_us()` after each edge as a cross-check.

| | ~100 Hz (10 000 µs) | ~1 kHz (1 000 µs) |
|---|---|---|
| Edges generated / captured | 1000 / 1000 | 1000 / 1000 |
| Median interval | 416 367 counts = 9 992.81 µs | 41 845 counts = 1 004.28 µs |
| Min | 415 964 = 9 983.14 µs | 40 545 = 973.08 µs |
| Max | 417 069 = 10 009.66 µs | 41 845 = 1 004.28 µs |
| Mean | 9 999.99 µs | 999.98 µs |
| PIO − CPU interval | −0.34 … +3.14 µs (median −0.22) | −0.72 … +2.08 µs (median +0.28) |
| Total span, PIO − CPU | +2.5 µs over 10 s | +1.9 µs over 1 s |

All V (`raw/10_pio_analysis.txt`).

**The spread comes from the pulse generator, not the capture.**
- At both rates the intervals take essentially two values, 16.87 µs apart: 9 992.8 / 10 009.7 µs and 987.4 / 1 004.3 µs. That's the period of the MicroPython busy-wait loop that makes the edges.
- Each value splits further by exactly 1 count (416 366 / 416 367), which is the 24 ns sampling step showing directly.

All V.

This shows PIO timestamping works under MicroPython, and that a ~17 µs Python polling loop drains the FIFO at 1 kHz without losing edges.

Three limits of this test program (V by construction; not exercised):
- the 32-bit counter wraps every 103 s at 24 ns per count;
- a false edge is pushed if X reaches 0 while waiting for a high;
- values ≥ 2³⁰ would become heap-allocated ints in MicroPython, so I started X at 2³⁰ − 1.

The spec's program has to deal with all three.

### Throughput, Pico → Mac (standard library only)

How the test worked:
- `scripts/picolink.py` finds the port with `ioreg -a` and `plistlib`, matching vendor `0x2e8a` and the serial.
- It opens the port with `os.open` (exclusive), puts it in raw mode with `tty`/`termios`, and raises DTR and RTS with `TIOCMBIS`.
- It enters the raw REPL and sends a script that writes a numbered byte pattern covering all 256 values to `sys.stdout.buffer`.
- It reads exactly N bytes and compares them with the expected stream. MB = 10⁶ bytes.

| Size | Write size | Intact | Time (OK → last byte) | MB/s (from OK) | MB/s (first → last byte) |
|---|---|---|---|---|---|
| 1 MiB | 4096 | yes, byte-identical | 1.607 s | 0.653 | 0.696 |
| 5 MiB | 4096 | yes, byte-identical | 7.726 s | **0.679** | 0.687 |
| 1 MiB | 256 | yes | 1.662 s | 0.631 | 0.646 |
| 1 MiB | 16384 | yes | 1.778 s | 0.590 | 0.708 |

All V (`raw/11_throughput.txt`). That's about 3–7× the 0.1–0.2 MB/s the meter needs, with no bytes lost or added. `sys.stdout.buffer` did no newline translation.

### Clock agreement

121 pairs over 120 s, one per second, through the raw REPL. The Mac sends one byte and the Pico answers with `time.ticks_us()`. The Mac time is `time.monotonic_ns()` (`mach_absolute_time`, not adjustable), taken at the midpoint of the exchange.

| | |
|---|---|
| Round trip | median **670 µs**, p99 **1 096 µs**, min 428 µs, max 1 229 µs |
| Rate, fastest 50 % (n = 60) | **Pico +2.95 ppm vs Mac** (± 0.11 ppm, 1σ), residual stdev 26 µs, max 106 µs |
| Rate, fastest 25 % (n = 30) | +3.10 ppm (± 0.15), residual stdev 25 µs |
| Rate, all pairs | +2.94 ppm (± 0.14), residual stdev 52 µs, max 314 µs |

All V (`raw/12_clock_*`). The rate is Pico crystal against the Mac's raw timebase, at room temperature over 2 minutes. It's not a rate against true time, and it will drift with temperature (NV).

A single exchange places the Pico's clock on the Mac's to about ±25–50 µs. A fit over many low-round-trip pairs does much better.

### I²C0 scan, nothing attached

`machine.I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)` came back as `I2C(0, freq=399361, scl=5, sda=4, timeout=50000)`. `scan()` **returned `[]` in 7.3 ms**, with no error and no hang. The host-side 20 s timeout wasn't needed: the whole mpremote call took 0.26 s. V (`raw/13_i2c_scan.txt`)

**The pads did have pull-ups.** I read (didn't write) the pad registers:
- after the constructor: PUE = 1, PDE = 0, funcsel = 3 (I²C) on both pins, and both lines read high;
- before it: pull-down only.

So MicroPython turns on the RP2040's weak internal pull-ups for I²C (V). Their value isn't measured; the datasheet range is ~50–80 kΩ (NV). With the INA228's 10 kΩ pull-ups this won't matter.

## 5. Final state (step 11)

V (`raw/14_final_state.txt`):
- `machine.reset()` at 16:37:27 UTC; the board enumerated again as `2e8a:0005`, serial `<pico-serial>`, `/dev/cu.usbmodem2101`.
- `os.listdir('/')` is `[]`: no `main.py`, no `boot.py`.
- `SIO GPIO_OE = 0`. GP4, 5, 16, 17 and 25 are at funcsel 31 (no function) with input enabled, which is the reset state.
- mpremote still connects.

The Pico is left plugged in, running MicroPython v1.29.0, with nothing stored on it. After you moved it, it sits on the other Mac port as `/dev/cu.usbmodem1101`, filesystem still `[]` (V, 16:46 UTC). That check only ran `os.listdir` and `ticks_ms`; no pins were touched.

## 6. Surprises

- **`python3` is Homebrew 3.15.0, not 3.12.** `python3.12` (3.12.15) exists, and I used it for the Mac-side scripts. The UF2 check ran under 3.15. V
- **mpremote's auto-selection can pick the Jetson.**
  - Bare `mpremote` (no `connect`) opens the first USB serial port in sorted order (`mpremote/commands.py`, lines 40–50; V by reading the source).
  - Which one it opens depends on the cable's port. `cu.usbmodem1791…` sorts before `cu.usbmodem2101` but after `cu.usbmodem1101`, so on the first port bare `mpremote` would open the Jetson's console, and on the second it would open the Pico (sorting V; behaviour with the Jetson attached NV).
  - My last check in step 11 ran bare `mpremote exec`. It was safe only because the Pico was the only USB serial device at that moment (the `connect list` just before showed that). Every other call used `connect id:<pico-serial>`.
- **Repo globs now match the Pico.** The `cu.usbmodem*` globs in the repo also match the Pico while it's plugged in (V by reading; not run):
  - SETUP_NOTES' shutdown check, `ls /dev/cu.usbmodem*` "gone means halted", will never come back empty;
  - `screen /dev/cu.usbmodem* 115200` would expand to two devices;
  - `scripts/jx` loops over the same glob.

  I didn't edit these (tracked files).
- Smaller ones, covered above: the LED wasn't seen on the first run, the I²C pins get internal pull-ups, the CPU runs at 125 MHz, and `mpremote reset` is a hard reset.

## 7. Recommendations for the spec

- **Is MicroPython fast enough?**
  - **For the decision marker, yes** (V). PIO does the timing at 24 ns, and the interpreter only drains the FIFO. In the spec, join the RX FIFO (8 deep) or use DMA, and extend the 32-bit counter in software or slow the clock (1 count = 1 µs gives 71 min before a wrap).
  - **For the INA228, not established** (no INA228 today). A single 24-bit register read is roughly 55 bus bits, about 140 µs at 400 kHz. So the "~10 kS/s" in exploration.md §4 is bus-limited before Python matters (estimate, NV).
  - Measure the read rate with the INA228 attached. Consider 1 MHz Fast-mode Plus and ALRT on GP17 as conversion-ready.
- **Can the Mac reader stay standard-library only? Yes** (V). That's `os.open` + `termios`/`tty` + `select` + `fcntl.ioctl(TIOCMBIS)` for DTR, with port lookup via `ioreg -a` + `plistlib`. It moved 5 MiB byte-identical at 0.68 MB/s.
- **How to pick the serial port.** Never by name or glob. Query IOKit for vendor `0x2e8a` *and* serial `<pico-serial>`, refuse anything with vendor `0x0955`, and require exactly one match. With mpremote, always pass `connect id:<pico-serial>`.
- **Clocks.** The power readings and the marker edges will both be timestamped on the Pico (one crystal). Only Mac alignment needs a fit: about 3 ppm here, which is 11 ms per hour. Keep a running fit on the shortest round trips rather than trusting single exchanges.
- **USB identity.** Keep it fixed. Each new identity (BOOTSEL, or a firmware with different VID/PID/serial) brought up the macOS accessory dialog, which would block an unattended run (V-user for the two cases seen). Once allowed, the same identity came back without a dialog after a replug (V-user) and after hard resets (V). So `machine.reset()` and replugs are safe in unattended runs. Entering BOOTSEL to reflash is not: that changes the identity and needs someone at the Mac. Moving to a different Mac USB port also brought no dialog (V-user), though the port name changed (see §2).

## 8. Files left

Temp files, all in `/private/tmp/jn_pico/` (not deleted, as agreed):
- `uf2check.py`
- `uv_install.log`
- `pio_edges.py`
- `pio_analyze.py`
- `picolink.py`
- `i2c_scan.py`
- `final_check.py`

In the run folder (gitignored `runs/pico_20261028/`):
- `firmware/RPI_PICO-20260824-v1.29.0.uf2`
- `raw/01…14_*`
- `scripts/` (copies of the six `.py` files)
- this report

On the Mac: the mpremote uv tool. On the Pico: firmware only.
