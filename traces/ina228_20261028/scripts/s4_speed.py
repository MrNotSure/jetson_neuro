# Step 4: read speed. 10,000 reads per register and frequency into preallocated buffers.
N = 10_000
REGS = (("VSHUNT", VSHUNT, 3), ("CURRENT", CURRENT, 3), ("ENERGY", ENERGY, 5), ("DIAG_ALRT", DIAG_ALRT, 2))

i2c = bus(400_000)
ina_reset(i2c)
w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)       # so CURRENT/ENERGY are computed; default continuous mode


def timed(fn, buf, reg):
    errs = 0
    t0 = time.ticks_us()
    for i in range(N):
        try:
            fn(ADDR, reg, buf)
        except OSError:
            errs += 1
    return time.ticks_diff(time.ticks_us(), t0), errs


def timed_ptr(i2c, buf):
    rd = i2c.readfrom_into
    errs = 0
    t0 = time.ticks_us()
    for i in range(N):
        try:
            rd(ADDR, buf)
        except OSError:
            errs += 1
    return time.ticks_diff(time.ticks_us(), t0), errs


def loop_overhead():
    t0 = time.ticks_us()
    for i in range(N):
        try:
            pass
        except OSError:
            pass
    return time.ticks_diff(time.ticks_us(), t0)


ov = loop_overhead()
print("loop+try overhead: %.2f us per iteration" % (ov / N))
for f in (100_000, 400_000, 1_000_000):
    i2c = bus(f)
    fhz = 1e6 / 1e6 * f
    for name, reg, n in REGS:
        buf = bytearray(n)
        dt, errs = timed(i2c.readfrom_mem_into, buf, reg)
        bits = 30 + 9 * n                              # S, addr+W, ptr, Sr, addr+R, n bytes, P
        print("SPEED f=%d reg=%s bytes=%d reads=%d errors=%d us_per_read=%.1f reads_per_s=%.0f bus_bits=%d bus_us=%.1f overhead_us=%.1f last=%s"
              % (f, name, n, N, errs, dt / N, N * 1e6 / dt, bits, bits * 1e6 / f, dt / N - bits * 1e6 / f, bytes(buf).hex()))
    # Pointer retained: set the pointer once, then plain reads (datasheet 7.5.1.1).
    i2c.writeto(ADDR, bytes((VSHUNT,)))
    buf = bytearray(3)
    dt, errs = timed_ptr(i2c, buf)
    bits = 11 + 9 * 3
    print("SPEED f=%d reg=VSHUNT_pointer_retained bytes=3 reads=%d errors=%d us_per_read=%.1f reads_per_s=%.0f bus_bits=%d bus_us=%.1f overhead_us=%.1f"
          % (f, N, errs, dt / N, N * 1e6 / dt, bits, bits * 1e6 / f, dt / N - bits * 1e6 / f))
    # VSHUNT then VBUS as two transactions, as streaming would do.
    b3a, b3b = bytearray(3), bytearray(3)
    rd = i2c.readfrom_mem_into
    t0 = time.ticks_us()
    for i in range(N):
        rd(ADDR, VSHUNT, b3a)
        rd(ADDR, VBUS, b3b)
    dt = time.ticks_diff(time.ticks_us(), t0)
    print("SPEED f=%d pair=VSHUNT+VBUS us_per_pair=%.1f pairs_per_s=%.0f" % (f, dt / N, N * 1e6 / dt))

# Does a 6-byte read from VSHUNT run on into VBUS (auto-increment)? Freeze the
# output registers in shutdown mode first so both reads see the same values.
i2c = bus(400_000)
time.sleep_ms(10)
w16(i2c, ADC_CONFIG, 0x0000 | (r16(i2c, ADC_CONFIG) & 0x0FFF))   # MODE 0 = shutdown
time.sleep_ms(10)
b6 = bytearray(6)
i2c.readfrom_mem_into(ADDR, VSHUNT, b6)
vsh, vb = r24(i2c, VSHUNT), r24(i2c, VBUS)
print("BURST 6 bytes from 0x04: %s | VSHUNT alone %06x | VBUS alone %06x | bytes 3..5 equal VBUS: %s, equal VSHUNT: %s"
      % (bytes(b6).hex(), vsh, vb, bytes(b6[3:]).hex() == "%06x" % vb, bytes(b6[3:]).hex() == "%06x" % vsh))
ina_reset(i2c)
print("INA228 reset")
