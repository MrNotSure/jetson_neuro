# Spec — controller A: event-cluster tracker, Kalman filter, PID

*Written 1 Nov 2026, after the measurement setup was finished (Stage 1 meter,
quiet board, closed loop measured with `hold` and `centroid`; `exploration.md`
§4). This is step 2 of `exploration.md` §7: build A, then measure its energy
per decision. Requirements here are numbered R1…, tasks T1…; requirements of
the simulator spec are cited as "sim R8.9". Revised 1 Nov after the T1–T4
review (`runs/review_ctl_a_20261101/review.md`): R4.4, R4.5, R6.2, R6.3,
R8.1, and the tests of T2, T3 and T5. Annotated 2 Nov with how R9 was run
(T6, T6b) and the R7.1 observation under the energy harness. T1–T7 are
done; results in `docs/ctl_a.md`.*

## 1. Purpose and scope

Controller A is family A of `exploration.md` §5: a classical event-cluster
tracker with a Kalman filter and PID. It runs as a `jn-sim` controller,
in-process on the Mac and on the Jetson over TCP, like `hold` and `centroid`.

It has two jobs:

1. **Track well.** It has to beat `centroid` clearly, so that the reference
   the learned controllers (B–D) are measured against is a good classical
   design, not a strawman (`exploration.md` §5, "Why A matters").
2. **Be measured.** Its energy per decision on the board, with a stated
   uncertainty, using the protocol from the 30–31 Oct sessions.

**In scope:**

- the controller, its tests and its registration;
- tuning and tracking evaluation on the Mac, on the four v1 scenarios;
- timing on the Jetson;
- one energy session on the board, and the writeup in the README.

**Out of scope:**

- fault injection and detectors (`exploration.md` §7 step 3). A's design keeps
  the fault sites addressable (R1.5), nothing more;
- clock points: this spec measures at default DVFS only;
- scene stages 2 and 3 (texture, distractors), which aren't built;
- a C implementation of A;
- changes to the simulator, the protocol or `ctl.py`.

**Core and optional.** T1–T7 are core. T8 (stage timer) and T9 (open-loop
replay) are optional, each with its condition.

**Where it comes from.** The tracker follows [L6] (Barranco, Fermüller, Ros
2018): mean-shift clustering of events, smoothed by a Kalman filter with
position and velocity. [L1] (the robotic goalie) is the closed-loop lineage: a
cluster tracker driving an actuator. Both use a fixed camera. The control half
is this spec's own design, for a camera that moves and isn't told where it
points: the servo model (R3), the feedforward across the 20 ms delay (R6.1)
and the PID (R6.2).

**Existing code, considered and not used** (checked 1 Nov 2026):

- [L6]'s own code (`fbarranco/dvs_clustering_tracking`): C++ on ROS 1
  Kinetic, GPL-3. A port is a rewrite, and copied code would bring the GPL.
- jAER's cluster trackers (the goalie's): Java.
- AEB-Tracker (Wang et al., T-RO 2024): C++ with OpenCV and Eigen, offline on
  recorded files, camera motion from a gyroscope the simulator doesn't have.
- iniVation's `dv-processing`, which has mean-shift clustering and Python 3.12
  wheels for aarch64: a compiled dependency for the board, a format
  conversion every period, and clustering only. Its cost would also land in
  A's energy number.
- `filterpy`, `simple-pid`: each replaces about 20 lines.

None of them is a controller, and the tracking part they cover is the
smallest part of A.

## 2. Decisions

