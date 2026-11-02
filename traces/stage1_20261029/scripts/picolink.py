"""Standard-library link to the Pico's MicroPython raw REPL (no pyserial).

  python3.12 picolink.py ports
  python3.12 picolink.py throughput <total_bytes> <chunk_bytes>
  python3.12 picolink.py clock <seconds> <out.csv>

The port is found from IOKit (ioreg) by USB vendor ID 0x2e8a and the Pico's
serial number; no other serial device is ever opened.
"""
import fcntl
import os
import plistlib
import select
import statistics as st
import subprocess
import sys
import termios
import time
import tty

PICO_VID = 0x2E8A
PICO_SERIAL = "<pico-serial>"
NVIDIA_VID = 0x0955


# ---------------------------------------------------------------- port lookup
def _callouts(node):
    out = []
    if "IOCalloutDevice" in node:
        out.append(node["IOCalloutDevice"])
    for child in node.get("IORegistryEntryChildren", []):
        out.extend(_callouts(child))
    return out


def usb_serial_ports():
    """[(vid, pid, serial, product, callout_path)] for every USB device with a tty."""
    raw = subprocess.run(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l"],
                         check=True, capture_output=True).stdout
    devices = plistlib.loads(raw) if raw.strip() else []
    rows = []
    for d in devices:
        for path in _callouts(d):
            rows.append((d.get("idVendor"), d.get("idProduct"), d.get("USB Serial Number"),
                         d.get("USB Product Name"), path))
    return rows


def find_pico(serial=PICO_SERIAL):
    rows = usb_serial_ports()
    hits = [r for r in rows if r[0] == PICO_VID and r[2] == serial and r[4].startswith("/dev/cu.")]
    if len(hits) != 1:
        raise SystemExit(f"expected exactly one Pico port (vid 0x2e8a, serial {serial}); found {hits} among {rows}")
    path = hits[0][4]
    if any(r[0] == NVIDIA_VID and r[4] == path for r in rows):
        raise SystemExit("refusing: path belongs to an NVIDIA device")
    return path


# ---------------------------------------------------------------- serial I/O
class Port:
    def __init__(self, path):
        self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        fcntl.ioctl(self.fd, termios.TIOCEXCL)            # exclusive open
        tty.setraw(self.fd)                               # no echo, no canon, no CR/LF mapping, 8 bits
        attrs = termios.tcgetattr(self.fd)
        attrs[2] |= termios.CLOCAL | termios.CREAD        # ignore modem-status lines
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)
        dtr_rts = (termios.TIOCM_DTR | termios.TIOCM_RTS).to_bytes(4, sys.byteorder)
        fcntl.ioctl(self.fd, termios.TIOCMBIS, dtr_rts)   # MicroPython's CDC waits for DTR
        termios.tcflush(self.fd, termios.TCIOFLUSH)
        self.buf = bytearray()

    def close(self):
        os.close(self.fd)

    def write(self, data):
        view = memoryview(data)
        while view:
            select.select([], [self.fd], [], 1.0)
            try:
                n = os.write(self.fd, view)
            except BlockingIOError:
                continue
            view = view[n:]

    def _fill(self, timeout):
        r, _, _ = select.select([self.fd], [], [], timeout)
        if not r:
            return 0
        try:
            chunk = os.read(self.fd, 1 << 16)
        except BlockingIOError:
            return 0
        self.buf += chunk
        return len(chunk)

    def read_until(self, marker, timeout=5.0):
        end = time.monotonic() + timeout
        while marker not in self.buf:
            if time.monotonic() > end:
                raise TimeoutError(f"waiting for {marker!r}; have {bytes(self.buf[-200:])!r}")
            self._fill(0.05)
        i = self.buf.index(marker) + len(marker)
        out = bytes(self.buf[:i])
        del self.buf[:i]
        return out

    def drain(self, quiet=0.2):
        while self._fill(quiet):
            pass
        out = bytes(self.buf)
        self.buf.clear()
        return out


