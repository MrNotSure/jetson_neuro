# Spec — event-vision simulator (simulation host)

*Drafted 22 October 2026 for review, revised the same day after a review.
Revised 23 October 2026: commands as data, controller seed, flags and
metadata, mission metrics, a fault-injection fixture, stage timing and
versioned scenarios (R8.9–R8.13, R11.3, R12.4). Revised again the same day:
tasks split into core and optional (§4, §5); Linux, SSH, the doctor, the fault
wrapper, the stage timer and the stage 2 budget moved to optional tasks.
Revised again the same day: Python 3.12 on every host, one venv and one test
run (§2, R14.3), replacing a 3.15 main venv plus a 3.12 test venv.
Revised 25 October 2026 after the final-checkpoint review: tuned `centroid`
values, error statistics over all periods, aggregation over episodes,
run-directory collisions, unexpected errors, in-process runs through the wire
format, metadata built at startup, viewer ready before the clock starts
(R7.8, R8.10, R9.2, R12.1–R12.3, defaults).*

## 1. Purpose and scope

The simulation host simulates the world for the closed loop in
`exploration.md` §2: a pan/tilt gimbal, a moving target and an event camera.
Each control period it sends that period's events to a controller and applies
the pan/tilt command it gets back. Later the controller runs on the Jetson and
gets measured.

The simulation host is the Mac. An Ubuntu 24.04 LTS computer is a possible
fallback. The coding rules (R2.2) keep that option open at no extra cost, but
Linux support itself is an optional task (T21), built only if the Mac causes
problems.

The goal is a simple, defensible instrument, not proof that an algorithm works:
a clean scene to start with (staged below), transparent models, deterministic
runs and logged provenance.

**In scope:**

- Camera, target, gimbal and event models; loop timing; the wire protocol.
- Connection adapters: in-process and direct TCP. An SSH tunnel is optional
  (T11).
- A host adapter for the few OS-specific pieces. A `doctor` command that checks
  a host and a connection step by step is optional (T16).
- Two test controllers that exercise the loop; live view; run logs; versioned
  scenarios (R12.4); tests; docs.
- In the controller runner, a fault-injection fixture (R11.3) and a stage timer
  (R8.13), both optional (T22, T23) and built when the fault study and the
  algorithm work need them.
- Running on macOS, where it is developed and verified. Ubuntu 24.04 is
  optional (T21).

**Out of scope:**

- Algorithms A–D and their training (`exploration.md` §5).
- Anything running on the Jetson. The controller runner and the modules it
  imports are written to run there from the repo checkout, with Python 3.12
  and numpy only (R1.3), but that is checked later.
- Power measurement, the idle / no-op / algorithm block harness, INA228 and
  Pico.
- Fault studies of A–D, their detectors and recoveries, and clock control
  (`exploration.md` §3, §5). This spec only provides the hooks they use.
- Textured background and distractors (stages 2 and 3, below); cross-checks
  against v2e or IEBCS; MuJoCo; real camera drivers.
- Clock synchronisation between hosts.
- Windows, and showing the live view over X11 forwarding.
- Setting up SSH keys or networking on the Linux machine. I have never seen
  that machine or its connection to anything, so the SSH adapter uses whatever
  the user's own SSH configuration provides (R9.3).

**Core and optional.** §5 splits the tasks. The core tasks reach the closed
loop, and acceptance (§4) covers only them. Optional tasks keep their
requirements in §3, so building one later needs no redesign. Each says when it
becomes worth building.

### Scene, in stages

This spec builds stage 1, a clean scene. It's the fastest way to the loop and
the Jetson measurements, and neither depends on the scene.

But a clean scene is a best case for event load. With a uniform background,
camera motion produces no background events, so events come only from the
target's edge and from noise. A real event camera panning across a real scene
fires on every edge in view. Controllers that do work per event (A and D in
`exploration.md` §5) therefore look cheaper here than they would in reality,
while dense ones (B and C) barely change. So clean-scene energy numbers are
reported as a lower bound, never as the comparison result.

| Stage | Scene | Gives | When |
|---|---|---|---|
| 1 (this spec) | uniform background, built as a swappable layer (R4.1) | the whole pipeline; energy against event load by raising the shot-noise rate (R6.4), which is already a setting | now |
| 2 | textured background with a contrast setting; contrast 0 is the stage 1 scene | realistic event counts and a real tracking problem | before any comparison of A–D is reported |
| 3 | moving distractors | something for the learned controllers to win at | only if needed |

The writeup then shows energy per decision against event load, with the clean
scene as the zero point of that curve.

Stage 2 is mostly renderer work: a generated panorama viewed through the
camera's rotation (`exploration.md` §2). The event model doesn't change, and
R13.4 measures the rendering budget in advance. It does bring one open
question: background events swamp the `centroid` test controller, so
controller A has to separate the target from the background. The likely route
is simulated gyro readings in each OBS. The DVXplorer Lite has an IMU, and
real event-camera systems use one to cancel their own motion. That decision
belongs in the stage 2 spec.

## 2. Decisions

| Topic | Decision | Reason |
|---|---|---|
| Platforms | macOS 14+ on arm64 (core). Ubuntu 24.04 LTS on x86_64 or arm64 as an optional fallback (T21). POSIX only. | the Mac is the machine in use. The coding rules keep Linux cheap to add later; its architecture is unknown, so both are allowed |
| Engine | none; numpy for plant, rendering and events | two joints, no contacts; every parameter visible |
| Resolution | 320 × 240 | matches the iniVation DVXplorer Lite, so a later upgrade to that camera keeps the controllers' input format unchanged |
| Control rate | 100 Hz | gives the power meter more samples per decision (INA228 sampling, `exploration.md` §4; the rate question itself is in §2) |
| Scene | stage 1: uniform background, one target, with the background as a swappable layer (R4.1). Textured background and distractors follow in stages 2 and 3 (§1). | the loop and the Jetson measurements don't depend on the scene, so a clean scene is the fastest way to them. Its event counts are a best case, which §1 states as a limitation. |
| Python | 3.12 on every host: Homebrew `python@3.12` on the Mac, the system 3.12.3 on the Jetson, and the system 3.12 on Ubuntu 24.04 (T21). `requires-python = ">=3.12,<3.13"` enforces it. | the Jetson stays on 3.12: JetPack 7.2 ships it, and the board's verified PyTorch install runs on it (SETUP_NOTES §6.4). With one version everywhere, one venv and one test run also cover the controller side. Homebrew's build is a framework build, which suits matplotlib's native Mac window. Decided 23 Oct 2026. |
| Dependencies | numpy is the package's only runtime dependency; matplotlib is an optional extra that the setup script always installs on a simulation host. One lock file for all platforms. | the controller host (the Jetson) needs numpy only; both simulation hosts get the same pins |
| Live view | matplotlib | requested |
| Transport | TCP, one connection, length-prefixed messages, `TCP_NODELAY` | during fast motion an event batch can exceed one UDP datagram (64 kB); TCP gives framing and delivery without fragmentation code. Replaces "UDP" in `exploration.md` §2. |
| Who listens | the controller is the server; the simulator connects | outbound from the simulation host works through the Mac's stealth-mode firewall (SETUP_NOTES §4.2) and needs no firewall assumptions on the Linux machine |
| SSH (optional, T11) | delegated to the system OpenSSH client and the user's SSH config | works on a host whose SSH setup I don't know, and the simulator never touches keys or passwords |
| Commands | absolute pan/tilt angle setpoints | models position-controlled hobby servos, as on the Tier 1 gimbal (`hardware_demo_plan.md` §2) |
| Controller interface | the simulator drives a `Link` (R9); no Gymnasium | the simulator owns the clock and calls a remote controller, the reverse of Gymnasium's agent-calls-environment pattern, and it avoids a dependency. A Gymnasium wrapper can come later for training. Replaces the optional Gymnasium interface in `exploration.md` §2. |
| Randomness | one seed, split into independent streams with fixed keys (R2.5) | reproducible, and adding a stream later never shifts the existing ones |

## 3. Requirements

### R1 Environment

- **R1.1** A venv `.venv/` at the repo root. The package's only runtime
  dependency is numpy; matplotlib is the optional extra `view`, and pytest the
  extra `dev`. On a simulation host the setup script always installs both
  extras (R1.5), so there the viewer is unavailable only without a display
  (R2.4).
  All versions, including transitive ones, are pinned exactly in one lock
  file, `requirements.lock`, generated with `uv pip compile --universal` so the
  same file installs on macOS arm64 and on Linux x86_64 and aarch64. Every
  compiled package in it (numpy, matplotlib, contourpy, kiwisolver, pillow)
  has binary wheels for Python 3.12 on all three platforms (checked on
  PyPI, 22 Oct 2026), so no install compiles anything.
