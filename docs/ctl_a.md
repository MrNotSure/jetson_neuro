# Controller A — event-cluster tracker, Kalman filter, PID

Controller `classical`, `src/jn_sim/classical.py`. The design, requirements
(R1–R9) and tasks (T1–T9) are in `docs/spec_ctl_a.md`; "sim R…" refers to
`docs/spec_sim.md`. This file records how A is run, its parameters and what it
measured on the Mac (T4). It was revised after the T1–T4 review
(`runs/review_ctl_a_20261101/review.md`); all results in §5–§7 are from code
`ce1bda2`. The Jetson timing check (T5, 2 Nov, code `0c397e1`) is in §8, the
energy per decision (T6, T6b) in §9.

## 1. What A is

Each period A:

1. advances its **servo model** (R3): a linear second-order servo per axis
   (ω_n = 25 rad/s, ζ = 0.8), exact zero-order hold at T, with CMD_k active
   over [(k + 2)T, (k + 3)T). It is fed A's own setpoints, since OBS carries
   no pan/tilt;
2. clusters the period's events (R4). ACQUIRE seeds from the strongest 3 × 3
   block of a 16 px ON-event grid. Tracking runs a gated mean-shift from the
   filter's prediction; its final window is the gate window. A jump check
   (R4.5) re-acquires when a strong ON block far from the gate seed leads, by
   mean-shift, to a cluster more than `r_gate` from the gate window's centre.
   A prediction behind the camera runs acquisition instead of the gate;
3. turns the cluster centre into a world angle at the model pose and updates a
   **constant-velocity Kalman filter** per axis (R5);
4. commands **feedforward + PID** (R6): the filter's prediction at the middle
   of the period in which the command is active, led by the servo's ramp lag
   2ζ/ω_n = 64 ms, plus a PID on the image error (pixel offset and intrinsics
   only, time base in periods). The result is clamped to the largest float32
   values inside ±90° / ±45°, so the float32 CMD never trips the simulator's
   clamp.

States: ACQUIRE (hold the last setpoint), TRACK (measurement this period),
COAST (no measurement; command from the prediction). After 30 periods
without a measurement, A goes back to ACQUIRE.

Fault sites (R1.5) are named float64 arrays on the controller: `meas`
(u, v, n, t of the last cluster), `kf_x` (per axis: angle, rate), `kf_P` (per
axis: p00, p01, p11), `pid_i` (per axis: ∫e dt) and `cmd` (last setpoint).

## 2. Running it

```sh
# controller server (binds 127.0.0.1:5555; no authentication, sim R9.6)
jn-sim ctl --controller classical [--param KEY=VALUE ...]
# realtime run against it
jn-sim run --scenario track-sine-v1 --controller tcp://127.0.0.1:5555 --mode realtime --duration 60
# in-process, defaults only
jn-sim run --controller inproc:classical --duration 5
# on the Jetson, from the checkout, bound to the USB-link address
PYTHONPATH=src ~/venvs/jn/bin/python -m jn_sim ctl --controller classical --listen 192.168.55.1:5555
```

Evaluation over scenarios × seeds, lockstep and in-process, with parameters
and config overrides (T4). It writes `runs/eval_<UTC>[_<tag>]/` with the run
directories, `eval.csv` and `eval.json`:

```sh
.venv/bin/python scripts/eval_controllers.py classical                      # 4 v1 scenarios, seeds 0-4
.venv/bin/python scripts/eval_controllers.py classical --seeds 5 6 7 8 9    # held-out seeds
.venv/bin/python scripts/eval_controllers.py classical --param kp=0.2 --seeds 0 1 --jobs 5
.venv/bin/python scripts/eval_controllers.py classical --set plant.omega_n=20 --tag r84
```

Lockstep tracking results don't depend on `--jobs`; `ctl_us` does. The
script's mean and worst rows cover all the seeds given, so the tables below
split one 10-seed evaluation; `--seeds 0 1 2 3 4` and `--seeds 5 6 7 8 9`
reproduce each half exactly.

## 3. Parameters

Unknown names and bad values are rejected at startup (`ValueError`, exit 2
from `jn-sim ctl`). `params` in the controller metadata lists every effective
value.