| Topic | Decision | Reason |
|---|---|---|
| Own implementation | written here, not adapted from existing code | no existing controller fits; the trackers that exist are C++, Java or a compiled library (§1) |
| Language | Python 3.12 and numpy only, no new dependencies | runs in the board's `~/venvs/jn` as is (sim R1.3). If Python overhead turns out to dominate A's energy, a C variant is a later, separate step |
| Name and module | controller `classical`, module `src/jn_sim/classical.py` | readable in run directory names (`…_sine_classical`) |
| Camera pose | estimated from A's own setpoints through a servo model ("efference copy") | OBS carries no pan/tilt (sim R8.4). Without a pose estimate there is no world-frame target velocity, so no prediction across the 20 ms from event to effective setpoint. That lag is what limits `centroid` (2.7° RMS on sine) |
| Filter | per axis, a 2-state constant-velocity Kalman filter of the target's world angle | the target moves smoothly in three of four scenarios; the axes are nearly decoupled at these angles |
| Tracker | coarse grid of ON events for acquisition, gated mean-shift for tracking | cheap with `np.bincount`; the gate rejects shot noise; ON-only acquisition finds a bright target that just appeared (R4.2) |
| Control law | filter feedforward with ramp lead, plus PID on the image error | the feedforward removes the lag; the PID's integral removes what the servo model gets wrong |
| Numbers | float64 | the native numpy type. How the fault study flips bits in it is that study's decision |
| Energy protocol | `hold` against A in counterbalanced 60 s rounds, pinned to one core, marker-aligned analysis | from the 31 Oct session (`exploration.md` §4) |
| Precision target | ±5 % on A's dynamic energy per decision (95 % CI), within a capped session | the user's requirement of an accurate measurement; the cap keeps the session bounded |
| Closed loop only | A and `hold` are measured in the closed loop | that is the claim. Open-loop replay (same inputs for both) is optional, T9 |

## 3. Requirements

### R1 Interface and placement

- **R1.1** `src/jn_sim/classical.py` defines `ClassicalController(params)`
  with the interface of sim R8.1: `reset(hello)` returns `"classical"`,
  `step(obs)` returns `(pan, tilt)`. No flags until the fault study.
  `self.params` holds every effective parameter (sim R8.10).
- **R1.2** `testctl.make_controller("classical", params)` builds it. The
  registry stays in `testctl.py` for now and imports `classical` lazily, so
  the `hold` and `centroid` paths don't load it. Unknown parameters raise
  `ValueError` at startup, as for `centroid`.
- **R1.3** Standard library and numpy only. It imports nothing from the
  simulator side (`camera`, `plant`, `config`, …). The import-boundary test
  (sim T15) also passes for `ctl --controller classical`, with
  `jn_sim.classical` added to the allowlist.
- **R1.4** A knows only HELLO (size, period, intrinsics, `pan0`, `tilt0`) and
  its parameters (sim R8.4). The servo model and angle limits are parameters
  whose defaults equal the simulator's defaults: the designer's model of the
  servo, not values read from the simulator.
- **R1.5** Deterministic: no randomness, `ctl_seed` unused. The same OBS
  sequence gives the same commands. `reset` restores the whole initial state,
  so episodes are independent. The fault sites of `exploration.md` §5 live in
  named attributes, so the fault study can reach them without restructuring:
  the cluster measurement, each axis's filter state and covariance, each
  axis's PID integrator, and the last command.

### R2 Geometry

- **R2.1** Pixel to world direction: the exact inverse of the camera
  conventions of sim R3 (world x forward, y left, z up; pan about z, tilt about
  the panned y axis; u right, v down), given a pose and HELLO's intrinsics.
  Implemented in `classical.py`; agrees with `camera.unproject` to 10⁻⁹ rad.
- **R2.2** World direction to pixel at a pose, for the gate (R4.4). Agrees
  with `camera.project_azel` to 10⁻⁶ px.

### R3 Camera-pose model

- **R3.1** Per axis, a linear second-order servo with the model parameters
  ω_n, ζ, discretised exactly (zero-order hold) at the period T. The setpoint
  from CMD_j is active over [(j + 1 + d)T, (j + 2 + d)T), with d =
  `model_dead_periods` (default 1, so (j + 2)T, as sim R5.3).
- **R3.2** The model ignores the rate limit: the largest step in the
  scenarios (20°) peaks at 3.7 rad/s against the 6 rad/s limit. A clamps its
  own setpoints to the angle limits (R6.3), so the simulator's clamp (sim
  R8.9) never acts.
- **R3.3** The pose between period boundaries is interpolated linearly.
- **R3.4** Known limit, stated in the writeup: a CMD that misses its deadline
  isn't applied (sim R7.3), but the model assumes it was. Misses were ≤ 0.4 %
  of decisions on 31 Oct.

### R4 Event-cluster tracker

- **R4.1** Each period, ON events are counted on a coarse grid of `cell` px
  (default 16, so 20 × 15 cells) with `np.bincount`, then summed over 3 × 3
  blocks.
- **R4.2** Acquisition seed: the block with the most ON events, if it holds at
  least `n_acq`. The seed is the mean position of those ON events. ON only,
  because the stage-1 target is brighter than the background: where it
  appears, pixels brighten. Shot noise puts about 1.2 ON events in a block per
  period, so `n_acq` = 20 is never reached by noise.