- **R1.2** Package `jn_sim` under `src/`, installed editable, with a `jn-sim`
  command.
- **R1.3** The controller runs on the Jetson straight from the repo checkout,
  with no install step:

  ```
  cd ~/jetson_neuro && PYTHONPATH=src ~/venvs/jn/bin/python -m jn_sim ctl …
  ```

  - Everything that command imports uses only the standard library, numpy and
    Python 3.12 features: `jn_sim/__init__.py`, `__main__.py`, `ctl.py`,
    `link.py`, `protocol.py`, `provenance.py` and `testctl.py` (the *shared
    modules*).
  - `__main__.py` imports a subcommand's modules only when that subcommand
    runs, so `ctl` never loads the simulator, `host.py`, the SSH adapter or
    matplotlib. `link.py` imports the SSH adapter only for `ssh://` endpoints.
  - The Jetson venv `~/venvs/jn` has Python 3.12.3 and numpy 2.5.4, the same
    numpy the lock file pins (`pip list` on the board, 19 Oct 2026; recorded
    in SETUP_NOTES §6.4).
- **R1.4** Run outputs go to `runs/`, which is gitignored.
- **R1.5** `scripts/setup_sim_env.sh` is the single setup entry point on both
  operating systems:
  - It is POSIX `sh`, so it runs under macOS `/bin/sh` and Ubuntu's `dash`.
  - It detects the OS and picks the interpreter per §2: on macOS, Homebrew's
    `python3.12`; on Linux (T21), the system `python3.12`, or uv's 3.12 if the
    system one lacks the `venv` module. Until T21 is built, it stops on Linux
    with a message saying so.
  - If `.venv` exists with any other Python version, it stops and says how to
    move the old venv aside, rather than reusing or deleting it.
  - It creates `.venv`, installs `requirements.lock` and installs the package
    editable. Running it twice is safe.
  - It never uses `sudo` and never installs system packages. If something is
    missing, it prints the exact command to fix it and stops.

### R2 Portability

- **R2.1** All OS-specific code lives in one module, `host.py`. Nothing else
  branches on the operating system. `host.py` provides:
  - **Keep-awake during realtime runs.** macOS: `caffeinate -i -w <pid>`.
    Linux: a child `systemd-inhibit --what=idle:sleep … sleep infinity`, ended
    with the run. If neither works, warn and continue.
  - **Viewer backend.** macOS: `macosx`. Linux: `TkAgg` if tkinter imports and
    `DISPLAY` or `WAYLAND_DISPLAY` is set. Otherwise there is no viewer.
    `MPLBACKEND` overrides the choice.
  - **Config directory.** `$XDG_CONFIG_HOME/jn_sim`, default
    `~/.config/jn_sim`, on both systems.

  The core build has only the macOS paths. The Linux paths come with T21 and
  the config directory with T11. On any other OS the adapter reports clearly
  what isn't supported yet.
- **R2.2** Coding rules for every other module:
  - Paths via `pathlib`; no hardcoded separators or home paths. Run directory
    names contain no colons.
  - Text files opened with `encoding="utf-8"`; CSV with `newline=""`.
  - Durations and deadlines use `time.monotonic_ns` or `time.perf_counter_ns`
    only. Wall-clock time is used only for metadata.
  - Multiprocessing always uses an explicit `spawn` context. The default
    differs between systems (macOS spawn, Linux fork, and forkserver on Linux
    from Python 3.14).
  - Binary formats are explicitly little-endian.
  - External tools (`git`, `ssh`, `caffeinate`, `systemd-inhibit`) are
    optional. They are found with `shutil.which`, called with argument lists
    (never `shell=True`), and a missing tool gives a clear message, not a
    traceback.
  - No host-specific names in code: no `jetson` alias, no `192.168.55.1`, no
    `/dev/cu.usbmodem*`. They appear only in documentation as examples or in a
    user's local endpoint file (R9.5).
- **R2.3** Determinism holds per platform: the same config and seed on the
  same platform give identical outputs, apart from measured durations (the
  timing columns of R12.2, including `ctl_rx_ns` and `ctl_tx_ns`) and
  wall-clock metadata. Across platforms, numpy's random
  streams are identical, but its vectorised `log` and `exp` can differ in the
  last bits between CPUs, so event counts can differ slightly. Cross-platform
  agreement is checked on summary metrics, within a tolerance set in T21.
- **R2.4** The viewer is optional on every platform. If matplotlib isn't
  installed, or there is no usable display, `--view` fails before the run
  starts, with a message naming the fix (`pip install -e '.[view]'`, setting
  `DISPLAY`, or installing tkinter). Runs without `--view` never import
  matplotlib.
- **R2.5** Seeding. One integer seed (`--seed`, default 0) drives all
  randomness. Each stream has its own generator,
  `np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=KEY)))`,
  with a fixed key:

  | Stream | Key | Scope |
  |---|---|---|
  | ON thresholds | (0,) | whole run: a sensor's pixel mismatch doesn't change between episodes |
  | OFF thresholds | (1,) | whole run |
  | trajectory | (2, e) | episode e |
  | shot noise | (3, e) | episode e |
  | controller | (4, e) | episode e; the simulator only derives `ctl_seed` from it (R8.12) |

  - A new stream gets a new key, so adding one never shifts the existing
    streams.
  - PCG64 is named explicitly instead of using `default_rng`, whose bit
    generator may change in future numpy versions.
  - Draws depend only on the seed, the episode and the period index, never on
    wall-clock time, the gimbal or the controller's commands. So misses in
    realtime mode don't shift the noise stream (R7.4).
  - Identical streams also need the same numpy version, which the lock file
    pins.

### R3 Camera and conventions

- **R3.1** Pinhole, 320 × 240 px, square pixels, no distortion. Horizontal FOV
  configurable, default 60° (assumption: the DVXplorer Lite has a CS mount, so
  the FOV depends on the lens). That gives fx = fy ≈ 277.1 px and a principal
  point at (159.5, 119.5).
- **R3.2** World frame: x forward, y left, z up. A target direction is given as
  azimuth (positive = left) and elevation (positive = up).
- **R3.3** Positive pan turns the camera left; positive tilt turns it up. The
  tilt axis rotates with pan. At pan = tilt = 0 the camera looks along +x.
- **R3.4** Image coordinates: u to the right, v down, origin at the centre of
  the top-left pixel. So a positive pan step moves a fixed target towards +u,
  and a positive tilt step moves it towards +v.

### R4 Scene and target

- **R4.1** The scene is a background layer with one target composited over it.
  Intensities are linear (no gamma or tone mapping).
  - The background is chosen by `scene.background`. This spec implements only
    `uniform` (intensity I_bg); any other value is a configuration error.
  - A background provides one call, the linear intensity of a pixel window at
    a given gimbal pose, and a flag saying whether it is uniform. The renderer
    uses only that call and the flag (R6.7). Nothing else depends on the
    background type: not the loop, the protocol, the controllers or the logs,
    apart from the config and `meta.json`.
  - The target is a disc of intensity I_t and angular radius r_t, with a 1 px
    linear anti-aliased edge.
- **R4.2** Trajectories in (az, el), all seeded:
  - static;
  - sine: frequency and phase per axis (a Lissajous path);
  - step: a jump every T_step, each at most step_max from the previous
    position;
  - smooth random: a sum of 5 sinusoids per axis, frequencies in
    [0.05, f_max] Hz, bounded by the amplitude.
- **R4.3** Same seed → identical trajectory.

### R5 Gimbal plant

- **R5.1** Per axis: a second-order position servo (natural frequency ω_n,
  damping ζ) with a rate limit, angle limits and a dead time τ_d on the
  setpoint.
- **R5.2** Fixed integration step dt_phys (default 1 ms).
- **R5.3** The setpoint from CMD_k takes effect at sim time (k+1)·T + τ_d. The
  dead time is fixed, so the plant never depends on measured network latency
  and runs stay deterministic. Default τ_d = 10 ms (one period), standing in
  for controller and servo latency.
- **R5.4** Setpoints reach the plant only through one validation call, which
  applies R8.9 per axis and returns the setpoint used plus the `cmd_invalid`
  and `cmd_clamped` flags. Nothing else writes a setpoint, so a non-finite
  value can never reach the integrator.

### R6 Event model

- **R6.1** The standard DVS model on log intensity L = ln(I + ε), where
  ε = 10⁻³ keeps the log finite at I = 0. A pixel emits
  an ON (OFF) event each time L rises (falls) by its threshold relative to the
  pixel's reference level. Each event moves the reference by one threshold.