| Parameter | Default | Meaning |
|---|---|---|
| `cell` | 16 px | ON grid cell (R4.1) |
| `n_acq` | 20 | ON events in a 3 × 3 block to seed (R4.2) |
| `r_win` | 12 px | mean-shift window radius (R4.3) |
| `ms_iter` | 3 | mean-shift iterations (R4.3) |
| `n_meas` | 15 | events for a measurement (R4.4); tuned, kept |
| `r_gate` | 24 px | gate radius; also the jump distances from the gate seed and from the gate window's centre (R4.4, R4.5); tuned, kept |
| `sigma_px` | 1.0 px | measurement sd (R5.2); kept, see §4 |
| `q` | **2.0** rad² s⁻³ | acceleration noise (R5.1); tuned, was 0.25 |
| `coast_max` | 30 periods | COAST before ACQUIRE (R5.3); tuned, kept |
| `kp` | **0.3** | proportional gain (R6.2); tuned, was 0.1 |
| `ki` | **8.0** s⁻¹ | integral gain; tuned, was 1.0 |
| `kd` | 0 s | derivative gain; tuned, kept |
| `i_max_deg` | 2° | bound on \|ki ∫e dt\| (R6.2) |
| `model_wn`, `model_zeta` | 25 rad/s, 0.8 | servo model (R3.1) |
| `model_dead_periods` | 1 | setpoint dead time in periods (R3.1) |
| `pan_lim_deg`, `tilt_lim_deg` | 90°, 45° | A's setpoint limits (R6.3). The clamp bound is the largest float32 not beyond each: 89.9999957° and 44.9999978° |

## 4. Tuning (T4)

Objective: the mean `rms_deg` over sine, random and step, subject to the R8.2
criteria. All R8.2 constraints held at every grid point. Screening used seeds
0–1 and confirmation seeds 0–4.

- **Run count: 510 tuning runs** (screens 150 + 162 + 108, confirmation 90),
  out of 666 lockstep runs in T4. The other 156: the `centroid` baseline and
  A at its initial defaults (40), six prechecks of R8.4 (36), the final
  evaluation (20) and R8.4 (60).
- **Budget.** That is more than T4's "a few dozen runs"; the session brief
  allowed about an hour of runs.
- **CPU time was not measured** for the tuning. About 40 CPU-minutes for the
  510 runs, 50 for all 666, is an estimate: 4.6 s of user CPU per run, from
  two timed 20-run evaluations (90.7 s and 92.5 s).
- **Code.** The tuning ran on `a5d3a58`, before the review fixes. Those
  change 2 of the 80 nominal runs, both on step, by at most 0.003° in v1
  `rms_deg` (§5.1). The tuning was not rerun.

Directories: `runs/tune_*` (gitignored).

**Screen 1**, one factor at a time from the initial defaults, seeds 0–1
(mean `rms_deg`, degrees):

| Change | sine | random | step |
|---|---|---|---|
| initial defaults | 0.266 | 0.262 | 2.950 |
| `kp` 0 / 0.05 / 0.2 / 0.3 | 0.280 / 0.272 / 0.253 / 0.247 | 0.284 / 0.269 / 0.245 / 0.240 | 2.971 / 2.959 / 2.936 / 2.922 |
| `ki` 0 / 0.5 / 2 / 4 | 0.268 / 0.269 / 0.242 / 0.198 | 0.264 / 0.261 / 0.256 / 0.223 | 2.940 / 2.945 / 2.959 / 2.956 |
| `kd` 0.002 / 0.005 | 0.272 / 0.261 | 0.259 / 0.258 | 2.952 / 2.953 |
| `q` 0.05 / 0.1 / 0.5 / 1 / 2 | 0.348 / 0.304 / 0.244 / 0.225 / 0.220 | 0.342 / 0.302 / 0.247 / 0.230 / 0.210 | 2.952 / 2.952 / 2.946 / 2.956 / 2.950 |
| `sigma_px` 0.5 / 2 / 4 | 0.232 / 0.335 / 0.461 | 0.225 / 0.339 / 0.437 | 2.950 / 2.954 / 2.953 |
| `n_meas` 8 / 30 | 0.265 / 0.289 | 0.263 / 0.281 | 2.949 / 2.953 |
| `r_gate` 16 / 36 | 0.266 / 0.266 | 0.262 / 0.262 | 2.948 / **3.744** |
| `coast_max` 10 / 60 | 0.266 / 0.266 | 0.262 / 0.262 | 2.949 / 2.952 |

- `sigma_px` acts through the ratio q/R, like `q`, so only `q` was tuned
  further.
- `kd`, `n_meas` and `coast_max` made no difference.
- `r_gate` = 36 px hurts step: jumps shorter than the gate (about 7°) no longer
  trigger re-acquisition.

