# jetson_neuro

Event-vision closed-loop control on a Jetson Orin Nano, with **energy per
control decision** measured at the board's power input.

A simulator on a laptop renders a pan/tilt camera tracking a moving target and
turns it into a stream of event-camera events. A controller on the Jetson
receives each 10 ms batch of events over USB-C and returns a pan/tilt command.
An INA228 power monitor on the Jetson's 19 V input, read by a Raspberry Pi
Pico, timestamps every conversion against a marker byte the controller sends at
the start of each decision, so energy can be attributed to individual
decisions.

The goal the project works toward:

> On one Jetson Orin Nano, classical, conventional-network and spiking-network
> controllers run in the same closed event-vision loop. Each is characterised
> for *energy per control decision*, latency and tracking quality across event
> load and clock frequency, with energy measured on the board's power rails
> inside a declared measurement boundary. Under software-injected compute
> faults, each is also characterised for how its tracking degrades and what
> detecting the faults costs in energy.

**Status (2 Nov 2026):** the simulator, the measurement setup and the classical
controller (family A) are built and measured. The network-based controllers
(B–D), the clock points and the fault study are planned
(`docs/exploration.md` §7).

---

## Results: controller A

Controller A is an event-cluster tracker with a Kalman filter and PID, in
Python and numpy (`src/jn_sim/classical.py`; design in `docs/spec_ctl_a.md`,
results in `docs/ctl_a.md`).

**Tracking** (simulator, lockstep, seeds 0–9, of which 5–9 were held out from
tuning; `docs/ctl_a.md` §5): RMS error 0.20–0.21° on the sine and random
trajectories, against 2.5–2.7° for the `centroid` reference controller, with the
target in view 100 % of the time. On steps, 1.2–1.4° from the first jump on,
against 3.4°. The step scenario's first 2 s are unobservable for any
controller, so its whole-episode score is 2.8–2.9° against 4.3°.

**Timing on the Jetson** (`docs/ctl_a.md` §8, `traces/t5_20261102/`): 0.47 ms
per decision at p50 and 0.56 ms at p99, against a 5 ms deadline. The rare slow
steps are Python garbage collections.

**Energy per decision** at the board's 19 V input, 100 Hz control, 25 W mode at
default DVFS (`docs/ctl_a.md` §9; pre-registered session
`traces/t6b_20261102/`, 12 rounds; 95 % CIs):

| | Energy per decision |
|---|---|
| Idle board | 63.21 mJ [63.18, 63.23] |
| + harness (link, decode, no-op controller) | +0.21 mJ [0.18, 0.24] |
| + controller A's algorithm, E_dyn(A) | **+207 µJ [195, 219]**, ±5.9 % |
| **Total, E_tot(A)** | **63.63 mJ [63.59, 63.66]** |

So the algorithm is 0.33 % of what the board spends per decision. A first
session with 10 Hz loggers running gave +217 µJ ±15 % (`traces/t6_20261102/`);
the loggers' own reads were the noise.

**Stated limits:**
- one scene stage (a single disc on a uniform background), one trajectory for
  energy (`track-sine-v1`), one clock point (default DVFS; the controller's
  core ran at 729.6 MHz);
- closed loop: A receives 158 events per decision against the no-op's 404, so
  E_dyn(A) includes a smaller decode cost and understates A's own compute by
  that amount (open-loop replay would remove it; not done);
- A knows the camera's pose only from a model of the servo it commands, not
  from a sensor (`docs/spec_ctl_a.md` R3);
- Python and numpy on CPython, not an optimised implementation;
- the meter's absolute scale rests on the INA228's and shunt's datasheet
  accuracy, not checked against a reference load;
- `VDD_IN` (the module's on-board sensor) can't resolve differences of this
  size.

### Earlier milestones

| Part | Result |
|---|---|
| Simulator and closed loop | runs in realtime at 100 Hz on a Mac, with a live viewer (`docs/sim.md`, `docs/img/viewer_t14.png`); closed loop with the controller on the Jetson: 0 misses in a 60 s run (26 Oct) |
| On-board power rails (`VDD_IN`) | 40 mW steps and about 0.6 s smoothing: too coarse for single decisions (`traces/board_20261026/`) |
| Board-level meter | INA228 on the 19 V input at 926 samples/s, 0 missed conversions, per-decision marker on header pin 8 (UART1 TX). 0.1 ms of one busy core reads +28 µJ [+23, +34] (`docs/stage1_wiring.md`, `traces/stage1_*/`) |

---

## Quickstart: the simulator

Python 3.12 and numpy; matplotlib for the live viewer. No hardware needed.

```sh
# macOS (Homebrew python@3.12)
sh scripts/setup_sim_env.sh
# other systems: the same steps by hand
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps -e .

MPLBACKEND=Agg .venv/bin/python -m pytest -q
.venv/bin/jn-sim run --scenario track-sine-v1 --controller inproc:classical --mode lockstep --duration 5
.venv/bin/python scripts/eval_controllers.py classical --seeds 0 --scenarios track-sine-v1
```

The setup script supports macOS only; the manual steps are untested on Linux.
`docs/sim.md` is the operator's guide (realtime runs, the viewer, running the
controller on another machine). The controller server `jn-sim ctl` has no
authentication; it binds to 127.0.0.1 unless told otherwise.