- **R4.3** Mean-shift: a uniform window of radius `r_win` (default 12 px; the
  target's radius is 7.3 px), up to `ms_iter` iterations (default 3) from the
  seed, stopping when the shift is under 0.1 px. All polarities. Result: the
  centre (u, v), the number of events n and their mean timestamp t̄.
- **R4.4** Gate: while tracking, the seed is the filter's prediction for the
  period's mid-time, projected at the model pose (R2.2). Mean-shift (R4.3)
  runs from it; its final window is the **gate window**. The result counts as
  a measurement if n ≥ `n_meas` (default 15) and the centre lies within
  `r_gate` (default 24 px) of the seed. Otherwise there is no measurement this
  period. If the prediction doesn't project (behind the camera), the period
  runs acquisition (R4.2) as in ACQUIRE: a seed re-acquires (R5.4), no seed
  means COAST.
- **R4.5** Jump check, every tracking period. A candidate is the best ON
  block (R4.2), located at the mean position of its ON events. It must lie
  more than `r_gate` from the gate seed, hold at least `n_acq` ON events, and
  hold more ON events than the gate window. Mean-shift (R4.3) then runs from
  the candidate. A re-acquires there (R5.4), taking precedence over a gated
  measurement in the same period, only if that result has n ≥ `n_meas` and
  its centre lies more than `r_gate` from the gate window's centre. The last
  condition stops the target's own leading edge from triggering a jump when
  the prediction lags: both mean-shifts then converge on the same disc
  (review S1, 1 Nov). With a still camera, a still target produces no
  events, so after a jump (`track-step-v1`) its only events are in the period
  of the jump.

### R5 Filter and track states

- **R5.1** Per axis, a constant-velocity Kalman filter of the target's world
  angle and rate, with continuous white-noise acceleration of spectral density
  `q` (rad² s⁻³). It is predicted to each measurement's time t̄ (variable
  step) and to the command time (R6.1).
- **R5.2** Measurement: the world angle of the cluster centre (R2.1) at the
  model pose at t̄. Variance (`sigma_px` / f)² per axis, with f = fx or fy.
- **R5.3** States:
  - ACQUIRE: no track. Hold the last setpoint; look for a seed (R4.2) each
    period.
  - TRACK: a measurement this period; update the filter.
  - COAST: no measurement this period; predict only, and keep commanding from
    the prediction, so the camera keeps moving and the target keeps producing
    events.
  - After `coast_max` periods without a measurement (default 30, 0.3 s): back
    to ACQUIRE, rates set to 0.
- **R5.4** (Re-)initialisation: angle = the measurement, rate 0, covariance
  diag(R, σ_v0²) with σ_v0 = 30°/s (above the scenarios' peak rates of
  24°/s), PID integrator 0.

### R6 Command

- **R6.1** Feedforward: ff = x̂(t_cmd) + τ_lead · v̂(t_cmd), per axis, with
  t_cmd = (k + 1.5 + d)T, the middle of the period in which CMD_k is active.
  τ_lead = 2ζ/ω_n of the servo model (64 ms): a second-order servo following
  a ramp lags by exactly that, 1.5° at the sine's peak rate of 23.6°/s.
- **R6.2** Feedback: a PID on the image error e, the angle from the image
  centre (the true boresight) to the cluster centre, per axis from the pixel
  offset and HELLO's intrinsics, so it doesn't depend on the servo model. It
  is added to the feedforward: u = Kp·e + Ki·∫e dt + Kd·ė. It updates only in
  periods with a measurement; otherwise it holds its last output.
  - **Time base: periods, not event timestamps** (a sampled PID; review S2).
    Each measured period adds e·T to the integral. The derivative is
    (e − e_prev) / ((k − k_prev)·T), with k_prev the last measured period.
  - **On (re-)initialisation** (R5.4) the integral and e_prev are cleared;
    the initialising period then adds its e·T and has no derivative term.
  - Anti-windup: |Ki·∫e dt| ≤ `i_max_deg`, and the integral is frozen while
    the setpoint is clamped.
  - Kd starts at 0, since the filter's rate already acts as derivative
    action through the feedforward.
- **R6.3** Setpoint = ff + u, clamped to ±`pan_lim_deg` and ±`tilt_lim_deg`.
  The clamp bound is the largest float32 value not beyond each limit, since
  CMD carries float32 (sim R8.2). Otherwise rounding takes ±90° to
  90.0000025° and the simulator's clamp flag fires (review C3). In ACQUIRE,
  the last setpoint. No NaN guard: catching corrupted state is
  the fault study's detector, and the simulator holds non-finite commands
  (sim R8.9).

