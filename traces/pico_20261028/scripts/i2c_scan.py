# I2C0 scan on GP4/GP5 with nothing attached. Run from RAM with `mpremote run`.
# Also reads (does not write) the pad and function registers of GP4/GP5 to show
# whether MicroPython enabled the internal pull-ups.
import time
import machine
from machine import Pin, mem32

PADS_BANK0 = 0x4001C000      # GPIOn pad register at +4 + 4n: bit3 PUE, bit2 PDE, bit6 IE
IO_BANK0 = 0x40014000        # GPIOn_CTRL at +8n + 4: bits 4:0 FUNCSEL (3 = I2C, 5 = SIO)
SIO_GPIO_IN = 0xD0000004


def pad(n):
    v = mem32[PADS_BANK0 + 4 + 4 * n]
    f = mem32[IO_BANK0 + 8 * n + 4] & 0x1F
    return "GP%d pad=0x%02x PUE=%d PDE=%d IE=%d funcsel=%d level=%d" % (
        n, v & 0xFF, (v >> 3) & 1, (v >> 2) & 1, (v >> 6) & 1, f, (mem32[SIO_GPIO_IN] >> n) & 1)


print("before:", pad(4), "|", pad(5))
i2c = machine.I2C(0, sda=Pin(4), scl=Pin(5), freq=400_000)
print("i2c object:", i2c)
print("after init:", pad(4), "|", pad(5))
t0 = time.ticks_us()
try:
    res = i2c.scan()
    kind = "returned"
except Exception as e:
    res = repr(e)
    kind = "raised"
dt = time.ticks_diff(time.ticks_us(), t0)
print("scan %s %s in %d us (%d addresses probed)" % (kind, res, dt, 0x78 - 0x08))
print("after scan:", pad(4), "|", pad(5))
