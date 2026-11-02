# Exploration — simulation, measurement, algorithms

*Started 17 October 2026. Working document: options get weighed here, then move
into code or the plan. Where it conflicts with `hardware_demo_plan.md` §2–§5,
this file wins.*

**Goal:** something defensible that shows competent work with a Jetson Orin Nano
and the algorithms on it. Not a perfect study. Every section is sized to that.

---

## 1. Claim and boundary

> On one Jetson Orin Nano, classical, conventional-network and spiking-network
> controllers run in the same closed event-vision loop. Each is characterised
> for *energy per control decision*, latency and tracking quality across event
> load and clock frequency, with energy measured on the board's power rails
> inside a declared measurement boundary. Under software-injected compute
> faults, each is also characterised for how its tracking degrades and what
> detecting the faults costs in energy.

What changed from the original wording, and why:

- **No "spiking substrate".** The Jetson is conventional silicon (so is the
  ESP32). Spiking networks run *on* it; that is the experiment. Only a
  neuromorphic chip (Speck, Tier 2) would earn the old phrase.
- **The sensor is outside the boundary.** Events are simulated on the Mac, so the
  measured system is the Jetson alone. Say so; a real sensor is a Tier 1
  extension.
- **Clock frequency and injected faults added (23 Oct 2026).** Frequency is the
  energy knob this board supports (§3). Faults show what keeping the loop
  working costs (§5). Fault effects are emulated in software and energy is
  measured, so the two are reported side by side and never combined into one
  number.

Three nested boundaries, all reported from the same runs:

| Boundary | Includes | Instrument | Stage (§4) |
|---|---|---|---|
| Compute | CPU + GPU + CV cores (`VDD_CPU_GPU_CV`) | on-board INA3221 | 0 |
| Module | whole Orin Nano module (`VDD_IN`) | on-board INA3221 | 0 |
| Board | module + carrier, fan, USB, 19 V → 5 V conversion | INA228 on the DC jack | 1 |

On novelty: the boundary effect itself (6.6× between `VDD_IN` and
`VDD_CPU_GPU_CV` at idle, SETUP_NOTES §8) is a *demonstration*, not a finding.
Tek et al. 2026 [L28] already study measurement boundaries on this exact board.
Cite them rather than present it as new.

---

## 2. Simulation on the Mac

Hardware-in-the-loop: the Mac runs the world, the Jetson runs only the
controller.

```
Mac (not measured)                          Jetson (measured)
plant + renderer + event model  --TCP-->    controller
        ^                                       |
        +-------------- pan/tilt command <------+
```

The USB-C link traffic is inside the boundary, but identical for every
controller, so it cancels in comparisons and shows up honestly in total energy.

### Recommendation: no engine, numpy only

| Part | Choice | Why |
|---|---|---|
| Plant | per-axis second-order servo model with rate/torque saturation and dead time | two revolute joints, no contacts. A physics engine adds opacity, not fidelity. Every parameter can be stated. |
| Target | scripted trajectories (static, sine, steps, smooth random); distractors only in scene stage 3 | repeatable; distractors would give learned controllers something to win (§5) |
| Renderer | rotation-only pinhole camera, linear intensity; uniform background in stage 1, a textured panorama in stage 2 (`spec_sim.md` §1) | a camera rotating about its optical centre has no parallax, so a textured background is a homography of a panorama. Linear intensity avoids the tone-mapping gap of game-style renderers. |
| Events | own log-intensity contrast-threshold model: per-pixel threshold mismatch, refractory period, noise | the standard DVS model, a few dozen lines of numpy, online by construction |
| Sub-stepping | render at 1–2 kHz so image motion stays ≤ ~1 px per sub-step; interpolate event timestamps within a step | avoids temporal aliasing, the known failure mode of frame-based emulation |
| Credibility check | offline, run v2e `EventEmulator(device='cpu')` [L16] or IEBCS `DvsSensor` on the same frames and compare event statistics | borrows established simulators' credibility without putting them in the loop |
| Interface | the simulator drives the controller over TCP; no Gymnasium | the simulator owns the clock and calls a remote controller, the reverse of Gymnasium's pattern (`spec_sim.md` §2) |

Feasibility: a quick naive numpy benchmark on this Mac ran render + event update
at about 3,000 fps at 128×128 and about 550 fps at 346×260, single core. The
chosen 320×240 therefore relies on rendering only the region around the target
in stage 1; the budget is measured in `spec_sim.md` R13.

Install: one venv on Homebrew's Python 3.12, the version the Jetson runs (the
system `python3` is 3.9.6, too old), with numpy and matplotlib pinned in one
lock file (`spec_sim.md` R1). Nothing else.

Fallback, if a "real engine" is ever wanted: MuJoCo (`pip install mujoco`,
native arm64 wheels, Apache-2.0) with its offscreen renderer feeding the same
event model.

Ruled out:
- **Gazebo, Isaac Sim, ROS-based ESIM** — complex installs.
- **PyBullet** — compiles from source on macOS arm64.
- **Genesis** — torch-heavy for two joints.
- **Neurosim, SEBVS** — Ubuntu + CUDA.

No pip-installable, macOS-ready closed-loop event environment was found, so this
part gets built.

### Decided (22 Oct 2026, `spec_sim.md` §2)

- **Resolution:** 320×240, matching the DVXplorer Lite, so a later real camera
  keeps the controllers' input format.
- **Control rate:** 100 Hz, which gives the power meter more samples per
  decision (§4). Paredes-Vallés et al. [L7] ran at 200 Hz.
- **Transport:** TCP, because an event batch can exceed one UDP datagram.
- **Task difficulty:** a clean scene first, then texture and distractors in
  stages (`spec_sim.md` §1). Clean-scene event counts are a best case.

---

## 3. Energy metrics

A **decision** is one controller call: the events of one control period in, one
pan/tilt command out.

Every measurement interleaves three kinds of block, plus a fourth when a fault
detector is measured:

| Block | Jetson runs | Gives |
|---|---|---|
| idle | logger only | `P_idle`, the platform floor |
| harness | full loop, no-op controller (receives events, returns a fixed command) | `P_harness`: networking, parsing, timing |
| algorithm | full loop, real controller | `P_run` |
| detector | full loop, real controller with its fault detector on, no faults injected | `P_det`; detector overhead `E_det = (P_det − P_run) / f` (§5) |