### R7 Timing

- **R7.1** `ctl_us` (sim R12.2), 60 s realtime `track-sine-v1`:
  - Mac: p99 ≤ 0.5 ms;
  - Jetson: p99 ≤ 1.5 ms and max ≤ 3 ms. The CMD deadline is 5 ms and the
    link's p99 about 1.6 ms (`docs/sim.md` §5).
  *Observed 2 Nov:* T5 met both bounds (max 2.30 ms). Under the energy
  harness in T6b, 2 of 72,000 steps took 4.06 ms, without a miss. The slow
  steps are garbage collections (`docs/ctl_a.md` §8); `gc.freeze()` after
  `reset` is the cheap fix, not applied.
- **R7.2** On the Jetson, A's step stays well inside the first 3 ms after the
  marker, so the energy analysis keeps its quiet baseline window
  ([5.5, 8.5) ms after the edge; R9.5). R7.1 implies this.

### R8 Tracking quality

- **R8.1** Evaluation: the four v1 scenarios, seeds 0–4, one 30 s episode
  each, lockstep, in-process. `centroid` runs on the same seeds as the
  reference. Seed 0 of `centroid` (3 episodes, 1 Nov): static 0°, sine
  2.67°, step 4.62°, random 2.58° `rms_deg`, all with in-FOV fraction 1.
  Seeds 5–9 are reported too, as held-out seeds, since the tuning used 0–4.
  - **The step score stays as `track-step-v1` defines it** (sim R12.4), but
    it is dominated by the first 2 s after warm-up: the target sits still
    until the first jump at 3 s, so no controller can see it (review S3).
    Step is therefore also reported from t = 3 s on. A versioned
    `track-step-v2` with an observable start is a simulator question, out of
    scope here.
- **R8.2** Pass criteria, with A's default parameters:
  - mean `rms_deg` over the seeds lower than `centroid`'s on sine, random and
    step;
  - in-FOV fraction 1.0 for every seed on static, sine and random;
  - step: episode success (sim R12.2) for every seed, and no unrecovered
    losses;
  - static: `max_deg` ≤ 0.2°, so shot noise doesn't move the camera.
- **R8.3** Goal, not a pass criterion: `rms_deg` ≤ 1° on sine.
- **R8.4** Robustness, recorded, with A's model left at its defaults: the
  simulator's servo changed to ω_n = 20 and 30 rad/s, and ζ = 0.6
  (`--set plant.omega_n=…`, `--set plant.zeta=…`). Sine and random should
  still keep the in-FOV fraction at 1.0.
- **R8.5** Recorded with the timing on the Jetson (R7.1): the realtime
  tracking metrics of the same 60 s run.

### R9 Energy per decision

- **R9.1** Boundary: the board input (INA228), with `VDD_IN` (INA3221)
  alongside for the Stage 0 comparison. 25 W mode, default DVFS, the quiet
  board of SETUP_NOTES §8.1, the session checklist of §8.3.
- **R9.2** Conditions, on `track-sine-v1`, realtime, 60 s blocks:
  - I: idle, no controller;
  - H: `hold`;
  - A: `classical` with its default parameters.

  Each H and A block runs a fresh controller process pinned with
  `taskset -c 2`, with the marker byte at the start of each step and one
  dummy byte after opening the port. The wrapper is
  `traces/stage1_20261031_final/scripts/mark_ctl.py`, extended to accept
  `classical`.
- **R9.3** Design:
  - rounds of one H and one A block, in counterbalanced order (H A, A H,
    A H, H A, repeating), so each comes first equally often;
  - one I block at the start of the session and one at the end;
  - 4 rounds first. From their spread of X_A − X_H, the number of rounds for
    ±5 % (95 % CI) is computed and run, up to a cap of 40 more minutes of
    blocks. The achieved half-width is reported either way.

  *As run, 2 Nov:* T6 used this design. Its 10 Hz loggers (R9.4) spread X,
  so a confirmation session T6b replaced it: 12 rounds of I, H and A, the
  order cycling twice through all six permutations, fixed length, with the
  design and analysis written down before the first block. T6b's design is
  the one to keep for B–D (`docs/ctl_a.md` §9).
