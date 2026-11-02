# INA228 bench test, 28 Oct 2026 (19 V supply unplugged)

Adafruit INA228 (5832) on the Pico's I²C0 (GP4/GP5), ALRT on GP17. No current
through the shunt. Work ran 19:09–19:53 UTC. Raw outputs are in `raw/`, the
scripts in `scripts/` (copies of `/private/tmp/jn_ina228/*.py`).

Tags: **V** = I ran it and saw the result. **V-user** = you observed or told me.
**NV** = not verified.

## 0. Setup

- **Supply.** You confirmed the 19 V supply was unplugged and nothing was in either DC adapter (V-user). I asked for no power-side change.
- **Pico.** USB `2e8a:0005`, serial `<pico-serial>`, `/dev/cu.usbmodem1101` (V).
- **Jetson.** No NVIDIA device was on USB at the start or the end (V).
- **Ports opened.** Only the Pico's port. Every call used `mpremote connect id:<pico-serial>` or `picolink.find_pico()` (V).
- **Wiring.** I didn't see it. I²C answers on GP4/GP5 and ALRT on GP17 follows the INA228's CNVR setting, so those connections work (V for function; physical pins NV).
- **Pins.** GP16 was never configured (V).
- **Datasheet.** TI INA228, literature number **SLYS021A** (Jan 2021, revised May 2022), from ti.com (V).
- **Calibration used.** CURRENT_LSB = 10.9 A / 2¹⁹ = 20.790 µA. SHUNT_CAL = 4088 (the formula gives exactly 4087.5; rounded up). For ADCRANGE 1, 16352.

## 1. IDs and temperature (step 2)

| | Result | |
|---|---|---|
| Scan at 100 kHz | `[64]` (0x40), 19 ms | V |
| MANUFACTURER_ID | `0x5449` ("TI") | V |
| DEVICE_ID | `0x2281`: DIEID `0x228`, REV_ID 1 | V |
| Power-on registers | all equal the datasheet reset values, except DIAG_ALRT `0x0003` instead of `0x0001`: CNVRF is set because the default mode converts continuously | V |
| DIETEMP | 25.41 °C (10 reads, 25.39–25.43) | V |
| ALRT idle (GP17, internal pull-up) | high | V |
| Quick look, default config | VSHUNT −5 to −2 steps; VBUS 18–37 steps (3.5–7.2 mV) | V |

## 2. I²C reliability (step 3)

10,000 reads of MANUFACTURER_ID at each frequency.

| Requested | Actual (MicroPython) | Exceptions | Wrong values | µs per read | |
|---|---|---|---|---|---|
| 100 kHz | 100 000 | 0 | 0 | 546 | V |
| 400 kHz | 399 361 | 0 | 0 | 181 | V |
| 1 MHz | 1 000 000 | 0 | 0 | 109 | V |

- **Highest zero-error frequency:** 1 MHz (V).
- **1 MHz is outside the INA228's spec.** Fast mode stops at 400 kHz, and high-speed mode (≤ 2.94 MHz) needs a master code first (datasheet §7.5.1, V).
- **The RP2040 can't send that code.** Its I²C block has no high-speed mode, per a third-party PIO-I²C project ([pio-i2c-hs](https://github.com/tmcqueen-materials/pio-i2c-hs)). NV against the RP2040 datasheet.
- **So 400 kHz is the highest in-spec frequency** that passed with zero errors.

## 3. Read speed (step 4)

10,000 reads per cell with `readfrom_mem_into` into a preallocated buffer, zero errors. Reads per second, with µs per read in brackets:

