# Shared INA228 helpers. mprun.py prepends this file to each test script on the
# Mac; the combined script runs from the Pico's RAM. Nothing is stored on the Pico.
import time
import machine
from machine import Pin, I2C

ADDR = 0x40
CONFIG, ADC_CONFIG, SHUNT_CAL, SHUNT_TEMPCO = 0x00, 0x01, 0x02, 0x03
VSHUNT, VBUS, DIETEMP, CURRENT, POWER = 0x04, 0x05, 0x06, 0x07, 0x08
ENERGY, CHARGE, DIAG_ALRT = 0x09, 0x0A, 0x0B
SOVL, SUVL, BOVL, BUVL, TEMP_LIMIT, PWR_LIMIT = 0x0C, 0x0D, 0x0E, 0x0F, 0x10, 0x11
MANUFACTURER_ID, DEVICE_ID = 0x3E, 0x3F

R_SHUNT = 0.015                      # ohm, Adafruit 5832
CURRENT_LSB = 10.9 / (1 << 19)       # A, as the brief specifies (ADCRANGE 0)
SHUNT_CAL_VAL = 4088                 # 13107.2e6 * CURRENT_LSB * R_SHUNT = 4087.5, rounded up
CT_US = (50, 84, 150, 280, 540, 1052, 2074, 4120)
AVG_N = (1, 4, 16, 64, 128, 256, 512, 1024)
CNVRF = 0x0002
CNVR = 0x4000
ALATCH = 0x8000

_b2 = bytearray(2)
_b3 = bytearray(3)
_b5 = bytearray(5)


def bus(freq):
    return I2C(0, sda=Pin(4), scl=Pin(5), freq=freq)


def r16(i2c, reg):
    i2c.readfrom_mem_into(ADDR, reg, _b2)
    return (_b2[0] << 8) | _b2[1]


def r24(i2c, reg):
    i2c.readfrom_mem_into(ADDR, reg, _b3)
    return (_b3[0] << 16) | (_b3[1] << 8) | _b3[2]


def r40(i2c, reg):
    i2c.readfrom_mem_into(ADDR, reg, _b5)
    v = 0
    for x in _b5:
        v = (v << 8) | x
    return v


def w16(i2c, reg, val):
    i2c.writeto_mem(ADDR, reg, bytes(((val >> 8) & 0xFF, val & 0xFF)))


def s20(raw24):
    """20-bit two's complement stored in bits 23..4 (VSHUNT, VBUS, CURRENT)."""
    v = raw24 >> 4
    return v - (1 << 20) if v & 0x80000 else v


def s16(v):
    return v - 0x10000 if v & 0x8000 else v


def s40(v):
    return v - (1 << 40) if v & (1 << 39) else v


def adc_config(mode, vbusct, vshct, vtct, avg):
    return (mode << 12) | (vbusct << 9) | (vshct << 6) | (vtct << 3) | avg


def cycle_us(mode, vbusct, vshct, vtct, avg):
    """Expected time per conversion cycle: enabled channels' times x averages."""
    t = 0
    if mode & 1:
        t += CT_US[vbusct]
    if mode & 2:
        t += CT_US[vshct]
    if mode & 4:
        t += CT_US[vtct]
    return t * AVG_N[avg]


def ina_reset(i2c):
    w16(i2c, CONFIG, 0x8000)          # RST: same as power-on reset; self-clearing
    time.sleep_ms(2)


def check_ids(i2c):
    m, d = r16(i2c, MANUFACTURER_ID), r16(i2c, DEVICE_ID)
    if m != 0x5449 or (d >> 4) != 0x228:
        raise RuntimeError("wrong IDs: manufacturer 0x%04x device 0x%04x" % (m, d))
    return m, d


def wait_cnvrf(i2c, timeout_ms=1000):
    """Poll DIAG_ALRT until CNVRF is set; the read itself clears the flag."""
    t0 = time.ticks_ms()
    while not (r16(i2c, DIAG_ALRT) & CNVRF):
        if time.ticks_diff(time.ticks_ms(), t0) > timeout_ms:
            raise RuntimeError("CNVRF timeout")
