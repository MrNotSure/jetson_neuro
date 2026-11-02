# jn_sim — event-vision simulator

The simulation host runs the world (pan/tilt gimbal, moving target, event
camera) and drives a controller over a closed loop. The controller is reached
through a pluggable `Link`: in-process, direct TCP, or (optionally) an SSH
tunnel. This document takes you from a clean checkout to a realtime run with the
live viewer.

The authority on behaviour is `docs/spec_sim.md`; this file is the operator's
guide. Requirement tags like `R9.2` refer to that spec.

---

## 1. Install (macOS)

The simulator targets **macOS 14+ on arm64** with **Python 3.12** (the version
the Jetson also runs, so one venv and one test run cover both sides — §2 of the
spec).

```sh
brew install python@3.12          # one-time, if not already present
scripts/setup_sim_env.sh          # creates .venv/, installs the pinned lock + package
source .venv/bin/activate         # puts `jn-sim` on PATH
```

`scripts/setup_sim_env.sh` is the single setup entry point (R1.5). It is POSIX
`sh`, never uses `sudo`, never installs system packages, and is safe to run
twice. If `.venv` already exists on a different Python it stops and tells you how
to move it aside rather than reusing or deleting it. If a tool is missing it
prints the exact command to fix it and stops.

Verify the install:

```sh
jn-sim --version
MPLBACKEND=Agg python -m pytest -q      # full suite, no display needed (R14.3)
```

One test asserts the interpreter is 3.12, so a wrong venv can't pass silently.

> **Do not keep this checkout in iCloud Drive.** Placeholder eviction and
> `file 2.py` conflict copies break git, and the viewer's `spawn` child and
> `runs/` output are sensitive to it. See the top-level `README.md`.

---

## 2. Quickstart — a realtime run with the viewer

Two terminals, both with `.venv` activated. Order doesn't matter: `run` retries
connecting for up to `link.connect_timeout` (default 10 s, R7.7).

**Terminal 1 — the controller server** (binds `127.0.0.1:5555` by default):

```sh
jn-sim ctl --controller centroid
```

**Terminal 2 — the simulator**, realtime, with the live view:

```sh
jn-sim run --controller tcp://127.0.0.1:5555 --mode realtime --view
```

A matplotlib window opens showing the last period's events (ON/OFF in different
colours, a centre crosshair and a marker at the true target), rolling pan/tilt
vs target az/el, rolling tracking error in px, and a status line (period, sim
time, events/period, compute time, round-trip, misses). Closing the window
doesn't stop the run; ending the run closes the window. Ctrl-C ends the run
cleanly: the current period finishes, BYE is sent, the adapter closes and the
logs and summary are written (R7.5, exit 130).

Each run writes a directory under `runs/` (gitignored):

```
runs/<UTC-timestamp>_<trajectory>_<controller>/
  meta.json      resolved config, seed, scenario+overrides, endpoint type,
                 provenance (git SHA of both hosts, OS/arch, versions), ctl_seed
  periods.csv    one row per control period (see §6)
  summary.json   status, tracking + mission metrics, timing percentiles, counts
  events.bin     only with --save-events (see §7)
```

### The simplest possible run

No controller process, no network — the controller runs in-process and the loop
runs as fast as possible (lockstep):

```sh
jn-sim run --controller inproc:centroid --mode lockstep --duration 5
```

`run` defaults to `--controller inproc:centroid` and `--mode lockstep`, so bare
`jn-sim run` does exactly this for one 30 s episode.

---

## 3. Conventions

Coordinate frames and sign conventions (R3), which the end-to-end tracking test
pins down:

- **World frame:** x forward, y left, z up. A target direction is azimuth
  (positive = left) and elevation (positive = up).
- **Gimbal:** positive pan turns the camera left; positive tilt turns it up. The
  tilt axis rotates with pan. At pan = tilt = 0 the camera looks along +x.