- **R6.2** Per-pixel thresholds are drawn once per seed from a Gaussian, for ON
  and OFF independently, and clipped at ≥ 0.01. Defaults come from the
  DVXplorer Lite datasheet: 50 % of pixels respond to 13 % contrast, 99.9 % to
  27.5 % contrast. That gives a median of ln(1.13) ≈ 0.12 and σ ≈ 0.039,
  assuming Weber contrast and a Gaussian spread.
- **R6.3** Per-pixel refractory period (default 0.5 ms, assumption). Events
  inside it are dropped.
- **R6.4** Shot noise: Poisson events at rate r_noise per pixel (default
  0.1 Hz, assumption), random polarity, uniform in time.
- **R6.5** Sub-stepping: within a period, poses are subdivided so that no image
  content moves more than max_px (default 1 px) between rendered sub-steps:
  the target always, and the background too when it isn't uniform. Event
  timestamps are interpolated linearly between sub-steps.
- **R6.6** All sim timestamps, both event `t` and OBS `t_start_us` /
  `t_end_us`, are µs since episode start, as uint32 (which overflows after
  about 71 min); episodes are capped at 60 min. Events within a batch are
  sorted by time.
- **R6.7** Two rendering paths, which must give identical events:
  - **Full frame:** every pixel at every sub-step. Used for any non-uniform
    background, and as the reference.
  - **Region of interest:** with a uniform background, only the pixels the
    target covered at either end of a sub-step can change, so rendering and
    event generation touch only those, plus a margin. Noise (R6.4) still
    covers the whole frame.

### R7 Loop and timing

- **R7.1** Period T = 10 ms. Period k covers sim time [kT, (k+1)T). At its end
  the simulator sends OBS_k with that period's events, then waits for CMD_k.
- **R7.2** Lockstep mode waits for every CMD (timeout 5 s, then abort) and runs
  as fast as possible. It is deterministic in the sense of R2.3.
- **R7.3** Realtime mode:
  - OBS_k is sent at monotonic time t0 + (k+1)·T, on an absolute schedule, so
    there is no cumulative drift.
  - CMD_k must arrive within the deadline (default 5 ms after OBS_k is sent).
    If it doesn't, the previous setpoint is held, a miss is logged, and the late
    CMD is discarded when it arrives (matched by k) if it is still in the same
    episode; a CMD from an earlier episode is malformed and aborts the run
    (R8.5, R7.6).
  - So that a late reply never crosses into the next episode: if the reply to
    an episode's last OBS missed its deadline, the simulator waits for it
    before sending BYE, up to the 5 s CMD timeout, and discards it. A timeout
    there counts as a lost connection (R7.6).
  - Periods are never skipped. A late send is logged as lateness.
- **R7.4** With zero misses, realtime and lockstep runs with the same config and
  seed produce identical trajectories.
- **R7.5** Ctrl-C ends a run cleanly: the current period finishes, BYE is sent,
  adapters close (including any SSH tunnel), and logs and summary are written.
- **R7.6** Connection loss. If the connection closes or fails mid-episode
  (controller crashed, SSH tunnel exited, socket reset, malformed message),
  the run aborts. There is no reconnect: a resumed episode would be neither
  deterministic nor a clean measurement block. The simulator stops the loop,
  closes the adapter, keeps `periods.csv` up to the last finished period and
  writes `summary.json` with the reason. A connection that stays open but goes
  silent, such as half-open TCP after a pulled cable, counts as lost after
  `loop.max_consecutive_misses` misses in a row in realtime mode (default 100,
  i.e. 1 s), or after the 5 s CMD timeout in lockstep.
- **R7.7** Startup. `jn-sim run` retries connecting every 0.2 s for up to
  `link.connect_timeout` (default 10 s), so `run` and `ctl` can be started in
  either order. After that it exits with the adapter's error and creates no
  run directory, since nothing ran. The SSH adapter's tunnel has its own 15 s
  readiness limit (R9.3).
- **R7.8** Exit status, mirrored as `status` in `summary.json`:

  | Exit | `status` | When |
  |---|---|---|
  | 0 | `completed` | all episodes finished |
  | 1 | `aborted` | R7.6, R7.7, R8.8, or an unexpected error in the loop, with the error text as the reason; logs are finalised before the error propagates |
  | 2 | — | usage or configuration error; no run directory |
  | 130 | `interrupted` | Ctrl-C (R7.5) |

### R8 Controller interface and protocol

- **R8.1** A controller implements `reset(hello) -> name` and
  `step(obs) -> (pan, tilt)` or `(pan, tilt, flags)`, with flags defaulting to
  0 (R8.11). From T23 on, the runner also gives each controller a stage timer
  (R8.13). How a controller is reached is the job of the connection adapters
  (R9).
- **R8.2** Message format. Everything is little-endian. Each message starts
  with a 12-byte header: magic `JNSM`, version (u16, = 1), type (u16) and
  payload length (u32). Payloads are at most 16 MiB.

  | Type | Direction | Payload | Bytes |
  |---|---|---|---|
  | 1 HELLO | sim → ctl | episode u32, width u16, height u16, period_us u32, fx fy cx cy f32, pan0 tilt0 f32, ctl_seed u64 (R8.12) | 44 |
  | 2 HELLO_ACK | ctl → sim | controller name: 32 bytes ASCII, NUL-padded (R8.7); meta_len u32; then meta_len bytes of UTF-8 JSON (R8.10) | 36 + meta_len, with meta_len ≤ 65,536 |
  | 3 OBS | sim → ctl | episode u32, k u32, t_start_us u32, t_end_us u32 (R6.6), n u32, then n events | 20 + 9n |
  | 4 CMD | ctl → sim | episode u32, k u32, pan f32, tilt f32 (rad, absolute setpoints; may be non-finite, R8.9), flags u32 (R8.11), t_rx_ns u64, t_tx_ns u64 (controller's monotonic clock; only their difference is meaningful, R12.2) | 36 |
  | 5 BYE | sim → ctl | episode u32 | 4 |

  Fields are packed in the order listed, with no padding. Each event is 9
  bytes: t u32 (µs), x u16, y u16, p u8 (1 = ON, 0 = OFF). The protocol stays
  at version 1, since nothing has been implemented against it yet.
- **R8.3** Episodes. One connection carries `--episodes N` episodes (default
  1), each HELLO … BYE, numbered e = 0 … N−1 in order. Each episode resets the
  plant, the trajectory, the event-model state and the noise stream (R2.5);
  the sensor thresholds stay. The controller's `reset` runs at each HELLO.
  The measurement harness will use this for repeated blocks over one
  connection (`exploration.md` §3). A controller serves one simulator at a
  time.
- **R8.4** The controller gets no ground truth, only events and the camera
  intrinsics from HELLO.
- **R8.5** A malformed message raises a clear error and closes the connection;
  on the simulator side that aborts the run (R7.6). Malformed means:
  - bad magic, version, type or size;
  - a message for an episode other than the current one (including a late CMD
    from an earlier episode, which aborts the run per R7.6), or a CMD for a
    future period;
  - an invalid controller name;
  - nonzero reserved bits in CMD `flags` (R8.11);
  - HELLO_ACK metadata over 64 KiB, not a UTF-8 JSON object, or different from
    the first episode's on the same connection (R8.10).

  Not malformed: a late reply, meaning a CMD for a past period of the current
  episode, which gets discarded (R7.3); and a non-finite or out-of-range pan
  or tilt, which is data (R8.9).
- **R8.6** `jn-sim ctl` serves connections one after another: when one closes,
  it waits for the next, until Ctrl-C. `--once` makes it exit after the first
  connection closes (for tests and scripts). BYE ends an episode, not the
  connection.
- **R8.7** Controller names match `[A-Za-z0-9_.-]{1,32}`, because they become
  part of run directory names. `jn-sim ctl` rejects any other name at
  startup, so the 32-byte field never needs truncating.
- **R8.8** If an OBS batch would exceed the 16 MiB payload cap (about 1.86 M
  events), the run aborts (R7.6) with a clear error rather than splitting the
  batch. The cap is above the DVXplorer Lite's maximum throughput (100 M
  events/s, i.e. 1 M per 10 ms period), so it can only happen with an
  implausible configuration.
- **R8.9** Commands are data. Each axis of a CMD is checked before it reaches
  the plant (R5.4):
  - a non-finite value (NaN, ±Inf) holds that axis's previous setpoint for the
    period and sets `cmd_invalid`;
  - a finite value outside the angle limits is clamped to the limit and sets
    `cmd_clamped`.

  Neither is malformed, and neither aborts the run. A bit flip in a float32
  produces exactly these values (R11.3), and so can a buggy learned
  controller; treating them as protocol errors would end every fault run.
  The hold stands in for an actuator driver's range check. It is a
  simulator-side safety net, not a controller's fault mitigation: a mitigation
  has to run on the controller, so that its energy is measured.
