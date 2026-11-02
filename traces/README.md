# traces

Raw data, the scripts that produced and analysed it, and a report, per
session. Committed on purpose: the measurement protocol publishes raw traces,
not only summary numbers. Each session folder has its own `README.md`.

| Session | What |
|---|---|
| `board_20261026/` | first board session: closed loop with the controller on the Jetson; the on-board power rails characterised; a pilot energy measurement |
| `mac_20261026/` | five 60 s realtime simulator runs on the Mac (`docs/sim.md` §10) |
| `pico_20261028/` | Raspberry Pi Pico bring-up, nothing wired |
| `ina228_20261028/` | INA228 bench test, supply unplugged |
| `stage1_20261029/`, `stage1_20261030/`, `stage1_20261030_fix/` | first power-up through the INA228; the marker moved from pin 29 to pin 8; quiet-board idle; synthetic decisions |
| `stage1_20261031_final/` | board services trimmed; closed loop with `hold` against `centroid` |
| `ctl_a_eval_20261101/` | controller A's evaluation and tuning summaries (simulator only) |
| `t5_20261102/` | controller A's timing on the Jetson |
| `t6_20261102/` | first energy session for controller A, with 10 Hz loggers running |
| `t6b_20261102/` | the pre-registered confirmation: the headline energy result |

## Conventions

- A session folder holds `report.md`, `commands.log` (every command with its
  UTC time, including every `sudo`), `raw/` (data and analysis outputs),
  `scripts/` (the scripts as they ran) and often `sim/` (simulator run folders
  with `meta.json`, `periods.csv`, `summary.json`).
- `*.gz` files are `gzip -9` of the original; read them with `gzip -dc`.
- `*.bin` are the Pico's binary capture records; `scripts/capdec.py` decodes
  them.
- Reports were written in a gitignored `runs/<session>/` folder and copied
  here, so `runs/<session>/…` in a report means `traces/<session>/…`. Other
  `runs/…` paths point at unpublished scratch runs.
- Reports cite `SETUP_NOTES.md` (the private rig notebook; see `docs/setup.md`
  §8 for the matching sections), the session brief ("the brief", bare `§N`),
  and sometimes `/private/tmp/jn_*` scratch folders. None of these are
  published.
- Tags: **V** = checked and seen, **V-user** = observed or reported by the
  author, **NV** = not verified. "The planner", "the bench agent" and "the
  user" are the roles described in the top-level README.
- Text files with Windows line ends (`periods.csv` from Python's `csv` writer,
  and the Pico's serial captures) are stored with Unix line ends. No recorded
  checksum covers them, and the analyses give identical results either way.

## Redactions

Personal and device identifiers were replaced in 105 text files before
publishing. No `.gz` or `.bin` file needed changes, and no file covered by a
recorded md5 was touched.

| Placeholder | Was |
|---|---|
| `/Users/<user>`, `/home/<user>`, `<user>` | the Mac and board user names |
| `<jetson-serial>`, `usbmodem<jetson-serial>…` | the Jetson's USB serial, also inside macOS tty names |
| `<pico-serial>` | the Pico's flash ID |
| `xx:xx:xx:xx:xx:xx`, `fe80::<redacted>` | MAC addresses and the link-local IPv6 addresses built from them |
| `<hotspot-ssid>`, `<mac-lan-ip>` | a phone hotspot's network name, the Mac's LAN address |
| `<root-partuuid>` | the board's root partition ID |
| `<bt-headset>` | a Bluetooth device in the Mac's serial-port list |
| `mac-hostname` | the Mac's network name |

So the per-session scripts don't run as they are: they need the host alias,
device IDs and paths of the rig that runs them.

## Removed files

Copies of NVIDIA system files whose notices don't allow redistribution were
removed. Reports still mention them:

- `board_20261026/raw/board/B/nvpmodel.conf`, `…/nvfancontrol.conf`: the
  board's L4T power-mode and fan configs;
- `board_20261026/raw/D_jetson_clocks_script.txt`: a copy of
  `/usr/bin/jetson_clocks`;
- `stage1_20261030/raw/C1_jetsonio_logic.txt`, `…/C2_hdr40_p3767_decoded.dts`,
  `…/board_tmp_jn_run1/hdr40_p3767.dts`: excerpts of NVIDIA's `jetson-io`
  tool and decompiled device-tree overlays.