- **Image:** u to the right, v down, origin at the centre of the top-left pixel.
  A positive pan step moves a fixed target towards +u; a positive tilt step
  moves it towards +v.
- **Camera:** pinhole, 320 × 240, square pixels, no distortion. Default
  horizontal FOV 60° gives fx = fy ≈ 277.1 px and principal point (159.5, 119.5).

Other conventions worth knowing:

- **Commands are absolute pan/tilt angle setpoints** in radians, not deltas.
- **Determinism:** one `--seed` (default 0) drives all randomness, split into
  independent streams with fixed keys (R2.5). The same config and seed on the
  same machine give identical outputs apart from measured durations and
  wall-clock metadata. With zero misses, realtime and lockstep produce identical
  trajectories (R7.4).
- **Time:** all sim timestamps are µs since episode start (uint32). Durations use
  monotonic clocks only; wall-clock time appears only in metadata.
- **Portability:** all OS-specific code lives in `host.py` (R2.1). Everything
  else uses `pathlib`, utf-8, explicit little-endian binary, and an explicit
  `spawn` multiprocessing context.

---

## 4. Endpoint types

The controller is chosen by an endpoint string passed to
`jn-sim run --controller` (R9.2):

| Endpoint | Adapter | Use |
|---|---|---|
| `inproc:NAME` | controller runs inside the simulator process | tests, fast local runs |
| `tcp://HOST:PORT` | direct TCP to a running controller | same machine, or any host the simulator can reach directly |
| `ssh://DEST/PORT` | SSH local port-forward, then TCP through it | *optional (T11), not built* — gives a clear "not built yet" error |
| `@NAME` | looks NAME up in a user-local endpoint file | *optional (T11), not built* — gives a clear "not built yet" error |

`NAME` for a test controller is `hold` or `centroid` (R11):

- **`hold`** always commands the initial setpoint. It is also the measurement
  harness's no-op controller.
- **`centroid`** takes the mean position of a period's events, converts it to an
  angular error with the intrinsics, and adds `gain × error` to its setpoint,
  skipping periods with fewer than `n_min` events. Tuned defaults: `gain=0.2`,
  `n_min=200` (§8).

**Use direct TCP for measurement runs (R9.4).** An SSH tunnel would encrypt on
the controller host too, so on the Jetson its CPU cost would fall inside the
measured boundary. The SSH adapter, when built, is for bring-up and fallback
only.

**Security (R9.6):** the controller server has no authentication. It binds to
`127.0.0.1` by default; any other bind address must be given explicitly with
`--listen HOST:PORT`. On the Jetson, bind it to the USB-link address, never
`0.0.0.0`, since the board is also on Wi-Fi.

---

## 5. Running the controller on the Jetson

The controller runs on the Jetson straight from the repo checkout, with **no
install step** (R1.3). Everything `jn-sim ctl` imports uses only the standard
library, numpy and Python 3.12 — the shared modules are `__init__.py`,
`__main__.py`, `ctl.py`, `link.py`, `protocol.py`, `provenance.py` and
`testctl.py`. `ctl` never loads the simulator, `host.py` or matplotlib.

On the Jetson (Python 3.12.3, numpy 2.5.4 in `~/venvs/jn`, SETUP_NOTES §6.4),
bound to the USB-link address so the Mac can reach it but Wi-Fi can't:

```sh
cd ~/jetson_neuro
PYTHONPATH=src ~/venvs/jn/bin/python -m jn_sim ctl \
    --controller centroid --listen 192.168.55.1:5555
```

The `192.168.55.1` address is an example for the operator; it never appears in
the code (R2.2). Then, from the Mac, a realtime run against it:

```sh
jn-sim run --controller tcp://192.168.55.1:5555 --mode realtime --duration 60
```

This is the closed-loop milestone (R14.6). It is not part of acceptance
(spec §4).

**R14.6 passed, 26 Oct 2026** (code `8d91a6d` on both machines; report and data
in `traces/board_20261026/`):