- **R9.4** Logged per block: both CPU clusters' `scaling_cur_freq` at 10 Hz
  (in the INA3221 sampler), temperatures and fan before and after, the
  controller's core, and the simulator's run directory (tracking metrics,
  `n_events`, `ctl_us`).

  *As run:* the 10 Hz logging was the main noise source in T6 (each read
  about 0.4 mJ, at a random phase). T6b ran no logger during the captures and
  took a snapshot in each gap instead: temperatures, fan, both clusters' and
  the GPU's frequency, one `VDD_IN` reading.
- **R9.5** Analysis, as `traces/stage1_20261031_final/scripts/p6_analyze.py`:
  - method (b): X per block, the excess energy over [−1, 4.5) ms around the
    marker edge above the baseline [5.5, 8.5) ms; periods of 8–15 ms only;
    flagged periods (miss, send lateness > 5 ms) dropped;
  - **dynamic energy E_dyn(A) = X_A − X_H per round**, mean and t CI over
    rounds;
  - check the window against A's profile. If A's excess starts before −1 ms
    or lasts past 4.5 ms, widen the window and say so;
  - method (a): block means, for E_dyn(a) = (P_A − P_H)/f, the harness cost
    (P_H − P_I)/f and E_tot = P_A/f; `VDD_IN` by method (a).
- **R9.6** Reported, each with its CI:
  - E_dyn(A) by both methods; X_A and X_H;
  - E_tot of A as a stack: idle floor, harness, algorithm;
  - `ctl_us` of A on the board;
  - `n_events` per decision for H and A. In the closed loop A tracks, so it
    receives fewer events than `hold` (centroid 262 against hold 404 on
    31 Oct), and E_dyn includes that smaller decode cost. Stated next to the
    number; T9 removes it if needed;
  - A's realtime tracking metrics from the same blocks;
  - the `VDD_IN` figures, for the boundary comparison. *As run:* `VDD_IN`
    can't resolve differences of about 20 mW; T6 read A − H larger on
    `VDD_IN` than at the 19 V input, which isn't physical. Only E_tot is
    compared across the two boundaries.

### Defaults

Initial values; T4 tunes the ones marked "tune" and records the result here.

| Parameter | Default | Source |
|---|---|---|
| `cell` | 16 px | decision (20 × 15 grid) |
| `n_acq` | 20 ON events per 3 × 3 block | noise gives ≈ 1.2 per block and period |
| `r_win` | 12 px | target radius 7.3 px plus motion smear |
| `ms_iter` | 3 | decision |
| `n_meas` | 15 events | tuned in T4, kept (`docs/ctl_a.md` §4) |
| `r_gate` | 24 px | tuned in T4, kept |
| `sigma_px` | 1.0 px | tuned in T4, kept (acts through q/R, like `q`) |
| `q` | 2.0 rad² s⁻³ | tuned in T4, was 0.25 (sine peak acceleration ≈ 0.65 rad/s²) |
| `coast_max` | 30 periods | tuned in T4, kept |
| `kp`, `ki`, `kd` | 0.3, 8.0 s⁻¹, 0 | tuned in T4, were 0.1, 1.0 s⁻¹, 0 |
| `i_max_deg` | 2° | decision |
| `model_wn`, `model_zeta` | 25 rad/s, 0.8 | simulator default (sim §3) |
| `model_dead_periods` | 1 | sim R5.3 |
| `pan_lim_deg`, `tilt_lim_deg` | 90°, 45° | simulator default |

## 4. Acceptance

This spec is done when:

1. T1–T4 meet their **Done when** on the Mac: the test suite passes and R8.2
   is met.
2. T5 meets R7.1 on the Jetson.
3. T6 has run and T7 has put E_dyn(A), E_tot and the tracking metrics into
   the README, with the raw traces under `traces/`.

The optional tasks (T8, T9) are not part of acceptance.

## 5. Tasks

| # | Task | Needs | Core or optional |
|---|---|---|---|
| T1 | Geometry and servo model | — | core |
| T2 | Event-cluster tracker | T1 | core |
| T3 | Filter, track states, command law, registration | T2 | core |
| T4 | Evaluation script, tuning, Mac evaluation | T3 | core |
| T5 | Jetson timing check | T4 | core |
| T6 | Energy session on the board | T5 | core |
| T7 | Writeup | T6 | core |
| T8 | Stage timer (sim T23) | T4 | optional: the writeup needs A's time split by stage |
| T9 | Open-loop replay | T6 | optional: the event-count difference between H and A matters for the comparison with B–D |