Reported per decision, at control rate `f`:

- **Dynamic energy** `E_dyn = (P_run − P_harness) / f` — what the algorithm
  itself costs. This is the comparison between algorithms.
- **Total energy** `E_tot = P_run / f` — what the board actually spends per
  decision, shown as a stack: idle floor + harness + algorithm. This is the
  "what can be achieved" number.
- **Task and timing:** latency (events in → command out, Jetson-side
  timestamps), RMS centring error, target-loss rate. Per-stage durations from
  the controller's stage timer (spec R8.13) show where each decision's time
  goes, in the manner of system-level workload characterisation [L41].

Tracking quality comes from the simulator's mission metrics (spec R12.2):
target losses, time to reacquire, longest time out of view and episode
success, alongside RMS error.

Two headline plots:

- **Event-load crossover.** `E_dyn` and latency against events per decision,
  swept by the shot-noise rate in stage 1 and texture contrast in stage 2
  (spec §1), dense GPU controllers (B, C) against event-driven ones (A, D).
  Event-driven cost grows with load and dense cost barely does, so the plot
  shows the load above which event-driven execution stops being cheaper. That
  number belongs to these implementations on this board, not to SNNs in
  general.
- **Pareto plot** at each clock point: tracking error and mission metrics
  against `E_dyn` and latency, one point per controller, compared at matched
  tracking error where possible.

Below the 5 ms command deadline, compute latency doesn't change control here,
because the simulator's dead time is fixed (spec R5.3). Slower clocks show up
in tracking only through missed deadlines. That's a modelling limit, stated as
such.

Expect `E_tot` to be dominated by the idle floor for every controller. That is a
result, not a failure: it quantifies how much the algorithm choice matters at
system level on this board.

Protocol for every stage:

- Fixed power mode (25 W). Clock frequency is a factor: three locked clock
  points, the same for every controller, set between blocks and included in
  the randomised block order. The actual frequencies are read back and stored
  with the trace. One run at default DVFS stays as a reference.
  - **The points (decided 23 Oct 2026):** CPU and GPU locked together at the
    low, mid and maximum entries of their available-frequency lists in the
    25 W mode; memory clock fixed at its maximum; all six CPU cores online.
    The exact values get read from the board.
  - **Rejected:** nvpmodel power modes as the points, because each mode
    changes several limits at once, only sets ceilings, and MAXN SUPER can
    throttle. Also rejected: sweeping only the unit each family uses (CPU for
    A and D, GPU for B and C). That is cleaner per controller, but the points
    would mean different things across families, so the per-point Pareto
    plot would compare unlike settings.
  - Idle and harness blocks run at every clock point too, because the harness,
    networking and logger also run on the CPU.
  - Locked clocks stop the board clocking down when idle, so `E_tot` at a
    locked point overstates what a board on default DVFS spends. The
    default-DVFS run is the reference for that.
  - Frequency is the knob because voltage on this board follows the DVFS
    tables for the chosen frequency (to verify). Voltage itself is never
    touched.
  - How to lock and read them on L4T R39.2.1 (nvpmodel, `jetson_clocks`, the
    cpufreq and devfreq interfaces) is **to verify on the board**. Setting
    them needs `sudo`. This is separate from the rule never to write the
    INA3221 nodes (§4).
  - Stretch, only after the static results: raise clocks when event load or
    tracking error rises.
- Every block records the boundary, instrument, clock point, scenario name
  and version (spec R12.4), controller metadata (spec R8.10) and fault
  configuration, so each number traces back to its conditions. This follows
  MLPerf Power [L24] and RobotPerf [L40]. The record format goes into the
  harness spec.
- Blocks of ~10 s, interleaved, repeated, **in randomised order** (Tek et al.
  [L28] report that hardware state depends on run sequence). Report mean and
  95 % CI.
- Radio off (`nmcli radio wifi off`) or ethernet. Fan pinned to a fixed speed,
  since it is a temperature-driven load on the carrier.
- `git rev-parse HEAD` stamped into every trace (SETUP_NOTES §6.2).

---

## 4. Measurement hardware — staged, buy only at a gate

### Stage 0 — €0, on-board INA3221

Read `VDD_IN`, `VDD_SOC` and `VDD_CPU_GPU_CV` from sysfs
(`/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*`) with a small logger on the
Jetson. The logger runs in all three block types, so its own cost cancels in the
differences.

This is defensible for module-level, averaged energy per decision. Yoo et al.
2026 [L20] use essentially this method (idle-subtracted `VDD_IN`) on the same
board.

Limits to state in the writeup:

- Module only: no carrier, fan, USB or regulator losses.
- Each read is a point sample of one conversion cycle (milliseconds), so a
  periodic loop can alias against it. Vary the control rate slightly and check
  the result doesn't move.
- Gain error is uncalibrated. Shalavi et al. [L26] found Jetson internal sensors
  reading up to 50 % low, but did not test the Orin Nano.
- Cannot resolve single decisions.
- **Never write to the INA3221 sysfs nodes** — NVIDIA warns it can damage the
  device. Read `update_interval` and `samples` to learn the actual cycle time.

**Measured on 26 Oct 2026** (`traces/board_20261026/`, SETUP_NOTES §8): about
40 mW per reading step on `VDD_IN`, about 0.6 s of smoothing, 10 Hz sampling is
enough. In the pilot, `centroid` cost +14.8 mW over `hold` (95 % CI +0.5 to
+29.1), about 0.15 mJ per decision. ±10 % precision on that would need about
200 repeats per condition at 30 s, so Stage 0 alone gives a coarse dynamic
energy for cheap controllers. (The Stage 1 meter later put the difference at
about +15 to +25 µJ, below what `VDD_IN` can resolve; Stage 1 state below.)

**Gate to Stage 1: met on 26 Oct 2026.** The Stage 0 pipeline produced numbers
for a no-op and a test controller, and showed the resolution limit Stage 1
fixes. The Stage 1 meter was built on 29 Oct 2026 and has run end to end
since 30 Oct (state below the parts table).