**Screens 2–3**, `kp` ∈ {0.2, 0.3, 0.4, 0.5} × `ki` ∈ {2, 4, 8, 12, 16} ×
`q` ∈ {1, 2, 3, 4}, seeds 0–1 (45 points). The best region was `ki` 8–12 with
`q` = 2 and any `kp` from 0.2 to 0.5, objective 1.091–1.092. `ki` = 16 and
`q` ≥ 3 were worse; `ki` = 2 was 0.01–0.02 worse.

**Confirmation**, seeds 0–4:

| Set | sine | random | step | objective |
|---|---|---|---|---|
| **kp 0.3, ki 8, q 2** (chosen) | 0.199 | 0.199 | 2.842 | 1.080 |
| same, `r_gate` 16 | 0.199 | 0.199 | 2.840 | 1.080 |
| same, `r_gate` 20 | 0.199 | 0.199 | 2.840 | 1.080 |
| kp 0.2, `r_gate` 16 | 0.197 | 0.198 | 2.846 | 1.081 |
| kp 0.4, `r_gate` 16 | 0.201 | 0.204 | 2.832 | 1.079 |
| ki 12, `r_gate` 16 | 0.214 | 0.210 | 2.839 | 1.088 |

The differences among the top sets are below 0.003°, so `r_gate` and `kp`
stay where the spec put them or in the middle of the flat region. `ki` = 12
loses on 5 seeds what it gained on 2.

The step term of the objective has a floor that no parameter moves (§5.2).

## 5. Tracking (R8.2, R8.3)

Lockstep, in-process, one 30 s episode per seed, A at its defaults and
`centroid` at its defaults, code `ce1bda2`, seeds 0–9:
`runs/eval_20261101T220436Z_r82_classical_ce1bda2_b` and
`runs/eval_20261101T220725Z_r82_centroid_ce1bda2`. Seeds 0–4 were used for
tuning; 5–9 are held out (R8.1).

`rms_deg` and `max_deg` are over all post-warm-up periods (sim R12.2).
"Worst" is the largest value over the seeds, or the smallest for in-FOV and
success.

### 5.1 R8.2 tables

**Seeds 0–4:**

| Scenario | Controller | `rms_deg` mean | `rms_deg` worst | `max_deg` worst | in-FOV min | success min | losses / unrecovered | events/period |
|---|---|---|---|---|---|---|---|---|
| static | centroid | 0.000 | 0.000 | 0.000 | 1.0 | 1.0 | 0 / 0 | 77 |
| static | **A** | 0.000 | 0.000 | **0.000** | 1.0 | 1.0 | 0 / 0 | 77 |
| sine | centroid | 2.674 | 2.732 | 5.927 | 1.0 | 1.0 | 0 / 0 | 260 |
| sine | **A** | **0.199** | 0.268 | 0.935 | 1.0 | 1.0 | 0 / 0 | 161 |
| step | centroid | 4.255 | 5.435 | 17.159 | 1.0 | 1.0 | 0 / 0 | 134 |
| step | **A** | **2.842** | 3.377 | 18.860 | 1.0 | 1.0 | 0 / 0 | 180 |
| random | centroid | 2.493 | 2.579 | 5.484 | 1.0 | 1.0 | 0 / 0 | 228 |
| random | **A** | **0.199** | 0.268 | 0.631 | 1.0 | 1.0 | 0 / 0 | 162 |

**Seeds 5–9 (held out):**

| Scenario | Controller | `rms_deg` mean | `rms_deg` worst | `max_deg` worst | in-FOV min | success min | losses / unrecovered | events/period |
|---|---|---|---|---|---|---|---|---|
| static | centroid | 0.000 | 0.000 | 0.000 | 1.0 | 1.0 | 0 / 0 | 77 |
| static | **A** | 0.000 | 0.000 | **0.000** | 1.0 | 1.0 | 0 / 0 | 77 |
| sine | centroid | 2.643 | 2.851 | 5.993 | 1.0 | 1.0 | 0 / 0 | 261 |
| sine | **A** | **0.209** | 0.282 | 0.744 | 1.0 | 1.0 | 0 / 0 | 177 |
| step | centroid | 4.341 | 5.123 | 18.602 | 1.0 | 1.0 | 0 / 0 | 152 |
| step | **A** | **2.924** | 4.414 | 19.295 | 1.0 | 1.0 | 0 / 0 | 198 |
| random | centroid | 2.746 | 2.976 | 7.305 | 1.0 | 1.0 | 0 / 0 | 219 |
| random | **A** | **0.209** | 0.287 | 0.876 | 1.0 | 1.0 | 0 / 0 | 179 |