| Register | 100 kHz | 400 kHz | 1 MHz |
|---|---|---|---|
| VSHUNT (3 B) | 1606 (622.8) | **5343 (187.1)** | 9917 (100.8) |
| CURRENT (3 B) | 1606 (622.8) | 5343 (187.1) | 9917 (100.8) |
| ENERGY (5 B) | 1227 (815.0) | 4167 (240.0) | 8016 (124.7) |
| DIAG_ALRT (2 B) | 1899 (526.6) | 6222 (160.7) | 11250 (88.9) |
| VSHUNT, pointer kept (`readfrom_into`) | 2451 (407.9) | 8291 (120.6) | 15939 (62.7) |
| VSHUNT + VBUS, two reads | 803 pairs (1244.9) | 2686 pairs (372.3) | 5048 pairs (198.1) |

All V (`raw/04_speed.txt`).

- **Overhead.** About 45–53 µs per transaction beyond the bus bits, or 25 µs when the register pointer isn't rewritten. That includes the 4.2 µs loop cost.
- **No auto-increment.** A 6-byte read from 0x04 returns VSHUNT and then `ff ff ff`, so VSHUNT and VBUS need two transactions (V).
- **The ~10 kS/s in exploration.md §4 is out of reach at 400 kHz.** One bare VSHUNT read already tops out at 5.3 kS/s. With VBUS and re-arming ALRT, it's about 0.9–1.35 kS/s (§6).

## 4. Zero-current noise (step 5)

**Settings.** ADCRANGE 0 except the last row. MODE 0xF with VBUSCT = VTCT = 50 µs, so the shunt setting dominates the cycle.

**Pacing.** Each sample waits for CNVRF, so every value is a fresh conversion. 5000 samples per row, 3 discarded first.

**Units.** 1 step = 312.5 nV = 20.83 µA (ADCRANGE 0), or 78.125 nV = 5.21 µA (ADCRANGE 1).

| VSHCT | AVG | Range | Mean (steps) | sd (steps) | Mean (µA) | sd (µA) | sd (nV) | p-p (steps) | Datasheet noise-free p-p | |
|---|---|---|---|---|---|---|---|---|---|---|
| 50 µs | 1 | 0 | −1.88 | 25.70 | −39 | 535 | 8031 | 296 | 194 | V |
| 280 µs | 1 | 0 | −5.35 | 11.96 | −111 | 249 | 3739 | 88 | 74 | V |
| 1052 µs | 1 | 0 | −5.33 | 6.07 | −111 | 126 | 1896 | 42 | 45 | V |
| 280 µs | 16 | 0 | −5.26 | 3.05 | −110 | 64 | 953 | 25 | 18 | V |
| 280 µs | 64 | 0 | −5.29 | 1.54 | −110 | 32 | 481 | 12 | – | V |
| 280 µs | 1 | **1** | −20.78 | 49.01 | −108 | 255 | 3829 | 380 | 294 | V |

What the table shows:
- **The noise is white** (V). sd scales as 1/√(shunt integration time): 4× for AVG 16, 7.8× for AVG 64, 1.97× from 280 to 1052 µs. Lag-1 autocorrelation is within ±0.02.
- **In current terms it's about 4.1–4.3 µA·√s**, which is 80 µW·√s at 19 V (derived from V data).
- **ADCRANGE 1 doesn't help** (V). Its noise in µA is the same as range 0 (255 vs 249 µA), so the 4× finer step buys nothing at this noise level.
- **The offset is −111 µA, about −1.67 µV, at every setting with VSHCT ≥ 280 µs** (V). That's outside the datasheet's ±1 µV maximum.
  - Why isn't known (NV). The common mode floats today, since VIN± connect to nothing but the shunt. Thermal EMFs in the board or terminal block are another candidate.
  - At 19 V it would be −2.1 mW, if it stays the same with a real common mode (NV).
- **Datasheet comparison.** The measured p-p is somewhat above the datasheet's noise-free p-p. That's expected: 5000 samples reach further into the tails than a p-p figure (V for our numbers; how TI counts p-p is NV).
- **The INA228's clock runs about 0.026 % fast against the Pico's.** Paced sample spacing came out at 1151.7 / 6078.5 / 24313.7 µs against 1152 / 6080 / 24320 expected (V; matches §6).

## 5. VBUS with nothing connected (step 6)

1000 CNVRF-paced reads per setting:

