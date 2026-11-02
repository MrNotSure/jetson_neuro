"""T6b (2 Nov 2026), orchestrator on the Mac: closed loop, idle (I) / hold (H) / classical (A), on track-sine-v1.
From traces/t6_20261102/scripts/t6_run.py. Changes for T6b: paths /tmp/jn_t6b, /private/tmp/jn_t6b and
runs/t6b_20261102; raw/order.txt lines are `roundN X Y Z` (an I block in every round), every block is tagged
R<round><cond> (R3I, R3H, R3A); the snapshot adds one INA3221 VDD_IN reading (in1_input, curr1_input, found
through the I2C path). No 10 Hz logger is started anywhere in T6b. Everything else is unchanged.

  .venv/bin/python scripts/t6_run.py smoke CAP                 # one 10 s classical block (tag S)
  .venv/bin/python scripts/t6_run.py blocks CAP FIRST LAST     # rounds FIRST..LAST = lines of raw/order.txt (1-based)

Per block: board snapshot (in the gap); for H and A a fresh pinned mark_ctl.py (mc_start.sh, waits for
"listening"); mark.py start; jn-sim run realtime 60 s, or sleep 61 s for I; mark.py end; mc_wait.sh (H, A);
snapshot; 10 s gap. Every command goes to commands.log with its UTC time first. Block records go to
raw/blocks.json, snapshots to raw/snapshots.txt, jn-sim output to raw/sim_<tag>.txt. Stops at the first failed
controller start, wrong affinity, failed sim run, INA228 alarm, current over 1.5 A or a temperature over 80 C, or
if /private/tmp/jn_t6b/stop_run exists (checked before each block).
"""
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(RUN))
LOG = os.path.join(RUN, "commands.log")
PY = os.path.join(REPO, ".venv", "bin", "python")
SIMDIR = os.path.join(RUN, "sim")
SCRATCH = "/private/tmp/jn_t6b"
CTL = {"H": "hold", "A": "classical"}
SNAP = ('date -u +%FT%T.%3NZ; for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/temp 2>/dev/null) && echo -n "$(cat $z/type)=$t "; done; echo; '
        'for h in /sys/class/hwmon/hwmon*; do n=$(cat $h/name); [ "$n" = pwmfan ] && echo -n "fan_pwm=$(cat $h/pwm1) "; [ "$n" = pwm_tach ] && echo -n "fan_rpm=$(cat $h/rpm) "; done; '
        'echo "cpu_cur policy0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq) policy4=$(cat /sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq) gpu_cur=$(cat /sys/class/devfreq/17000000.gpu/cur_freq)"; '
        'H=$(ls -d /sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon*); echo "vdd_in mV=$(cat $H/in1_input) mA=$(cat $H/curr1_input)"; '
        'pgrep -a -x "apt|apt-get|apt-helper|dpkg" || echo "no apt/dpkg"; systemctl list-jobs --no-pager | tail -1')
JOURNAL = ('journalctl --since "-80s" --no-pager -o short-iso 2>/dev/null | grep -v -E "dhcpd|systemd-resolved|sudo|sshd|session" '
           '| tail -5; echo "journal lines in the last 80 s (all): $(journalctl --since "-80s" --no-pager 2>/dev/null | wc -l)"')


def utc():
    t = time.time()
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(t)) + ".%03dZ" % (int(t * 1000) % 1000)


def log(where, cmd):
    with open(LOG, "a") as f:
        f.write(f"{utc()}\t{where}\t{cmd}\n")


def board(cmd, timeout=60):
    log("board", "ssh jetson-usb " + cmd.replace("\n", " ⏎ "))
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=5", "jetson-usb", cmd], capture_output=True, text=True, timeout=timeout)
    return r.stdout + r.stderr


def mark(label):
    out = subprocess.run([PY, os.path.join(HERE, "mark.py"), label], capture_output=True, text=True).stdout.strip()
    return out, int(out.split()[2])


def safety(cap, snap_txt):
    """Rule 10: INA228 alarm or current > 1.5 A (cap_host status), any temperature > 80 C (snapshot)."""
    msgs = []
    try:
        st = json.load(open(os.path.join(SCRATCH, cap + ".status.json")))
        if st.get("alarm_ever") or "ALARM" in st:
            msgs.append(f"INA228 over-current alarm: {st}")
        if (st.get("peak_I_A") or 0) > 1.5:
            msgs.append(f"peak current {st['peak_I_A']} A > 1.5 A")
    except (OSError, ValueError) as e:
        msgs.append(f"no capture status for {cap}: {e}")
    temps = [int(v) for v in re.findall(r"thermal=(-?\d+)", snap_txt)]
    if not temps:
        msgs.append("no temperatures in the snapshot")
    elif max(temps) > 80000:
        msgs.append(f"temperature {max(temps) / 1000:.1f} C > 80 C")
    return msgs


