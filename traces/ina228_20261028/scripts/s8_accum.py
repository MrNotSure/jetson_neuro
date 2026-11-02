# Step 8: ENERGY and CHARGE accumulators at zero current, 120 s.
# Config: ADCRANGE 0, SHUNT_CAL 4088, MODE 0xF, VBUSCT 50 / VSHCT 1052 / VTCT 50 us, AVG 1
# (the step-5 setting "ct1052_avg1", so the CHARGE rate can be compared with its VSHUNT mean).
DUR_S = 120
CFG = adc_config(0xF, 0, 5, 0, 0)
i2c = bus(400_000)
check_ids(i2c)


def snap(tag, t0):
    d = r16(i2c, DIAG_ALRT)              # flags first: ENERGYOF/CHARGEOF clear on reading those registers
    e = r40(i2c, ENERGY)
    q = s40(r40(i2c, CHARGE))
    p = r24(i2c, POWER)
    vb = s20(r24(i2c, VBUS))
    cu = s20(r24(i2c, CURRENT))
    tt = s16(r16(i2c, DIETEMP))
    t = time.ticks_diff(time.ticks_us(), t0)
    print("D,%s,%d,%d,%d,0x%04X,%d,%d,%d,%d" % (tag, t, e, q, d, p, vb, cu, tt))


try:
    ina_reset(i2c)
    w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
    w16(i2c, ADC_CONFIG, CFG)
    t0 = time.ticks_us()
    time.sleep(3)
    snap("before_rstacc", t0)
    w16(i2c, CONFIG, 0x4000)                         # RSTACC
    cfg_after = r16(i2c, CONFIG)
    snap("just_after_rstacc", t0)
    print("CONFIG after writing RSTACC: 0x%04X (RSTACC bit %s)" % (cfg_after, "still set" if cfg_after & 0x4000 else "self-cleared"))
    if cfg_after & 0x4000:
        w16(i2c, CONFIG, 0x0000)
        print("wrote CONFIG = 0 to release RSTACC; now 0x%04X" % r16(i2c, CONFIG))
    # Reference: mean CURRENT and VSHUNT between the 1 s snapshots (every ~5 ms).
    t_start = time.ticks_us()
    snap("t0", t_start)
    for s in range(1, DUR_S + 1):
        acc_c = acc_v = n = 0
        target = time.ticks_add(t_start, s * 1_000_000)
        while time.ticks_diff(target, time.ticks_us()) > 6000:
            acc_c += s20(r24(i2c, CURRENT))
            acc_v += s20(r24(i2c, VSHUNT))
            n += 1
            time.sleep_ms(5)
        while time.ticks_diff(target, time.ticks_us()) > 0:
            pass
        snap("t%d" % s, t_start)
        print("M,%d,%d,%d,%d" % (s, n, acc_c, acc_v))
    w16(i2c, CONFIG, 0x4000)
    snap("end_rstacc", t_start)
    print("CONFIG after second RSTACC: 0x%04X" % r16(i2c, CONFIG))
finally:
    ina_reset(i2c)
    print("INA228 reset")
