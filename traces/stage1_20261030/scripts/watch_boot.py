"""Stage 1 run: watch the Jetson boot from the Mac. Logs (unix time, UTC, event) to OUT.

  .venv/bin/python watch_boot.py CAPTURE_NAME OUT.txt

- power-up: first 1 s mean current above 0.05 A in the capture's live status file;
- USB: first NVIDIA device (vendor 0x0955) in IOKit, and the console tty name appearing
  (existence only; the console is never opened);
- ssh: first `ssh -o ConnectTimeout=2 -o BatchMode=yes jetson-usb true` that succeeds (tried every
  1 s once USB is seen).
Says a warning aloud if no NVIDIA USB device 180 s after power-up. Exits after ssh answers + 5 s,
or after 900 s.
"""
import glob
import json
import plistlib
import subprocess
import sys
import time

SCR = "/private/tmp/jn_run1"
name, out = sys.argv[1], sys.argv[2]
status = f"{SCR}/{name}.status.json"
f = open(out, "a", buffering=1)


def log(s):
    f.write(f"{time.time():.3f}\t{time.strftime('%H:%M:%S', time.gmtime())}Z\t{s}\n")


def walk(node, acc):
    if isinstance(node, dict):
        if node.get("idVendor") == 0x0955:
            acc.append((node.get("idVendor"), node.get("idProduct"), node.get("USB Product Name"),
                        node.get("USB Serial Number"), node.get("locationID")))
        for c in node.get("IORegistryEntryChildren", []):
            walk(c, acc)
    elif isinstance(node, list):
        for c in node:
            walk(c, acc)


def nvidia():
    raw = subprocess.run(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l"], capture_output=True).stdout
    acc = []
    if raw.strip():
        walk(plistlib.loads(raw), acc)
    return sorted(set(acc), key=str)


log(f"watcher start; capture {name}")
t0 = time.time()
t_pow = t_usb = t_tty = t_ssh = None
warned = False
last_print = 0
while time.time() - t0 < 900:
    now = time.time()
    try:
        st = json.load(open(status))
    except Exception:
        st = {}
    if now - last_print > 5:
        last_print = now
        log(f"status I_1s={st.get('I_1s_A')} A Imax_1s={st.get('I_max_1s_A')} peak={st.get('peak_I_A')} "
            f"conv={st.get('conversions')} alarm={st.get('alarm_ever')}")
    if t_pow is None and (st.get("I_1s_A") or 0) > 0.05:
        t_pow = now
        log(f"POWER-UP: 1 s mean current {st.get('I_1s_A')} A")
    if t_usb is None:
        d = nvidia()
        if d:
            t_usb = now
            log(f"USB: NVIDIA device(s) {d}" + (f"; {t_usb - t_pow:.1f} s after power-up" if t_pow else ""))
    if t_tty is None:
        g = glob.glob("/dev/cu.usbmodem<jetson-serial>*")
        if g:
            t_tty = now
            log(f"TTY: {g}" + (f"; {t_tty - t_pow:.1f} s after power-up" if t_pow else ""))
    if t_usb is not None and t_ssh is None:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes", "jetson-usb", "true"],
                           capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            t_ssh = time.time()
            log(f"SSH: answered" + (f"; {t_ssh - t_pow:.1f} s after power-up" if t_pow else ""))
        else:
            log(f"ssh attempt rc={r.returncode} {r.stderr.strip()[:120]}")
    if t_pow and t_usb is None and now - t_pow > 180 and not warned:
        warned = True
        log("WARNING: no NVIDIA USB device 180 s after power-up")
        subprocess.Popen(["say", "No Jetson USB after three minutes. Unplug the supply."])
    if t_ssh and time.time() - t_ssh > 5:
        break
    time.sleep(0.5)
log(f"watcher end: power-up {t_pow}, usb {t_usb}, tty {t_tty}, ssh {t_ssh}")