- **R8.10** Controller metadata. HELLO_ACK carries a JSON object that `ctl.py`
  builds once, at startup, so it describes the code the process actually
  loaded:
  - controller name and parameters;
  - fault configuration (R11.3), or `null`;
  - stage-log directory (R8.13), or `null`;
  - git SHA and dirty flag of the controller host's checkout, or `unknown` if
    `git` is missing;
  - OS and architecture; Python and numpy versions, and torch's if it is
    loaded.

  It is the same for every connection and episode the process serves. `meta.json` stores it
  under `controller`, and the in-process adapter builds the same object
  locally. The lookups live in `provenance.py`, shared by both sides (R1.3).
  Without this, a run measured on the Jetson couldn't be tied to the code that
  ran there, because only the simulation host's SHA would be recorded
  (SETUP_NOTES §6.2).
- **R8.11** CMD `flags`: bit 0, a fault was injected in this decision; bit 1, a
  detector fired; bit 2, a recovery was applied. All other bits are reserved
  and must be 0 (R8.5). The simulator only records them, in the same
  `periods.csv` row as that period's tracking metrics, so no join across host
  clocks is needed. It never acts on them.
- **R8.12** Controller seed. HELLO's `ctl_seed` is
  `np.random.SeedSequence(seed, spawn_key=(4, e)).generate_state(1, np.uint64)[0]`
  (R2.5). All controller-side randomness, fault injection included, derives
  from it, so a run is reproducible from its seed. The run seed itself is
  never sent: with it, a controller could regenerate the trajectory stream,
  which R8.4 rules out.
- **R8.13** Stage timing (optional, T23). `ctl.py` gives each controller a stage timer, which
  `step` uses to mark named stages such as decode, representation, inference,
  control law and encode. By default the timer does nothing. With
  `jn-sim ctl --stage-log DIR`, durations go to
  `DIR/<YYYYMMDDTHHMMSSZ>_<name>/stages.csv` on the controller's monotonic
  clock: one directory per connection, one row per (episode, k, stage). The
  directory is in the controller metadata (R8.10), so the file joins to
  `periods.csv` offline by episode and k. No protocol change. On the Jetson
  those writes fall inside the measured boundary, which is why the log is off
  by default and its state is recorded.

### R9 Connection adapters

- **R9.1** The loop talks to a controller only through a `Link` interface:
  `open(hello) -> controller name`, `exchange(obs, deadline) -> cmd or None`,
  `close()`. It does not know which adapter is behind it.
- **R9.2** The adapter is chosen by an endpoint string:

  | Endpoint | Adapter | Use |
  |---|---|---|
  | `inproc:NAME` | runs the controller inside the simulator process; HELLO, OBS and CMD still go through the wire encode and decode (R8.2), so an in-process lockstep run gives the same outputs as a TCP lockstep run | tests, fast local runs |
  | `tcp://HOST:PORT` | direct TCP to a running controller | same machine, or any controller host the simulation host can reach directly |
  | `ssh://DEST/PORT` | an SSH local port forward to `127.0.0.1:PORT` on DEST, then TCP through it | when direct TCP isn't possible, or the network between the hosts isn't trusted; optional (T11) |
  | `@NAME` | looks NAME up in the user's endpoint file (R9.5) | host-specific addresses kept out of the repo; optional (T11) |

  Until T11 is built, `ssh://` and `@NAME` endpoints give a clear "not built
  yet" error.