- `jn-sim ctl --controller centroid --listen 192.168.55.1:5555` on the board,
  started from the checkout. `ss -ltn` showed it bound to `192.168.55.1` only.
- Three 60 s realtime runs of `track-sine-v1` from the Mac: all `completed`,
  6000 periods each, with **0**, 1 and 1 misses. A later 60 s run also had 0.
- Controller compute on the board, `ctl_us`: p50 about 90 µs, p99 130–178 µs
  (default DVFS).
- USB-C link, `link_us`: p50 1.0–1.1 ms, p99 about 1.55 ms, against 0.2–0.36 ms
  on Mac loopback. That leaves about 3.8 ms of the 5 ms deadline.
- `meta.json` carries the board's SHA, `aarch64` and Python 3.12.3 under
  `controller` (R8.10).
- A 10 s lockstep run against the board equals the Mac's in-process run in
  all 24 non-timing columns, 1000 rows.
- Misses: 12 in 75,000 board periods over the session. 4 coincide with Mac
  stalls, 3 with small lateness or link bumps, and 5 aren't explained by any
  logged column. Attribution is carried into the next spec.

> **macOS Local Network permission:** the first time the Mac process that
> launches Python opens a connection to the Jetson, macOS may prompt for Local
> Network access (SETUP_NOTES §4.2). Grant it, or the connect silently fails.

---

## 6. Run logs — `periods.csv`

One row per control period, streamed to disk (R12.2). Columns:

```
episode, k, t_us,
pan, tilt, pan_rate, tilt_rate, pan_sp, tilt_sp,     gimbal state + setpoints in effect
cmd_pan, cmd_tilt,                                    as received (may be non-finite; NaN if missed)
cmd_invalid, cmd_clamped, ctl_flags,                  R8.9 safety-net flags; R8.11 controller flags
target_az, target_el, target_u, target_v, err_px, in_fov,
n_events, n_on, n_off,
sim_us, ctl_us, rtt_us, link_us,                      timing (see below)
miss, ctl_rx_ns, ctl_tx_ns, send_lateness_us
```

Timing columns are each measured on **one** host's monotonic clock. Absolute
timestamps from different hosts are never subtracted (there is no clock sync):

- `sim_us` — simulator compute for the period (plant, render, events, encode).
- `ctl_us` = `ctl_tx_ns − ctl_rx_ns` — controller compute, on the controller's
  clock.
- `rtt_us` — OBS sent to CMD received, simulator clock.
- `link_us` = `rtt_us − ctl_us` — transport both ways (a difference of two
  durations, valid across clocks up to their ppm rate difference).
- `send_lateness_us` — OBS send time minus its scheduled time (realtime only).

`summary.json` is accumulated as the rows stream, so memory stays bounded for
long runs (R12.3), and a compact form is printed to the terminal. It holds:
status (and reason if not completed); **tracking error** after a 1 s warm-up, in
two parts — over *all* periods, the angular error `rms_deg`/`max_deg` (the
boresight-to-target angle, defined even with the target out of view or behind
the camera, so losing the target can only raise it), and over *in-view* periods
only, `rms_px_in_view`, `max_px_in_view`, `rms_deg_in_view`, `max_deg_in_view`;
in-FOV fraction; mission metrics (target losses, reacquire times, unrecovered
losses, longest out-of-view interval, per-episode success against
`run.success_in_fov`, and the success rate); events-per-period stats; timing
percentiles; misses; achieved rate; flag counts; and `scenario_exact`.

The "over all episodes" figures come from the per-episode results — counts
summed, maxima taken, the reacquire mean weighted by each episode's ended
losses, RMS values and the in-FOV fraction pooled over all post-warm-up periods
— never from one time series across episodes, since `t_us` restarts each
episode.

---

## 7. Reading `events.bin`

