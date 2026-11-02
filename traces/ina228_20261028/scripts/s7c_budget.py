# Step 7c: (1) which conversion cycle a Python handler sustains when it reads VSHUNT,
# VBUS and DIAG_ALRT on every ALRT edge at 400 kHz (the streaming case); (2) when, within
# a cycle, the VSHUNT and DIETEMP registers update (order of the conversions, AVG 1).
import rp2
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
edges = array("I", [0] * MAXE)
cpu_a = array("i", [0] * 2048)
cpu_b = array("i", [0] * 2048)
b2 = bytearray(2)
b3a = bytearray(3)
b3b = bytearray(3)


def sync(sm):
    t0 = time.ticks_us()
    mem32[PIO0_SM0_INSTR] = IN_X_32
    t1 = time.ticks_us()
    while not sm.rx_fifo():
        pass
    return (t0 + t1) / 2, sm.get(), t1 - t0


def start_sm():
    sm = rp2.StateMachine(0, both_edges, freq=machine.freq(), jmp_pin=Pin(17))
    sm.put(START)
    sm.active(1)
    time.sleep_ms(2)
    return sm


def stop_sm(sm, i2c, n):
    w16(i2c, DIAG_ALRT, 0)
    r16(i2c, DIAG_ALRT)
    time.sleep_ms(10)
    while sm.rx_fifo() and n < MAXE:
        edges[n] = sm.get()
        n += 1
    sm.active(0)
    rp2.PIO(0).remove_program()
    return n


def budget(label, cfg, nconv):
    i2c = bus(400_000)
    ina_reset(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, cfg)
    sm = start_sm()
    ta, xa, wa = sync(sm)
    rx, get, rd, tk = sm.rx_fifo, sm.get, i2c.readfrom_mem_into, time.ticks_us
    w16(i2c, DIAG_ALRT, CNVR | ALATCH)
    n = na = 0
    t_end = time.ticks_add(time.ticks_ms(), 5000)
    while na < nconv and n < MAXE - 2 and time.ticks_diff(t_end, time.ticks_ms()) > 0:
        if rx():
            edges[n] = get()
            if not n & 1:
                a = tk()
                rd(ADDR, VSHUNT, b3a)
                rd(ADDR, VBUS, b3b)
                rd(ADDR, DIAG_ALRT, b2)
                cpu_a[na] = a
                cpu_b[na] = tk()
                na += 1
            n += 1
    n = stop_sm(sm, i2c, n)
    mode, vbusct, vshct, vtct, avg = cfg >> 12, (cfg >> 9) & 7, (cfg >> 6) & 7, (cfg >> 3) & 7, cfg & 7
    print("RUN %s freq=%s diag=0x%04X adc_config=0x%04X expected_cycle_us=%d edges=%d actions=%d sync_window_us=%d"
          % (label, i2c, CNVR | ALATCH, cfg, cycle_us(mode, vbusct, vshct, vtct, avg), n, na, wa))
    print("D,%s,sync,%.1f,%d" % (label, ta, xa))
    for i in range(n):
        print("D,%s,edge,%d,%d" % (label, i, edges[i]))
    for i in range(na):
        print("D,%s,act,%d,%d,%d,%d,%d" % (label, i, cpu_a[i], cpu_a[i], cpu_b[i], 0))


def update_order(label, cfg, ncycles):
    """After each ALRT fall, poll VSHUNT and DIETEMP alternately at 1 MHz until the
    next fall; note when each value changes, as time since the fall (CPU ticks)."""
    i2c = bus(1_000_000)
    ina_reset(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, cfg)
    time.sleep_ms(20)
    rd, tk = i2c.readfrom_mem_into, time.ticks_us
    w16(i2c, DIAG_ALRT, CNVR | ALATCH)
    ch_sh, ch_t = [], []
    for c in range(ncycles + 1):
        while alrt.value():            # wait for the fall (CPU polling, a few us)
            pass
        t0 = tk()
        rd(ADDR, DIAG_ALRT, b2)        # re-arm
        rd(ADDR, VSHUNT, b3a)
        rd(ADDR, DIETEMP, b2)
        sh, tp = bytes(b3a), bytes(b2)
        while alrt.value():
            rd(ADDR, VSHUNT, b3a)
            t1 = tk()
            if bytes(b3a) != sh:
                sh = bytes(b3a)
                if c:
                    ch_sh.append((c, time.ticks_diff(t1, t0)))
            rd(ADDR, DIETEMP, b2)
            t2 = tk()
            if bytes(b2) != tp:
                tp = bytes(b2)
                if c:
                    ch_t.append((c, time.ticks_diff(t2, t0)))
    w16(i2c, DIAG_ALRT, 0)
    r16(i2c, DIAG_ALRT)
    mode, vbusct, vshct, vtct, avg = cfg >> 12, (cfg >> 9) & 7, (cfg >> 6) & 7, (cfg >> 3) & 7, cfg & 7
    print("ORDER %s adc_config=0x%04X CT bus/shunt/temp = %d/%d/%d us, cycle %d us"
          % (label, cfg, CT_US[vbusct], CT_US[vshct], CT_US[vtct], cycle_us(mode, vbusct, vshct, vtct, avg)))
    print("  VSHUNT changed at us after the fall (cycle, t):", ch_sh[:40])
    print("  DIETEMP changed at us after the fall (cycle, t):", ch_t[:40])


check_ids(bus(400_000))
try:
    budget("B1_modeB_280_280_560us", adc_config(0xB, 3, 3, 0, 0), 1500)
    budget("B2_modeF_150_540_50_740us", adc_config(0xF, 2, 4, 0, 0), 1500)
    budget("B3_modeB_540_540_1080us", adc_config(0xB, 4, 4, 0, 0), 1000)
    budget("B4_modeF_1052x3_avg1_3156us", adc_config(0xF, 5, 5, 5, 0), 600)
    update_order("O1_long_bus", adc_config(0xF, 7, 0, 0, 0), 15)
    update_order("O2_long_shunt", adc_config(0xF, 0, 7, 0, 0), 15)
    update_order("O3_long_temp", adc_config(0xF, 0, 0, 7, 0), 15)
finally:
    ina_reset(bus(400_000))
    print("INA228 reset; GP17 level", alrt.value())