**Reproducing the energy analysis from the published data** (no hardware):

```sh
cd traces/t6b_20261102
for k in K1 K2 K3; do gzip -dc raw/$k.bin.gz > raw/$k.bin; done
MPLBACKEND=Agg ../../.venv/bin/python scripts/t6_analyze.py raw/rerun K1 K2 K3
# raw/rerun.json equals the published raw/result.json
```

**Rerunning a measurement on hardware** needs the rig in
`docs/stage1_wiring.md` and the board configuration in `docs/setup.md`. The
measurement scripts are the per-session copies in `traces/<session>/scripts/`,
with this rig's host alias, device IDs and temp paths built in; a single
configurable measurement tool doesn't exist yet.

---

## Layout

```
README.md             this file
LICENSE               MIT
docs/
  exploration.md      simulation, staged measurement, algorithms, literature, plan
  spec_sim.md         simulator spec: requirements, protocol, tasks
  sim.md              simulator operator's guide
  spec_ctl_a.md       controller A spec: requirements, energy protocol, tasks
  ctl_a.md            controller A: running, tuning, tracking, timing, energy
  stage1_wiring.md    wiring of the INA228 and Pico power meter
  setup.md            board and session configuration used for the measurements
  img/                figures referenced from the docs
scripts/
  setup_sim_env.sh    builds the simulator venv on macOS
  eval_controllers.py tracking evaluation over scenarios × seeds
scenarios/            named, versioned run configurations (track-*-v1)
src/jn_sim/           simulator, controllers, wire protocol, CLI (`jn-sim`)
tests/                pytest suite; run with MPLBACKEND=Agg
traces/               raw data, scripts and reports per session (see traces/README.md)
```

---

## Hardware

```
Jetson Orin Nano Super developer kit, 8 GB · 25 W power mode
L4T R39.2.1 / JetPack 7.2.1 · CUDA 13.2 · TensorRT 10.16
Adafruit INA228 (product 5832, 15 mΩ shunt) on the 19 V input
Raspberry Pi Pico (RP2040), MicroPython 1.29.0, as the logger
```

Board configuration and the per-session checklist: `docs/setup.md`. Wiring:
`docs/stage1_wiring.md`.

---

## Provenance

The code was developed in a private repository, and the traces and docs cite
its commit SHAs (`0c397e1`, `cbcae21`, …). Those commits aren't in this repo's
history. The link is the `src/` tree:

- controller A's final evaluation (`docs/ctl_a.md` §5–§7, code `ce1bda2`)
  and the board sessions T5, T6 and T6b (code `0c397e1`) ran `src/` tree
  `8a190b7ca99ad4fedcde25b8c0194ba7767dd413`, which is this repo's `src/`.
  Check it with `git rev-parse HEAD:src`; `traces/t6b_20261102/raw/board_src_md5.txt`
  also lists the board's files by md5;
- controller A's tuning grid (`docs/ctl_a.md` §4) ran an earlier
  `classical.py`, before the review fixes;
- sessions up to 31 Oct ran tree `d096a60`: the same code without controller A
  (`classical.py` absent, and the 8-line `classical` branch in `testctl.py`).

---

## Notes on the data and the docs

- **How the work was done.** The sessions were planned, run and reported with
  AI coding agents, under the author's direction; the author did every
  physical step and approved the board's `sudo` commands. Reports call these
  roles "the planner", "the bench agent" and "the user". Findings are tagged
  **V** (checked and seen), **V-user** (observed or reported by the author)
  and **NV** (not verified).
- **Models used in development:** Claude Opus 5.5 and Claude Opus 4.8
  (Anthropic), and GPT-6 Astra (OpenAI), through the Kiro IDE.
- **References to private notes.** Docs and reports cite `SETUP_NOTES.md`
  (the private rig notebook: board setup, troubleshooting, the session
  checklist) and `hardware_demo_plan.md` (the private project plan). Neither is
  published; `docs/setup.md` summarises the parts the measurements depend on.
  Session briefs ("the brief", bare `§N` in reports) and one internal code
  review are not published either.
- **`runs/…` paths.** Reports were written in a gitignored `runs/<session>/`
  folder and copied to `traces/<session>/`; read `runs/<session>` as
  `traces/<session>`. The evaluation and tuning runs cited in `docs/ctl_a.md`
  are summarised in `traces/ctl_a_eval_20261101/`.
- **Redactions and removals** are listed in `traces/README.md`.

---

## Licence

MIT, see `LICENSE`. Dependencies (numpy, matplotlib, pytest and their
requirements, pinned in `requirements.lock`) are under permissive licences and
not vendored.