With `--save-events`, every period's events are written in period order as raw
little-endian records of the wire event dtype (R12.2). Each record is 9 bytes:
`t` u32 (µs), `x` u16, `y` u16, `p` u8 (1 = ON, 0 = OFF). It is not `.npy`
because that format stores the array length up front; this stream is appended
period by period through a buffered writer (about 1 MB/s, ~3.6 GB/hour — never
committed).

Read the whole file, then split it back into periods using the `n_events`
column of `periods.csv`:

```python
import numpy as np
import csv
from jn_sim.protocol import EVENT_DTYPE   # fields: t, x, y, p

run = "runs/20261023T120000Z_sine_centroid"

events = np.fromfile(f"{run}/events.bin", dtype=EVENT_DTYPE)   # or np.memmap for huge files

with open(f"{run}/periods.csv", newline="") as fh:
    counts = [int(row["n_events"]) for row in csv.DictReader(fh)]

offsets = np.cumsum([0] + counts)
period_0 = events[offsets[0]:offsets[1]]        # events of the first period
```

`EVENT_DTYPE.itemsize == 9` exactly (packed, no padding), so
`len(events) == sum(counts)`.

---

## 8. Scenarios

`scenarios/` holds named, versioned run configurations (R12.4):
`track-static-v1`, `track-sine-v1`, `track-step-v1`, `track-random-v1`. A
scenario fixes everything except the controller endpoint and the mode (lockstep
or realtime):

```sh
jn-sim run --scenario track-sine-v1 --controller tcp://127.0.0.1:5555 --mode realtime
```

- Without `--scenario`, the defaults apply and the recorded scenario is `null`.
- A committed scenario file is **never edited**; a change gets a new version
  (`-v2`, …).
- `meta.json` records every override layered on top of the scenario (`--config`,
  `--set`, `--trajectory`, `--seed`, `--duration`, `--episodes`), and
  `summary.json`'s `scenario_exact` is true only for a scenario run with no
  overrides.

Override precedence: scenario (or defaults) < `--config` file < `--set` <
specific flags. Overrides are additive and fully recorded, so a run is
reproducible from its `meta.json`.

---

## 9. Protocol summary

TCP, one connection, length-prefixed little-endian messages, `TCP_NODELAY`. The
controller is the server; the simulator connects outbound. One connection
carries `--episodes N` episodes, each framed `HELLO … BYE`. Full field layouts,
sizes and validation rules are in `docs/spec_sim.md` R8; the summary:

| Type | Direction | Payload |
|---|---|---|
| 1 HELLO | sim → ctl | episode, intrinsics, initial pan/tilt, `ctl_seed` (44 B) |
| 2 HELLO_ACK | ctl → sim | controller name (32 B) + JSON metadata |
| 3 OBS | sim → ctl | episode, k, t_start/t_end µs, n, then n × 9-byte events |
| 4 CMD | ctl → sim | episode, k, pan, tilt (may be non-finite), flags, controller timestamps (36 B) |
| 5 BYE | sim → ctl | episode (4 B) |

Key rules:

- **Commands are data (R8.9), not protocol errors.** A non-finite axis holds the
  previous setpoint for that period and sets `cmd_invalid`; an out-of-range
  finite value is clamped and sets `cmd_clamped`. Neither aborts the run — this
  is a simulator-side safety net, not a controller's fault mitigation.
- **A malformed message aborts the run (R8.5, R7.6):** bad magic/version/type/
  size, a message for the wrong episode (including a late CMD from an *earlier*
  episode), a CMD for a future period, an invalid controller name, nonzero
  reserved flag bits, or bad HELLO_ACK metadata.
- **A late reply** — a CMD for a *past* period of the *current* episode — is not
  malformed; it is discarded (R7.3).
- **`ctl_seed`** seeds all controller-side randomness (R8.12); the run seed
  itself is never sent, so a controller can't regenerate the trajectory (R8.4).

---

## 10. Performance (R13)

Targets are set for the Mac. Measured with `jn-sim bench` (R13.1, R13.3) and 60 s
realtime runs (R13.2).