- **R9.3** The SSH adapter (optional, T11).
  - DEST goes to the system `ssh` exactly as given: an alias from the user's
    SSH config, `user@host`, or an address. SSH port, user, keys, jump hosts
    and host keys come from the user's SSH configuration. The simulator never
    reads `~/.ssh` and never handles keys or passwords. That is what lets it
    work on a host whose SSH setup I don't know.
  - It runs:

    ```
    ssh -N -L 127.0.0.1:LOCAL:127.0.0.1:PORT
        -o BatchMode=yes -o ExitOnForwardFailure=yes
        -o ControlMaster=no -o ControlPath=none
        -o ServerAliveInterval=5 -o ServerAliveCountMax=3 -o ConnectTimeout=10
        [link.ssh_options …] DEST
    ```

    - `BatchMode` never prompts, so a missing key fails fast instead of
      hanging.
    - `ExitOnForwardFailure` makes a failed forward an error rather than a
      silent dead tunnel.
    - `ControlMaster=no` and `ControlPath=none` give a dedicated connection
      whose lifetime the adapter controls, even when the user's config
      multiplexes connections (the Mac's does).
    - `ServerAlive*` notices a pulled cable within about 15 s.
  - LOCAL is a free port the adapter picks. The tunnel counts as ready once a
    TCP connect to LOCAL succeeds (polled, 15 s timeout).
  - If `ssh` exits first, its stderr is reported and classified the same way
    as SETUP_NOTES §6.1: authentication refused, host key mismatch, name not
    resolved, unreachable, or timed out. If it exits during a run, the
    forwarded connection closes and R7.6 applies, with the classified stderr
    as the abort reason.
  - `ssh` starts in its own session, so Ctrl-C reaches only the simulator. The
    simulator sends BYE, then ends `ssh` with SIGTERM, and SIGKILL after 2 s.
    No `ssh` process is left running.
  - The `ssh` executable is configurable (`link.ssh_command`, default `ssh`),
    which is how the tests substitute a stub.
- **R9.4** The endpoint type is recorded in `meta.json`. An SSH tunnel encrypts
  on the controller host too, so on the Jetson its CPU cost would fall inside
  the measured boundary. Measurement runs should use direct TCP; the SSH
  adapter is for bring-up and fallback.
- **R9.5** Named endpoints (optional, T11) are kept in a user-local file
  `<config dir>/endpoints.json` (R2.1), mapping names to endpoint strings, for
  example `{"jetson": "tcp://192.168.55.1:5555"}`. It is not in the repo,
  because addresses differ per host.
- **R9.6** Security: the controller server has no authentication.
  - It binds to `127.0.0.1` by default; any other address has to be given
    explicitly with `--listen`.
  - On the Jetson, bind it to the USB-link address, never `0.0.0.0`, since the
    board is also on Wi-Fi. Alternatively, keep it on localhost and use the SSH
    adapter, which then supplies the authentication.

### R10 Doctor (optional, T16)

- **R10.1** `jn-sim doctor [--controller ENDPOINT] [--json]` checks a host and
  optionally a connection, step by step. It stops at the first failure and
  prints the raw error with a hint. It changes nothing on either host.
- **R10.2** The steps:
  1. **Host:** OS, architecture, Python version and whether it is in the
     supported range, installed versions compared with the lock file, display
     and chosen viewer backend, keep-awake method, whether `git` and `ssh`
     exist.
  2. **Timer:** 200 periods at the configured control period (default 10 ms)
     on the absolute schedule, reporting
     lateness p50, p99 and max against R13.2.
  3. **Endpoint**, if given:
     - `tcp`: resolve the name, connect, HELLO/ACK handshake (showing the
       controller metadata, R8.10), then 200 OBS/CMD
       exchanges with empty event batches, reporting round-trip p50, p99 and
       max.
     - `ssh`: first `ssh -o BatchMode=yes -o ConnectTimeout=10 DEST true`, to
       separate "can't reach or log in" from "tunnel or controller problem",
       classified as in R9.3; then the tunnel; then the same steps as `tcp`.
- **R10.3** This is the tool for bringing up the Linux machine, or any other
  new host, without knowing in advance how it is set up.

### R11 Test controllers

These are fixtures for exercising the loop, not algorithms A–D.

- **R11.1** `hold` always returns the initial setpoint. It doubles as the no-op
  controller of the measurement harness (`exploration.md` §3).
- **R11.2** `centroid` takes the mean position of the period's events, turns it
  into an angular error using the intrinsics, and adds gain × error to its
  setpoint. It skips periods with fewer than n_min events.
- **R11.3** Fault wrapper (optional, T22; built at the start of the fault study
  in `exploration.md` §7 step 3). `jn-sim ctl --fault cmd_bitflip:p=P` wraps any
  controller. With probability P per decision it flips one uniformly chosen
  bit of the float32 pan or tilt output, sends the flipped value bit for bit,
  and sets flag bit 0 (R8.11). Its generator is seeded from `ctl_seed`
  (R8.12) and makes the same draws every decision, so whether and where
  decision k flips depends only on the seed, the episode and k. Unknown fault
  names or parameters are rejected at startup.

  It is a fixture: output flips exercise R8.9, the flags and the logs. They
  are not the resilience study. Faults in controller state and weights belong
  to the algorithm specs and use the same `--fault` option and flags
  (`exploration.md` §5).

### R12 Live view, logging and provenance

- **R12.1** Live view (`--view`, optional).
  - It runs matplotlib in a separate process, so drawing can't stall the loop.
    Only the latest snapshot is shown, at most 20 Hz. The process is started
    and ready before the episode clock starts, so its start-up can't stall the
    first periods either.
  - It shows the last period's events as an image, ON and OFF in different
    colours, with a crosshair at the image centre and a marker at the true
    target position.
  - Next to it: a rolling 10 s plot of pan/tilt against target az/el, and the
    rolling tracking error in px.
  - A status line shows period, sim time, events per period, compute time,
    round-trip time and misses.
  - Closing the window doesn't stop the run; ending the run closes the window.
- **R12.2** Each run writes `runs/<YYYYMMDDTHHMMSSZ>_<trajectory>_<controller>/`,
  created exclusively. If that name already exists, `_2`, `_3`, … is
  appended, so two runs in the same second never share a directory. It holds:
  - `meta.json`:
    - resolved config and seed;
    - scenario name, or `null`, and every override (R12.4);
    - git SHA and dirty flag of the simulation host's checkout, or `unknown`
      if `git` is missing;
    - endpoint type;
    - OS, architecture, and Python, numpy and matplotlib versions;
    - `ctl_seed` per episode (R8.12);
    - `controller`: the controller metadata (R8.10), including the controller
      host's git SHA;
    - start time in UTC.
  - `periods.csv`: one row per period, streamed to disk, with columns
    episode, k, t_us, pan, tilt, pan_rate, tilt_rate, pan_sp, tilt_sp
    (setpoints in effect), cmd_pan, cmd_tilt (as received, possibly
    non-finite; NaN if missed, which the `miss` column tells apart),
    cmd_invalid, cmd_clamped (R8.9), ctl_flags (R8.11), target_az, target_el,
    target_u, target_v, err_px, in_fov, n_events, n_on, n_off, sim_us, ctl_us,
    rtt_us, link_us, miss, ctl_rx_ns, ctl_tx_ns, send_lateness_us.
  - Timing columns. Each is measured on one host's monotonic clock. Absolute
    timestamps from different hosts are never subtracted, since there is no
    clock sync:
    - `sim_us`: simulator compute for the period (plant, render, events,
      encode), simulator clock;
    - `ctl_us` = `ctl_tx_ns − ctl_rx_ns`: controller compute, controller
      clock;
    - `rtt_us`: from OBS sent to CMD received, simulator clock;
    - `link_us` = `rtt_us − ctl_us`: transport time both ways. A difference
      of two durations, which is valid across clocks up to their rate
      difference (parts per million);
    - `send_lateness_us`: OBS send time minus its scheduled time (realtime
      only), simulator clock.
  - `summary.json`, also printed to the terminal:
    - `status`, and the reason if not completed (R7.8);
    - tracking error after a 1 s warm-up, per episode and over all episodes:
      - over all periods, RMS and max of the angular error, the angle between
        the camera's boresight and the target direction (`rms_deg`,
        `max_deg`). It is defined in every period, also with the target out
        of view or behind the camera, where `err_px` is NaN. Counting
        out-of-view periods means losing the target can't improve the RMS;
      - over in-view periods only, RMS and max in px and degrees
        (`rms_px_in_view`, `max_px_in_view`, `rms_deg_in_view`,
        `max_deg_in_view`);
    - in-FOV fraction;
    - mission metrics, after the warm-up, per episode and over all episodes:
      target losses (`in_fov` going 1 → 0); time to reacquire, mean and max,
      over losses that end; unrecovered losses (still out of view when the
      episode ends); longest out-of-view interval; and episode success
      (in-FOV fraction ≥ `run.success_in_fov`), with the success rate over
      episodes. An out-of-view interval already open when the warm-up ends
      counts as a loss starting then;
    - "over all episodes" values come from the per-episode results, never
      from one time series across episodes, since `t_us` restarts each
      episode. Counts are summed, maxima are the largest per-episode maximum,
      the reacquire mean is weighted by each episode's number of ended
      losses, and RMS values and the in-FOV fraction are pooled over all
      post-warm-up periods;
    - events per period: mean, p95, max;
    - `sim_us`, `ctl_us`, `rtt_us` and `link_us`: mean, p99, max;
    - misses and achieved rate;
    - counts of `cmd_invalid`, `cmd_clamped` and each `ctl_flags` bit;
    - `scenario_exact` (R12.4).
  - `events.bin`, only with `--save-events`: every period's events in period
    order, as raw little-endian records of the wire event dtype (R8.2),
    streamed through a buffered writer. The `n_events` column of
    `periods.csv` splits the file back into periods. Read it with
    `np.fromfile` or `np.memmap` and `protocol.EVENT_DTYPE`. Not `.npy`,
    because its header stores the array length up front. At about 1 MB/s
    this is about 3.6 GB per hour; never committed.
- **R12.3** Memory use stays bounded for runs of up to 60 min: CSV rows and
  events are streamed to disk, the summary is accumulated while the rows
  stream (or read back from `periods.csv` a column at a time, never as one
  record per row), and the viewer keeps only its 10 s window. T13's Done-when
  measures it.
- **R12.4** Scenarios. `scenarios/` holds named, versioned run configurations:
  `track-static-v1`, `track-sine-v1`, `track-step-v1` and `track-random-v1`.
  - A scenario fixes everything except the controller endpoint and the mode
    (lockstep or realtime). `jn-sim run --scenario NAME` uses it as the base
    config; without `--scenario`, the defaults apply and the scenario is
    `null`.
  - A committed scenario file is never edited; a change gets a new version.
  - `meta.json` records every override on top of the scenario (`--config`,
    `--set`, `--trajectory`, `--seed`, `--duration`, `--episodes`).
    `summary.json` has `scenario_exact`, true only for a scenario run with no
    overrides.
  - Sweeps over event load, clock points or fault rates are sequences of runs,
    so they belong to the measurement harness, not here.

### R13 Performance

Targets are set for the Mac, where the hardware is known. On the Linux machine
the same numbers are measured and reported, without targets.

- **R13.1** Default scenario (sine trajectory, `centroid` controller):
  `sim_us` at p99 ≤ 4 ms.
- **R13.2** Realtime, 60 s, with `centroid` running locally over TCP, with and
  without the viewer:
  - zero misses;
  - achieved rate 100 Hz ± 0.01 %;
  - send lateness at p99 ≤ 0.5 ms.
- **R13.3** Step and random trajectories are measured and reported, but have no
  hard target, since fast gimbal moves need many sub-steps.
- **R13.4** Stage 2 budget (optional, T24), reported without a target. `jn-sim bench` times one
  full-frame sub-step (render and events, 320 × 240). For each trajectory it
  also estimates how many sub-steps per period a textured background would
  need, from the gimbal rates in the run:
  ⌈√(ω_pan² + ω_tilt²) · fx · T / max_px⌉, reported as p50, p99 and max.
  Together they show which trajectories would fit the 10 ms realtime period in
  stage 2.

### R14 Verification

- **R14.1** pytest unit tests per module, plus loop tests:
  - determinism (R7.2);
  - realtime equals lockstep (R7.4);
  - `centroid` keeps a sine target in view for 100 % of periods after warm-up,
    with `rms_px_in_view` < 30 px (≈ 6°). Because this needs every sign convention to
    be right, it checks them end to end;
  - connection loss: a controller that exits mid-episode gives exit status 1,
    an `aborted` summary, and `periods.csv` complete up to the last finished
    period;
  - startup: `run` started before `ctl` connects once `ctl` is up, within
    `link.connect_timeout`;
  - episodes: a 3-episode run has three HELLO … BYE exchanges over one
    connection, the same thresholds in all three, and reruns identically;
  - episode boundary (R7.3): in a realtime 2-episode run, a controller that
    misses the deadline on episode 0's last period gets its late reply
    collected and discarded before BYE, and the run completes. A CMD for
    episode 0 sent after episode 1 has started aborts the run;
  - invalid commands (R8.9): a controller that returns NaN for one period
    gives a completed run, with the setpoint held for that period and the
    event counted; an out-of-range command is clamped and counted;
  - fault wrapper (R11.3, with T22): with p = 0, `periods.csv` is identical to the
    unwrapped controller's apart from the timing columns; reruns with the
    same seed flip the same bits; with p = 1 the run completes, bit 0 is set
    in every row, and the `cmd_invalid` and `cmd_clamped` counts equal the
    rows whose flipped value was non-finite or out of range.
