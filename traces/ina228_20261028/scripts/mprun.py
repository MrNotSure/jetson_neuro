"""Run one INA228 test on the Pico from RAM, then machine.reset().

  python3.12 mprun.py <test.py> <output.txt> [timeout_s]

Prepends ina_common.py, runs the result with `mpremote connect id:<serial> run`
under a host-side timeout, saves the full output, prints everything except data
lines (prefix "D,"), then always resets the Pico and checks it enumerates again.
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MP = os.path.expanduser("~/.local/bin/mpremote")
SERIAL = "<pico-serial>"
DEV = "id:" + SERIAL


def enumerated():
    out = subprocess.run([MP, "connect", "list"], capture_output=True, text=True, timeout=20).stdout
    return [l for l in out.splitlines() if "2e8a:0005" in l and SERIAL in l]


def main():
    script, out_path = sys.argv[1], sys.argv[2]
    timeout = float(sys.argv[3]) if len(sys.argv) > 3 else 120.0
    combined = os.path.join(HERE, "build", os.path.basename(script))
    with open(combined, "w") as f:
        f.write(open(os.path.join(HERE, "ina_common.py")).read())
        f.write("\n# ---------------- test ----------------\n")
        f.write(open(script).read())
    found = enumerated()
    if len(found) != 1:
        sys.exit(f"[mprun] expected exactly one Pico (2e8a:0005, {SERIAL}); found {found}")
    t0 = time.monotonic()
    try:
        p = subprocess.run([MP, "connect", DEV, "run", combined],
                           capture_output=True, text=True, timeout=timeout)
        text, rc = p.stdout + p.stderr, p.returncode
    except subprocess.TimeoutExpired as e:
        raw = e.stdout or ""
        text = raw.decode(errors="replace") if isinstance(raw, bytes) else raw
        text += f"\nHOST TIMEOUT after {timeout:.0f} s\n"
        rc = "timeout"
    wall = time.monotonic() - t0
    with open(out_path, "w") as f:
        f.write(text)
    r = subprocess.run([MP, "connect", DEV, "reset"], capture_output=True, text=True, timeout=30)
    time.sleep(3)
    after = enumerated()
    lines = text.splitlines()
    shown = [l for l in lines if not l.startswith("D,")]
    print("\n".join(shown))
    print(f"[mprun] {os.path.basename(script)}: exit {rc}, wall {wall:.1f} s, "
          f"{len(lines) - len(shown)} data lines saved to {out_path}")
    print(f"[mprun] machine.reset() exit {r.returncode}; enumerated afterwards: {after}")


if __name__ == "__main__":
    main()