**R8.2 is met on both seed sets:**

- A's mean `rms_deg` is below `centroid`'s on sine, random and step;
- in-FOV is 1.0 for every seed on static, sine and random;
- step succeeds for every seed, with no unrecovered losses;
- static `max_deg` is 0.000°. Shot noise never reaches `n_acq`, so A stays in
  ACQUIRE and holds the initial setpoint.

**R8.3 (goal ≤ 1° on sine): met**, 0.199° and 0.209° mean, 0.282° worst.

**Held out, nothing collapses.** On seeds 5–9, A is 92 % below `centroid` on
sine and random and 33 % below on step, as on seeds 0–4. A's step worst grows
from 3.38° to 4.41°. That is seed 9, whose target sits invisible at 16° for
the first 3 s (§5.2).

**The review fixes** change 2 of the 80 nominal runs, both on step, compared
in every non-timing column with the runs on `a5d3a58` (T4's and the
review's):

- **Seed 3**, a 5.6° jump at 21 s (k = 2099):
  - Under both rules A coasts for 2 periods (k = 2100–2101), because the
    candidate block lies 21 px from the gate seed, inside `r_gate`.
  - At k = 2102 the gate window has walked onto the new disc and gives a
    measurement. The old rule re-initialised there anyway; the revised R4.5
    keeps the track and updates it (the S1 case).
  - v1 `rms_deg` 2.334° → 2.335°.
- **Seed 7**, a 4.5° jump at 24 s (k = 2399):
  - The old rule re-initialised at k = 2400.
  - Under the revised R4.5, the candidate's mean-shift lands 20–22 px from
    the empty gate window's centre, inside `r_gate`. So A coasts for 3
    periods until the gate reaches the disc at k = 2403.
  - v1 `rms_deg` 3.466° → 3.469°.

The jump check never fires on sine or random, under either rule.

At the initial defaults (before tuning, `a5d3a58`, seeds 0–4) A had already
met R8.2: sine 0.297°, random 0.251°, step 2.858°
(`runs/eval_20261101T150112Z_initial_defaults`).

On sine seed 0, A is in TRACK for 92 % of periods and in COAST for 8 %. A
tracks well, so it receives about 160–180 events per period, against 260 for
`centroid`.

### 5.2 Step: the v1 score and the score from 3 s (S3, C4)

`track-step-v1` holds the target still from t = 0 until the first jump at
3 s. With a still camera it produces no events, so neither controller can see
it. The error stays at the initial offset for the 200 scored periods before
3 s. The v1 score stays as defined (sim R12.4); the score from t = 3 s on
(R8.1) is reported next to it. "From 3 s" starts with the row at exactly
3.00 s, the first after the jump.

| Seeds | Controller | v1 `rms_deg` mean / worst | from 3 s mean / worst | pre-3 s floor | floor's share of A's squared error |
|---|---|---|---|---|---|
| 0–4 | centroid | 4.255 / 5.435 | 3.420 / 5.100 | 2.19–3.20° | — |
| 0–4 | **A** | 2.842 / 3.377 | **1.169** / 1.339 | 2.19–3.20° | 76–90 % |
| 5–9 | centroid | 4.341 / 5.123 | 3.427 / 3.964 | 0.39–4.23° | — |
| 5–9 | **A** | 2.924 / 4.414 | **1.391** / 1.508 | 0.39–4.23° | 8–92 % |

The floor is the quadrature RMS contribution of the pre-3 s periods; it is
the same for both controllers. From 3 s on, A's step error is 2.5–3× lower
than `centroid`'s, against 1.5× in the v1 score.

**The step `max_deg` comes from the jumps, not the initial hold.** The
initial offsets are 8.4–12.2° on seeds 0–4 and 1.5–16.1° on seeds 5–9, while
the maxima are 12.2–19.3°. They occur at a jump, at t = 3.00–27.01 s, in the
period the target lands or the next. No command can respond that fast: a
command takes effect two periods later.

The error then is the distance from the camera to the new position.

- **First jump (3 s):** both cameras are still at the start pose, so both
  controllers get the same maximum. That is the case on seeds 1–3.
- **Later jumps:** A sits on the old position (error about 0.1° before each
  jump), so its maximum is close to the jump size. `centroid` is often still
  converging from the previous jump (up to 7.7° behind), which can put it
  nearer the new position.

So A's `max_deg` can exceed `centroid`'s despite a much lower RMS: 18.86°
against 17.16° worst on seeds 0–4, 19.30° against 18.60° on 5–9.

## 6. Robustness (R8.4)

The simulator's servo was changed and A's model left at its defaults. Same
evaluation, 4 scenarios × seeds 0–9, code `ce1bda2`. Directories:

- `runs/eval_20261101T221040Z_r84_plant_omega_n_20_ce1bda2`
- `runs/eval_20261101T221124Z_r84_plant_omega_n_30_ce1bda2`
- `runs/eval_20261101T221211Z_r84_plant_zeta_0_6_ce1bda2`

`rms_deg` mean / worst:

| Plant | Seeds | sine | random | step | in-FOV min (static, sine, random) | step success min |
|---|---|---|---|---|---|---|
| nominal (ω_n 25, ζ 0.8) | 0–4 | 0.199 / 0.268 | 0.199 / 0.268 | 2.842 / 3.377 | 1.0 | 1.0 |
| | 5–9 | 0.209 / 0.282 | 0.209 / 0.287 | 2.924 / 4.414 | 1.0 | 1.0 |
| ω_n = 20 | 0–4 | 0.268 / 0.399 | 0.275 / 0.396 | 3.002 / 3.489 | 1.0 | 1.0 |
| | 5–9 | 0.292 / 0.384 | 0.291 / 0.391 | 3.158 / 4.540 | 1.0 | 1.0 |
| ω_n = 30 | 0–4 | 0.200 / 0.248 | 0.195 / 0.237 | 2.817 / 3.354 | 1.0 | 1.0 |
| | 5–9 | 0.213 / 0.250 | 0.212 / 0.249 | 3.031 / 4.401 | 1.0 | 1.0 |
| ζ = 0.6 | 0–4 | 0.227 / 0.258 | 0.223 / 0.255 | 2.830 / 3.365 | 1.0 | 1.0 |
| | 5–9 | 0.254 / 0.290 | 0.251 / 0.305 | 2.912 / 4.411 | 1.0 | 1.0 |

- Sine and random keep in-FOV at 1.0 in every case, and no run lost the
  target or set `cmd_clamped`.
- A servo slower than modelled (ω_n = 20) costs the most: +0.07–0.08° on
  sine.
- **Changes from T4** (seeds 0–4, against T4's runs on `a5d3a58`): 2 of 60
  runs, both on step, from the revised jump check. ω_n = 20 seed 2 moved the
  step mean / worst from 3.000 / 3.481 to 3.002 / 3.489; ζ = 0.6 seed 4
  moved the mean from 2.829 to 2.830.

## 7. Timing on the Mac (R7.1)

Three 60 s realtime `track-sine-v1` runs, 1 Nov 2026, 22:18–22:21 UTC.

- **Setup:** `jn-sim ctl --controller classical` and `jn-sim run … --controller
  tcp://127.0.0.1:5555 --mode realtime --duration 60`, as background
  processes.
- **Code:** `ce1bda2`, `git_dirty` false on both sides.
- **Conditions:** the Mac was on battery, with background software running
  (antivirus, browser, IDE), and a load average of 6.6 at the start of the
  first run. Nothing else of mine was running.

Directories: `runs/rt_classical_ce1bda2/`.

| Run (UTC) | `ctl_us` p50 / p99 / max | periods > 1 ms | misses | `rms_deg` / `max_deg` | in-FOV | lateness p99 / max | rate |
|---|---|---|---|---|---|---|---|
| 22:18:09 | 153 / **424** / 4179 µs | 15 | 4 | 0.177 / 0.544 | 1.0 | 0.61 / 12.8 ms | 99.993 Hz |
| 22:19:15 | 149 / **287** / 4587 µs | 11 | 0 | 0.182 / 0.474 | 1.0 | 0.028 / 16.1 ms | 99.996 Hz |
| 22:20:22 | 148 / **238** / 1733 µs | 4 | 1 | 0.184 / 0.517 | 1.0 | 0.027 / 5.0 ms | 99.994 Hz |

**R7.1 (Mac p99 ≤ 0.5 ms): met** in all three runs, 238–424 µs. The first
run is within 15 % of the bound.

- **`ctl_us` maxima** were 1.7–4.6 ms; 30 of 18,000 periods took over 1 ms.
  Their cause is **unattributed**. Host scheduling is a hypothesis:
  - the event counts in those periods are ordinary: median 178, max 437,
    against a median of 150 and a max of 553 over all periods;
  - hot replays of recorded OBS show wall-time outliers too (review §6:
    maxima 0.74–13.3 ms, with no GC collection inside the loop).

  This is consistent with host interference but doesn't prove it. The Mac
  maxima already exceed the Jetson's 3 ms bound, so R7.1's max criterion is
  the open risk for T5.
- **Misses**: 5 in 18,000 periods (0.03 %), also unattributed.
  - 3 of them (first run, k = 318, 319 and 1293) come with simulator send
    lateness of 2.2–12.8 ms at or right after the miss. That is consistent
    with a simulator-side stall.
  - 2 (first run k = 3894, third run k = 2384) have at most 1.8 ms of
    lateness around them.
  - The link discards late replies, so the controller's time for a missed
    period is unknown. T5's diagnostic wrapper (spec T5) records it.
- **Lockstep** (in-process, one run at a time): the per-scenario mean of
  `ctl_us` p99 is 106–147 µs on sine, step and random. Realtime is slower:
  the CPU idles between periods.
- **Earlier runs**, 1 Nov 15:20–15:23, code `1b546cb` with the tuned defaults
  uncommitted (`git_dirty` true): p99 335 and 279 µs, max 1925 and 3035 µs, 6
  and 5 misses. Superseded by the runs above.

## 8. Jetson (T5)

Four 60 s realtime `track-sine-v1` runs, 2 Nov 2026, 09:40–10:06 UTC.
Data, scripts and analysis: `traces/t5_20261102/`.

- **Setup:** `jn-sim ctl --controller classical --once` on the Jetson,
  pinned with `taskset -c 2`; the simulator on the Mac over the USB link. A
  10 Hz log of both CPU clusters' and the GPU's frequency ran on core 5.
- **Board:** cold boot, quiet (SETUP_NOTES §8.1, §8.3): 25 W mode applied
  (nvpmodel `Result=success`, masks 240/2), clock synced, the six maintenance
  timers stopped, radio off, `multi-user.target`. tj 46.5–47.6 °C.
- **Code:** `0c397e1` on both sides, `git_dirty` false.
- **Runs:** R1–R3 with the plain runner. D1 with a diagnostic wrapper
  (`steplog_ctl.py`) that times every `step()` on the board's clock,
  including steps whose CMD arrives late, and logs context switches, page
  faults and GC collections.

| Run | `ctl_us` p50 / p99 / max | > 1 ms | misses | link p99 | `rms_deg` / `max_deg` | in-FOV | events/period |
|---|---|---|---|---|---|---|---|
| R1 | 465 / **549** / **2301** µs | 2 | 0 | 1.63 ms | 0.182 / 0.474 | 1.0 | 158 |
| R2 | 476 / **568** / **2284** µs | 2 | 0 | 1.70 ms | 0.182 / 0.474 | 1.0 | 158 |
| R3 | 473 / **569** / **1046** µs | 1 | 1 | 1.42 ms | 0.184 / 0.805 | 1.0 | 159 |
| D1 (diagnostic) | 499 / 600 / 2721 µs | 3 | 1 | 1.30 ms | 0.182 / 0.570 | 1.0 | 157 |

**R7.1 (Jetson p99 ≤ 1.5 ms, max ≤ 3 ms): met** in R1–R3. Pooled, 17,999
steps: p50 471, p99 564, p99.9 617, max 2301 µs, none over 3 ms. D1's
`ctl_us` includes the wrapper's own cost (p50 23 µs).

- **The slow steps are garbage collection.** In D1, the slowest step
  (2686 µs on the board) overlaps the run's one generation-1 collection
  (2.12 ms), and the second slowest (1077 µs) a generation-0 one. Neither
  had a context switch or a page fault; only 1 of 6000 steps had a context
  switch at all. The other 8 collections took 0.15–0.53 ms. So on the quiet
  board the tail is the controller's own Python allocations, not host
  scheduling. The Mac's tail (§7) stays unattributed.
- **Margin on the max is about 0.7 ms.** A generation-2 collection would be
  longer, but follows only after 10 generation-1 collections, about one per
  60 s here. In T6 every block is a fresh 60 s process, so it shouldn't
  occur in a block. If it does, `gc.freeze()` after `reset`, or a collection
  between episodes, is the cheap fix (not applied).
- **Misses are on the Mac side.** D1's miss at k = 4513 took 527 µs on the
  board, an ordinary step; the next period's send lateness was 5.8 ms and its
  `sim_us` 9.1 ms, a simulator stall. R3's miss (k = 4168) had normal
  `ctl_us` around it and 0.5 ms lateness after it; its board time wasn't
  logged. 2 misses in 24,000 periods (0.008 %).
- **The pinned core idles at the lowest frequency.** `policy0` (cores 0–3)
  read 729.6 MHz in 99.7 % of samples; schedutil doesn't ramp for a step of
  0.5 ms every 10 ms. A's energy in T6 is therefore measured at 729.6 MHz.
- **Jetson against Mac:** p50 about 3.1× slower (471 against 150 µs), p99
  about 1.6× (564 against 238–424 µs). The review's estimate from
  `centroid`'s ratio was p99 0.70–1.17 ms.
- **R7.2:** a 0.5 ms step leaves the energy analysis's baseline window
  ([5.5, 8.5) ms after the marker) untouched.
- **R8.5:** realtime tracking on the Jetson matches the Mac: `rms_deg`
  0.182–0.184° against 0.177–0.184° on the Mac (§7), in-FOV 1.0, no losses.

## 9. Energy per decision (T6, T6b)

Measured on the board's 19 V input with the Stage 1 meter (INA228 read by a
Pico, per-decision marker on header pin 8), 2 Nov 2026. Two sessions:

- **T6** (`traces/t6_20261102/`): 20 rounds of `hold`/A, idle blocks only at
  the ends, with 10 Hz loggers running (INA3221 sampler, CPU frequency log).
- **T6b** (`traces/t6b_20261102/`), the headline: 12 rounds of idle, `hold`
  and A, the order cycling through all six permutations, **no loggers during
  the captures**, design and analysis fixed in advance (`raw/plan.txt`). All
  12 rounds passed the integrity check; nothing was excluded.

Both: `track-sine-v1`, realtime, 60 s blocks, a fresh controller process per
block pinned to core 2, code `0c397e1`, 25 W mode at default DVFS on the quiet
board. The pinned core ran at 729.6 MHz (99.5–100 % of samples in T6).

**Method.** E_dyn(A) is A's energy per decision above `hold`'s, paired within
each round. Method (b), the primary: INA228 samples aligned on each
decision's marker edge, the excess over [−1, 4.5) ms above the same period's
quiet part [5.5, 8.5) ms, per block; then D = X_A − X_H per round, mean and t
CI over rounds. Method (a) uses block means instead. Harness = `hold` above
idle; E_tot = block mean power / 100 Hz.

**T6b results** (95 % CI, t over 12 rounds):

| Quantity | Value | 95 % CI |
|---|---|---|
| **E_dyn(A), method (b)** | **+207 µJ per decision** | [+195, +219], ±5.9 % |
| E_dyn(A), method (a) | +211 µJ | [+162, +259] |
| X_A / X_H (excess above the period's quiet part) | 336 / 130 µJ | [327, 346] / [123, 137] |
| Harness (`hold` above idle) | +208 µJ | [+179, +237] |
| **E_tot(A)** | **63.63 mJ per decision** | [63.59, 63.66] |
| … idle floor + harness + A | 63.21 + 0.21 + 0.21 mJ | |
| Events per decision | `hold` 404, A 158 | |
| A's `ctl_us` on the board | p50 489, p99 581 µs | |
| A's tracking in the energy blocks | `rms_deg` 0.181°, in-FOV 1.0, 0 losses | |

- **A's algorithm is 0.33 % of the board's energy per decision;** the idle
  floor is 99.3 %. Its 207 µJ over `hold` is 20.7 mW at 100 Hz, or about
  440 mW while its extra 0.47 ms of compute runs. That is about 1.8× the
  249 mW of a busy loop on one core (Stage 1 Part 5). Why is not verified;
  memory traffic from numpy is the leading guess.
- **The harness costs as much as A's algorithm.** It covers the link, the
  decoding of 404 events per decision, `hold`'s step and the marker write.
- **The ±5 % target was just missed:** ±5.9 % with 12 rounds; 16 would have
  reached it. The precision is set in µJ, not percent: round-to-round sd of
  D is 19 µJ, so 12 rounds give about ±12 µJ.

**T6 and the loggers.** T6's planned analysis gave +217 µJ [+184, +250],
±15 %, because each 10 Hz logger read costs about 0.4 mJ and lands at a
random phase relative to the decisions. Excluding them after the fact gave
+200 µJ [+193, +207]. T6b, without loggers and fixed in advance, gives
+207 µJ [+195, +219], and the sd of D fell from 67 to 19 µJ, as T6b's
pre-registered test of that explanation required. Every estimate across
both sessions, both boots, both methods and all windows lies within
197–224 µJ.

**What E_dyn includes and what it doesn't:**
- It is A's step **plus every closed-loop difference from `hold`**. A tracks,
  so it receives 158 events per decision against `hold`'s 404 and pays less
  to receive and decode them; E_dyn understates A's own compute by that
  amount (not measured; open-loop replay, spec T9, would remove it).
- X levels moved by about 20 µJ between sessions and boots while D stayed
  put, so only within-round differences are compared.
- The absolute scale rests on the INA228 and its 15 mΩ, 0.1 % shunt at their
  datasheet accuracy. It wasn't checked against a reference load. The
  chip's own ENERGY and CHARGE accumulators agree with the summed samples to
  0.002 % and 0.01 % (Stage 1, 29–30 Oct), which checks the sampling and
  timestamps, not the gain.
- `VDD_IN` (the module's own INA3221) can't resolve differences this small:
  in T6 it read A − H larger than the input itself.
- The energy blocks used the Jetson-side step timing of §8; under the
  harness, two of 72,000 steps took 4.06 ms (R7.1's 3 ms bound), without a
  miss.

## 10. Known limits

- **Bright target.** Acquisition counts ON events only (R4.2). This holds
  for the stage-1 scene (I_t > I_bg); a dark target would need OFF.
- **No proprioception.** The pose comes from a model of a servo A can't
  observe (R3). §6 shows how much mismatch it tolerates. The PID's integral
  corrects slow model error but also winds up during each jump transient,
  bounded by `i_max_deg`.
- **Missed CMDs.** A CMD that misses its deadline isn't applied (sim R7.3),
  but the model assumes it was (R3.4). That was 0.03–0.09 % of decisions on
  the Mac and 0.008 % with the controller on the Jetson (§8).
- **Event starvation.** Good tracking means few events. A coasts in about 8 %
  of sine periods, and its events per period are about 60–80 % of
  `centroid`'s on sine and random, which matters for the energy comparison
  (R9.6).
- **Jumps of about 4–6° can coast for a few periods.** R4.5 needs the
  candidate block more than `r_gate` (24 px, about 5°) from the gate seed,
  and its re-acquired centre more than `r_gate` from the gate window's
  centre. A jump that misses either condition and also lies beyond the gate
  window's reach gets neither a jump nor a gated measurement. A then coasts
  until the gate reaches the disc. In the 80 nominal runs this happened at
  two jumps (step seeds 3 and 7, §5.1), for 2 and 3 periods. Seed 3's coast
  happened under the old rule too.
- **Re-acquisition bias after short jumps.** When the old and new positions
  are within about r_win + 7 px, the old disc's OFF events fall in the first
  mean-shift window. They bias the initial measurement by about 1 px, and the
  filter removes it within a few periods.
- **Stage-1 scene, Python.** One disc on a uniform background. The
  implementation is numpy on CPython, so `ctl_us` and the energy measure that
  implementation, not the algorithm's floor.

## 11. Implementation choices

Where the spec leaves room. The gate window, the jump check, the
behind-camera case, the PID time base and the float32 clamp are now
specified (R4.4, R4.5, R6.2, R6.3); the code follows that wording.

- **Block sums** (R4.1) slide over the cell grid (one 3 × 3 block per cell,
  zero beyond the border), so a target straddling cells is always inside one
  block.
- **Acquisition** (ACQUIRE, R4.5 and the behind-camera case) needs a
  mean-shift result with n ≥ `n_meas`. The gate distance doesn't apply.
- **An empty gate window** has its centre at the seed, so R4.5's distance from
  the gate window's centre is then the distance from the seed.
- **Anti-windup.** If the setpoint with the updated integral would be
  clamped, the update is undone for that axis. |ki ∫e dt| is capped at
  `i_max_deg`.
- **Filter time.** The filter state stays at the last measurement time. The
  gate seed, COAST and the feedforward extrapolate from it, which equals
  predict-only steps for a constant-velocity model.
- **Diagnostics.** `n_jumps` counts R4.5 re-acquisitions only, not those
  from the behind-camera case; `n_inits` counts every (re-)initialisation.
  Neither is a fault site.
