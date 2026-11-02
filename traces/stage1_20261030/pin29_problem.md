# Problem: Jetson header pin 29 doesn't drive the per-decision marker

*30 Oct 2026, Stage 1 session day 2. For the planning agent.* Tags: **V** = run and seen, **V-user** = the user measured or reported it, **NV** = not verified. Raw files are in `runs/stage1_20261030/raw/`; day 1 is in `runs/stage1_20261029/`.

## 1. What the connection is for

The Jetson toggles a pin at each control decision, and the Pico timestamps the edge on GP16. The same PIO counter (120 ns per count) also timestamps every INA228 conversion, so power and decisions share one clock.

That's what makes **per-decision** energy measurable:
- A `centroid` decision costs about 0.15 mJ (pilot). That's about 0.2 % of the board's 64 mJ per 10 ms period.
- Board power fluctuates by about 260 mW (sd) from one 1.08 ms conversion to the next (V, today).
- So decisions only show up when thousands of windows are averaged, aligned on their marker edges (brief Part 5 method b, Part 6 per-decision wrapper).

Block-level energy (Part 4, Part 5 method a, Part 6 block means) works without the marker, using clock-aligned block times.

The user has decided the marker matters and chose a persistent pinmux change (option C, §5).

## 2. What was tried and observed

| | Result | |
|---|---|---|
| `gpioset --mode=time gpiochip0 105=1`, then `=0` (line 105 = `PQ.05`, header pin 29) | rc 0; `gpioinfo` shows line 105 as a `gpioset` output `[used]` while held; released with `gpioget` (reads 0) | V, 3 runs (day 1: 60 s and 90 s per level; day 2: 120 s) |
| Voltage on pin 29, on a spare jumper against Pico GND | **3–5 mV while "high" and while "low"**, all runs | V-user |
| Method check: pin 1 (3.3 V), same jumper and reference | 3.43 V | V-user |
| Pin 29 released (line 105 unused input; pad pull-up on, `tristate=1`) | **−6.9 mV** (day 2, about 16:35 UTC) | V-user; board state V |

Every check that decides "doesn't drive" used `sudo` only for read-only debugfs reads, which the user approved. The INA228 meter and the capture path work: details in `runs/stage1_20261029/report.md`, plus today's notes.

## 3. Cause, as far as known

The pad's output driver is disabled in the SoC pinmux. Pad group `soc_gpio32_pq5` (pinctrl pin 105, device `2430000.pinmux`), read through `/sys/kernel/debug/pinctrl/2430000.pinmux/pinconf-groups` (V):

| Field | Released | While `gpioset` holds the line high |
|---|---|---|
| `tristate` | **1** | **1** |
| `enable-input` | 1 | 1 |
| `gpio-mode` (the SFIO select bit) | 0 | 0 |
| `pull` | 2 (pull-up) | 2 |
| `io-hv` | 0 | 0 |
| `function` | rsvd0 | rsvd0 |

- **The GPIO request doesn't touch the pad.** Taking the line through the GPIO character device sets the controller's direction and value only, and `tristate=1` keeps the output buffer off (V, the table).
- **NVIDIA's own tool reads this state as "unused".** `/opt/nvidia/jetson-io/Jetson/pmx.py` (V, read on the board):
  - `gpio-mode`/sfio 1 means SFIO;
  - sfio 0 with tristate 0 means GPIO;
  - sfio 0 with tristate 1 means **UNUSED**, which is pin 29 today.

  This also settles the bit's polarity: `gpio-mode=0` already means GPIO-capable.
- **No other header GPIO drives.** Of the 24 header signal pins surveyed (`raw/C1_header_pin_survey.txt`), every GPIO pad has `tristate=1`. The only exception is pin 8, `uart1_tx_pr2`: tristate 0, input 0, function `uarta`. The table matching header pins to SoC pads comes from the devkit pinout (NV), except pin 29 = `PQ.05` (`gpioinfo`, V).
- **Where the default comes from.** No node in the live device tree mentions `soc_gpio32_pq5`: `grep -rl` over `/proc/device-tree` found nothing (V). So the default is probably programmed before Linux, by the bootloader's pinmux configuration, and the kernel DT doesn't override it (NV).
- **The pad's pull-up doesn't reach the header.** Released, with the pad pulled up (`pull=2`), pin 29 reads −6.9 mV (V-user). Something between the pad and the header holds the header low or isolates it. What it is isn't known (NV). Candidates:
  - a level translator on the carrier board (p3768). `io-hv=0` suggests a 1.8 V pad, while the header is 3.3 V (pin 1: 3.43 V). If such a translator is disabled or one-directional, it would also block a driven signal;
  - a pull-down on the carrier that is stronger than the pad's pull-up;
  - a header pin that isn't routed to this pad (wrong position).
  
  A voltmeter can't tell "floating" from "pulled low". A resistance reading from pin 29 to GND with the board off can, and so can the carrier schematic.