| Check | Target | Measured | Verdict |
|---|---|---|---|
| R13.1 `sim_us` p99, sine + centroid | ≤ 4 ms | **2.6–3.9 ms** | PASS |
| R13.2, realtime 60 s, five user runs (table below) | 0 misses, rate 100 Hz ± 0.01 %, lateness p99 ≤ 0.5 ms | met in full in 1 run; met apart from the rate figure in 1 more | met on a quiet run; see below |
| R13.3 `sim_us` p99, step | — (no target) | 4.5–6.0 ms | recorded |
| R13.3 `sim_us` p99, random | — (no target) | 2.3–4.3 ms | recorded |

**Measurements are load-sensitive.** `bench` percentiles vary run-to-run. Two
representative `jn-sim bench` runs gave sine p99 2.58 ms and 3.94 ms, step
6.05 ms and 4.48 ms, random 2.30 ms and 4.34 ms — hence the ranges above. R13.1
(sine p99 ≤ 4 ms) passed in both; step and random have no hard target (R13.3).

**R13.2: met on a quiet run; this Mac stalls occasionally.** Five 60 s
realtime runs by the user on 26 Oct 2026, `track-sine-v1` with `centroid` over
local TCP, 6000 periods each, all `completed`:

| Run (UTC) | Viewer | Misses | Lateness p99 | Lateness max | Rate (Hz) |
|---|---|---|---|---|---|
| 09:25 | no | 1 | 0.39 ms | 24 ms | 99.995 |
| 09:26 | yes | **0** | **0.003 ms** | 0.18 ms | 99.996 |
| 09:29 | yes | 3 | 0.82 ms | 31 ms | 99.996 |
| 11:42 | yes, window closed mid-run | **0** | **0.004 ms** | 4.3 ms | 99.989 |
| 11:50 | yes, screenshot taken | 2 | 1.23 ms | 68 ms | 99.990 |

- **The code meets the target.** The 09:26 run passes every R13.2 criterion,
  with p99 lateness about 150× under the limit. 11:42 passes everything except
  the rate figure.
- **The failures are single host stalls of 24–68 ms**, not drift. This is a
  Mac running endpoint-security software that can't be switched off; the
  68 ms stall happened while the screenshot was being taken. Keep-awake was
  active, and the viewer is ready before the episode clock starts (B3).
- **The two runs at 99.989–99.990 Hz are a measurement artefact.**
  `achieved_hz` divides the periods by the span from run start until after the
  link closes, so it includes the handshake and the end of the run, about
  6 ms in 60 s. The schedule itself is absolute and doesn't drift. The span
  should be measured over the periods themselves; that fix is carried into the
  next spec, since the measurement harness needs the same number.
- For Jetson measurements, periods with a Mac stall are flagged by
  `send_lateness_us` rather than relied on to be absent.

R13.4 (stage-2 rendering budget) is optional (T24) and not built.

Reproduce:

```sh
jn-sim bench                                           # R13.1 + R13.3; exit 1 if sine p99 > 4 ms
# R13.2: in two terminals, on an otherwise-idle Mac —
jn-sim ctl --controller centroid
jn-sim run --scenario track-sine-v1 --controller tcp://127.0.0.1:5555 \
           --mode realtime --duration 60               # then once more with --view
```

---

## 11. Manual checks

Two things the spec requires a human to confirm once on the Mac, since an
automated display test isn't meaningful:

- **matplotlib window (T1).** A `macosx`-backend window opens from this
  interpreter. Confirmed.
- **Live viewer (T14).** The viewer ran in its `spawn` child process fed by a
  size-1 queue, and a realtime run was hand-checked at the window: events frame,
  pan/tilt tracking the target, rolling error plot and the status line all
  rendered correctly. Screenshot: `docs/img/viewer_t14.png` (user, 26 Oct 2026,
  run 11:50 UTC).
