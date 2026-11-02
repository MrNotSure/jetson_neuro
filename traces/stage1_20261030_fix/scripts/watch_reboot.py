"""Stage 1 fix session: watch a reboot from the Mac. Times relative to the reboot command.

  .venv/bin/python watch_reboot.py REBOOT_MONO_NS OUT.txt [CAPTURE_NAME]

Polls every 0.5 s: the NVIDIA USB device (vendor 0x0955, existence only via IOKit; the console tty
is never opened), and `ssh -o ConnectTimeout=2 -o BatchMode=yes jetson-usb true` once the USB
device is back. Logs the capture's live current every 5 s. Ends 5 s after ssh answers, or at 600 s.
"""
import json
import plistlib
import subprocess
import sys
import time

t0 = int(sys.argv[1])
out = open(sys.argv[2], "a", buffering=1)
cap = sys.argv[3] if len(sys.argv) > 3 else None


def rel():
    return (time.monotonic_ns() - t0) / 1e9


def log(s):
    out.write(f"{time.strftime('%H:%M:%S', time.gmtime())}Z\t+{rel():7.2f} s\t{s}\n")


def nvidia_present():
    raw = subprocess.run(["ioreg", "-a", "-r", "-c", "IOUSBHostDevice", "-l"], capture_output=True).stdout
    devs = plistlib.loads(raw) if raw.strip() else []
    return any(d.get("idVendor") == 0x0955 for d in devs)


log("watcher start")
state = nvidia_present()
log(f"NVIDIA USB device present: {state}")
t_gone = t_back = t_ssh = None
last = 0
while rel() < 600:
    p = nvidia_present()
    if p != state:
        state = p
        log(f"NVIDIA USB device present: {p}")
        if not p and t_gone is None:
            t_gone = rel()
        if p and t_gone is not None and t_back is None:
            t_back = rel()
    if t_back is not None and t_ssh is None:
        r = subprocess.run(["ssh", "-o", "ConnectTimeout=2", "-o", "BatchMode=yes", "-o", "ControlPath=none",
                            "jetson-usb", "true"], capture_output=True, text=True, timeout=8)
        if r.returncode == 0:
            t_ssh = rel()
            log("SSH answered")
        else:
            log(f"ssh rc {r.returncode} {r.stderr.strip()[:100]}")
    if cap and time.time() - last > 5:
        last = time.time()
        try:
            st = json.load(open(f"/private/tmp/jn_fix/{cap}.status.json"))
            log(f"I_1s {st.get('I_1s_A')} A, P_1s {st.get('P_1s_W')} W, V {st.get('V_1s')} V, Imax_1s {st.get('I_max_1s_A')}, alarm {st.get('alarm_ever')}")
        except Exception as e:
            log(f"status read failed: {e}")
    if t_ssh is not None and rel() - t_ssh > 5:
        break
    time.sleep(0.5)
log(f"watcher end: USB gone +{t_gone}, USB back +{t_back}, ssh +{t_ssh}")