- **This doesn't change the diagnosis:** `tristate=1` alone stops the pad from driving. It does add a risk to option C: **after the pinmux fix, pin 29 may still read about 0 V at the header** if the carrier path is the reason. So the voltage after the fix has to be measured, not assumed (§6).
- **Not excluded:** a wrong jumper position on the header.
  - Pin 1 was located correctly (3.43 V), and the `tristate=1` reading explains the result by itself.
  - The position will show in the re-run of D4 after the fix.

## 4. Board facts relevant to a fix (V unless marked)

- **Board:** `NVIDIA Jetson Orin Nano Engineering Reference Developer Kit Super`, compatible `nvidia,p3768-0000+p3767-0005-super`. L4T R39.2.1 / JetPack 7.2.1, kernel 6.8.12-1021-tegra.
- **`/boot/extlinux/extlinux.conf`:**
  - one entry, `LABEL primary` (`LINUX /boot/Image`, `INITRD /boot/initrd`, `APPEND ${cbootargs} root=PARTUUID=… console=ttyTCU0,115200 … nv-auto-config`);
  - **no `FDT` and no `OVERLAYS` line**;
  - `TIMEOUT 30`;
  - a backup `extlinux.conf.nv-update-extlinux-backup` (Sep 23) sits next to it.
- **DTBs in `/boot`:** `kernel_tegra234-p3768-0000+p3767-0005-nv-super.dtb` and `tegra234-p3768-0000+p3767-0005-nv-super.dtb`, among others. There's no p3768-specific `hdr40` overlay; there is one for the p3509 carrier.
- **Tools:**
  - `dtc`, `fdtoverlay`, `fdtget` and `fdtput` (device-tree-compiler 1.7.0);
  - `nvidia-l4t-jetson-io` 39.2.1 (`jetson-io.py`, `config-by-pin.py`, `config-by-function.py`, `config-by-hardware.py`);
  - `busybox`.
- **What `jetson-io` writes for a GPIO pin** (`Jetson/board.py`, read): an overlay node with `nvidia,tristate = 0`, `nvidia,enable-input = 1`, `nvidia,gpio-mode = 0`.
- **How `jetson-io` changes the boot config** (`Linux/extlinux.py`): it adds a new `LABEL` with `FDT` and `OVERLAYS` lines, copying `LINUX`/`INITRD`/`APPEND` from the default entry. Whether it also makes the new entry the default isn't checked (NV).
- **`jetson-io` does offer plain GPIO for pin 29.** V by reading the code and the overlay on the board; the tool itself wasn't run.
  - The base header overlay for this board is `/boot/tegra234-p3767-0000+p3509-a02-hdr40.dtbo`: `overlay-name` "Jetson 40pin Header", `compatible` includes `nvidia,p3768-0000+p3767-0005-super`.
  - It defines `hdr40-pin29` with `nvidia,pins = "soc_gpio32_pq5"`, `nvidia,function = "extperiph3"`, `nvidia,pin-group = "extperiph3_clk"`. Decoded copy: `raw/C2_hdr40_p3767_decoded.dts`.
  - In the interactive menu `jetson-io.py` ("configure header pins manually"), each pin group cycles through `[ ] unused [ ] gpio [ ] extperiph3_clk`. That's lines 106–111 and 290–295; selecting toggles unused → gpio → SFIO.
  - When it saves the configuration, the gpio state writes `tristate 0`, `enable-input 1`, `gpio-mode 0` (`Jetson/board.py` 343–349).
  - `config-by-pin.py` only takes `-l`/`-p`/`-n`; it shows pin information and doesn't set states.
  - The menu is a curses UI, so someone has to run it in a terminal (`ssh -t`); the agent can't drive it non-interactively.
- **Not checked** (NV): whether the kernel applies an overlay pinmux node at boot on JetPack 7.2.1. That `jetson-io` exists for exactly this suggests it does.
- **A warm reboot keeps the clock** (SETUP_NOTES §7.5). The serial console `ttyTCU0` is the Jetson's USB console on the Mac (`/dev/cu.usbmodem<jetson-serial>21`). It's the only way to pick the old boot entry if a new one fails.

## 5. Options

### C, chosen by the user: persistent pinmux change
Pin 29 gets `tristate=0` at every boot.
- **Two ways:**
  - the `jetson-io.py` menu: set pin group `extperiph3_clk` (pin 29) to `gpio` (§4: supported). The user runs it interactively over `ssh -t`;
  - a small hand-written overlay setting `soc_gpio32_pq5` to `nvidia,tristate = <0>`, `nvidia,enable-input = <1>`, `nvidia,gpio-mode = <0>`, with a new extlinux entry.