- **Closing the viewer window (R12.1).** Closing the window mid-run doesn't stop
  the run: the 11:42 UTC run finished `completed` with 0 misses after the
  window was closed (user, 26 Oct 2026).

---

## 12. Limitations

- **Clean scene only (stage 1).** The background is uniform, so camera motion
  produces no background events — events come only from the target's edge and
  shot noise. This is a *best case* for event load: controllers that do work per
  event look cheaper here than against a textured scene. Clean-scene energy
  numbers are a **lower bound**, never the comparison result (spec §1). Textured
  background (stage 2) and distractors (stage 3) come later.
- **The sensor is outside the measured boundary.** Events are simulated on the
  Mac; the measured system is the Jetson alone. A real event camera is a Tier 1
  extension (exploration.md §1).
- **Thresholds are derived under stated assumptions** from the DVXplorer Lite
  datasheet (R6.2); several model values are assumptions, all configurable and
  listed in §13.
- **No cross-check against v2e or IEBCS yet.** The credibility check against an
  established simulator (exploration.md §2) is planned, not done.
- **Optional features not built:** SSH tunnel and `@NAME` endpoints (T11), the
  `doctor` command (T16), the replay viewer (T20), Linux support (T21), the
  fault wrapper (T22), the stage timer (T23) and the stage-2 rendering budget
  (T24). Each gives a clear message where it would be reached. Linux is
  macOS-only for now — see §14.

---

## 13. Defaults

From `docs/spec_sim.md` §3, with the `centroid` values tuned in T12.

| Parameter | Default | Source |
|---|---|---|
| resolution | 320 × 240 | DVXplorer Lite |
| horizontal FOV | 60° | assumption (lens-dependent) |
| control period | 10 ms (100 Hz) | decision |
| background | `uniform` | stage 1 |
| I_bg, I_t | 0.25, 1.0 | assumption (log contrast ln 4) |
| target angular radius | 1.5° (≈ 7 px) | assumption |
| sine | az 15° @ 0.25 Hz, el 8° @ 0.35 Hz | assumption |
| step | every 3 s, ≤ 20°/jump, within ±15° az / ±8° el | assumption |
| smooth random | ±15° az, ±8° el, 5 sines, f ∈ [0.05, 0.5] Hz | assumption |
| servo ω_n, ζ | 25 rad/s, 0.8 | assumption |
| servo rate limit | 6 rad/s | assumption |
| angle limits | pan ±90°, tilt ±45° | assumption |
| dead time τ_d | 10 ms | decision (R5.3) |
| dt_phys | 1 ms | — |
| threshold median, σ | 0.12, 0.039 | DVXplorer Lite datasheet (R6.2) |
| log offset ε | 10⁻³ | assumption |
| refractory period | 0.5 ms | assumption |
| shot noise | 0.1 Hz/pixel (≈ 77 events/period) | assumption |
| max_px per sub-step | 1.0 | exploration.md §2 |
| CMD deadline | 5 ms | decision |
| episode length | 30 s | — |
| episodes per run | 1 | — |
| seed | 0 | — |
| consecutive misses before abort | 100 (1 s) | decision (R7.6) |
| connect timeout | 10 s | decision (R7.7) |
| episode success threshold | 0.95 | assumption |
| controller port | 5555 | — |
| **`centroid` gain, n_min** | **0.2, 200** | **tuned in T12** (gain started at 0.05; the spec defaults table was updated to match) |

Every value is configurable via `--set section.key=value`, a `--config` file, or
a scenario.

---

## 14. Linux checklist (optional, T21 — not built)

Linux support is an optional task (T21), built only if the Mac causes problems.
Until then `scripts/setup_sim_env.sh` stops on Linux with a message pointing
here, and the host adapter reports Linux unsupported. When T21 is built, run this
on the Ubuntu machine and record the results below (R14.5):

