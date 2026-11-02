# Step 2: detect and identify. Reads power-on register values before any write.
from machine import mem32

PADS_BANK0 = 0x4001C000


def pad(n):
    v = mem32[PADS_BANK0 + 4 + 4 * n]
    return "GP%d PUE=%d PDE=%d" % (n, (v >> 3) & 1, (v >> 2) & 1)


alrt = Pin(17, Pin.IN, Pin.PULL_UP)
i2c = bus(100_000)
print("i2c:", i2c, "|", pad(4), pad(5), pad(17))
t0 = time.ticks_us()
found = i2c.scan()
print("scan at 100 kHz: %s in %d us" % (found, time.ticks_diff(time.ticks_us(), t0)))
print("GP17 (ALRT) level, internal pull-up:", alrt.value())
if found != [ADDR]:
    raise SystemExit("unexpected scan result; stopping")

expected = [
    (CONFIG, "CONFIG", 0x0000), (ADC_CONFIG, "ADC_CONFIG", 0xFB68),
    (SHUNT_CAL, "SHUNT_CAL", 0x1000), (SHUNT_TEMPCO, "SHUNT_TEMPCO", 0x0000),
    (DIAG_ALRT, "DIAG_ALRT", 0x0001), (SOVL, "SOVL", 0x7FFF), (SUVL, "SUVL", 0x8000),
    (BOVL, "BOVL", 0x7FFF), (BUVL, "BUVL", 0x0000), (TEMP_LIMIT, "TEMP_LIMIT", 0x7FFF),
    (PWR_LIMIT, "PWR_LIMIT", 0xFFFF), (MANUFACTURER_ID, "MANUFACTURER_ID", 0x5449),
    (DEVICE_ID, "DEVICE_ID", 0x2281),
]
print("register values before any write (datasheet reset value in brackets):")
for reg, name, exp in expected:
    v = r16(i2c, reg)
    print("  %-16s 0x%02X = 0x%04X [0x%04X] %s" % (name, reg, v, exp, "same" if v == exp else "DIFFERENT"))

m, d = check_ids(i2c)
print("MANUFACTURER_ID 0x%04X = %r; DEVICE_ID 0x%04X -> DIEID 0x%03X, REV_ID %d"
      % (m, bytes((m >> 8, m & 0xFF)), d, d >> 4, d & 0xF))

try:
    temps = []
    for i in range(10):
        time.sleep_ms(5)            # default cycle is 3 x 1052 us
        temps.append(s16(r16(i2c, DIETEMP)) * 7.8125e-3)
    print("DIETEMP x10 (C): " + " ".join("%.3f" % t for t in temps))
    print("DIETEMP mean %.3f C" % (sum(temps) / len(temps)))
    vsh = [s20(r24(i2c, VSHUNT)) for _ in range(5)]
    vb = [s20(r24(i2c, VBUS)) for _ in range(5)]
    print("quick look, default config: VSHUNT steps %s (x312.5 nV); VBUS steps %s (x195.3125 uV = %s mV)"
          % (vsh, vb, ["%.2f" % (x * 0.1953125) for x in vb]))
finally:
    ina_reset(i2c)
    print("after CONFIG.RST: CONFIG 0x%04X ADC_CONFIG 0x%04X SHUNT_CAL 0x%04X"
          % (r16(i2c, CONFIG), r16(i2c, ADC_CONFIG), r16(i2c, SHUNT_CAL)))
