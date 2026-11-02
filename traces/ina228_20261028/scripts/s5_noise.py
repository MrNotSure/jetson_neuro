# Step 5: zero-current VSHUNT noise. MODE 0xF (continuous bus, shunt, temperature),
# VBUSCT = VTCT = 50 us so the shunt setting dominates the cycle. Each sample waits
# for CNVRF (read of DIAG_ALRT, which clears it), so every value is a fresh conversion.
from array import array

N = 5000
DISCARD = 3
# (label, ADCRANGE, VSHCT code, AVG code)
SETTINGS = (
    ("ct50_avg1", 0, 0, 0),
    ("ct280_avg1", 0, 3, 0),
    ("ct1052_avg1", 0, 5, 0),
    ("ct280_avg16", 0, 3, 2),
    ("ct280_avg64", 0, 3, 3),
    ("ct280_avg1_range1", 1, 3, 0),
)
i2c = bus(400_000)
ina_reset(i2c)
check_ids(i2c)
vals = array("i", [0] * N)
try:
    for label, rng, vshct, avg in SETTINGS:
        ina_reset(i2c)
        w16(i2c, CONFIG, rng << 4)
        w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL * (4 if rng else 1))
        cfg = adc_config(0xF, 0, vshct, 0, avg)
        w16(i2c, ADC_CONFIG, cfg)
        exp = cycle_us(0xF, 0, vshct, 0, avg)
        t_before = s16(r16(i2c, DIETEMP)) * 7.8125e-3
        for i in range(DISCARD):
            wait_cnvrf(i2c)
            r24(i2c, VSHUNT)
        t0 = time.ticks_us()
        for i in range(N):
            wait_cnvrf(i2c)
            vals[i] = s20(r24(i2c, VSHUNT))
        dt = time.ticks_diff(time.ticks_us(), t0)
        t_after = s16(r16(i2c, DIETEMP)) * 7.8125e-3
        print("SETTING %s ADCRANGE=%d VSHCT=%dus AVG=%d CONFIG=0x%04X ADC_CONFIG=0x%04X SHUNT_CAL=%d expected_cycle_us=%d samples=%d elapsed_us=%d us_per_sample=%.1f dietemp_before=%.3f dietemp_after=%.3f"
              % (label, rng, CT_US[vshct], AVG_N[avg], r16(i2c, CONFIG), r16(i2c, ADC_CONFIG),
                 r16(i2c, SHUNT_CAL), exp, N, dt, dt / N, t_before, t_after))
        for i in range(N):
            print("D,%s,%d,%d" % (label, i, vals[i]))
finally:
    ina_reset(i2c)
    print("INA228 reset")