| Setting | Mean | sd | Range | Zero readings | |
|---|---|---|---|---|---|
| Reset default, VBUSCT 1052 µs | 9.85 steps = 1.92 mV | 11.9 steps = 2.33 mV | 0–44 steps (0–8.6 mV) | 47.6 % | V |
| VBUSCT 50 µs | 22.0 steps = 4.30 mV | 45.1 steps = 8.80 mV | 0–303 steps (0–59 mV) | 74.4 % | V |

- **Readings clip at 0** (the register is "always positive"), so mean and sd are biased and aren't a noise figure (V).
- **At 50 µs the values are coarse and discrete:** 0, 3, 71, 80, 149, 157, 235, 303 steps (V).
- **The streams read similar values:** VBUSCT 540 µs gave mean 3.8 mV, max 14 mV; 150 µs gave mean 4.7 mV, max 29 mV (V).
- **Nothing implausible.** All of it is millivolts.
- **It doesn't reveal the VBUS jumper.** The VBUS pin has about 1 MΩ to ground inside the chip, so it reads near 0 V whether the jumper is open or closed (datasheet Z_VBUS; inference, NV).

## 6. Conversion ready on ALRT (step 7)

### 6.1 How the edges were captured

- **PIO program.** Adapted from `pio_edges.py`, with the same 3-cycles-per-count down-counter. It watches GP17 (input, internal pull-up) and timestamps both edges at 24 ns per count. The streaming version timestamps falling edges only, at 120 ns per count (integer divider 5).
- **Aligning with the CPU.** The CPU injects `in x, 32` into the state machine to tie PIO time to `ticks_us`, within ±17 µs.

### 6.2 What ALRT does and what clears it

| Test | Result | |
|---|---|---|
| CNVR on, transparent (ALATCH 0), no reads, 50 ms | ALRT falls once and stays low for the whole 50 ms | V (E1) |
| Same, latched (ALATCH 1) | same | V (E2) |
| Read VSHUNT, VBUS, CURRENT, DIETEMP, wait 5 ms | ALRT stays low | V (E3) |
| Then read DIAG_ALRT | ALRT goes high; it falls at the next conversion end | V (E3) |
| Reading DIAG_ALRT after every fall, latched, at 100 kHz, 400 kHz and 1 MHz | one clean fall per conversion; **0 glitches in any latched run** | V (E5, I1, I2, V1–V4, B1–B4, both streams) |
| Same in transparent mode at 400 kHz | spurious edges: 25 pulses under 1 µs in 513 falls (E4), 116 in 1000 (T1), plus falls off the conversion grid | V |
| Transparent at 100 kHz / 1 MHz | 0 / 1 glitch | V (E6, E7) |

- **What clears ALRT.** Only a read of DIAG_ALRT, in both modes (V). It stays asserted until then, so in practice transparent mode doesn't release ALRT by itself either.
  - The datasheet (§7.3.4) also clears CNVRF on a write to ADC_CONFIG (NV here). That write restarts conversions, so it's no use for re-arming.
- **Latency.** ALRT rises about 1.6 bit-times before the DIAG_ALRT transaction ends, near the second data byte's ACK.
  - Fitted from the 1 MHz, 400 kHz and 100 kHz runs: 33.7 / 38.6 / 48.8 µs between the rise and the call returning. That's p = 33 µs of software time, plus 1.6 bit-times. V, derived; ±17 µs alignment.
  - In MicroPython at 400 kHz, ALRT is back high **about 196 µs after `readfrom_mem_into` starts**. The call returns about 38 µs later.
