# Stage 1 run, Pico side: stream every INA228 conversion plus the marker edges on GP16,
# all timestamped by one PIO counter. Sent by cap_host.py through the raw REPL, prepended
# with ina_common.py and a few parameter lines (MAX_S). Nothing is stored on the Pico.
#
# GP16 is never configured: no Pin(16, mode) call, no PIO output or set pins. PIO reads the
# pad's input path directly (reset state: input enabled, pull-down, funcsel NULL).
#
# INA228: ADCRANGE 0, SHUNT_CAL 4088, MODE 0xB, VSHCT = VBUSCT = 540 us, AVG 1 (1080 us).
# ALRT: CNVR | ALATCH (DIAG_ALRT 0xC000); one falling edge per conversion, re-armed by
# reading DIAG_ALRT last in each handler.
#
# PIO0, three state machines on one 25 MHz clock (divider 5), started in the same cycle by
# one CTRL write (enable + CLKDIV_RESTART). Each counts X down from 0xFFFFFFFF, one count per
# 3 SM cycles = 120 ns on every path, including the fall-through when X passes 0, so X wraps
# every 2**32 counts (515.4 s) without false edges or lost cycles. The host unwraps.
#   SM0: ALRT (GP17) falling edges     SM1: GP16 rising edges     SM2: GP16 falling edges
# RX FIFOs are joined (8 deep). X is loaded with `mov x, ~null` through exec, so no TX FIFO.
#
# Records, 16 bytes, little-endian unless noted:
#   0xA5 conversion: [1] FIFO level, [2:4] seq16, [4:8] X, [8:11] VSHUNT (BE), [11:14] VBUS (BE),
#                    [14:16] DIAG_ALRT as read (BE)
#   0xB6 GP16 rise / 0xB7 GP16 fall: [1] FIFO level, [2:4] seq16, [4:8] X
#   0xC7 accumulator: [1] register (0x09 ENERGY, 0x0A CHARGE), [2:4] seq16 of the last
#                    conversion, [4:8] ticks_us, [8:13] register (BE)
#   0xD8 sync: [1] phase (0 start, 1 end), [2:4] (a1 - a2) & 0xFFFF, [4:8] SM0 X (a1),
#                    [8:12] SM1 X, [12:16] SM2 X; X values injected by exec `in x, 32`
#                    as SM0, SM1, SM2, SM0 (a2)
#   0x5A trailer, then one text line "STATS ..."
import sys
import gc
import rp2
import select
import uctypes
from array import array
from machine import mem32

PIO0 = 0x50200000
CTRL, FDEBUG = PIO0 + 0x00, PIO0 + 0x08
SM_FREQ = 25_000_000
CFG = adc_config(0xB, 4, 4, 0, 0)
NREC = 8
I_MOV_X_NOT_NULL = 0xA02B
I_IN_X_32 = 0x4020


@rp2.asm_pio(autopush=True, push_thresh=32, fifo_join=rp2.PIO.JOIN_RX)
def falls():
    label("armed")
    jmp(x_dec, "wait_low")      [1]   # 0  fall-through at 0 -> 1 = wait_low
    wrap_target()
    label("wait_low")
    jmp(pin, "still_high")            # 1
    in_(x, 32)                        # 2  falling edge
    jmp(x_dec, "wait_high")           # 3  fall-through -> 4 = wait_high
    label("wait_high")
    jmp(pin, "armed")                 # 4  entry
    jmp(x_dec, "wait_high")     [1]   # 5  fall-through -> 6, a copy of wait_high
    jmp(pin, "armed")                 # 6
    jmp(x_dec, "wait_high")     [1]   # 7  (never at 0: X has just wrapped)
    label("still_high")
    jmp(x_dec, "wait_low")      [1]   # 8  fall-through -> wrap -> 1
    wrap()


@rp2.asm_pio(autopush=True, push_thresh=32, fifo_join=rp2.PIO.JOIN_RX)
def rises():
    label("wl_stay")
    jmp(x_dec, "wait_low")      [1]   # 0  fall-through -> 1
    wrap_target()
    label("wait_low")
    jmp(pin, "wl_stay")               # 1  entry
    jmp(x_dec, "wait_rise")     [1]   # 2  fall-through -> 3
    label("wait_rise")
    jmp(pin, "edge")                  # 3
    jmp(x_dec, "wait_rise")     [1]   # 4  fall-through -> 5, a copy
    jmp(pin, "edge")                  # 5
    jmp(x_dec, "wait_rise")     [1]   # 6  (never at 0)
    label("edge")
    in_(x, 32)                        # 7  rising edge
    jmp(x_dec, "wait_low")            # 8  fall-through -> wrap -> 1
    wrap()


def pin_state(n):
    v = mem32[0x4001C000 + 4 + 4 * n]
    return "GP%d funcsel=%d OE=%d IN=%d pad=0x%02x" % (
        n, mem32[0x40014000 + 8 * n + 4] & 0x1F, (mem32[0xD0000020] >> n) & 1,
        (mem32[0xD0000004] >> n) & 1, v & 0xFF)