- **R14.2** `jn-sim bench` covers R13.
- **R14.3** The test suite runs in `.venv` (Python 3.12) with
  `MPLBACKEND=Agg`, so no test needs a display. The Jetson runs the same
  Python, so this one run also covers the shared modules (R1.3). One test
  fails if the interpreter isn't 3.12, so a wrong venv can't pass silently.
- **R14.4** (Optional, with T11.) The SSH adapter is tested without a real SSH server, using a stub
  `ssh` (R9.3) that implements the port forward in Python and records its
  arguments. The tests cover:
  - the exact argument list;
  - readiness detection;
  - an early `ssh` exit, with the error classified;
  - Ctrl-C teardown leaving no child process.

  A real SSH test runs against the Jetson the next time it is connected
  (`jn-sim doctor --controller ssh://<alias>/5555`). Not part of acceptance
  (§4).
- **R14.5** (Optional, with T21.) I can't verify on the Linux machine, because I have no access to it.
  `docs/sim.md` gets a checklist to run there, by you or by me once access
  exists:
  1. the setup script;
  2. `pytest`;
  3. `jn-sim doctor`;
  4. a 60 s realtime run, with the viewer if there is a display;
  5. if the machine can reach the Jetson, `jn-sim doctor --controller …`.

  Results get recorded in `docs/sim.md`. Not part of acceptance (§4).
- **R14.6** The controller runner (R1.3) is checked on the Jetson the next
  time it is connected. Start `jn-sim ctl` there from the checkout, bound to
  the USB-link address (R9.6). Then do a 60 s realtime run from the Mac with
  `--controller tcp://…`, with zero misses. Not part of acceptance (§4), but
  it is the closed-loop milestone in `exploration.md` §7.

### Defaults

| Parameter | Default | Source |
|---|---|---|
| resolution | 320 × 240 | DVXplorer Lite |
| horizontal FOV | 60° | assumption (lens-dependent) |
| control period | 10 ms | decision |
| background | `uniform` | stage 1 (§1) |
| I_bg, I_t | 0.25, 1.0 | assumption (log contrast ln 4) |
| target angular radius | 1.5° (≈ 7 px) | assumption |
| sine | az 15° at 0.25 Hz, el 8° at 0.35 Hz | assumption |
| step | every 3 s, ≤ 20° per jump, within ±15° az / ±8° el | assumption |
| smooth random | ±15° az, ±8° el, f_max 0.5 Hz | assumption |
| servo ω_n, ζ | 25 rad/s, 0.8 | assumption (hobby-servo-like) |
| servo rate limit | 6 rad/s | assumption (≈ 0.17 s per 60°) |
| angle limits | pan ±90°, tilt ±45° | assumption |
| dead time τ_d | 10 ms | decision (R5.3) |
| dt_phys | 1 ms | — |
| threshold median, σ | 0.12, 0.039 | derived from DVXplorer Lite datasheet (R6.2) |
| log offset ε | 10⁻³ | assumption (R6.1) |
| refractory period | 0.5 ms | assumption |
| shot noise | 0.1 Hz per pixel (≈ 77 events per period) | assumption |
| max_px per sub-step | 1.0 | `exploration.md` §2 |
| CMD deadline | 5 ms | decision |
| episode length | 30 s | — |
| episodes per run | 1 | — |
| seed | 0 | — |
| consecutive misses before abort | 100 (1 s) | decision (R7.6) |
| connect timeout | 10 s | decision (R7.7) |
| episode success threshold (`run.success_in_fov`) | 0.95 | assumption (R12.2) |
| controller port | 5555 | — |
| `centroid` gain, n_min | 0.2, 200 (n_min ≈ 2.5× the expected noise per period) | tuned in T12 (gain started at 0.05) |

The "assumption" values are not identified from hardware. They are stated so a
reviewer can see them, and every one is configurable.

## 4. Acceptance

This spec is done when, on the Mac:

1. Every core task meets its **Done when**: T1–T10, T12–T15 and T17–T19.
2. The full test suite passes in `.venv` (Python 3.12) with `MPLBACKEND=Agg`
   (R14.3).
3. R13.1 and R13.2 are met, and the R13.3 numbers are recorded in
   `docs/sim.md`.
4. The portability searches in T18 find nothing.
5. The setup script and the quickstart in `docs/sim.md` work from a clean
   checkout.

The optional tasks (T11, T16 and T20–T24) are not part of acceptance. Each
says when it becomes worth building.

Checked later and recorded in `docs/sim.md`, but not required, because the
hardware isn't available now:

- the controller runner on the Jetson (R14.6), which is the closed-loop
  milestone;
- with their optional tasks: the Linux checklist (R14.5) and the SSH adapter
  against a real server (R14.4).

## 5. Tasks

| # | Task | Needs | Core or optional |
|---|---|---|---|
| T1 | Environment, setup script, package skeleton | — | core |
| T2 | Configuration | T1 | core |
| T3 | Host adapter | T1 | core |
| T4 | Camera and gimbal geometry | T2 | core |
| T5 | Target trajectories | T2 | core |
| T6 | Gimbal plant | T2 | core |
| T7 | Renderer | T4 | core |
| T8 | Event model | T7 | core |
| T9 | Wire protocol | T1 | core |
| T10 | Controller interface, in-process and TCP adapters, test controllers, controller runner | T9 | core |
| T11 | SSH tunnel adapter and endpoint file | T3, T10 | optional: direct TCP isn't possible, or a Linux host is used |
| T12 | Simulation loop and pacing | T3–T10 | core |
| T13 | Run logging | T12 | core |
| T14 | Live viewer | T3, T12 | core |
| T15 | Command line | T12–T14 | core |
| T16 | Doctor | T15 | optional: bringing up a host whose setup is unknown |
| T17 | Performance check and tuning | T15 | core |
| T18 | Portability check | T15 | core |
| T19 | Documentation | T17, T18 | core |
| T20 | Replay viewer | T14 | optional: recorded runs need re-watching |
| T21 | Linux support | T18 | optional: the Mac causes problems |
| T22 | Fault wrapper | T15 | optional: start of the fault study (`exploration.md` §7 step 3) |
| T23 | Stage timer | T15 | optional: a real controller needs per-stage timing |
| T24 | Stage 2 rendering budget | T17 | optional: before scene stage 2 starts |

Core tasks run in the order of the table. Optional tasks wait until their
condition holds.

All modules go in `src/jn_sim/`, tests in `tests/`.

### T1 Environment, setup script, package skeleton

- `brew install python@3.12` on the Mac (a new install).
- `pyproject.toml`:
  - package `jn_sim` from `src/`, `requires-python = ">=3.12,<3.13"` (§2);
  - dependency: numpy; optional extras `view` (matplotlib) and `dev` (pytest);
  - console script `jn-sim`.
- `requirements.lock`: `uv pip compile --universal` with numpy 2.5.4,
  matplotlib 3.11.2 and pytest 9.1.1, resolved for Python 3.12 (`-p 3.12`).
  The Mac's uv 0.6.12 can do this.
- `scripts/setup_sim_env.sh` per R1.5, macOS branch only. On Linux it stops
  with a message pointing to T21.
- Add `runs/` to `.gitignore`.
- One-off check that a matplotlib window opens with the `macosx` backend.
- **Done when:** the setup script builds a working venv on the Mac from a clean
  checkout, imports report the pinned versions, the test window opens, and
  `pytest` runs.

### T2 Configuration — `config.py`

- One dataclass per section: camera, scene, target, plant, events, loop, link,
  view, run. `scene` holds the background (R4.1): `background` and its
  intensity I_bg. Defaults as in the §3 table.
- Load and save JSON. Apply `--set section.key=value` overrides with type
  conversion.
- Validate values (positive sizes, rates and limits; amplitudes within the
  gimbal limits).
- Derive the intrinsics fx, fy, cx and cy.
- Scenarios (R12.4): load `scenarios/NAME.json` as the base, apply overrides
  and list them. Write the four v1 scenario files.
- **Done when:** a JSON round trip gives the same config, bad values raise a
  clear error, the derived intrinsics match R3.1, each v1 scenario loads, and
  a scenario run with overrides lists every one of them.

### T3 Host adapter — `host.py`

- Implements R2.1 for macOS: keep-awake with `caffeinate`, and the `macosx`
  viewer backend with the `MPLBACKEND` override. OS detection is structured so
  T21 can add the Linux paths without touching any other module.
- Also provides `which(tool)` and a helper that runs a tool with an argument
  list and a timeout.