### Stage 1 — about €45, board-level meter

Bought as listed. The table is the shopping state of 26 Oct 2026:

| Item | State | Why |
|---|---|---|
| Adafruit INA228 breakout (product 5832) | **in hand** (facts below) | measures the 19 V input; on-chip energy accumulator |
| Raspberry Pi Pico (RP2040), SC0916, no headers | to buy, ≈ €5 | separate logger: reads the INA228 and timestamps the Jetson's per-decision marker edge on one clock |
| 2 × 20 male pin headers, 2.54 mm | to buy, ≈ €1 | soldered onto the Pico |
| USB-C to micro-USB cable that carries data | check one is at hand | Mac to Pico; a charge-only cable looks the same |
| breadboard, jumper wires | in hand | Pico ↔ INA228; Jetson marker pin and GND to the Pico |
| 2 × 5.5 × 2.5 mm DC barrel adapters with screw terminals (one plug, one jack), rated ≥ 5 A | to buy, ≈ €8 | puts the shunt inline without cutting the adapter cable. Not 5.5 × 2.1, not 2 A-rated |
| stranded wire ≥ 0.5 mm², red and black, about 30 cm | to buy if not at hand | the 19 V path, which doesn't go through the breadboard |
| multimeter | recommended | polarity, the VBUS jumper, and 19 V where expected before the Jetson is plugged in |

Prices are approximate (EU shops, October 2026).

Why the Pico: about €5, 3.3 V logic like the Jetson header, PIO for
microsecond edge timestamps, one clock for power and markers. The plain
SC0916 needs its headers soldered; the Pico H has them fitted and works the
same. A Pico 2 also works, but early RP2350 steppings have a GPIO input
erratum (E9) and nothing here needs the extra speed. The ESP32 in the Tier 0
BOM is not needed for this and is deferred together with the ESP32 algorithm
leg.

**The INA228 in hand** (checked 26 Oct 2026). The silkscreen reads "STEMMA QT ·
VBUS · INA228 DC Current Monitor · Max BusV 0–85V · Max Curr ±10A · I2C Addr
0x40 · Vlogic/Vcc 3–5VDC", which is Adafruit's product 5832. From Adafruit's
product guide (learn.adafruit.com, "Adafruit INA228 I2C Power Monitor"):

- **Shunt:** 15 mΩ, 0.1 %, on the board. Two ADC ranges:
  - ±163.84 mV, so about ±10.9 A, with a shunt step of 312.5 nV = **about
    21 µA, or 0.4 mW at 19 V**;
  - ±40.96 mV, so about ±2.73 A, with a step of 78.125 nV = about 5.2 µA, or
    0.1 mW at 19 V.

  Adafruit's guide quotes about 10 µA and 2.5 µA, half the ADC step;
  the figures above follow from the register scaling in Adafruit's own
  driver. Start on the wide range: the Jetson's input is specified up to
  4.2 A. The board draws about 0.25–0.35 A in the pilot's conditions, so if
  its measured peak stays well under 2.7 A, the narrow range gives 4× finer
  steps. Either way that's about 100× finer than the INA3221's 40 mW, before
  averaging.
- **Bus voltage:** up to 85 V DC, measured between VBUS and GND. The 19 V
  input fits with margin.
- **Measured side:** the VBUS jumper on the back joins VBUS to VIN+, which
  high-side wiring needs. Adafruit's current guide says it ships open (low
  side); an older version of the guide described it as closed. So measure
  VIN+ to VBUS first and solder it closed only if it reads open.
- **I²C:** address 0x40 by default (A0 and A1 jumpers on the back open); SDA
  and SCL have 10 kΩ pull-ups on the board. The Jetson's INA3221 also sits at
  0x40, but on the Jetson's own bus, so the two never meet.
- **Logic power:** VIN takes 3–5 V. Feed it 3.3 V from the Pico.
- **Connectors:** a 3.5 mm terminal block for the measured current, and a pin
  header to solder for the breadboard. The STEMMA QT sockets stay unused,
  since the Pico has none.
- **ALRT pin:** active low; can signal conversion-ready to the Pico.

What Stage 1 unlocks:

- The board-level boundary (third row of the §1 table).
- An independent meter to calibrate the INA3221 gain on this board. That
  comparison is a methods paragraph by itself.
- Window energy per decision, from INA228 samples aligned on the marker
  edges. Measured rate: 926 samples/s, not the ~10 kS/s first hoped for, so
  a single decision isn't resolved; averaging thousands of aligned windows
  is.

**State on 30 Oct 2026** (SETUP_NOTES §8.2–§8.3, `docs/stage1_wiring.md`;
reports in `traces/ina228_20261028/`, `traces/stage1_20261029/`,
`traces/stage1_20261030/`, `traces/stage1_20261030_fix/`):

- **Built and running.** INA228 on the high side, VBUS jumper closed, read
  by the Pico at 400 kHz I²C. 0 missed conversions in every capture so far.
- **Sample rate: 926 S/s.** One conversion per 1.08 ms (MODE 0xB, 540/540 µs,
  AVG 1), each timestamped by PIO from the conversion-ready signal on ALRT.
  The I²C bus alone caps three register reads per conversion at about
  2.4 kS/s, so ~10 kS/s was never reachable.
- **Energy from samples, not the ENERGY register.** ENERGY's step is 1.06 mJ,
  about 56 counts per 10 ms decision at 6 W, and each read costs 240 µs.
  ENERGY and CHARGE stay a cross-check over seconds; CHARGE matched the
  sampled current to 1.2 %.
- **Idle board, 25 W mode, quiet** (timers stopped, radio off; 5 min):
  6.362 W through the meter (330 mA at 19.26 V), against 4.542 W on
  `VDD_IN`. The carrier board and its 19 V → 5 V conversion take the other
  1.82 W. Zero-current offset −111 µA, subtracted.
- **Noise is the board's own activity, not the meter.** sd 130 mW per
  conversion, 114 mW for 10 ms means, 35 mW for 1 s means, 8 mW for 10 s
  means; the meter's own floor is 3.6 mW per conversion. Beyond 10–30 s,
  slow drift (−4 mW/min) dominates. `VDD_IN` looks quieter only because it
  sits on one 40 mW code.