- **Reaction time.** From the falling edge to the Python handler starting: 45–50 µs median, polling `sm.rx_fifo()` (V).
- **Transparent-mode glitches.** The cause is unknown (NV). They come at the moment ALRT is released.
  - ALRT has only the Pico's weak internal pull-up. Adafruit's pinout page lists 10 kΩ pull-ups for SDA and SCL but none for ALRT ([guide](https://learn.adafruit.com/adafruit-ina228-i2c-power-monitor/pinouts)). Schematic not checked, NV.

### 6.3 Intervals

**Settings.** The brief names only the shunt settings, so I set VBUSCT = VTCT = 50 µs:
- 280 µs, AVG 1 → expected 50 + 280 + 50 = **380 µs**;
- 1052 µs, AVG 4 → expected (50 + 1052 + 50) × 4 = **4608 µs**.

| Setting | Edges | Median interval | p1–p99 | sd (without steps) | vs expected | |
|---|---|---|---|---|---|---|
| 380 µs (I1, latched) | 1900/1900 | 379.896 µs | 379.872–379.920 | 15–16 ns (V1, V4) | −0.027 % | V |
| 4608 µs (I2, latched) | 599/599 | 4606.704 µs | 4606.632–4606.776 | – | −0.026 % | V |

- **The grid has a phase step.** Once every ~0.50 s, one conversion cycle is **+10.0 µs longer**:
  - in I2/V2 at 488, 990, 1488, 1990 and 2488 ms;
  - 120 steps in each 60 s stream.

  V, in every latched run longer than 0.5 s. That's +20 ppm on the average rate. The cause is internal to the INA228 (NV).
- **Apart from those steps, conversion ends are regular** to about the PIO resolution (±24 ns) (V).

### 6.4 Is every conversion caught?

| Handler on each fall | I²C | Cycle | Conversions seen / slots | |
|---|---|---|---|---|
| DIAG_ALRT only | 400 kHz | 380 µs | 1900 / 1900 | V |
| DIAG_ALRT only | 400 kHz | 4608 µs | 599 / 599 | V |
| VSHUNT + DIAG_ALRT | 400 kHz | 380 µs | **1000 / 1499**, every other one missed | V |
| same, `@micropython.native` | 400 kHz | 380 µs | 999 / 1392 | V |
| VSHUNT + DIAG_ALRT | 1 MHz (out of spec) | 380 µs | 1000 / 1000 | V |
| VSHUNT + DIAG_ALRT | 400 kHz | 4608 µs | 599 / 599 | V |
| VSHUNT + VBUS + DIAG_ALRT | 400 kHz | 560 µs (MODE B, 280/280) | 1500 / 2248 | V |
| VSHUNT + VBUS + DIAG_ALRT | 400 kHz | 740 µs (MODE F, 150/540/50) | 1500 / 1500, 133 µs margin | V |
| VSHUNT + VBUS + DIAG_ALRT | 400 kHz | 1080 µs (MODE B, 540/540) | 999 / 999, 496 µs margin | V |
| VSHUNT + VBUS + DIAG_ALRT | 400 kHz | 3156 µs (reset default) | 599 / 599 | V |

- **380 µs isn't sustainable at 400 kHz** (V). The VSHUNT + DIAG_ALRT handler finishes about 400 µs after the edge, longer than the 380 µs cycle.
- **4608 µs is.** At 400 kHz, VSHUNT + VBUS + DIAG_ALRT needs a cycle of ≥ 740 µs (V).
- **A late handler shows up as a missing edge.** The handler reads data first and DIAG_ALRT last, so an overrun leaves a 2T gap in the PIO timestamps instead of silently pairing data with the wrong edge.
- **Register update timing within a cycle (AVG 1): my test was inconclusive.** Its timing resolution was ±230 µs (NV).
  - The datasheet says that with AVG 1 each register updates at the end of its own conversion, and with AVG > 1 all update together.
  - So with AVG 1, a VSHUNT/VBUS pair read late may span two cycles. For a steady 19 V that hardly matters.

## 7. Accumulators (step 8)

**Settings.** MODE 0xF, 50/1052/50 µs, AVG 1 (the step-5 "1052 µs" setting), SHUNT_CAL 4088. One snapshot per second for 120 s.

| | Result | |
|---|---|---|
| 3 s after config | CHARGE −17 LSB, ENERGY 0 | V |
| Right after RSTACC | CHARGE −1, ENERGY 0 (a few ms of conversions) | V |
| RSTACC bit | **self-clears**: CONFIG reads `0x0000` right after; the datasheet doesn't say | V |
| CHARGE over 120 s | 0 → −659 LSB, monotonic, −5 or −6 LSB per second, fit residual 0.50 LSB | V |
| **Offset from CHARGE** | −5.491 LSB/s × 20.79 µC = **−114.2 µA** | V |
| Mean CURRENT register, same period | −112.9 µA (n = 21 368, about ±0.9 µA standard error) | V |
| Mean VSHUNT, same period | −112.5 µA (−5.40 steps) | V |
| Ratio CHARGE / CURRENT | 1.012, about 1.5σ, so consistent | V |
| ENERGY | 0 for all 120 s; POWER 0 (VBUS is mV only) | V |
| Flags | DIAG_ALRT always `0x0003` (CNVRF + MEMSTAT); no ENERGYOF, CHARGEOF or MATHOF | V |
| Second RSTACC at the end | CHARGE 0, ENERGY 0 | V |

- **ENERGY drift at zero current needs 19 V.** One prediction (NV): POWER is unsigned, so a −111 µA offset at 19 V would read as about +2.1 mW, which is 2.1 mJ/s or 7.6 J per hour into ENERGY with no load.

## 8. Streaming end to end (step 9)

**Path.**
- **Pico.** Code sent through the raw REPL (nothing stored). One 16-byte record per conversion: magic `0xA5`, FIFO level, seq u32, PIO count u32 at 120 ns, VSHUNT 3 B, VBUS 3 B. Written to `sys.stdout.buffer` in 128-byte blocks.
- **Mac.** `stream_host.py`, standard library only. It imports `picolink.py` from `traces/pico_20261028/scripts`.

| | Main run: 1080 µs (MODE B, 540/540, AVG 1) | Extra run: 740 µs (MODE F, 150/540/50), loop inside a function | |
|---|---|---|---|
| Duration (PIO clock) | 59.998 s | 59.998 s | V |
| Records | 55 570 | 81 101 | V |
| **Records per second** | **926.2** | **1351.7** | V |
| Sequence gaps | 0 | 0 | V |
| Bad framing | 0 | 0 | V |
| **Missed conversions** (PIO interval > 1.5 T) | **0** | **1** | V |
| FIFO backlog (> 1 pending when serviced) | 0 | 0 | V |
| Irregular intervals, apart from the +10 µs steps | 0 | 0 | V |
| Bytes per second | 14 818 | 21 626 | V |
| Pico handler busy time | 77.1 % → **about 23 % headroom** | 87.9 % → about 12 % | V |
| Longest handler / longest USB write | 1325 µs / 268 µs | 865 µs / 221 µs | V |
| VSHUNT | mean −108 µA, sd 178 µA | mean −105 µA, sd 178 µA | V |

- **Headroom.** "Busy" is the time from taking an edge to finishing the handler, including the blocking I²C reads. The remaining time is spent polling the FIFO, on one core. The second core is unused (V for the numbers; the split is my reading).
- **Heap.** It barely moved: 64 B and 480 B over the runs (V).
- **Link.** The USB link (0.65 MB/s, Pico bring-up) is used at 2–3 %.

## 9. INA228 facts that differ from the brief

Checked against SLYS021A (V for each, by reading the datasheet):

1. **Document number:** SLYS021A, not SBOSA20.
2. **CURRENT** is 20-bit two's complement in bits 23–4, like VSHUNT. So it's `(raw24 >> 4) × CURRENT_LSB`, not `raw × CURRENT_LSB`. POWER (24 bits, unsigned), ENERGY (40, unsigned) and CHARGE (40, two's complement) use the full register, as the brief says.
3. **I²C:** fast mode stops at 400 kHz. High-speed mode needs a master code, and Fast-mode Plus isn't listed. The device never stretches the clock.
4. **SHUNT_CAL** is 15 bits (bit 15 reserved, max 32767). The ×4 value for ADCRANGE 1, 16352, fits.
5. **CNVRF also clears on a write to ADC_CONFIG**, not only on a DIAG_ALRT read (§7.3.4).
6. **ENERGYOF clears when ENERGY is read; CHARGEOF when CHARGE is read.**
7. **DIAG_ALRT has bits the brief doesn't list:** 13 SLOWALERT, 10 CHARGEOF, 9 MATHOF, 7–2 limit flags, 0 MEMSTAT (reads 1 when healthy).
8. **CONFIG** also has CONVDLY (bits 13–6, 2 ms steps) and TEMPCOMP (bit 5).
9. **Measured, not in the datasheet:**
   - RSTACC self-clears (V);
   - ALRT stays asserted until DIAG_ALRT is read in transparent mode too (V);
   - the conversion grid gets a +10 µs step every ~0.5 s (V).

All the other facts in the brief match: register map, conversion-time and averaging codes, mode `0xF`, scaling factors, IDs, ALRT open drain and active low.

## 10. Still needs 19 V, a meter or a load

- **Bus voltage.** The reading's accuracy needs 19 V with the temporary ground jumper from `stage1_wiring.md`'s bench section (not done; needs 19 V).
- **VBUS jumper state.** Needs a multimeter (VIN+ to VBUS), or 19 V. VBUS reads near 0 either way today (§5).
- **Current, power and energy accuracy.** Needs a known load: the 4.7 kΩ resistor is 4 mA, which is 192 steps, 25 times the per-sample sd. Or a cross-check against the Jetson's INA3221.
- **Zero-current offset with a real common mode.** Needs 19 V and no load: does the −111 µA (−1.67 µV) stay the same?
- **ENERGY drift at zero current.** Needs 19 V (prediction in §7).
- **I²C and ALRT behaviour with 19 V present** and the Jetson switching. Needs 19 V and the Jetson.

## 11. Recommendations for the spec

- **I²C frequency: 400 kHz.** It's in spec and had zero errors over 10,000 reads plus all the streaming.
  - 1 MHz worked here (V), but it's outside the INA228's fast mode and not a documented mode for this pair. Don't build on it.
- **ALRT: use it, latched.** Set `DIAG_ALRT = CNVR | ALATCH` (0xC000) and timestamp falling edges with PIO.
  - Per conversion: read the data, then DIAG_ALRT last, so an overrun shows up as a missing edge.
  - Don't use transparent mode: it gave spurious edges at 400 kHz.
  - Consider an external pull-up on ALRT (for example 10 kΩ to 3V3) for faster edges (NV that it's needed).
- **ADCRANGE 0.** Range 1 gave no lower noise in µA, and it clips at about 2.73 A, below the Jetson's 4.2 A maximum.
- **Conversion time and averaging.** Noise is white, about 4.2 µA·√s, so what counts is the shunt integration time inside each decision window. Settings, in order of preference:
  - **Robust, verified:** MODE 0xB, VSHCT = VBUSCT = 540 µs, AVG 1. That's 1080 µs, 926 S/s, 0 missed in 60 s, 23 % headroom.
  - **Faster, marginal:** MODE 0xF 150/540/50 (740 µs, 1352 S/s). It missed 1 in 81 100 (V).
  - **More shunt time per cycle:** for example VSHCT 1052 with VBUSCT 150 (MODE 0xB, about 1.2 ms, 88 % shunt duty). NV, not tested.
- **Expected per-decision noise.** For a 10 ms decision with 50 % shunt duty, about 59 µA, so ≈ 1.1 mW mean-power noise, or ≈ 11 µJ against about 60 mJ per decision at 6 W. That's 0.02 % (derived estimate, NV on the Jetson).
- **Sample rate: about 0.9 kS/s** in MicroPython at 400 kHz with VSHUNT and VBUS on every conversion. Ways to go higher (all NV):
  - read VBUS every Nth conversion;
  - move the I²C loop to the second core, or to PIO/DMA.

  Even then, the bus alone limits three reads per conversion to about 2.4 kS/s at 400 kHz.
- **Energy: integrate samples (on the Mac or the Pico) with the PIO timestamps.** Don't read ENERGY at each marker.
  - ENERGY's LSB is 16 × 3.2 × 20.79 µA = **1.06 mJ**, about 56 counts per 10 ms decision at 6 W. That's 1.8 % quantisation at 100 Hz and about 17 % at 1 kHz.
  - Each ENERGY read also costs 240 µs, and it only updates once per conversion cycle.
  - Keep ENERGY and CHARGE as a cross-check over windows of seconds and longer. CHARGE matched the sampled current to 1.2 % here.
- **Timebase.** Timestamp each conversion. Don't assume a fixed grid: the INA228 runs −0.027 % against the Pico crystal and inserts a +10 µs step every ~0.5 s.
- **Offset.** Measure it at 19 V with no load and subtract it: −111 µA here.
- **Mac reader:** the standard library is enough (`stream_host.py` + `picolink.py`).

## 12. Surprises and procedure notes

- **Biggest findings:** the −1.67 µV offset, beyond the datasheet maximum; the +10 µs steps; and transparent mode's spurious edges.
- **Script bugs and recovery.** My first step-7a script raised an AttributeError before touching the INA228. The second hung: joining the RX FIFO broke `sm.put()`.
  - The host-side timeout ended it after 120 s, and `machine.reset()` followed.
  - The INA228 kept its CNVR setting until the next script reset it at its start, so that one step didn't end with CONFIG.RST (V).
- **Overlapping commands.** In step 10 I ran two mpremote commands at the same time by mistake. One enumeration check came back empty while the other was connected.
  - A sequential re-check right after showed the Pico enumerated 1 s after reset, with an empty filesystem (V, `raw/10_final_pico_recheck.txt`).

## 13. Files and hardware state

**Temp files** in `/private/tmp/jn_ina228/`, not deleted:
- `ina228.pdf` (TI datasheet, SHA-256 `a138d39e…7447`) and `ina228.txt` (extracted text);
- 20 scripts: `ina_common.py`, `mprun.py`, `s2_identify.py`, `s3_reliability.py`, `s4_speed.py`, `s5_noise.py`, `s6_vbus.py`, `s7a_alrt.py`, `s7b_cnvr.py`, `s7c_budget.py`, `s8_accum.py`, `s9_stream_pico.py`, `s9b_stream_pico_fn.py`, `s10_final_ina.py`, `stream_host.py`, `noise_analyze.py`, `alrt_analyze.py`, `alrt_stats.py`, `cnvr_analyze.py`, `accum_analyze.py`;
- `build/` with 10 combined Pico scripts (`s2`–`s8`, `s10`).

**Run folder** (gitignored), `runs/ina228_20261028/`:
- this report;
- `raw/` (25 files, including the two binary streams). Two of the step-7a analysis files have unreliable grid figures: `07a_offgrid.txt` assumed an approximate period, and `07a_alrt_analysis.txt` mis-fits the E4/E7 grid. Use `07a_phase.txt` and `07b_cnvr_analysis.txt` for intervals;
- `scripts/` (copies of the 20 scripts).

No tracked file was edited; `git status` is unchanged from the start (V).

**Hardware state:**

| | State | |
|---|---|---|
| INA228 | reset with CONFIG.RST: CONFIG `0x0000`, ADC_CONFIG `0xFB68`, SHUNT_CAL `0x1000`, CNVR off. It runs its power-on default (continuous conversions) while the Pico powers it | V |
| Pico | `machine.reset()`; enumerates as `2e8a:0005` / `<pico-serial>` at `/dev/cu.usbmodem1101`; `os.listdir('/')` is `[]`; GP4, 5, 16, 17 and 25 at their reset state (no function, inputs); mpremote connects | V |
| 19 V side | untouched; supply unplugged | V-user |