- **Tests:**
  - OS detection is overridable, so tests can simulate another OS;
  - on an OS without support, the adapter says so clearly, before a run
    starts;
  - a missing `caffeinate` warns rather than fails;
  - `MPLBACKEND` overrides the backend choice.
- **Done when:** these tests pass.

### T4 Camera and gimbal geometry — `camera.py`

- Intrinsics; the gimbal rotation from pan and tilt; az/el to a unit vector.
- Projection to (u, v) with an in-front flag; pixel radius from angular radius;
  an in-FOV test.
- All vectorised over arrays of poses, since sub-steps come in batches.
- **Tests:**
  - the boresight projects to the principal point;
  - the sign conventions of R3.4;
  - a target 10° left at zero pan projects to u = cx − fx·tan 10°;
  - pixel → direction → pixel round trip.
- **Done when:** these tests pass.

### T5 Target trajectories — `target.py`

- The four trajectories of R4.2, each with a vectorised `az_el(t)`, seeded
  from the episode's trajectory stream (R2.5).
- **Tests:**
  - determinism by seed;
  - sine matches its formula;
  - step jumps only at multiples of T_step and never by more than step_max;
  - smooth random stays within its amplitude.
- **Done when:** these tests pass.

### T6 Gimbal plant — `plant.py`

- Per-axis servo (R5.1) with a dead-time buffer, integrated with semi-implicit
  Euler at dt_phys.
- API: advance n steps under a setpoint schedule; return the angle and rate at
  each step.
- The setpoint validation call (R5.4, R8.9).
- **Tests:**
  - a NaN or ±Inf on one axis holds that axis's setpoint and sets
    `cmd_invalid`; an out-of-range value is clamped and sets `cmd_clamped`;
    the other axis is unaffected; the plant state stays finite;
  - step response settles to within 2 %, with overshoot consistent with ζ;
  - the rate limit is never exceeded;
  - motion starts τ_d (± dt_phys) after a setpoint change;
  - limits clamp;
  - an unchanged setpoint gives no motion.
- **Done when:** these tests pass.

### T7 Renderer — `render.py`

- The background interface and the `uniform` background (R4.1).
- The full-frame and region-of-interest paths (R6.7). The disc's edge coverage
  uses a 1 px ramp. Output is log intensity.
- **Tests:**
  - with the uniform background, the region-of-interest path equals the full
    frame for random poses, including a target partly off the sensor;
  - a test-only gradient background goes through the full-frame path and gives
    the expected frame. That shows the layer can be swapped before stage 2
    needs it;
  - total coverage ≈ π r² (within 2 %);
  - with the uniform background, a target off the sensor gives a uniform
    frame.
- **Done when:** these tests pass.

### T8 Event model — `events.py`

- State: reference level, last-event time and per-pixel thresholds.
- Each sub-step update emits events with interpolated timestamps, applies the
  refractory period, and adds shot noise.
- Output is sorted, using the event dtype from `protocol.py`.
- Thresholds and noise come from their R2.5 streams. Noise is drawn with
  fixed-shape calls per period, independent of the gimbal and the
  controller.
- **Tests:**
  - a rise of 3.5 thresholds gives exactly 3 ON events at the expected
    timestamps;
  - a fall gives OFF events;
  - the refractory period drops events;
  - no change with noise off gives zero events;
  - the noise rate is within 5 % of nominal over 10 s;
  - output is deterministic per seed and sorted.
- **Done when:** these tests pass.

### T9 Wire protocol — `protocol.py` (shared with the Jetson)

- The struct layouts of R8.2, encode and decode, the event dtype, an exact-length
  socket read, the size, magic and version checks, the 16 MiB cap (R8.8),
  controller-name validation (R8.7), the HELLO_ACK metadata checks (R8.10)
  and the reserved-flag check (R8.11).
- **Tests:**
  - every fixed-size payload has its R8.2 size: HELLO 44, CMD 36, BYE 4 bytes,
    OBS 20 + 9n, HELLO_ACK 36 + meta_len;
  - every message type survives a round trip;
  - non-finite pan and tilt survive a round trip bit for bit and are not
    rejected (R8.9);
  - nonzero reserved flag bits, and metadata that is oversized, not UTF-8 or
    not a JSON object, are rejected;
  - event arrays come back bit-identical;
  - bad magic, version, type or size raises;
  - bytes delivered one at a time still decode correctly;
  - an oversized batch and an invalid name are rejected.
- **Done when:** these tests pass.

### T10 Controller interface, in-process and TCP adapters, test controllers, controller runner — `link.py`, `testctl.py`, `ctl.py` (shared)

- The `Link` interface (R9.1), the endpoint parser (R9.2), and the in-process
  adapter.
- TCP adapter, simulator side: connect timeout, receive with deadline, discard
  stale CMDs by k.
- TCP server, controller side: `TCP_NODELAY`, one client at a time, monotonic
  timestamps on receive and send, bind default `127.0.0.1` (R9.6).
- The `hold` and `centroid` controllers (R11).
- The controller runner `ctl.py`: serves connections one after another,
  `--once`, controller parameters, name validation at startup (R8.6, R8.7).
- `provenance.py`: git SHA and dirty flag, OS, architecture and versions,
  used by `ctl.py` and by run logging (R8.10, R12.2).
- In `ctl.py`: the controller metadata (R8.10), with `null` for the fault and
  stage-log fields until T22 and T23; `ctl_seed` handed to the controller
  (R8.12); optional flags from `step` (R8.1, R8.11).
- **Tests:**
  - a round trip over localhost;
  - a deliberately slow controller: the miss is counted, the setpoint held, and
    the late reply discarded;
  - several episodes over one connection;
  - endpoint strings parse, and invalid ones give clear errors;
  - `--once` exits after one connection; without it a second simulator
    connects after the first closes; an invalid name is rejected at startup;
  - the metadata reports the checkout's SHA and dirty flag, and `unknown`
    when `git` is hidden from PATH; metadata that changes between episodes is
    rejected;
  - flags returned by `step` arrive in the CMD.
- **Done when:** these tests pass.

### T11 *Optional:* SSH tunnel adapter and endpoint file — `link_ssh.py`

- **When:** direct TCP isn't possible, or a Linux host is used (T21).
- The SSH adapter per R9.3, plus `@NAME` lookup in the endpoint file (R9.5)
  and the config directory in the host adapter (R2.1).
- The stub `ssh` for tests: a small Python script that parses `-L`, forwards
  the port and logs its arguments. It can also be told to fail in the ways
  R9.3 classifies.
- **Tests:** per R14.4, plus `@NAME` lookup and a clear error for an unknown
  name or a missing file.
- **Done when:** these tests pass and no `ssh` child process outlives a test.

### T12 Simulation loop and pacing — `sim.py`

- Episode reset (R2.5, R8.3): thresholds stay; the trajectory and noise
  streams are derived for episode e; plant and event-model state reset. Then
  the HELLO handshake.
- Per period:
  1. Update the setpoint schedule and advance the plant.
  2. Compute target and gimbal poses per physics step.
  3. Subdivide adaptively (R6.5).
  4. Render and generate events per sub-step, then add noise.
  5. Build the batch and exchange it through the `Link`: OBS out, CMD back.
     Apply the CMD through the validation call (R5.4), and record
     `cmd_invalid`, `cmd_clamped` and `ctl_flags`.
  6. Call the logging and viewer hooks.
- Lockstep and realtime pacing (R7). Realtime uses an absolute schedule: sleep,
  then spin for the last ~1 ms. Keep-awake comes from the host adapter.
- Episodes (R8.3), connect retry (R7.7), connection loss and silent-link
  detection (R7.6), Ctrl-C (R7.5) and exit status (R7.8).
- Tune the `centroid` gain and n_min, and record the values.
- **Tests:** the loop tests in R14.1, and that `hold` leaves the gimbal still.
- **Done when:** these tests pass and the tuned `centroid` values are in the
  defaults table.

### T13 Run logging — `runlog.py`

- Implements R12.2–R12.3: run directory, `meta.json` (git SHA via
  `git rev-parse HEAD` and dirty flag via `git status --porcelain`, both
  through `provenance.py`; scenario and overrides; `ctl_seed` per episode;
  controller metadata), streamed CSV with the timing, command and flag
  columns, summary with status, mission metrics (episode success against
  `run.success_in_fov`), counts and `scenario_exact`, and the optional
  streamed `events.bin`.