def prep(sm, idx, entry):
    base = mem32[PIO0 + 0xD4 + 0x18 * idx] & 0x1F       # PC = program start after init
    sm.exec(I_MOV_X_NOT_NULL)                            # X = 0xFFFFFFFF
    sm.exec(base + entry)                                # jmp to the entry state
    return base


words = array("I", [0] * (4 * NREC))
rec = uctypes.bytearray_at(uctypes.addressof(words), 16 * NREC)
mvw = memoryview(words)
mvb = memoryview(rec)
wsl = [mvw[4 * k + 1:4 * k + 2] for k in range(NREC)]   # X       -> [4:8]
vsl = [mvb[16 * k + 8:16 * k + 11] for k in range(NREC)]  # VSHUNT  -> [8:11]
bsl = [mvb[16 * k + 11:16 * k + 14] for k in range(NREC)]  # VBUS -> [11:14]
dsl = [mvb[16 * k + 14:16 * k + 16] for k in range(NREC)]  # DIAG -> [14:16]
asl = [mvb[16 * k + 8:16 * k + 13] for k in range(NREC)]  # accumulator -> [8:13]
w = sys.stdout.buffer.write
trailer = bytearray(16)
trailer[0] = 0x5A


@micropython.viper
def inject():
    # `in x, 32` into SM0, SM1, SM2 with three back-to-back stores (a few ns apart, well under
    # one 120 ns count), then SM0 again after a short spin, so SM0's pair shows the counter moving.
    p = ptr32(0x50200000)
    p[0x36] = 0x4020          # SM0_INSTR
    p[0x3C] = 0x4020          # SM1_INSTR
    p[0x42] = 0x4020          # SM2_INSTR
    i = 0
    while i < 200:
        i += 1
    p[0x36] = 0x4020


def sync_record(phase, sms):
    a, r, f = sms
    for sm in sms:
        while sm.rx_fifo():
            sm.get()
    inject()
    a1, a2, xr, xf = a.get(), a.get(), r.get(), f.get()
    b = bytearray(16)
    b[0] = 0xD8
    b[1] = phase
    d = (a1 - a2) & 0xFFFF
    b[2], b[3] = d & 0xFF, d >> 8
    for o, v in ((4, a1), (8, xr), (12, xf)):
        for j in range(4):
            b[o + j] = (v >> (8 * j)) & 0xFF
    return b, a1 - a2, (a1 - xr) & 0xFFFFFFFF, (a1 - xf) & 0xFFFFFFFF


def loop(smA, smR, smF, i2c, max_s):
    rxA, rxR, rxF = smA.rx_fifo, smR.rx_fifo, smF.rx_fifo
    gA, gR, gF = smA.get, smR.get, smF.get
    rd = i2c.readfrom_mem_into
    tk, td, tms, tadd = time.ticks_us, time.ticks_diff, time.ticks_ms, time.ticks_add
    poller = select.poll()
    poller.register(sys.stdin, select.POLLIN)
    k = sa = sr = sf = nacc = 0
    busy_us = busy_s = maxh = backlog = nw = maxw = mbacklog = 0
    acc_due = 0
    hk = 0
    stop = "max_s"
    t_hk = tadd(tms(), 250)
    t_end = tadd(tms(), max_s * 1000)
    while True:
        n = rxA()
        if n:
            a = tk()
            o = k << 4
            gA(wsl[k])
            rd(0x40, 0x04, vsl[k])
            rd(0x40, 0x05, bsl[k])
            rd(0x40, 0x0B, dsl[k])                   # re-arms ALRT
            rec[o] = 0xA5
            rec[o + 1] = n
            rec[o + 2] = sa & 0xFF
            rec[o + 3] = (sa >> 8) & 0xFF
            sa += 1
            if n > 1:
                backlog += 1
            k += 1
            if k == NREC:
                wb = tk()
                w(rec)
                dw = td(tk(), wb)
                nw += 1
                if dw > maxw:
                    maxw = dw
                k = 0
            if acc_due:
                o = k << 4
                rd(0x40, acc_due, asl[k])
                t = tk()
                rec[o] = 0xC7
                rec[o + 1] = acc_due
                rec[o + 2] = (sa - 1) & 0xFF
                rec[o + 3] = ((sa - 1) >> 8) & 0xFF
                rec[o + 4] = t & 0xFF
                rec[o + 5] = (t >> 8) & 0xFF
                rec[o + 6] = (t >> 16) & 0xFF
                rec[o + 7] = (t >> 24) & 0xFF
                acc_due = 0
                nacc += 1
                k += 1
                if k == NREC:
                    w(rec)
                    nw += 1
                    k = 0
            d = td(tk(), a)
            busy_us += d
            if busy_us > 1_000_000:
                busy_us -= 1_000_000
                busy_s += 1
            if d > maxh:
                maxh = d
        n = rxR()
        if n:
            o = k << 4
            gR(wsl[k])
            rec[o] = 0xB6
            rec[o + 1] = n
            rec[o + 2] = sr & 0xFF
            rec[o + 3] = (sr >> 8) & 0xFF
            sr += 1
            if n > 1:
                mbacklog += 1
            k += 1
            if k == NREC:
                w(rec)
                nw += 1
                k = 0
        n = rxF()
        if n:
            o = k << 4
            gF(wsl[k])
            rec[o] = 0xB7
            rec[o + 1] = n
            rec[o + 2] = sf & 0xFF
            rec[o + 3] = (sf >> 8) & 0xFF
            sf += 1
            if n > 1:
                mbacklog += 1
            k += 1
            if k == NREC:
                w(rec)
                nw += 1
                k = 0
        if td(tms(), t_hk) >= 0:
            t_hk = tadd(t_hk, 250)
            hk += 1
            q = hk & 3
            if q == 1:
                acc_due = 0x09                       # ENERGY once a second
            elif q == 3:
                acc_due = 0x0A                       # CHARGE once a second, offset 0.5 s
            elif q == 0:
                got = False
                for _ in poller.ipoll(0):
                    got = True
                if got and sys.stdin.buffer.read(1) == b"q":
                    stop = "host"
                    break
                if td(tms(), t_end) >= 0:
                    break
    return k, sa, sr, sf, nacc, busy_s * 1_000_000 + busy_us, maxh, backlog, mbacklog, nw, maxw, stop