def stop_now(why):
    print(f"STOP: {why}", flush=True)
    log("mac", f"t6_run.py stopped: {why}")
    raise SystemExit(2)


def block(cap, tag, cond, rnd, dur, snaps, blocks):
    if os.path.exists(os.path.join(SCRATCH, "stop_run")):
        stop_now(f"{SCRATCH}/stop_run exists (before block {tag})")
    rec = {"capture": cap, "tag": tag, "cond": cond, "round": rnd, "duration_s": dur}
    s0 = board(SNAP)
    snaps.write(f"== {tag} ({cond}, round {rnd}, {cap}) before\n{s0}")
    snaps.flush()
    bad = safety(cap, s0)
    if bad:
        stop_now("; ".join(bad))
    if cond in CTL:
        out = board(f"bash /tmp/jn_t6b/scripts/mc_start.sh {tag} {CTL[cond]}")
        snaps.write(f"== {tag} mc_start\n{out}")
        snaps.flush()
        m = re.search(r"affinity: pid \d+'s current affinity list: (\S+)", out)
        rec["affinity"] = m.group(1) if m else None
        if "port 5555 listening" not in out or "listening 192.168.55.1:5555" not in out:
            print(f"{tag}: controller start failed:\n{out}", flush=True)
            stop_now(f"{tag}: controller start failed")
        if rec["affinity"] != "2":
            print(out, flush=True)
            stop_now(f"{tag}: controller affinity {rec['affinity']!r}, not cpu 2")
    txt, rec["mark_start_mono_ns"] = mark(f"{tag} start ({cond}, round {rnd}, {cap})")
    print(txt, flush=True)
    if cond in CTL:
        args = ["run", "--scenario", "track-sine-v1", "--controller", "tcp://192.168.55.1:5555", "--mode", "realtime",
                "--duration", str(dur), "--out", "runs/t6b_20261102/sim"]
        log("mac", ".venv/bin/jn-sim " + " ".join(args))
        before = set(os.listdir(SIMDIR))
        r = subprocess.run([os.path.join(REPO, ".venv", "bin", "jn-sim"), *args], cwd=REPO, capture_output=True, text=True,
                           timeout=dur + 90)
        new = sorted(set(os.listdir(SIMDIR)) - before)
        rec["sim_rc"] = r.returncode
        rec["sim_dir"] = new[-1] if new else None
        with open(os.path.join(RUN, "raw", f"sim_{tag}.txt"), "w") as f:
            f.write(f"rc {r.returncode}; new dirs {new}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}\n")
        print(f"{tag}: jn-sim rc {r.returncode}, dir {rec['sim_dir']}\n{r.stdout.strip()}", flush=True)
    else:
        log("mac", f"sleep {dur + 1}   (idle block {tag}: no controller, no marker)")
        time.sleep(dur + 1)
    txt, rec["mark_end_mono_ns"] = mark(f"{tag} end")
    print(txt, flush=True)
    if cond in CTL:
        out = board(f"bash /tmp/jn_t6b/scripts/mc_wait.sh {tag}")
        snaps.write(f"== {tag} mc_wait\n{out}")
        print(out.strip(), flush=True)
        rec["mc_csv"] = f"mc_{tag}.csv"
    s1 = board(SNAP + "; " + JOURNAL)
    snaps.write(f"== {tag} after\n{s1}")
    snaps.flush()
    blocks.append(rec)
    with open(os.path.join(RUN, "raw", "blocks.json"), "w") as f:
        json.dump(blocks, f, indent=1)
    if cond in CTL and (rec["sim_rc"] != 0 or not rec["sim_dir"]):
        stop_now(f"{tag}: jn-sim rc {rec['sim_rc']}, dir {rec['sim_dir']}")
    bad = safety(cap, s1)
    if bad:
        stop_now("; ".join(bad))


def main():
    what, cap = sys.argv[1], sys.argv[2]
    bpath = os.path.join(RUN, "raw", "blocks.json")
    blocks = json.load(open(bpath)) if os.path.exists(bpath) else []
    snaps = open(os.path.join(RUN, "raw", "snapshots.txt"), "a")
    if what == "smoke":
        block(cap, "S", "A", 0, 10, snaps, blocks)
        return
    first, last = int(sys.argv[3]), int(sys.argv[4])
    lines = [l.split() for l in open(os.path.join(RUN, "raw", "order.txt")) if l.strip() and not l.startswith("#")]
    for n in range(first, last + 1):
        name, conds = lines[n - 1][0], lines[n - 1][1:]
        rnd = int(name[5:])
        assert name.startswith("round") and rnd == n and sorted(conds) == ["A", "H", "I"], lines[n - 1]
        for cond in conds:
            tag = f"R{rnd}{cond}"
            block(cap, tag, cond, rnd, 60, snaps, blocks)
            log("mac", "sleep 10   (gap)")
            time.sleep(10)
        print(f"== done: line {n} ({name} {' '.join(conds)}) at {utc()}", flush=True)


if __name__ == "__main__":
    main()
