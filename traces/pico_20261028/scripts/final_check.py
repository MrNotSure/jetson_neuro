# Final state check after machine.reset(). Read-only: no pin is configured or driven.
import os, sys, time
from machine import mem32

PADS_BANK0 = 0x4001C000
IO_BANK0 = 0x40014000
SIO_GPIO_OE = 0xD0000020

print("ticks_ms since boot:", time.ticks_ms())
print("version:", sys.implementation.version, os.uname().machine)
print("os.listdir('/'):", os.listdir("/"))
print("main.py present:", "main.py" in os.listdir("/"), " boot.py present:", "boot.py" in os.listdir("/"))
st = os.statvfs("/")
print("fs used bytes:", st[0] * (st[2] - st[3]), "of", st[0] * st[2])
oe = mem32[SIO_GPIO_OE]
print("SIO GPIO_OE = 0x%08x (bit n set = GPn is an SIO output)" % oe)
for n in (4, 5, 16, 17, 25):
    v = mem32[PADS_BANK0 + 4 + 4 * n]
    f = mem32[IO_BANK0 + 8 * n + 4] & 0x1F
    print("GP%-2d funcsel=%-2d OE=%d pad PUE=%d PDE=%d IE=%d" % (n, f, (oe >> n) & 1, (v >> 3) & 1, (v >> 2) & 1, (v >> 6) & 1))
