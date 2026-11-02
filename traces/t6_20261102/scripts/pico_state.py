# Stage 1 run: read-only Pico state check. No pin is configured or driven.
# Run with: mpremote connect id:<pico-serial> run pico_state.py
import os, sys, time
from machine import mem32

PADS_BANK0 = 0x4001C000
IO_BANK0 = 0x40014000
SIO_GPIO_IN = 0xD0000004
SIO_GPIO_OE = 0xD0000020
PIO0_CTRL = 0x50200000

print("ticks_ms since boot:", time.ticks_ms())
print("version:", sys.implementation.version, os.uname().machine)
print("os.listdir('/'):", os.listdir("/"))
oe = mem32[SIO_GPIO_OE]
gin = mem32[SIO_GPIO_IN]
print("SIO GPIO_OE = 0x%08x  GPIO_IN = 0x%08x" % (oe, gin))
print("PIO0 CTRL = 0x%08x (SM enable bits)" % mem32[PIO0_CTRL])
for n in (4, 5, 16, 17, 25):
    v = mem32[PADS_BANK0 + 4 + 4 * n]
    f = mem32[IO_BANK0 + 8 * n + 4] & 0x1F
    print("GP%-2d funcsel=%-2d OE=%d IN=%d pad=0x%02x PUE=%d PDE=%d IE=%d OD=%d" % (
        n, f, (oe >> n) & 1, (gin >> n) & 1, v & 0xFF, (v >> 3) & 1, (v >> 2) & 1, (v >> 6) & 1, (v >> 7) & 1))