- **The Stage 1 brief forbids it:** it needs `sudo` writes under `/boot`, a reboot, and possibly running `jetson-io`. The planner has to allow each one explicitly.
- **Risk:** a bad DTB or overlay can stop the board from booting.
- **Mitigation:**
  - leave `LABEL primary` untouched and add a new label;
  - back up `extlinux.conf`;
  - make the first boot of the new entry interactive, choosing it from the 30 s menu on the serial console, rather than making it the default straight away;
  - recovery is choosing `primary` from the same menu. That needs the serial console, which the brief says never to open, so the planner has to allow it for recovery.
- **Optional:** also configure pin 31 (`soc_gpio33_pq6`, same state today) as a second marker channel.

### A, fallback: pin 8 (UART1 TX, `/dev/ttyTHS1` = `3100000.serial`) as the marker
- **Already driven today:** tristate 0, function `uarta`. No getty or process uses it; the console is on `ttyTCU0`.
- **How it works:** one byte per event; the Pico timestamps the start-bit falling edge. A 0xFF byte at 115200 baud gives one 8.7 µs low pulse.
- **Needs:**
  - write access: `/dev/ttyTHS1` is `root:dialout 0660`, and `<user>` isn't in `dialout`, so one `sudo usermod -aG dialout <user>`;
  - measuring pin 8's idle voltage (expected high, about 3.3 V; NV).
- **Cost:** the latency and jitter between `write()` and the edge are unmeasured.
- **No reboot.**

### B, fallback: one register write per boot
Clear TRISTATE in pin 29's pad register with `sudo busybox devmem`.
- **Upside:** no reboot.
- **Downside:**
  - lost at every power-off;
  - needs the register address from NVIDIA documentation;
  - a wrong address can hang the board, though a power cycle recovers;
  - the kernel doesn't know about the change.
- `busybox`'s `devmem` applet is NV.

### No zero-change header GPIO
None exists (§3 survey).

## 6. Verification after any fix
1. Re-read `pinconf-groups`:
   - `soc_gpio32_pq5` shows `tristate=0`;
   - diff the rest against `raw/C1_pinconf_groups_held_high.txt`, so that no other pad changed unintentionally.
2. **Repeat D4 with nothing connected to GP16** (brief Part 3.3): pin 29 high reads about 3.3 V and **under 3.6 V** on a spare jumper against Pico GND; low reads about 0 V. This also checks the header position.
   If `tristate=0` is confirmed but the header still reads about 0 V, the carrier path is the cause (§3). In that case:
   - check the p3768 carrier schematic (NVIDIA Download Center) for what sits between the pad and pin 29, for example a level translator and its enable pin;
   - measure resistance from pin 29 to GND with the board off;
   - option A (pin 8) becomes the fallback. Its pad is driven, but its voltage at the header hasn't been measured yet (NV).
3. Release with `gpioget`. Only then do the Pico reset and the marker-wire connection, then M3.
4. Confirm the rest of the rig is unchanged:
   - `nvpmodel` 25 W;
   - ssh over USB;
   - USB device mode;
   - the INA3221 hwmon found by its I²C path.

## 7. What doesn't wait on the marker
- Part 4: idle INA228 against `VDD_IN`, and the noise table.
- Part 5 method (a): block means.
- Part 6 at block level.

Each needs block start and end times only. Today the board clock syncs to the Mac within about 0.05 s, and the Pico-to-Mac clock can be fitted to tens of µs, so trimming about 1 s per block edge is enough. The planner could schedule these first.

## 8. Other findings from these two days the plan should know
- **The INA3221's hwmon number changes between boots:** hwmon3 or hwmon4 (V, three boots). Fixed in the scratch sampler, which resolves `/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*` and checks the name and labels.
- **The board clock after a power cut** read 26 Oct twice and 1970 once (V). Syncing starts catch-up jobs **in waves over at least 30 minutes**: today 16:08:44 to after 16:39, with apt-daily still running at the end. An empty `systemctl list-jobs` between waves doesn't mean the catch-up is over (V).
- **`nvpmodel.service` failed at today's boot** ("Reboot required for changing to this power mode: 1", then "bad input" at its prompt) (V).
  - `nvpmodel -q` still reports 25W, but the 25 W limits aren't applied: CPU max 1728 MHz, GPU max 1020 MHz, GPU governor `performance` at 1020 MHz.
  - **Idle is about 1.1 W higher than on day 1** (V): INA228 7.37 W against 6.24–6.37 W; `VDD_IN` 5.62 W against 4.55 W on 26 Oct.
  - Today's board state isn't the reference state, and no measurement should use it. The cause isn't known (NV); see `report.md`.
- **Plugging in the supply** caused one spurious ALRT edge and one 0.12 µs GP16 pulse on the open marker wire (V, day 1). The ALRT edge is recognisable by CNVRF clear in DIAG_ALRT; analyses drop it.
- **Meter:**
  - VBUS jumper closed: 0.01 Ω (V-user). VBUS reads 19.24 V at idle and sags to 18.7–19.1 V at the boot peaks (V).
  - Idle 6.37 W (V).
  - ENERGY register against summed P·dt: −0.005 % (V).
  - The PIO counter unwrap is verified across one wrap (V).
