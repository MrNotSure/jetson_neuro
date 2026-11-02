# Step 10: reset the INA228 and confirm it is back at its reset values (read-only after RST).
i2c = bus(100_000)
print("scan:", i2c.scan())
ina_reset(i2c)
m, d = check_ids(i2c)
for reg, name, exp in ((CONFIG, "CONFIG", 0x0000), (ADC_CONFIG, "ADC_CONFIG", 0xFB68),
                       (SHUNT_CAL, "SHUNT_CAL", 0x1000), (SHUNT_TEMPCO, "SHUNT_TEMPCO", 0)):
    v = r16(i2c, reg)
    print("  %-12s 0x%04X [reset 0x%04X] %s" % (name, v, exp, "ok" if v == exp else "DIFFERENT"))
dg = r16(i2c, DIAG_ALRT)
print("  DIAG_ALRT    0x%04X (CNVR %d, ALATCH %d, MEMSTAT %d)" % (dg, (dg >> 14) & 1, (dg >> 15) & 1, dg & 1))
print("IDs 0x%04X 0x%04X; ALRT (GP17) level with pull-up: %d" % (m, d, Pin(17, Pin.IN, Pin.PULL_UP).value()))
