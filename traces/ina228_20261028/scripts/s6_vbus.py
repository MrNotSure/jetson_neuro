# Step 6: VBUS with nothing connected. 1000 fresh conversions (CNVRF-paced) at the
# reset configuration (all channels 1052 us, AVG 1), then 1000 at VBUSCT 50 us
# (the setting the streaming test uses).
from array import array

N = 1000
i2c = bus(400_000)
ina_reset(i2c)
check_ids(i2c)
vals = array("i", [0] * N)
try:
    for label, cfg in (("reset_default_ct1052", None), ("vbusct50_vshct280", adc_config(0xF, 0, 3, 0, 0))):
        ina_reset(i2c)
        w16(i2c, SHUNT_CAL, SHUNT_CAL_VAL)
        if cfg is not None:
            w16(i2c, ADC_CONFIG, cfg)
        for i in range(3):
            wait_cnvrf(i2c)
        raw_last = 0
        for i in range(N):
            wait_cnvrf(i2c)
            raw_last = r24(i2c, VBUS)
            vals[i] = s20(raw_last)
        print("VBUS %s ADC_CONFIG=0x%04X raw_last=0x%06X reserved_bits=%d"
              % (label, r16(i2c, ADC_CONFIG), raw_last, raw_last & 0xF))
        for i in range(N):
            print("D,%s,%d,%d" % (label, i, vals[i]))
finally:
    ina_reset(i2c)
    print("INA228 reset")
