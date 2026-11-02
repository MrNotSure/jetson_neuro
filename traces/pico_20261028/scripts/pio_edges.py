# PIO rising-edge timestamp test on GP16, run from RAM with `mpremote run`.
# Nothing is written to the Pico's filesystem.
#
# The CPU drives GP16 as a plain SIO output. A PIO state machine watches the
# same pad's input through its JMP pin and, on each rising edge, pushes the
# current value of a down-counter X to the RX FIFO.
#
# Every path through the program takes exactly 3 state-machine cycles per
# decrement of X, so one count = 3 / f_sm. With f_sm = sysclk (divider 1),
# one count = 3 / 125 MHz = 24 ns.
import time
import machine
import rp2
from machine import Pin
from array import array

N = 1000
START = (1 << 30) - 1      # keep counter values below 2**30 so they stay small ints (no heap allocation)


@rp2.asm_pio(autopush=True, push_thresh=32)
def edge_ts():
    pull(block)                     # initial counter value from the CPU
    mov(x, osr)
    wrap_target()
    label("wait_low")               # wait for the pin to be low (re-arm)
    jmp(pin, "wl_dec")              # 1 cycle
    jmp(x_dec, "wait_high")   [1]   # pin low:  2 cycles -> 3 total, 1 decrement
    label("wl_dec")
    jmp(x_dec, "wait_low")    [1]   # pin high: 2 cycles -> 3 total, 1 decrement
    label("wait_high")              # wait for the rising edge
    jmp(pin, "edge")                # 1 cycle
    jmp(x_dec, "wait_high")   [1]   # still low: 2 cycles -> 3 total, 1 decrement
    label("edge")
    in_(x, 32)                      # 1 cycle, autopush to RX FIFO
    jmp(x_dec, "wait_low")          # 1 cycle -> 3 total, 1 decrement
    wrap()


def run(period_us, n):
    pio_ts = array("I", [0] * (n + 16))
    cpu_ts = array("I", [0] * n)
    f = machine.freq()
    sm = rp2.StateMachine(0, edge_ts, freq=f, jmp_pin=Pin(16))
    pin = Pin(16, Pin.OUT, value=0)     # after SM creation, so GP16 stays an SIO output
    sm.put(START)
    sm.active(1)
    time.sleep_ms(20)
    half = period_us // 2
    got = 0
    t = time.ticks_add(time.ticks_us(), 2000)
    for i in range(n):
        while time.ticks_diff(t, time.ticks_us()) > 0:
            while sm.rx_fifo():
                pio_ts[got] = sm.get()
                got += 1
        pin.value(1)
        cpu_ts[i] = time.ticks_us()
        t = time.ticks_add(t, half)
        while time.ticks_diff(t, time.ticks_us()) > 0:
            while sm.rx_fifo():
                pio_ts[got] = sm.get()
                got += 1
        pin.value(0)
        t = time.ticks_add(t, period_us - half)
    time.sleep_ms(20)
    while sm.rx_fifo() and got < len(pio_ts):
        pio_ts[got] = sm.get()
        got += 1
    sm.active(0)
    rp2.PIO(0).remove_program()
    pin.value(0)
    print("RUN period_us=%d generated=%d captured=%d sysclk=%d sm_freq=%d cycles_per_count=3"
          % (period_us, n, got, f, f))
    for i in range(max(got, n)):
        print("E,%d,%d,%d" % (i, pio_ts[i] if i < got else -1, cpu_ts[i] if i < n else -1))
    print("END")


run(10_000, N)   # ~100 Hz
run(1_000, N)    # ~1 kHz
