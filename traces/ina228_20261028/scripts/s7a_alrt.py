# Step 7a: how ALRT behaves with conversion-ready enabled, and what clears it.
#
# PIO program adapted from pio_edges.py (Pico bring-up): same down-counter with
# exactly 3 SM cycles per decrement, but it timestamps BOTH edges on GP17 (input
# with internal pull-up), pushing X on each falling and each rising edge. Pushes
# therefore alternate fall, rise, fall, ... SM at sysclk: 1 count = 24 ns.
#
# Alignment with the CPU clock: the CPU injects `in x, 32` into the SM (write to
# SM0_INSTR) and notes ticks_us() around it, at the start and at the end.
import rp2
from machine import mem32
from array import array

PIO0_SM0_INSTR = 0x502000D8
IN_X_32 = 0x4020                     # encoding of `in x, 32`
START = (1 << 30) - 1                # stays a small int; 2**30 counts = 25.8 s at 24 ns
NS_PER_COUNT = 3 * 1e9 / machine.freq()


@rp2.asm_pio(autopush=True, push_thresh=32)   # no FIFO join: sm.put() needs the TX FIFO
def both_edges():
    pull(block)
    mov(x, osr)
    label("lo_wait")                 # pin high: wait for a falling edge
    jmp(pin, "lo_stay")              # 1
    in_(x, 32)                       # 1   falling-edge timestamp
    jmp(x_dec, "hi_wait")            # 1   -> 3 cycles, one decrement
    label("lo_stay")
    jmp(x_dec, "lo_wait")      [1]   # 2   -> 3 cycles
    label("hi_wait")                 # pin low: wait for a rising edge
    jmp(pin, "rise")                 # 1
    jmp(x_dec, "hi_wait")      [1]   # 2   -> 3 cycles
    label("rise")
    in_(x, 32)                       # 1   rising-edge timestamp
    jmp(x_dec, "lo_wait")            # 1   -> 3 cycles with the jmp pin


alrt = Pin(17, Pin.IN, Pin.PULL_UP)
print("GP17 funcsel=%d PUE=%d level=%d" % (mem32[0x40014000 + 8 * 17 + 4] & 0x1F,
                                           (mem32[0x4001C000 + 4 + 4 * 17] >> 3) & 1, alrt.value()))
edges = array("I", [0] * 4096)
cpu_a = array("i", [0] * 512)       # CPU ticks before each action
cpu_b = array("i", [0] * 512)       # CPU ticks after each action


def sync(sm):
    t0 = time.ticks_us()
    mem32[PIO0_SM0_INSTR] = IN_X_32
    t1 = time.ticks_us()
    while not sm.rx_fifo():
        pass
    return (t0 + t1) / 2, sm.get(), t1 - t0


def run(label, i2c, diag, action, duration_ms, cfg):
    """action(i2c) is called after every falling edge; None = no I2C traffic."""
    ina_reset(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, cfg)
    sm = rp2.StateMachine(0, both_edges, freq=machine.freq(), jmp_pin=Pin(17))
    sm.put(START)
    sm.active(1)
    time.sleep_ms(2)
    ta, xa, wa = sync(sm)
    n = 0
    nact = 0
    w16(i2c, DIAG_ALRT, diag)                 # enable CNVR (and ALATCH if set)
    t_end = time.ticks_add(time.ticks_ms(), duration_ms)
    while time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if sm.rx_fifo():
            edges[n] = sm.get()
            if n % 2 == 0 and action is not None and nact < 512:
                cpu_a[nact] = time.ticks_us()
                action(i2c)
                cpu_b[nact] = time.ticks_us()
                nact += 1
            n += 1
            if n >= len(edges):
                break
    w16(i2c, DIAG_ALRT, 0)                    # CNVR off
    r16(i2c, DIAG_ALRT)                       # clear any pending flag
    time.sleep_ms(5)
    while sm.rx_fifo() and n < len(edges):
        edges[n] = sm.get()
        n += 1
    tb, xb, wb = sync(sm)
    sm.active(0)
    rp2.PIO(0).remove_program()
    falls = [edges[i] for i in range(0, n, 2)]
    rises = [edges[i] for i in range(1, n, 2)]
    us = lambda c: c * NS_PER_COUNT / 1000
    ivals = sorted(us(a - b) for a, b in zip(falls, falls[1:]))
    lows = sorted(us(f - r) for f, r in zip(falls, rises))
    med = lambda xs: xs[len(xs) // 2] if xs else -1
    print("EXP %s diag=0x%04X freq=%d dur_ms=%d edges=%d falls=%d rises=%d actions=%d "
          "fall_interval_us med=%.2f min=%.2f max=%.2f low_width_us med=%.2f min=%.2f max=%.2f "
          "sync_a_ticks=%.1f(%dus) sync_b_ticks=%.1f(%dus) pio_vs_ticks_ppm=%.1f"
          % (label, diag, i2c_freq[0], duration_ms, n, len(falls), len(rises), nact,
             med(ivals), ivals[0] if ivals else -1, ivals[-1] if ivals else -1,
             med(lows), lows[0] if lows else -1, lows[-1] if lows else -1,
             ta, wa, tb, wb, (us(xa - xb) / (tb - ta) - 1) * 1e6))
    # Raw: edge counts and CPU actions, for the Mac-side analysis.
    print("D,%s,sync,%.1f,%d,%.1f,%d" % (label, ta, xa, tb, xb))
    for i in range(n):
        print("D,%s,edge,%d,%d" % (label, i, edges[i]))
    for i in range(nact):
        print("D,%s,act,%d,%d,%d" % (label, i, cpu_a[i], cpu_b[i]))


def read_diag(i2c):
    r16(i2c, DIAG_ALRT)


def read_vshunt(i2c):
    r24(i2c, VSHUNT)


_done = [False]


def read_others_then_diag(i2c):
    # Only on the first fall: VSHUNT, VBUS, CURRENT, DIETEMP, then after 5 ms DIAG_ALRT.
    if _done[0]:
        return
    _done[0] = True
    r24(i2c, VSHUNT); r24(i2c, VBUS); r24(i2c, CURRENT); r16(i2c, DIETEMP)
    time.sleep_ms(5)
    r16(i2c, DIAG_ALRT)
CFG = adc_config(0xF, 0, 3, 0, 0)          # 50 + 280 + 50 us = 380 us per cycle
i2c_freq = [400_000]
i2c = bus(400_000)
check_ids(i2c)
try:
    run("E1_transparent_noreads", i2c, CNVR, None, 50, CFG)
    run("E2_latched_noreads", i2c, CNVR | ALATCH, None, 50, CFG)
    run("E3_transparent_data_reads_then_diag", i2c, CNVR, read_others_then_diag, 30, CFG)
    run("E4_transparent_diag_400k", i2c, CNVR, read_diag, 200, CFG)
    run("E5_latched_diag_400k", i2c, CNVR | ALATCH, read_diag, 200, CFG)
    i2c_freq[0] = 100_000
    i2c = bus(100_000)
    run("E6_transparent_diag_100k", i2c, CNVR, read_diag, 200, CFG)
    i2c_freq[0] = 1_000_000
    i2c = bus(1_000_000)
    run("E7_transparent_diag_1M", i2c, CNVR, read_diag, 200, CFG)
finally:
    i2c = bus(400_000)
    ina_reset(i2c)
    print("INA228 reset; GP17 level now", alrt.value())