Code goes in `src/jn_sim/classical.py`, tests in `tests/test_classical.py`.

### T1 Geometry and servo model — `classical.py`

- R2.1, R2.2 and R3.
- **Tests:**
  - pixel → direction against `camera.unproject` and direction → pixel
    against `camera.project_azel`, over a grid of poses (pan ±60°, tilt ±30°)
    and pixels;
  - the servo model against `plant.py`: pose error under 0.05° for a
    23.6°/s ramp and the sine trajectory, under 0.25° for a 20° step. The
    plant integrates with semi-implicit Euler at 1 ms and the model is exact,
    so they differ: 0.02° and 0.17° measured on 1 Nov;
  - the dead time: a setpoint change in CMD_k first moves the model at
    (k + 2)T.
- **Done when:** these tests pass.

### T2 Event-cluster tracker — `classical.py`

- R4. Synthetic batches built like `tests/test_testctl.py` builds them.
- **Tests:**
  - noise only (77 random events, random polarity): no acquisition;
  - edge events of a moving disc plus noise: the centre within 1 px of the
    disc's mid-period position;
  - a jump: OFF events at the old position, ON events at a new one, the gate
    at the old one: R4.5 fires and the seed is at the new position;
  - no jump on smooth motion with a lagging prediction: one disc moving 1, 2,
    4, 8, 12 and 20 px per period, gate seed 19 px behind it. R4.5 must not
    fire, and the gate gives a measurement;
  - fewer than `n_meas` events in the gate: no measurement.
- **Done when:** these tests pass.

### T3 Filter, track states, command law, registration — `classical.py`, `testctl.py`

- R1, R5 and R6.
- **Tests:**
  - the filter converges on a synthetic constant-velocity target: rate error
    under 1°/s after 0.5 s;
  - anti-windup: the integral stays within `i_max_deg` while the setpoint is
    clamped;
  - `reset` restores the initial state: two episodes give identical commands;
  - jump re-acquisition through `step()`: after a track is established, a
    period with OFF events at the old position (a valid gated measurement)
    and ON events at a distant new one re-acquires at the new position,
    with rates 0, the covariance reset and the PID cleared (review C1);
  - PID time base (R6.2) with Kd ≠ 0 and a measurement gap: the derivative
    divides by (k − k_prev)·T;
  - COAST expiry: after `coast_max` periods without a measurement, ACQUIRE
    with rates 0;
  - the default clamp through the protocol and the plant: a saturated
    command in each direction on both axes doesn't set `cmd_clamped`;
  - unknown parameters raise `ValueError`; `params` lists every effective
    parameter;
  - loop test (sim R14.1 style), in-process lockstep, 3 s of sine: in-FOV
    fraction 1.0 after warm-up and `rms_deg` below `centroid`'s on the same
    run;
  - the import-boundary test passes for `ctl --controller classical`.
- **Done when:** these tests pass.

### T4 Evaluation script, tuning, Mac evaluation — `scripts/eval_controllers.py`, `docs/ctl_a.md`

- `scripts/eval_controllers.py`: runs a controller with given parameters over
  scenarios × seeds in lockstep, in-process (through `InProcLink`, so
  parameters can be passed), writes the runs under `runs/eval_<UTC>/` and
  prints one table: scenario, seed, `rms_deg`, `max_deg`, in-FOV fraction,
  losses, unrecovered losses, events per period, `ctl_us` p99. Reused for
  B–D later.
- Tuning: a small grid over the "tune" parameters (§3 Defaults), objective
  the mean `rms_deg` over sine, random and step, subject to the R8.2
  criteria. A few dozen runs, not an optimiser.
- Set the tuned values as the code defaults, update the Defaults table, and
  record in `docs/ctl_a.md`:
  - the R8.2 table, A against `centroid`;
  - R8.3 and R8.4;
  - `ctl_us` on the Mac (R7.1), 60 s realtime sine over TCP on localhost;
  - how to run A (`jn-sim ctl --controller classical`, the parameters).
- **Done when:** R8.2 and the Mac part of R7.1 are met and recorded.

### T5 Jetson timing check

- The planner updates the board checkout (`git pull`) to the commit that
  has A. On the quiet board (SETUP_NOTES §8.3), it runs three 60 s realtime
  `track-sine-v1` runs against `jn-sim ctl --controller classical`, pinned
  with `taskset -c 2` as in R9.2, and records both clusters' CPU frequency.
