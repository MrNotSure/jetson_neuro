# Step 7b: conversion-ready intervals, and reading VSHUNT on every ALRT edge.
# PIO program as in s7a (both edges on GP17, 24 ns per count, adapted from pio_edges.py).
import rp2
import micropython
from machine import mem32
from array import array

PIO0_SM0_INSTR = 0x502000D8
IN_X_32 = 0x4020
START = (1 << 30) - 1
NS_PER_COUNT = 3 * 1e9 / machine.freq()


@rp2.asm_pio(autopush=True, push_thresh=32)
def both_edges():
    pull(block)
    mov(x, osr)
    label("lo_wait")
    jmp(pin, "lo_stay")
    in_(x, 32)
    jmp(x_dec, "hi_wait")
    label("lo_stay")
    jmp(x_dec, "lo_wait")      [1]
    label("hi_wait")
    jmp(pin, "rise")
    jmp(x_dec, "hi_wait")      [1]
    label("rise")
    in_(x, 32)
    jmp(x_dec, "lo_wait")


alrt = Pin(17, Pin.IN, Pin.PULL_UP)
MAXE = 4096
MAXA = 2048
edges = array("I", [0] * MAXE)
cpu_a = array("i", [0] * MAXA)      # ticks_us when the handler starts
cpu_m = array("i", [0] * MAXA)      # after the VSHUNT read (or = cpu_a if none)
cpu_b = array("i", [0] * MAXA)      # after the DIAG_ALRT read
vals = array("i", [0] * MAXA)
b2 = bytearray(2)
b3 = bytearray(3)


def sync(sm):
    t0 = time.ticks_us()
    mem32[PIO0_SM0_INSTR] = IN_X_32
    t1 = time.ticks_us()
    while not sm.rx_fifo():
        pass
    return (t0 + t1) / 2, sm.get(), t1 - t0


def loop_diag(sm, i2c, nconv, tmo_ms):
    """Python loop: on each fall, read DIAG_ALRT only (clears ALRT)."""
    rx, get, rd, tk = sm.rx_fifo, sm.get, i2c.readfrom_mem_into, time.ticks_us
    n = na = 0
    t_end = time.ticks_add(time.ticks_ms(), tmo_ms)
    while na < nconv and n < MAXE - 2 and time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if rx():
            edges[n] = get()
            if not n & 1:
                a = tk()
                rd(ADDR, DIAG_ALRT, b2)
                cpu_a[na] = a
                cpu_m[na] = a
                cpu_b[na] = tk()
                na += 1
            n += 1
    return n, na


def loop_vsh_diag(sm, i2c, nconv, tmo_ms):
    """Python loop: on each fall, read VSHUNT, then DIAG_ALRT to re-arm ALRT."""
    rx, get, rd, tk = sm.rx_fifo, sm.get, i2c.readfrom_mem_into, time.ticks_us
    n = na = 0
    t_end = time.ticks_add(time.ticks_ms(), tmo_ms)
    while na < nconv and n < MAXE - 2 and time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if rx():
            edges[n] = get()
            if not n & 1:
                a = tk()
                rd(ADDR, VSHUNT, b3)
                m = tk()
                rd(ADDR, DIAG_ALRT, b2)
                cpu_a[na] = a
                cpu_m[na] = m
                cpu_b[na] = tk()
                vals[na] = (b3[0] << 16) | (b3[1] << 8) | b3[2]
                na += 1
            n += 1
    return n, na


@micropython.native
def loop_vsh_diag_native(sm, i2c, nconv, tmo_ms):
    """Same as loop_vsh_diag, compiled with the native emitter."""
    rx, get, rd, tk = sm.rx_fifo, sm.get, i2c.readfrom_mem_into, time.ticks_us
    n = 0
    na = 0
    t_end = time.ticks_add(time.ticks_ms(), tmo_ms)
    while na < nconv and n < MAXE - 2 and time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if rx():
            edges[n] = get()
            if not n & 1:
                a = tk()
                rd(ADDR, VSHUNT, b3)
                m = tk()
                rd(ADDR, DIAG_ALRT, b2)
                cpu_a[na] = a
                cpu_m[na] = m
                cpu_b[na] = tk()
                vals[na] = (b3[0] << 16) | (b3[1] << 8) | b3[2]
                na += 1
            n += 1
    return n, na


def run(label, freq, cfg, diag, loop, nconv, tmo_ms):
    i2c = bus(freq)
    ina_reset(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, cfg)
    sm = rp2.StateMachine(0, both_edges, freq=machine.freq(), jmp_pin=Pin(17))
    sm.put(START)
    sm.active(1)
    time.sleep_ms(2)
    ta, xa, wa = sync(sm)
    w16(i2c, DIAG_ALRT, diag)
    n, na = loop(sm, i2c, nconv, tmo_ms)
    w16(i2c, DIAG_ALRT, 0)
    r16(i2c, DIAG_ALRT)
    time.sleep_ms(10)
    while sm.rx_fifo() and n < MAXE:
        edges[n] = sm.get()
        n += 1
    sm.active(0)
    rp2.PIO(0).remove_program()
    mode, vbusct, vshct, vtct, avg = cfg >> 12, (cfg >> 9) & 7, (cfg >> 6) & 7, (cfg >> 3) & 7, cfg & 7
    print("RUN %s freq=%s diag=0x%04X adc_config=0x%04X expected_cycle_us=%d edges=%d actions=%d sync_window_us=%d"
          % (label, i2c, diag, cfg, cycle_us(mode, vbusct, vshct, vtct, avg), n, na, wa))
    print("D,%s,sync,%.1f,%d" % (label, ta, xa))
    for i in range(n):
        print("D,%s,edge,%d,%d" % (label, i, edges[i]))
    for i in range(na):
        print("D,%s,act,%d,%d,%d,%d,%d" % (label, i, cpu_a[i], cpu_m[i], cpu_b[i], s20(vals[i])))


C380 = adc_config(0xF, 0, 3, 0, 0)       # 50 + 280 + 50 us, AVG 1 -> 380 us
C4608 = adc_config(0xF, 0, 5, 0, 1)      # (50 + 1052 + 50) us x 4 -> 4608 us
LAT = CNVR | ALATCH
check_ids(bus(400_000))
try:
    run("T1_transparent_diag_400k_repeat", 400_000, C380, CNVR, loop_diag, 1000, 2000)
    run("I1_latched_diag_380", 400_000, C380, LAT, loop_diag, 1900, 3000)
    run("I2_latched_diag_4608", 400_000, C4608, LAT, loop_diag, 600, 5000)
    run("V1_latched_vsh_380_400k", 400_000, C380, LAT, loop_vsh_diag, 1000, 3000)
    run("V2_latched_vsh_4608_400k", 400_000, C4608, LAT, loop_vsh_diag, 600, 5000)
    run("V3_latched_vsh_380_400k_native", 400_000, C380, LAT, loop_vsh_diag_native, 1000, 3000)
    run("V4_latched_vsh_380_1M", 1_000_000, C380, LAT, loop_vsh_diag, 1000, 3000)
finally:
    ina_reset(bus(400_000))
    print("INA228 reset; GP17 level", alrt.value())
