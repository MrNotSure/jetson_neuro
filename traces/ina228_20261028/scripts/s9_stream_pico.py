# Step 9, Pico side: stream one binary record per INA228 conversion for 60 s.
# Sent by stream_host.py through the raw REPL (prepended with ina_common.py).
#
# Conversion: MODE 0xB (shunt + bus), VSHCT = VBUSCT = 540 us, AVG 1 -> 1080 us,
# the slowest setting step 7c found safe for VSHUNT + VBUS + DIAG_ALRT per edge at 400 kHz.
# ALRT: CNVR + ALATCH. PIO (falling edges only, adapted from pio_edges.py) at
# 25 MHz with 3 cycles per count: 1 count = 120 ns, integer divider 5.
#
# Record, 16 bytes: 0xA5, FIFO level when serviced, seq u32 LE, PIO count u32 LE
# (increasing), VSHUNT 3 bytes and VBUS 3 bytes as read (big-endian, bits 3..0 reserved).
# Trailer: 0x5A followed by 15 zero bytes, then one text line of statistics.
import sys
import gc
import rp2
from machine import mem32

DUR_MS = 60_000
CFG = adc_config(0xB, 4, 4, 0, 0)
START = (1 << 30) - 1
SM_FREQ = 25_000_000
REC = 16
NREC = 8                               # 128-byte USB writes


@rp2.asm_pio(autopush=True, push_thresh=32)
def falls():
    pull(block)
    mov(x, osr)
    label("wait_high")                 # re-arm: wait for ALRT high
    jmp(pin, "armed")                  # 1
    jmp(x_dec, "wait_high")      [1]   # 2 -> 3
    label("armed")
    jmp(x_dec, "wait_low")       [1]   # 2 -> 3 with the jmp pin
    label("wait_low")
    jmp(pin, "still_high")             # 1
    in_(x, 32)                         # 1  falling edge = conversion ready
    jmp(x_dec, "wait_high")            # 1 -> 3
    label("still_high")
    jmp(x_dec, "wait_low")       [1]   # 2 -> 3


alrt = Pin(17, Pin.IN, Pin.PULL_UP)
buf = bytearray(REC * NREC)
mv = memoryview(buf)
trailer = bytearray(REC)
trailer[0] = 0x5A
b2 = bytearray(2)
b3a = bytearray(3)
b3b = bytearray(3)
w = sys.stdout.buffer.write
i2c = bus(400_000)
sm = None
try:
    ina_reset(i2c)
    check_ids(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, CFG)
    sm = rp2.StateMachine(0, falls, freq=SM_FREQ, jmp_pin=Pin(17))
    sm.put(START)
    sm.active(1)
    time.sleep_ms(5)
    rx, get, rd, tk, td = sm.rx_fifo, sm.get, i2c.readfrom_mem_into, time.ticks_us, time.ticks_diff
    seq = k = busy = max_h = max_w = w_total = nw = backlog = 0
    gc.collect()
    mem0 = gc.mem_free()
    w16(i2c, DIAG_ALRT, CNVR | ALATCH)
    t0 = tk()
    t_end = time.ticks_add(time.ticks_ms(), DUR_MS)
    while td(t_end, time.ticks_ms()) > 0:
        if rx():
            a = tk()
            lvl = rx()
            x = get()
            rd(ADDR, VSHUNT, b3a)
            rd(ADDR, VBUS, b3b)
            rd(ADDR, DIAG_ALRT, b2)          # re-arms ALRT (latched mode)
            ts = START - x
            o = k * REC
            buf[o] = 0xA5
            buf[o + 1] = lvl
            buf[o + 2] = seq & 0xFF
            buf[o + 3] = (seq >> 8) & 0xFF
            buf[o + 4] = (seq >> 16) & 0xFF
            buf[o + 5] = (seq >> 24) & 0xFF
            buf[o + 6] = ts & 0xFF
            buf[o + 7] = (ts >> 8) & 0xFF
            buf[o + 8] = (ts >> 16) & 0xFF
            buf[o + 9] = (ts >> 24) & 0xFF
            buf[o + 10] = b3a[0]
            buf[o + 11] = b3a[1]
            buf[o + 12] = b3a[2]
            buf[o + 13] = b3b[0]
            buf[o + 14] = b3b[1]
            buf[o + 15] = b3b[2]
            if lvl > 1:
                backlog += 1
            seq += 1
            k += 1
            if k == NREC:
                wb = tk()
                w(mv)
                dw = td(tk(), wb)
                w_total += dw
                nw += 1
                if dw > max_w:
                    max_w = dw
                k = 0
            d = td(tk(), a)
            busy += d
            if d > max_h:
                max_h = d
    elapsed = td(tk(), t0)
    if k:
        w(mv[: k * REC])
    w(trailer)
    mem1 = gc.mem_free()
    w16(i2c, DIAG_ALRT, 0)
    r16(i2c, DIAG_ALRT)
    div = mem32[0x502000C8]
    print("\nSTATS records=%d elapsed_us=%d busy_us=%d busy_frac=%.4f max_handler_us=%d writes=%d write_total_us=%d max_write_us=%d backlog_records=%d mem_free_before=%d mem_free_after=%d sm_clkdiv=0x%08X adc_config=0x%04X i2c=%s"
          % (seq, elapsed, busy, busy / elapsed, max_h, nw, w_total, max_w, backlog, mem0, mem1, div, r16(i2c, ADC_CONFIG), i2c))
finally:
    if sm is not None:
        sm.active(0)
        rp2.PIO(0).remove_program()
    ina_reset(i2c)
    print("INA228 reset")
