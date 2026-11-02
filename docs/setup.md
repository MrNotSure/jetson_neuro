# Board and session setup

The configuration the measurements in `traces/` were taken with. It's the
public summary of the private rig notebook (`SETUP_NOTES.md`), which the docs
and reports cite by section; the table at the end maps those sections to this
file. Wiring of the power meter: `docs/stage1_wiring.md`.

## 1. Hardware and software

| | |
|---|---|
| Board | Jetson Orin Nano Super developer kit, 8 GB, root on NVMe |
| Software | L4T R39.2.1 / JetPack 7.2.1, CUDA 13.2, TensorRT 10.16, cuDNN 9.20 |
| Power mode | 25 W (`nvpmodel` mode 1), default DVFS (schedutil, `nvhost_podgov`) |
| Controller runtime | Python 3.12.3 (system), venv with numpy 2.5.4 only; the repo runs from a checkout with `PYTHONPATH=src`, no install step |
| Simulation host | a Mac (Apple silicon, macOS), Python 3.12 venv from `scripts/setup_sim_env.sh` |
| Power meter | Adafruit INA228 (5832) on the 19 V input, read by a Raspberry Pi Pico (MicroPython 1.29.0) on the Mac's USB |

PyTorch (2.14.1+cu132, from PyTorch's own aarch64 CUDA 13.2 wheels) also runs
on the board with real CUDA kernels; no controller uses it yet.

## 2. Link between Mac and board

- **USB-C device mode.** The board's USB-C port presents a network interface;
  the board is `192.168.55.1`, the Mac gets `192.168.55.100` by DHCP. The
  traces call the board `jetson-usb`, an SSH alias for that address, logged in
  with a key.
- **Serial port for the marker.** The marker byte goes out on `/dev/ttyTHS1`
  (header pin 8, UART1 TX), which needs the board user in the `dialout` group.
- **`sudo`.** Session commands that need root (clock, timers, `nvpmodel -q
  --verbose`, reboot, poweroff) run as `ssh jetson-usb 'sudo …'`, without a
  password prompt; every one is logged in each session's `commands.log`.
- **Radio off** during measurements (`nmcli radio wifi off`). The board needs
  no internet during a session; code goes over as a git bundle on the USB link.

## 3. Board services (applied 31 Oct 2026)

Everything not needed for the loop is disabled (disabled, never masked, so
`systemctl enable --now` reverses it):

- default target `multi-user.target`: no desktop (gdm, Xorg, GNOME);
- disabled: `docker`, `docker.socket`, `containerd`, `bluetooth`,
  `nvargus-daemon`, `iperf3`, `saned.socket`, `gnome-remote-desktop`,
  `ModemManager`;
- disabled timers: `apt-daily`, `apt-daily-upgrade`, `motd-news`,
  `update-notifier-download`, `update-notifier-motd`, `fwupd-refresh`;
- kept, but stopped during sessions: `anacron`, `man-db`, `fstrim`,
  `e2scrub_all`, `dpkg-db-backup`, `systemd-tmpfiles-clean` timers;
- kept running: `ssh`, USB device mode, NetworkManager (radio off),
  `systemd-timesyncd`, `fake-hwclock`, `nvfancontrol`, `nvpmodel`, and the
  base system.

Running services went from 43 to 28. Before/after lists:
`traces/stage1_20261031_final/raw/services_*.txt`.

## 4. Clock

The carrier board has no RTC battery, so a power cut leaves the clock at 1970
or at the last saved time, and a warm reboot comes back behind by its own
length (31–34 s). With the radio off there's no NTP. So after every boot:

1. **stop the six maintenance timers first** (§3), so the clock jump starts no
   catch-up jobs (otherwise apt, anacron and others fire in waves for half an
   hour);
2. **sync the clock from the Mac with a relative step**,
   `sudo date -u -s '<+offset> seconds'`, which is right however long ssh and
   sudo take (`traces/t6b_20261102/scripts/clocksync.py`);
3. in a long session, re-sync every hour: the clock drifts about 19 ppm.

## 5. Power mode check

Once (cold boot, 30 Oct 2026) `nvpmodel` reported 25 W but hadn't applied it,
which raised idle power by about 1 W. A warm reboot fixed it. Check after
every boot:

- `systemctl show -p Result nvpmodel` → `Result=success`;
- CPU `scaling_max_freq` 1344000 on `policy0` and `policy4`;
- GPU devfreq governor `nvhost_podgov`, max 918 MHz;
- `sudo nvpmodel -q --verbose`: TPC_PG_MASK 240 and FBP_PG_MASK 2 under REAL.

## 6. Power monitors

- **On-board INA3221** (`VDD_IN`, `VDD_CPU_GPU_CV`, `VDD_SOC`): read from
  `/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*` (the hwmon number changes
  between boots), never written. 40 mW steps, about 0.6 s smoothing: usable
  for totals, not for single decisions.
- **INA228 + Pico** (Stage 1): 400 kHz I²C, ADCRANGE 0, SHUNT_CAL 4088, MODE
  0xB 540/540 µs, AVG 1, so one conversion per 1.08 ms (926/s), each
  timestamped by the Pico's PIO from the conversion-ready signal. The marker
  edges on GP16 share the same clock. Zero-current offset −111 µA, subtracted.
  The Pico runs MicroPython with an empty filesystem; the capture code is sent
  from the Mac each session (`traces/<session>/scripts/cap_pico.py`).

## 7. Session checklist

**After every boot:** timers stopped, clock synced (§4), power mode checked
(§5), INA3221 found by path, nothing apt-related running
(`pgrep -x 'apt|apt-get|apt-helper|dpkg'`; a plain `pgrep 'apt|dpkg'` also
matches kernel threads).

**Wiring:** connect the marker wire (Jetson pin 8 → Pico GP16) before the
Jetson powers up, with the Pico on USB. Take it off GP16 before the Pico is
unplugged. GP16 is always an input.

**During energy blocks:**
- controller pinned to one core (`taskset -c 2`), a fresh process per block;
- **no logger running** (no INA3221 sampler, no frequency log): each read costs
  about 0.4 mJ at a random phase and tripled the spread in T6. Take a snapshot
  of temperatures, frequencies and `VDD_IN` in the gaps instead;
- radio off; the Mac on AC, lid open, `caffeinate -ims`, and nobody touching
  the charger or USB cables during a capture.

**At the end:** start the six timers again; leave `fake-hwclock-save` running.

## 8. Section map for citations of `SETUP_NOTES.md`

| Cited as | Here |
|---|---|
| §2 (architecture, identity) | §1, §2 |
| §4 (USB device-mode fixes), §6 (code sync), §6.2, §6.3 | §2 (code goes over by git bundle) |
| §6.4 (Python and PyTorch on the board) | §1 |
| §7, §7.1, §7.2 (troubleshooting, serial console) | not published |
| §7.5 (clock) | §4 |
| §7.6 (clean shutdown) | `sudo systemctl poweroff`, then wait for the board's USB device to disappear |
| §7.7 (power mode not applied) | §5 |
| §8 (power measurement, INA3221) | §6 |
| §8.1 (board services) | §3 |
| §8.2 (Pico logger) | §6 |
| §8.3 (session checklist) | §7 |
| §9 (open items) | not published |