alrt = Pin(17, Pin.IN, Pin.PULL_UP)
i2c = bus(400_000)
smA = smR = smF = None
try:
    ina_reset(i2c)
    check_ids(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, CFG)
    smA = rp2.StateMachine(0, falls, freq=SM_FREQ, jmp_pin=Pin(17))
    smR = rp2.StateMachine(1, rises, freq=SM_FREQ, jmp_pin=Pin(16))
    smF = rp2.StateMachine(2, falls, freq=SM_FREQ, jmp_pin=Pin(16))
    bA = prep(smA, 0, 4)
    bR = prep(smR, 1, 1)
    bF = prep(smF, 2, 4)
    gp16_before = pin_state(16)
    mem32[FDEBUG] = 0xFFFFFFFF                       # clear sticky stall/overflow flags
    mem32[CTRL] = 0x707                              # SM0-2 enable + clock-divider restart, one write
    time.sleep_ms(2)
    sms = (smA, smR, smF)
    s0, s0_aa, s0_ar, s0_af = sync_record(0, sms)
    w(s0)
    gc.collect()
    mem0 = gc.mem_free()
    t0 = time.ticks_ms()
    w16(i2c, DIAG_ALRT, CNVR | ALATCH)
    k, sa, sr, sf, nacc, busy, maxh, backlog, mbacklog, nw, maxw, why = loop(smA, smR, smF, i2c, MAX_S)
    elapsed = time.ticks_diff(time.ticks_ms(), t0) * 1000
    mem1 = gc.mem_free()
    w16(i2c, DIAG_ALRT, 0)
    r16(i2c, DIAG_ALRT)
    time.sleep_ms(3)
    if k:
        w(mvb[:16 * k])
    # leftover edges after the loop, as text (should be at most the last conversion)
    left = [smA.rx_fifo(), smR.rx_fifo(), smF.rx_fifo()]
    s1, s1_aa, s1_ar, s1_af = sync_record(1, sms)
    w(s1)
    fdebug = mem32[FDEBUG]
    e_end = r40(i2c, ENERGY)
    q_end = s40(r40(i2c, CHARGE))
    w(trailer)
    print("\nSTATS stop=%s conversions=%d rises=%d falls=%d acc=%d elapsed_us=%d busy_us=%d busy_frac=%.4f "
          "max_handler_us=%d backlog=%d marker_backlog=%d writes=%d max_write_us=%d mem_free=%d->%d "
          "leftover_fifo=%s fdebug=0x%08x sync_start=(%d,%d,%d) sync_end=(%d,%d,%d) energy_end=%d charge_end=%d "
          "prog_base=(%d,%d,%d) clkdiv=0x%08x adc_config=0x%04x gp16_before=[%s] gp16_after=[%s] gp17=[%s]"
          % (why, sa, sr, sf, nacc, elapsed, busy, busy / elapsed, maxh, backlog, mbacklog, nw, maxw, mem0, mem1,
             left, fdebug, s0_aa, s0_ar, s0_af, s1_aa, s1_ar, s1_af, e_end, q_end, bA, bR, bF,
             mem32[PIO0 + 0xC8], r16(i2c, ADC_CONFIG), gp16_before, pin_state(16), pin_state(17)))
finally:
    for sm in (smA, smR, smF):
        if sm is not None:
            sm.active(0)
    rp2.PIO(0).remove_program()
    ina_reset(i2c)
    print("INA228 reset")