class RawRepl:
    def __init__(self, port):
        self.p = port

    def enter(self):
        self.p.write(b"\r\x03\x03")          # interrupt anything running
        time.sleep(0.1)
        self.p.drain()
        self.p.write(b"\r\x01")              # Ctrl-A: raw REPL
        self.p.read_until(b"raw REPL; CTRL-B to exit\r\n>")

    def start(self, code):
        """Send code and Ctrl-D; return after the device answers OK."""
        data = code.encode()
        for i in range(0, len(data), 256):
            self.p.write(data[i:i + 256])
            time.sleep(0.01)
        self.p.write(b"\x04")
        ok = self.p.read_until(b"OK", timeout=5)
        if not ok.endswith(b"OK"):
            raise RuntimeError(f"no OK: {ok!r}")

    def finish(self, timeout=10):
        out = self.p.read_until(b"\x04", timeout)[:-1]
        err = self.p.read_until(b"\x04", timeout)[:-1]
        self.p.read_until(b">", timeout)
        return out, err

    def exit(self):
        self.p.write(b"\x02")                # Ctrl-B: back to the normal REPL
        time.sleep(0.05)
        self.p.drain(0.1)


def open_repl():
    path = find_pico()
    port = Port(path)
    repl = RawRepl(port)
    repl.enter()
    return path, port, repl


# ---------------------------------------------------------------- tests
PATTERN_STEP, PATTERN_OFF = 7, 3     # byte j of a chunk = (7j+3) & 0xFF; covers all 256 values