- **Marker: header pin 8 (UART1 TX), one byte per decision.** Pin 29 doesn't
  drive: its pad is tristated, and fixing that needs `jetson-io` and a boot
  change. Pin 8 passed 6000/6000 edges at 100 Hz and 10000/10000 at 1 kHz,
  with 5–12 µs per write and 0.6–1.4 µs jitter. One byte frame takes 87 µs,
  so only decision starts are marked.
- **Synthetic decisions resolve at the µJ level** (one busy core for W =
  0.1, 0.3, 1 ms at 100 Hz, 3 × 60 s each). Marker-aligned windows with
  each block's own baseline give **+28.1 µJ [+22.5, +33.8] for 0.1 ms** and
  a linear slope of 249 mW, about 25× tighter than block means, which carry
  the slow drift. ±5 % on a 28 µJ difference needs about 10⁵ decisions per
  condition, 15–20 min at 100 Hz (uncertain by a factor of several).
- **Board made quiet for good (31 Oct):** desktop, docker, bluetooth, the
  camera daemon, iperf3 and the update timers disabled, radio off (SETUP_NOTES
  §8.1). Idle 6.291 W through the meter, 4.509 W on `VDD_IN`.
- **Closed loop, `centroid` against `hold`** (`traces/stage1_20261031_final/`;
  4 interleaved rounds of 60 s, marker at the start of each step, 95 % CIs
  over rounds):
  - Integrity: every block had falls = marker rows = OBS = 6000, 0 missed
    conversions. The decision's power rises about 0.5 ms before the marker
    edge (OBS reception) and is back near baseline by about 2 ms.
  - **Per decision, marker-aligned: `hold` 172 µJ, `centroid` 188 µJ.**
    That's receive, decode, step and send, above the in-period baseline.
  - **Centroid − hold: +15 µJ [−42, +73]**, not resolved from 0. A window
    ending at 2 ms instead of 4.5 ms gives +24 µJ [−15, +63]. Expected from
    Part 5's 249 mW per busy core and the 85 µs longer step: about +21 µJ.
    **The pilot's 0.15 mJ isn't confirmed;** it came from `VDD_IN`, whose
    40 mW steps can't resolve this.
  - The limit is `hold`: its per-decision excess fell from 228 to 141 µJ
    over the session, while `centroid` held at 188 µJ (sd 7 µJ per block).
    Cause not known; the leading guess is unpinned core placement or CPU
    frequency.
  - **Harness cost:** `hold` against no controller is +23.7 mW, 237 µJ per
    decision [182, 292], ten times the centroid − hold difference.
  - **Total per decision** (block mean / 100 Hz): 63.1 mJ for both, almost
    all of it the board's idle.
- **Controller A measured (2 Nov;** `docs/ctl_a.md` §9,
  `traces/t6b_20261102/`): E_dyn(A) = +207 µJ per decision [+195, +219]
  above `hold`, harness +208 µJ [+179, +237], E_tot(A) = 63.63 mJ, from a
  pre-registered session of 12 rounds. The first session (T6) showed that
  10 Hz loggers running during blocks were the main noise source.
- **Measurement protocol for B–D** (from T6b):
  - rounds of idle, `hold` and the controller, 60 s each, the order cycling
    through all six permutations; a fixed number of rounds, with the design
    and analysis written down before the first block;
  - a fresh process per block, pinned to one core, one dummy marker byte,
    then one marker byte per decision;
  - no logger running during the captures; a snapshot of temperatures,
    frequencies and `VDD_IN` in each gap;
  - one capture per 4 rounds; marker pulses under 1 µs dropped; integrity =
    marker edges = logged decisions = observations;
  - method (b) as the primary, window [−1, 4.5) ms, baseline [5.5, 8.5) ms,
    checked against each controller's profile (a step longer than about
    3 ms needs a later baseline);
  - compare only within a round: X levels move by about 20 µJ between
    sessions and boots, D doesn't;
  - precision is set in µJ: with a round-to-round sd of about 19 µJ, 12
    rounds give about ±12 µJ. A small difference (a detector, say) needs a
    target in µJ, not percent, or many more rounds.

Wiring rules:

- Shunt on the **high side**: adapter + → VIN+ → VIN− → Jetson +, ground
  unbroken. The 19 V path runs through the terminal block and stranded wire,
  never through the breadboard.
- VIN+ and VBUS must read about 0 Ω: close the VBUS jumper if they don't.
- Full wiring, pin numbers and checks: `docs/stage1_wiring.md`.
- Common ground between the Pico and a Jetson header GND pin. The INA228
  measures the bus voltage against its own GND, which is the Pico's, so this
  wire is also what makes the VBUS reading valid.
- Power the Pico only from the Mac's USB, never from the Jetson's 3.3 V / 5 V
  pins.
- Rewire only with the adapter unplugged.

**Gate to Stage 2:** a reviewer or collaborator requires traceable calibration,
or the INA228 and INA3221 disagree in a way neither explains.

### Stage 2 — only if that gate opens

- **Joulescope cannot measure the board input.** JS220 and its successor JS320
  are rated ±15 V; the DC input is 19 V. (Correction to
  `hardware_demo_plan.md` §2.)
- Otii Ace Pro covers 25 V / 5 A at about $1,750 excl. VAT, the only analyser
  found that fits directly.
- Nordic PPK2 and Otii Arc are ≤ 5 V; not usable here.

---

## 5. Algorithms

Four families, same loop, same board, same metrics. Each builds on published
work (§6). Training happens on the Mac; only inference runs on the Jetson.

| | Family | Builds on | Runs as | Board dependency |
|---|---|---|---|---|
| A | Classical: event cluster / mean-shift tracker + Kalman filter + PID | [L1], [L5], [L6] | CPU, numpy or C | none |
| B | Small CNN on an event representation (event frame, time surface or voxel grid) regressing target position | [L12]–[L15] | GPU, TensorRT FP16/INT8 | TensorRT (in JetPack) |
| C | SNN, time-stepped, surrogate-gradient trained | [L7], [L9], [L31], [L32] | GPU, PyTorch CUDA | PyTorch on JetPack 7.2 (risk below) |
| D | Same SNN weights, executed event-driven: only neurons reached by incoming events update | [L18], [L20] as the counterpoint | CPU, numpy or C | none |