- **Diagnostic, not for energy blocks:** a wrapper logs every step's duration
  on the controller's clock, including steps whose CMD arrives late, so
  misses can be attributed (review C2). The Mac misses of 1 Nov aren't
  attributed.
- If p99 or max fails: first the tracker's allocation and reduction overhead
  (`runs/review_ctl_a_20261101/review.md` §6), then measure again. T6 waits
  for both bounds.
- **Done when:** R7.1's Jetson numbers are met, and they and R8.5's metrics
  are recorded in `docs/ctl_a.md`.

### T6 Energy session on the board

- The planner writes the bench-agent prompt from R9 and the 31 Oct prompt;
  the bench agent runs it; the user does the physical steps and approves each
  `sudo`.
- The session's data go to `traces/` (gzip above 5 MB, as before).
- **Done when:** the R9.6 numbers exist with their CIs, and the precision
  reached against ±5 % is stated.

### T7 Writeup — `README.md`, `exploration.md`

- README status: A's E_dyn and E_tot stack, tracking against `centroid`,
  links to the traces, and the stated limits: closed-loop event-count
  difference (R9.6), the servo model without proprioception (R3.4), stage-1
  scene only, Python implementation, one clock point.
- `exploration.md` §7: step 2 done; what step 3 needs from A.
- **Done when:** both are updated and pushed.

### T8 *Optional:* stage timer — `ctl.py`

- **When:** the writeup needs A's time split into decode, tracker, filter and
  command.
- Builds sim T23 (sim R8.13); A marks its stages. Off by default, so energy
  blocks are unaffected.
- **Done when:** sim T23's tests pass and A's stages appear in `stages.csv`.

### T9 *Optional:* open-loop replay

- **When:** the event-count difference between `hold` and A (R9.6) matters,
  for example when comparing A against B–D at equal input.
- A replay sender: OBS from a recorded run (`--save-events`) sent at 100 Hz
  to the controller, CMDs logged but not applied. H and A then get identical
  inputs.
- **Done when:** one replayed H/A session gives E_dyn(A) at equal input.

## 6. Risks and unknowns

- **Good tracking starves the tracker.** Events come from relative motion:
  about 77 noise events plus roughly 270 per pixel of relative motion per
  period (`hold` saw 404 at about 1.2 px per period on 31 Oct). The better A
  tracks, the fewer events it gets. COAST (R5.3) covers short gaps; if
  measurements drop out often, T4 lowers `n_meas` or accumulates two
  periods' events.
- **No proprioception.** The pose comes from a model of a servo A can't
  observe directly. R8.4 measures how much mismatch it tolerates; the PID's
  integral is the correction.
- **A stage-1 scene is easy.** One bright disc on a uniform background, no
  clutter. A may look near-perfect here; `exploration.md` §5 says B–D need
  clutter to have anything to win. That's a later scene stage.
- **The bright-target assumption** in ON-only acquisition (R4.2) holds for
  stage 1 only. A dark target would need OFF; stated in `docs/ctl_a.md`.
- **Python overhead may dominate E_dyn(A).** The number measures A as
  implemented in numpy on CPython, not the algorithm's floor. Stated in the
  writeup.
- **Precision depends on pinning.** On 31 Oct, unpinned `hold` drifted by
  40 % over the session (sd 39 µJ per block), against 7 µJ for `centroid`.
  If pinning doesn't cure it, ±5 % may not be reachable within the cap; the
  achieved CI is reported either way.
- **R4.5 has a blind band for jumps of about 4–6°** (found after the review
  fixes, 1 Nov; `docs/ctl_a.md` §10). The distinctness threshold r_gate is
  wider than the S1 case needs: two mean-shifts on the same disc converge
  within a few px. A jump that the gate window can't reach, and whose
  re-acquired centre lies within r_gate of it, gets neither a jump nor a
  measurement, so A coasts. Seen twice in 80 nominal runs, for 2 and 3
  periods, costing 0.001–0.002° of step RMS. It never fires on sine or
  random, the energy scenario. **Deferred.** The likely fix: when the gate
  gives no measurement, run acquisition (R4.2) as in the behind-camera case;
  when it does, require separation > `r_win` instead of r_gate. Revisit with
  the fault study, where recovery after a corrupted filter state depends on
  exactly this path.