def expected_stream(total, chunk):
    base = bytearray((j * PATTERN_STEP + PATTERN_OFF) & 0xFF for j in range(chunk))
    out = bytearray()
    for k in range(total // chunk):
        base[0:4] = bytes((k & 0xFF, (k >> 8) & 0xFF, (k >> 16) & 0xFF, 0xA5))
        out += base
    return bytes(out)


def throughput(total, chunk):
    assert total % chunk == 0 and chunk >= 4
    code = f"""
import sys
C = {chunk}
N = {total // chunk}
b = bytearray(C)
for j in range(C):
    b[j] = (j * {PATTERN_STEP} + {PATTERN_OFF}) & 0xFF
w = sys.stdout.buffer.write
for k in range(N):
    b[0] = k & 0xFF; b[1] = (k >> 8) & 0xFF; b[2] = (k >> 16) & 0xFF; b[3] = 0xA5
    w(b)
"""
    path, port, repl = open_repl()
    try:
        repl.start(code)
        t_ok = time.monotonic_ns()
        t_first = None
        got = bytearray(port.buf)
        port.buf.clear()
        if got:
            t_first = t_ok
        last_progress = time.monotonic()
        while len(got) < total:
            r, _, _ = select.select([port.fd], [], [], 0.5)
            if r:
                try:
                    chunk_in = os.read(port.fd, 1 << 16)
                except BlockingIOError:
                    continue
                if chunk_in:
                    if t_first is None:
                        t_first = time.monotonic_ns()
                    got += chunk_in
                    last_progress = time.monotonic()
            if time.monotonic() - last_progress > 5:
                break
        t_last = time.monotonic_ns()
        extra = bytes(got[total:])
        payload = bytes(got[:total])
        port.buf += extra
        out, err = repl.finish()
        repl.exit()
    finally:
        port.close()
    exp = expected_stream(total, chunk)
    first_bad = next((i for i in range(min(len(payload), len(exp))) if payload[i] != exp[i]), None)
    dt_first = (t_last - t_first) / 1e9 if t_first else float("nan")
    dt_ok = (t_last - t_ok) / 1e9
    print(f"port {path}")
    print(f"requested {total} bytes in {chunk}-byte writes; received {len(payload)} payload bytes")
    print(f"identical to expected stream: {payload == exp}; first mismatch at {first_bad}")
    print(f"trailing stdout after payload: {out!r}  stderr: {err!r}")
    print(f"time OK->last byte {dt_ok:.3f} s, first->last byte {dt_first:.3f} s")
    print(f"throughput {total / dt_ok / 1e6:.3f} MB/s (from OK), {total / dt_first / 1e6:.3f} MB/s (first->last); MB = 1e6 bytes")
    return payload == exp


def clock(seconds, csv_path):
    code = """
import sys, time
rd = sys.stdin.buffer.read
wr = sys.stdout.write
while True:
    c = rd(1)
    if c == b'q':
        break
    wr('%d\\n' % time.ticks_us())
"""
    rows = []
    path, port, repl = open_repl()
    try:
        repl.start(code)
        time.sleep(0.2)
        for _ in range(5):                         # warm-up exchanges, not recorded
            port.write(b"p"); port.read_until(b"\n", 2)
        t_start = time.monotonic()
        for i in range(int(seconds) + 1):
            target = t_start + i
            while time.monotonic() < target:
                time.sleep(min(0.01, max(0.0, target - time.monotonic())))
            t0 = time.monotonic_ns()
            port.write(b"p")
            line = port.read_until(b"\n", 2)
            t1 = time.monotonic_ns()
            rows.append((i, t0, t1, int(line.strip())))
        port.write(b"q")
        out, err = repl.finish()
        repl.exit()
    finally:
        port.close()
    with open(csv_path, "w") as f:
        f.write("i,mac_t0_ns,mac_t1_ns,pico_ticks_us\n")
        for r in rows:
            f.write("%d,%d,%d,%d\n" % r)
    print(f"port {path}; {len(rows)} pairs written to {csv_path}; trailing out {out!r} err {err!r}")
    print("monotonic clock info:", time.get_clock_info("monotonic"))
    analyse_clock(csv_path)


def _fit(xs, ys):
    mx, my = st.fmean(xs), st.fmean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    icpt = my - slope * mx
    res = [y - (icpt + slope * x) for x, y in zip(xs, ys)]
    return slope, icpt, res


def analyse_clock(csv_path):
    rows = [tuple(map(int, l.split(","))) for l in open(csv_path).read().splitlines()[1:]]
    period = 1 << 30                     # MicroPython ticks_us wraps at 2**30 us
    unwrapped, base, prev = [], 0, None
    for r in rows:
        v = r[3]
        if prev is not None and v < prev:
            base += period
        unwrapped.append(v + base)
        prev = v
    rtt_us = [(r[2] - r[1]) / 1000 for r in rows]
    mid_us = [((r[1] + r[2]) / 2 - rows[0][1]) / 1000 for r in rows]
    pico = [u - unwrapped[0] for u in unwrapped]
    srt = sorted(rtt_us)
    p99 = srt[min(len(srt) - 1, int(round(0.99 * (len(srt) - 1))))]
    print(f"pairs {len(rows)}, span {mid_us[-1] / 1e6:.1f} s")
    print(f"round trip us: median {st.median(rtt_us):.1f}, p99 {p99:.1f}, min {srt[0]:.1f}, max {srt[-1]:.1f}")
    for label, frac in (("all pairs", 1.0), ("fastest 50%", 0.5), ("fastest 25%", 0.25)):
        cut = srt[max(1, int(len(srt) * frac)) - 1]
        idx = [i for i in range(len(rows)) if rtt_us[i] <= cut]
        slope, icpt, res = _fit([mid_us[i] for i in idx], [pico[i] for i in idx])
        print(f"{label:12s} n={len(idx):3d} (rtt <= {cut:.1f} us): rate {((slope - 1) * 1e6):+.2f} ppm "
              f"(Pico ticks vs Mac monotonic), residual stdev {st.pstdev(res):.1f} us, max |res| {max(abs(x) for x in res):.1f} us")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "ports":
        for r in usb_serial_ports():
            print(f"vid=0x{(r[0] or 0):04x} pid=0x{(r[1] or 0):04x} serial={r[2]} product={r[3]!r} path={r[4]}")
        print("selected:", find_pico())
    elif cmd == "throughput":
        ok = throughput(int(sys.argv[2]), int(sys.argv[3]))
        sys.exit(0 if ok else 1)
    elif cmd == "clock":
        clock(float(sys.argv[2]), sys.argv[3])
    elif cmd == "analyse":
        analyse_clock(sys.argv[2])