- **Tests:**
  - all files are created;
  - the CSV has one row per period;
  - `meta.json` has the SHA and dirty flag, and `unknown` when `git` is hidden
    from PATH;
  - summary values recomputed from the CSV match `summary.json`;
  - mission metrics on a synthetic `in_fov` sequence with known answers: two
    losses with known reacquire times, one unrecovered loss, an interval
    already open at the end of the warm-up, and one failed episode;
  - `meta.json` has the controller metadata, `ctl_seed` per episode and the
    scenario overrides, and `scenario_exact` is false whenever an override
    exists;
  - `events.bin` splits back into periods by `n_events` and matches the events
    sent;
  - an aborted run still leaves a valid CSV and summary.
- **Done when:** these tests pass, and the peak memory (RSS) of a 10-minute
  lockstep run with `--save-events` is within 10 % of a 1-minute run's
  (R12.3).

### T14 Live viewer — `viewer.py`

- Implements R12.1 and R2.4: a `spawn` child process fed by a size-1 queue that
  drops stale snapshots. A snapshot is the last period's events plus a few
  state values, so it stays small.
- The backend comes from the host adapter.
- **Tests:** starts and stops cleanly with the Agg backend; `--view` without
  matplotlib or without a display fails before the run starts.
- **Done when:** these tests pass and the viewer has been checked by hand once
  on the Mac, with a screenshot.

### T15 Command line — `__main__.py`

```
jn-sim run [--scenario NAME] [--config FILE] [--set KEY=VALUE ...]
           [--controller inproc:NAME|tcp://HOST:PORT]
           [--mode lockstep|realtime] [--trajectory static|sine|step|random]
           [--duration S] [--episodes N] [--seed N]
           [--view] [--save-events] [--out DIR]
jn-sim ctl --controller hold|centroid [--param KEY=VALUE ...]
           [--listen HOST:PORT] [--once]
jn-sim bench
```

- Optional tasks add `ssh://DEST/PORT` and `@NAME` endpoints (T11),
  `jn-sim doctor [--config FILE] [--set KEY=VALUE ...] [--controller ENDPOINT] [--json]`
  (T16), `jn-sim view RUN_DIR` (T20), `ctl --fault SPEC` (T22) and
  `ctl --stage-log DIR` (T23).
- Subcommand modules are imported lazily (R1.3); exit statuses follow R7.8.
- **Test:** in a fresh interpreter, serving one episode with
  `jn-sim ctl --once` loads no module outside the standard library, numpy and
  the shared modules. T22 and T23 extend this test to their options.
- **Done when:** that test passes and the quickstart commands in the docs work
  as written.

### T16 *Optional:* Doctor — `doctor.py`

- **When:** bringing up a host whose setup is unknown, such as the Linux
  machine. The Jetson check (R14.6) uses a realtime run instead.
- Implements R10, reusing the host adapter and the connection adapters, so it
  tests the same code a run uses.
- **Tests:**
  - every step's pass and failure output against local controllers and the
    stub `ssh`;
  - it stops at the first failure;
  - the `--json` output parses.
- **Done when:** these tests pass, and on the Mac `jn-sim doctor` and
  `jn-sim doctor --controller tcp://127.0.0.1:5555` pass every step against a
  local `jn-sim ctl`.

### T17 Performance check and tuning

- `jn-sim bench` measures R13.1 and R13.3. Then do the 60 s realtime runs of
  R13.2, with and without the viewer.
- If R13.1 fails: profile and vectorise hot paths first. Adding numba is a new
  dependency, so it needs your approval.
- If R13.2 lateness fails: check whether keep-awake is active, and record the
  result.
- **Done when:** R13.1 and R13.2 pass and the R13.3 numbers are recorded.

### T18 Portability check

- Run the test suite with `MPLBACKEND=Agg` (R14.3).
- Search the code for host-specific names and for OS branches outside
  `host.py` (R2.1–R2.2).
- **Done when:** the suite passes and the searches find nothing.

### T19 Documentation

- `docs/sim.md`:
  - install and quickstart on macOS;
  - conventions;
  - the endpoint types (R9.2), and direct TCP for measurement runs (R9.4);
  - running the controller on the Jetson from the checkout (R1.3, R14.6);
  - reading `events.bin` (R12.2);
  - scenarios (R12.4);
  - a protocol summary, pointing to this spec;
  - the defaults table;
  - limitations: clean scene only, so event counts are a best case and energy
    numbers for per-event controllers a lower bound (§1); sensor outside the
    measured boundary; thresholds derived under stated assumptions; no
    cross-check against v2e yet; Linux, SSH and the doctor are optional and
    not built.
- Check that `exploration.md` §2 still matches what was built (it was brought
  in line with this spec on 23 Oct 2026), and add `docs/sim.md` to the README
  layout.
- **Done when:** a reader can go from a clean checkout to a realtime run with
  the viewer using `docs/sim.md` alone.

### T20 *Optional:* replay viewer

- **When:** recorded runs need re-watching.
- `jn-sim view RUN_DIR` replays a run recorded with `--save-events` through the
  same viewer.
- **Done when:** a run saved with `--save-events` replays with the same
  frames the live view showed.

### T21 *Optional:* Linux support

- **When:** the Mac causes problems and the Ubuntu machine takes over as the
  simulation host.
- The Linux branch of `scripts/setup_sim_env.sh` (R1.5), in order:
  1. If `python3.12 -m venv` works, use the system Python.
  2. Else, if uv exists: `uv python install 3.12`, then create the venv with
     it.
  3. Else, print the `apt` command for `python3.12-venv` (and `python3-tk` for
     the viewer), and stop.
- The Linux paths of the host adapter (R2.1): keep-awake with
  `systemd-inhibit`, and `TkAgg` with display detection.
- A bashism check of the setup script under `sh`, if a checker is available;
  otherwise review it by hand.
- The cross-platform tolerance for summary metrics (R2.3).
- The Linux checklist in `docs/sim.md` (R14.5), with an empty results section.
- **Tests:**
  - the Linux paths of the host adapter run on the Mac with OS detection
    overridden;
  - with no display, the viewer is reported unavailable, with the fix;
  - a missing `systemd-inhibit` warns rather than fails.
- **Done when:** these tests pass on the Mac and the checklist is ready to
  run.

### T22 *Optional:* fault wrapper — `testctl.py`, `ctl.py`

- **When:** at the start of the fault study (`exploration.md` §7 step 3).
- The fault wrapper (R11.3), seeded from `ctl_seed` (R8.12), with
  `jn-sim ctl --fault SPEC`. The fault configuration goes into the controller
  metadata (R8.10).
- **Tests:**
  - the fault-wrapper loop test in R14.1;
  - an unknown fault name or parameter is rejected at startup;
  - the T15 import-boundary test also passes with `--fault cmd_bitflip:p=0.5`.
- **Done when:** these tests pass.

### T23 *Optional:* stage timer — `ctl.py`

- **When:** a real controller (A–D) needs per-stage timing
  (`exploration.md` §3).
- The stage timer and `jn-sim ctl --stage-log DIR` (R8.13). The stage-log
  directory goes into the controller metadata (R8.10).
- **Tests:**
  - with `--stage-log`, `stages.csv` has one row per (episode, k, stage) and
    its directory is in the metadata; without it, nothing is written;
  - the T15 import-boundary test also passes with `--stage-log DIR`.
- **Done when:** these tests pass.

### T24 *Optional:* stage 2 rendering budget

- **When:** before scene stage 2 starts (§1).
- Adds R13.4 to `jn-sim bench`.
- **Done when:** the R13.4 numbers are recorded in `docs/sim.md`.

## 6. Risks and unknowns

- **The Linux machine is unknown** (matters only if T21 is built). Its architecture, whether it has a display,
  whether you have `sudo` there, which Python tools are installed, and whether
  and how it reaches the Jetson (USB-C, LAN, SSH keys) are all unknown. The
  mitigations are no host assumptions in code (R2), the doctor (R10) and the
  checklist (R14.5).
- **Realtime pacing** may suffer from timer precision and power management
  (App Nap on macOS). It's measured in T17; keep-awake is the first
  mitigation.
- **Viewer in a child process.** matplotlib backends in a `spawn` child are
  checked in T1 and T14. Fallback: run the viewer as a separate command fed
  over a local socket.
- **Fast gimbal moves** need many sub-steps, and Python overhead per sub-step
  may exceed the period budget (R13.3). That affects realtime mode only.
- **Stage 2 realtime budget.** A textured background needs full-frame
  rendering at every sub-step. A rough estimate from the earlier benchmark:
  smooth tracking fits the 10 ms period, fast step moves probably need
  lockstep. R13.4 (T24) measures it before stage 2 starts.
- **The SSH adapter, once built (T11), is untested against a real server**
  until the Jetson is connected (R14.4).
- **Connecting from the Mac to the Jetson** will need macOS Local Network
  permission for the process that launches Python (SETUP_NOTES §4.2). This is
  macOS-only and not exercised in this spec.