1. `scripts/setup_sim_env.sh`
2. `MPLBACKEND=Agg python -m pytest -q`
3. `jn-sim doctor` (needs T16)
4. a 60 s realtime run, with the viewer if there is a display
5. if the machine can reach the Jetson, `jn-sim doctor --controller tcp://…`

**Results:** _(empty — T21 not built; no Linux machine accessed yet.)_

---

## 15. Decisions made during implementation

Choices that aren't spelled out field-by-field in the spec, recorded here so a
reader knows why the code looks the way it does.

- **In-process runs go through the wire format.** `inproc:NAME` encodes and
  decodes HELLO, OBS and CMD through `protocol` just like TCP, so the controller
  sees the same f32 intrinsics and setpoints and the 16 MiB cap applies. An
  in-process lockstep run therefore matches a TCP lockstep run byte-for-byte
  (R9.2). Without this, in-process `cmd_pan` stayed float64 and diverged from
  TCP from period 0.
- **Tracking error counts out-of-view periods.** The headline `rms_deg`/`max_deg`
  use the boresight-to-target angle, which is defined even when the target is
  off-sensor or behind the camera. Counting those periods means losing the
  target can't improve the RMS. The pixel error (only defined in view) is
  reported separately as `*_in_view`.
- **The summary is accumulated while rows stream.** It is never built from a
  list of all rows, so peak memory is flat in run length (R12.3). Percentiles
  come from a per-metric sample capped at 2¹⁸ values (exact for runs up to
  ~16 min, a uniform reservoir beyond that); means and maxima are exact.
- **Overall figures aggregate the per-episode results**, never one time series
  across episodes, because `t_us` restarts each episode (a loss open at one
  episode's end must not merge into the next).
- **The run directory is created exclusively.** Two runs in the same second with
  the same trajectory and controller get `…_2`, `…_3`, so neither overwrites the
  other.
- **An unexpected error in the loop finalises the logs as `aborted`** (with the
  error text as the reason) and then propagates, so a controller bug can't leave
  a half-written run labelled `completed` (R7.8).
- **Realtime pacing and deadlines use `monotonic_ns` throughout**; the schedule
  is absolute (`t0 + (k+1)·T`), so a slow period never shifts later sends.
- **Ctrl-C finishes the current period.** A SIGINT handler sets a flag that the
  loop checks at the next period boundary; the in-flight period completes, BYE
  is sent, and the logs are written (R7.5).
- **A late reply to an episode's last OBS is waited for before BYE** (up to the
  CMD timeout) and discarded, so it can't collide with the next episode's
  handshake; a timeout there is a lost connection (R7.3).
- **OBS encoding is counted in `sim_us`.** The message is encoded inside the
  `sim_us` window and the bytes handed to the link, so the timing reflects the
  simulator's real per-period work (R12.2).
- **A startup connect failure and a mid-run drop are told apart.** Only the
  initial connect raises `LinkConnectError` ("could not connect"); a later
  `ConnectionResetError`/`BrokenPipeError` is reported as "connection lost".
- **The target disc is anti-aliased in pixel space** with a 1 px linear edge
  ramp; the on-axis pixel radius sizes the ROI bounds, which carry a margin.
- **Controller metadata is built once, at process startup**, so it describes the
  code the process actually loaded and is identical for every connection and
  episode it serves (R8.10).
- **Events are emitted in a total order** (time, then y, x, polarity), so the
  full-frame and ROI paths produce byte-identical batches (R6.7).
- **Refractory and noise interact by construction:** shot noise is drawn over
  the whole frame per period from the episode noise stream and then passed
  through the same refractory filter as scene events, so a noisy pixel can't
  exceed its refractory rate.
- **Timeouts without a spec value:** the controller waits 15 s for a HELLO
  (handshake) and drops a connection that goes silent mid-run after 30 s
  (`--idle-timeout`), chosen over TCP keep-alive because an explicit read
  deadline is portable and testable.
- **`achieved_hz`** is the number of logged periods divided by the wall-clock
  span of the run, reported in `summary.json`.