**Why A matters.** If a tracker + PID centres the target at a fraction of the
energy, a reviewer will ask why learn at all. The task needs enough clutter that
B–D have something to win, or the writeup says plainly that A wins.

**Why D matters.** GPUs don't exploit spike sparsity, so C will very likely lose
to B. That is already shown ([L18], [L20]), so it is not our finding. D is the
fair test of whether sparsity pays on conventional silicon at all. An SNN-PID
([L8]) is an alternative for D's control stage.

Hypotheses from the literature: A cheapest in `E_dyn`; C above B; D the open
question; all four small against the idle floor in `E_tot`.

**PyTorch on JetPack 7.2: resolved 19 Oct 2026.** The official Jetson wheels
target JetPack 6, but PyTorch's own `cu132` aarch64 build works on this board.
`torch 2.14.1+cu132` ran real CUDA, cuBLAS and cuDNN kernels and matched the CPU
reference. A small 128×128 CNN ran at 0.68 ms per inference, batch 1, eager
mode. That leaves headroom at 100–200 Hz control even before TensorRT.

It needed no `sudo` and no system libraries, unlike the community guide this
path came from
([jetson-jp7.2-install](https://github.com/iuliaferoli/jetson-jp7.2-install)).
Install recipe and gotchas: SETUP_NOTES §6.4. So C runs natively on the GPU. An
ONNX → TensorRT export of an unrolled SNN is still worth trying as a variant,
but it is no longer a fallback.

The ESP32 leg (plan baseline b) is deferred until A–D produce numbers.

**Stretch:** switch between C and D per period on the same weights, depending on
event load. That first needs a check that both execution styles give the same
commands.

### Resilience under injected faults

Faults are emulated in software on the Jetson: single bit flips in float32
values the controller holds, at log-spaced rates per decision. Tracking
results under faults are emulated; energy numbers are measured. The two are
reported side by side and never combined into one number.

Fault sites per family:

| | Per-decision values (wrong for one decision) | State carried between decisions | Weights (wrong until reloaded) |
|---|---|---|---|
| A | cluster position, command | Kalman state and covariance, PID integrator | — |
| B | activations, one layer at a time | — | weights |
| C | activations and spikes | membrane potentials | weights |
| D | as C, on the CPU path | membrane potentials | weights |

The simulator's fault wrapper (spec R11.3) only flips command bits. It tests
the pipeline, not the controllers. Sites inside each family use the same
`--fault` option and flags.

**Paired runs.** In lockstep, a faulted run and a clean run with the same seed
are identical up to the first fault. The simulator's random streams never
depend on the commands (spec R2.5), so the difference afterwards is
attributable to that fault. Report *fault persistence*, the number of periods
until the error is back within a stated band of the clean run, together with
the mission metrics.

Hypotheses to test, not assumptions:

- B is memoryless across decisions, so an activation fault lasts one decision
  unless the bad command loses the target. Weight faults persist.
- A corrupted Kalman state decays as measurements correct it, at a rate set by
  the filter gain. A corrupted covariance can be worse, since a negative or
  huge variance can destabilise the filter.
- A corrupted PID integrator acts like a step disturbance that integral action
  works off. A flip in a high exponent bit gives a huge value that saturates
  the command and may not unwind within an episode. The simulator clamps the
  command (spec R8.9), but the controller's state stays wrong.
- In C and D, leak pulls a corrupted membrane potential back towards rest. A
  huge value keeps firing until it is reset, so persistence depends on the
  reset rule (reset to zero or subtract the threshold).
- MAVFI [L35] found planning and control more vulnerable than perception in a
  UAV pipeline. Whether that holds here, where A has explicit control state and
  B–D map events straight to a command, is open.

**Detector and recovery.** One cheap detector, after MAVFI [L35]: a range or
rate check, or a Gaussian anomaly score on the command stream. Recovery holds
the last good command or resets the state. It runs on the Jetson, so its cost
is measured as its own block type (§3, `E_det`). The simulator's hold of
non-finite commands (spec R8.9) is a safety net, not this mitigation.

**B under TensorRT.** Engines are compiled, so injecting faults into them is
awkward. Either run the fault study in PyTorch eager with the same weights and
measure energy in TensorRT, stating the split, or rebuild one engine per
persistent weight fault. The first is simpler; the split is acceptable
because fault effects are emulated anyway.

---

## 6. Literature

Checked 17 Oct 2026 against arXiv, CrossRef or publisher pages; summaries are
paraphrased. Items marked UNVERIFIED are leads, not citations.

### Closed-loop event-camera systems

- **[L1]** Delbruck, Lang (2013). Robotic goalie with 3 ms reaction time at 4%
  CPU load using event-based dynamic vision sensor. *Front. Neurosci.* 7:223.
  doi:10.3389/fnins.2013.00223 — the canonical closed-loop event tracker with an
  actuator; reports latency and CPU load, no energy. Lineage for A.
- **[L2]** Conradt, Cook, Berner, Lichtsteiner, Douglas, Delbruck (2009). A
  pencil balancing robot using a pair of AER dynamic vision sensors. *ISCAS
  2009*, 781–784. doi:10.1109/ISCAS.2009.5117867 — event-driven balance control
  on a small embedded processor.
- **[L3]** Glover, Bartolozzi (2017). Robust visual tracking with a
  freely-moving event camera. *IROS 2017*, 3769–3776.
  doi:10.1109/IROS.2017.8206226 — particle-filter tracking with a moving camera
  on the iCub; the closest analogue to a pan/tilt head.
- **[L4]** Vitale, Renner, Nauer, Scaramuzza, Sandamirskaya (2021). Event-driven
  vision and control for UAVs on a neuromorphic chip. *ICRA 2021*, 103–109.
  doi:10.1109/ICRA48506.2021.9560881 — SNN tracker on Loihi closing a fast loop.

### Event-based tracking (A)

- **[L5]** Lagorce, Meyer, Ieng, Filliat, Benosman (2015). Asynchronous
  event-based multikernel algorithm for high-speed visual features tracking.
  *IEEE TNNLS* 26(8), 1710–1720. doi:10.1109/TNNLS.2014.2352401
- **[L6]** Barranco, Fermüller, Ros (2018). Real-time clustering and multi-target
  tracking using event-based sensors. *IROS 2018*.
  doi:10.1109/IROS.2018.8593380, arXiv:1807.02851 — mean-shift on events plus
  Kalman smoothing; the recipe for A.

### SNNs for event vision and control (C, D)

- **[L7]** Paredes-Vallés, Hagenaars, Dupeyroux, Stroobants, Xu, de Croon
  (2024). Fully neuromorphic vision and control for autonomous drone flight.
  *Science Robotics* 9(90), eadi0591. doi:10.1126/scirobotics.adi0591 —
  events-to-control SNN on Loihi at 200 Hz, 27 µJ per inference. Code:
  github.com/tudelft/event_planar. Primary anchor.
- **[L8]** Stagsted, Vitale, Binz, Renner, Bonde Larsen, Sandamirskaya (2020).
  Towards neuromorphic control: a spiking neural network based PID controller
  for UAV. *RSS XVI*. doi:10.15607/RSS.2020.XVI.074
- **[L9]** Neftci, Mostafa, Zenke (2019). Surrogate gradient learning in spiking
  neural networks. *IEEE Signal Processing Magazine* 36(6). arXiv:1901.09948 —
  the standard citation for how C is trained.
- **[L10]** Shrestha, Orchard (2018). SLAYER: spike layer error reassignment in
  time. *NeurIPS 2018*.

### Event representations and simulators (B, §2)

- **[L11]** Gallego et al. (2020). Event-based vision: a survey. *IEEE TPAMI*.
  doi:10.1109/TPAMI.2020.3008413 — the field's reference survey.
- **[L12]** Lagorce, Orchard, Galluppi, Shi, Benosman (2017). HOTS: a hierarchy
  of event-based time-surfaces for pattern recognition. *IEEE TPAMI* 39(7),
  1346–1359. doi:10.1109/TPAMI.2016.2574707
- **[L13]** Sironi, Brambilla, Bourdis, Lagorce, Benosman (2018). HATS:
  histograms of averaged time surfaces for robust event-based object
  classification. *CVPR 2018*.
- **[L14]** Gehrig, Loquercio, Derpanis, Scaramuzza (2019). End-to-end learning
  of representations for asynchronous event-based data. *ICCV 2019*.
  arXiv:1904.08245 — one taxonomy for event frames, voxel grids and time
  surfaces. Code: github.com/uzh-rpg/rpg_event_representation_learning.
- **[L15]** Zhu, Yuan, Chaney, Daniilidis (2019). Unsupervised event-based
  learning of optical flow, depth, and egomotion. *CVPR 2019* — the usual
  citation for voxel grids.
- **[L16]** Hu, Liu, Delbruck (2021). v2e: from video frames to realistic DVS
  events. *CVPR Workshops*, 1312–1321. Code: github.com/SensorsINI/v2e.
- **[L17]** Rebecq, Gehrig, Scaramuzza (2018). ESIM: an open event camera
  simulator. *CoRL 2018*, PMLR 87.

### SNN vs ANN energy on conventional hardware

- **[L18]** Dampfhoffer, Mesquida, Valentian, Anghel (2023). Are SNNs really
  more energy-efficient than ANNs? An in-depth hardware-aware study. *IEEE
  TETCI* 7(3), 731–741. doi:10.1109/TETCI.2022.3214509 — counting operations
  misses memory and data movement. Anchor.
- **[L19]** Bhattacharjee, Yin, Moitra, Panda (2024). Are SNNs truly
  energy-efficient? — A hardware perspective. *ICASSP 2024*, 13311–13315.
  doi:10.1109/ICASSP48485.2024.10448269
- **[L20]** Yoo, Garg, Chakraborty, Alam (2026). When spike sparsity does not
  translate to deployed cost: VS-WNO on Jetson Orin Nano. arXiv:2604.17040
  (preprint) — an snnTorch SNN with 18–54 % spike rates still costs more than
  the dense model on this board, because the GPU runtime doesn't skip work as
  spikes get sparser. Same board, nearly the Stage 0 method, open-loop. Anchor.
- **[L21]** Gamage, Zeng, Cadena, Fumagalli, Tolu (2026). Real-time frame- and
  event-based object detection with spiking neural networks on edge
  neuromorphic hardware: design, deployment and benchmark. *Neurocomputing*.
  doi:10.1016/j.neucom.2026.133820, arXiv:2605.00146 — SNNs on Loihi 2 vs ANNs
  on an Orin Nano; Loihi 2 had the lowest dynamic energy per inference, the Orin
  Nano ANN the higher rate. Open-loop.
- **[L22]** Kosta et al. (2025). TOFFE: temporally-binned object flow from
  events. arXiv:2501.12482 — hybrid SNN/ANN with energy on Jetson TX2 and
  Loihi 2. Full author list UNVERIFIED.

### Benchmarking methodology

- **[L23]** Yik et al. (2025). The NeuroBench framework for benchmarking
  neuromorphic computing algorithms and systems. *Nature Communications* 16,
  1545. doi:10.1038/s41467-025-56739-4 — metric vocabulary (footprint,
  activation sparsity, synaptic operations); names closed-loop sensorimotor
  tasks as future work, which this project addresses in miniature. Anchor.
- **[L24]** Tschand et al. (2025). MLPerf Power: benchmarking the energy
  efficiency of machine learning systems from µW to MW. *HPCA 2025*.
  arXiv:2410.12032 — measure with a physical analyser, include system
  components, report efficiency at a quality target.
- **[L25]** Banbury et al. (2021). MLPerf Tiny benchmark. *NeurIPS Datasets and
  Benchmarks*. arXiv:2106.07597 — single-stream energy method, EEMBC
  EnergyRunner.

### Jetson power measurement

- **[L26]** Shalavi, Khoshsirat, Stellini, Zanella, Rossi (2023). Accurate
  calibration of power measurements from internal power sensors on NVIDIA
  Jetson devices. *IEEE EDGE 2023*, 166–170. doi:10.1109/EDGE60047.2023.00034 —
  internal sensors up to 50 % low vs an oscilloscope, ±3 % after regression
  calibration. Orin Nano not tested.
- **[L27]** Aslan, Yilmazer-Metin (2022). A study on power and energy
  measurement of NVIDIA Jetson embedded GPUs using built-in sensor. *UBMK
  2022*. doi:10.1109/UBMK55850.2022.9919522
- **[L28]** Tek, Weißbeck, Rachmann, Poschmann (2026). Measurement boundaries and
  sequence-dependent hardware-state realization in edge-AI energy benchmarking:
  a blocked factorial study on the NVIDIA Jetson Orin Nano. *Electronics*
  15(15), 3372. doi:10.3390/electronics15153372 — 558 audited runs on three
  boards; boundary choice and run order change the result. Overlaps directly
  with the boundary argument. Full text not yet read. Anchor.
- **[L29]** AgriJetsonBench: external-power-referenced TensorRT benchmarking of
  agricultural vision models on Jetson edge platforms. arXiv:2608.00927 (2026)
  — external board-input logging plus internal telemetry on an Orin Nano Super,
  TensorRT INT8, J per inference. Methodology precedent for Stage 1. Authors
  not recorded.
- **[L30]** NVIDIA Jetson Linux Developer Guide r36.5, *Platform Power and
  Performance* — INA3221 at 0x40 on Orin Nano/NX; `VDD_IN` is module input,
  not the carrier.

### Frameworks

- **[L31]** snnTorch — Eshraghian et al. (2023). Training spiking neural
  networks using lessons from deep learning. *Proc. IEEE* 111(9), 1016–1054.
  doi:10.1109/JPROC.2023.3308088 — PyTorch-based, NIR export; no ONNX/TensorRT
  path seen.
- **[L32]** SpikingJelly — Fang et al. (2023). *Science Advances*.
  doi:10.1126/sciadv.adi1480 — current README: backend chosen among Torch,
  Triton and native CUDA, no CuPy needed.
- **[L33]** NIR — Pedersen et al. (2024). Neuromorphic intermediate
  representation. *Nature Communications*. doi:10.1038/s41467-024-52259-9 —
  interchange format for SNNs.
- **[L34]** Tonic — Lenz et al. (2021). Zenodo. doi:10.5281/zenodo.5079802 —
  event transforms (ToFrame, Denoise); useful for B's representations.
- Leads, UNVERIFIED: Norse (github.com/norse/norse); Lava / lava-dl on aarch64.

### Resilience of autonomous systems (§5)

Checked 23 Oct 2026 against arXiv; venues as stated on arXiv unless marked.

- **[L35]** Hsiao, Wan, Jia, Ghosal, Mahmoud, Raychowdhury, Brooks, Wei,
  Janapa Reddi (2023). MAVFI: an end-to-end fault analysis framework with
  anomaly detection and recovery for micro aerial vehicles. *DATE 2023*.
  arXiv:2105.12882 — fault injection judged by mission metrics (flight time,
  success rate); planning and control more vulnerable than perception;
  Gaussian and autoencoder anomaly detection with recovery. Extended as ROSFI
  in *IEEE TCAD* (year not checked), which reports detector overhead as
  computation, not energy. Anchor for §5.
- **[L36]** Wan, Chandramoorthy, Swaminathan, Chen, Janapa Reddi,
  Raychowdhury (2023). BERRY: bit error robustness for energy-efficient
  reinforcement learning-based autonomous systems. *DAC 2023*.
  arXiv:2307.10041 — robust learning for low-voltage operation, offline and on
  board a UAV; energy and quality-of-flight together.
- **[L37]** Xie, Qi, Wen, Wan, Dong, Wang, Cai, Liang, Jia, Wang, Wang, Li
  (2026). CREATE: cross-layer resilience characterization and optimization for
  efficient yet reliable embodied AI systems. *ASPLOS 2026*.
  doi:10.1145/3779212.3790147, arXiv:2601.14140 — error injection across the
  layers of an LLM-planner and RL-controller stack; fault tolerance differs by
  layer; autonomy-adaptive voltage scaling of the controllers. Anchor for §5.
- **[L38]** Spyrou, Hamdioui, Stratigopoulos (2024). SpikeFI: a fault
  injection framework for spiking neural networks. arXiv:2412.06795 (venue not
  checked) — neuron and synapse fault models, permanent and transient, on
  SLAYER/PyTorch.
- **[L39]** Gogebakan, Magliano, Carpegna, Ruospo, Savino, Di Carlo (2024).
  SpikingJET: enhancing fault injection for fully and convolutional spiking
  neural networks. *IOLTS 2024*. arXiv:2404.00383 — faults in weights, neuron
  parameters, internal states and activation functions.

### Robotics-computing benchmarks (§3)

- **[L40]** Mayoral-Vilches, Jabbour, Hsiao, Wan et al. (2024). RobotPerf: an
  open-source, vendor-agnostic benchmarking suite for evaluating robotics
  computing system performance. arXiv:2309.09212. Venue ICRA 2024 UNVERIFIED
  (not stated on arXiv) — ROS 2 benchmarks with black-box and grey-box
  measurement.
- **[L41]** Wan, Qian, Du, Jabbour, Du, Zhao, Raychowdhury, Krishna, Janapa
  Reddi (2025). Generative AI in embodied systems: system-level analysis of
  performance, efficiency and scalability. *ISPASS 2025*. arXiv:2504.18945 —
  workload characterisation of embodied-agent systems, per module. Sometimes
  cited as "EmbodiedPerf"; that name is UNVERIFIED.

### Positioning

Anchor against [L7], [L18], [L20] with [L21], [L23] and [L28], with [L1] for the
classical lineage, and against [L35] and [L37] for the resilience part.

**What this project can claim:**

- Measured energy per *closed-loop* control decision, alongside a task metric,
  for four algorithm families on one Orin Nano, at nested measurement
  boundaries and across clock frequency.
- How tracking degrades under injected compute faults, per family, judged by
  mission metrics, with the measured energy cost of detecting the faults, in
  the same loop on the same board.

**What it cannot claim as new**, because prior work already shows it:

- SNNs don't win on GPUs — [L18], [L20].
- The measurement boundary changes the answer on this board — [L28].
- SNN and ANN energy on a Jetson, open-loop — [L20], [L21], [L29].
- Closed-loop SNN vision-to-control — on Loihi, [L4], [L7].
- Mission-level metrics for fault studies of autonomous systems, and control
  being more fault-sensitive than perception — [L35].
- Fault injection into SNNs — [L38], [L39].
- Trading energy against task quality by scaling voltage — [L36], [L37]. This
  project changes clock frequency, not voltage, and makes no low-voltage
  claims.

The new part is the combination: closed loop, task-matched comparison,
classical baseline, one Orin Nano, stated boundaries, and fault behaviour
observed in the same loop whose energy is measured.

---

## 7. Status and plan

*Status on 2 Nov 2026. The §1 claim is the goal; it is earned for controller A
at one clock point, without faults.*

### Done

- **Rig:** Jetson on NVMe, SSH over USB-C, JetPack 7.2.1 compute stack,
  verified across a cold boot; code sync Mac ↔ GitHub ↔ Jetson (SETUP_NOTES).
- **PyTorch with CUDA on the board**, checked with real GPU kernels (19 Oct
  2026; §5, SETUP_NOTES §6.4).
- **Simulator** built and reviewed (`spec_sim.md`, `docs/sim.md`); realtime at
  100 Hz on the Mac (25 Oct 2026).
- **Step 1, the closed loop with the controller on the Jetson: passed** on
  26 Oct 2026. 0 misses in a 60 s run, about 90 µs of board compute per
  decision (`docs/sim.md` §5).
- **On-board power rails characterised, plus a pilot** (§4, SETUP_NOTES §8,
  `traces/board_20261026/`).
- **Stage 1 board-level meter** built and validated (29–31 Oct; §4), and the
  board's services trimmed for measurement (SETUP_NOTES §8.1).
- **Step 2, controller A: done** on 2 Nov 2026, with Stage 1 energy rather
  than Stage 0 (`docs/spec_ctl_a.md`, `docs/ctl_a.md`):
  - tracking 0.2° RMS on sine and random, about 13× better than `centroid`,
    confirmed on held-out seeds;
  - 0.47 ms per decision on the Jetson;
  - E_dyn(A) +207 µJ [+195, +219], E_tot(A) 63.63 mJ per decision;
  - written up in the README with the raw traces and the stated limits.

**What step 3 needs from A, and what's ready:**
- **Fault sites:** A keeps its filter state and covariance, PID integrator,
  cluster measurement and last command in named arrays (spec R1.5), so the
  fault wrapper can reach them without restructuring. The fault wrapper and
  `--fault` (sim T22) aren't built yet.
- **Recovery path:** a corrupted filter state is recovered through
  re-acquisition, which has a known gap for jumps of about 4–6° (spec §6,
  R4.5). Fix it before measuring persistence.
- **A detector's energy** will be small, a few µJ at most. With a
  round-to-round sd of about 19 µJ, ±5 % isn't reachable, so the target has
  to be absolute (±5 µJ needs about 55 rounds, about 3.5 h of blocks) or the
  detector measured open-loop.
- **Clock points:** need clock locking (§3), whose recipe raises idle
  `VDD_IN` by 1.1–1.8 W (SETUP_NOTES §8). Each point needs its own I/H/A
  rounds.
- **Timing:** under the energy harness, A's slowest steps reached 4.06 ms
  (garbage collection). `gc.freeze()` after `reset` is the first fix if a
  clock point lowers the margin.

### Plan

In order. About 7 weeks of evenings remain until mid-December, which is not
enough for all of it:

- **Firm for mid-December:** steps 1–2, the closed loop and controller A with
  Stage 0 energy, written up in the README with raw traces and stated limits.
- **If on track by late November:** step 3, time-boxed.
- **After December:** steps 4–7, unless the firm part lands early. B is next
  in line.

So by December the §1 claim is earned for A only. Its fault clause holds only
if step 3 lands, and the detector's energy only if it fits the box. The
README's status table says which parts exist.

1. **Closed loop — now, and the first milestone.** Build the simulator's core
   tasks (`spec_sim.md` §4–§5); Linux, SSH and the doctor stay optional. Close
   the loop on the Mac with the `centroid` test
   controller, then with the controller running on the Jetson over USB-C
   (spec R14.6). At this point the project can be shown: a running loop on
   real hardware, plus the plan below.
2. **Stage 0 harness and A.** Build controller A, then the idle / no-op /
   algorithm blocks with the sysfs logger, for the first `E_dyn` and `E_tot`
   of A. Write them up in the README with the raw traces. *Done 2 Nov 2026,
   measured with the Stage 1 meter instead of the sysfs logger (Done,
   above).*
3. **A under faults plus 3 clock points, time-boxed to 4 evenings** (§3, §5).
   Needs only A and the harness.
   - Must have:
     - the three clock points, with idle, harness and A blocks at each (1–2
       evenings, more if clock control on R39.2.1 fights back);
     - the fault wrapper and `--fault` option first (spec T22), then faults in
       the Kalman state and the PID integrator at three rates, with paired
       runs, persistence and mission metrics (about 2 evenings). These
       are emulated lockstep runs, so they run on the Mac (`jn-sim ctl` on
       localhost) and need no board time.
   - If it fits: one range or rate detector with recovery, and its measured
     `E_det`.
   - Later, with the resilience work for B–D: the detector if it didn't fit,
     the covariance and cluster sites, more rates, a Gaussian detector.

   When the four evenings are up, stop and move on to B.
4. **B** — train on the Mac, TensorRT on the Jetson.
5. **C and D** — one SNN, two execution styles.
6. **Stage 1 measurements** — board-level boundary, INA3221 cross-check.
   *The board-level boundary is in use since step 2. The INA3221
   cross-check works for totals only: its 40 mW steps can't resolve
   per-decision differences.*
7. **Writeup** — crossover and Pareto plots, raw traces, boundary table,
   stated limits.

Still open: the exact clock frequencies, read from the board (§3).
