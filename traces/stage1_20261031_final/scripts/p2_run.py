"""Stage 1 final (31 Oct 2026), Part 2 orchestrator on the Mac: closed loop, hold (H) / centroid (C) / idle (I).

  .venv/bin/python scripts/p2_run.py smoke     # one 10 s hold block (tag S)
  .venv/bin/python scripts/p2_run.py rounds    # the 4 rounds from raw/order.txt

Per block: board snapshot; for H and C a fresh mark_ctl.py (mc_start.sh, waits for "listening");
mark.py start; jn-sim run realtime (60 s) or sleep 61 s for I; mark.py end; mc_wait.sh (H, C);
snapshot; 10 s gap. Every command goes to commands.log with its UTC time first. Block records go to
raw/P2_blocks.json (appended), snapshots to raw/P2_snapshots.txt, jn-sim output to raw/P2_<tag>_sim.txt.
Stops at the first failed controller start.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
RUN = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(RUN))
LOG = os.path.join(RUN, "commands.log")
PY = os.path.join(REPO, ".venv", "bin", "python")
SIMDIR = os.path.join(RUN, "sim")
CTL = {"H": "hold", "C": "centroid"}
SNAP = ('date -u +%FT%T.%3NZ; for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/temp 2>/dev/null) && echo -n "$(cat $z/type)=$t "; done; echo; '
        'for h in /sys/class/hwmon/hwmon*; do n=$(cat $h/name); [ "$n" = pwmfan ] && echo -n "fan_pwm=$(cat $h/pwm1) "; [ "$n" = pwm_tach ] && echo -n "fan_rpm=$(cat $h/rpm) "; done; '
        'echo "cpu_cur policy0=$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq) policy4=$(cat /sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq) gpu_cur=$(cat /sys/class/devfreq/17000000.gpu/cur_freq)"; '
        'pgrep -a -x "apt|apt-get|apt-helper|dpkg" || echo "no apt/dpkg"; systemctl list-jobs --no-pager | tail -1')


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


def block(tag, cond, rnd, dur, snaps, blocks):
    rec = {"tag": tag, "cond": cond, "round": rnd, "duration_s": dur}
    snaps.write(f"== {tag} ({cond}, round {rnd}) before\n{board(SNAP)}")
    if cond in CTL:
        out = board(f"bash /tmp/jn_final/scripts/mc_start.sh {tag} {CTL[cond]}")
        snaps.write(f"== {tag} mc_start\n{out}")
        snaps.flush()
        if "port 5555 listening" not in out or "listening 192.168.55.1:5555" not in out:
            print(f"{tag}: controller start failed:\n{out}", flush=True)
            raise SystemExit(2)
    txt, rec["mark_start_mono_ns"] = mark(f"{tag} start ({cond}, round {rnd})")
    print(txt, flush=True)
    if cond in CTL:
        args = ["run", "--scenario", "track-sine-v1", "--controller", "tcp://192.168.55.1:5555", "--mode", "realtime",
                "--duration", str(dur), "--out", "runs/stage1_20261031_final/sim"]
        log("mac", ".venv/bin/jn-sim " + " ".join(args))
        before = set(os.listdir(SIMDIR))
        r = subprocess.run([os.path.join(REPO, ".venv", "bin", "jn-sim"), *args], cwd=REPO, capture_output=True, text=True,
                           timeout=dur + 90)
        new = sorted(set(os.listdir(SIMDIR)) - before)
        rec["sim_rc"] = r.returncode
        rec["sim_dir"] = new[-1] if new else None
        with open(os.path.join(RUN, "raw", f"P2_{tag}_sim.txt"), "w") as f:
            f.write(f"rc {r.returncode}; new dirs {new}\n--- stdout\n{r.stdout}\n--- stderr\n{r.stderr}\n")
        print(f"{tag}: jn-sim rc {r.returncode}, dir {rec['sim_dir']}\n{r.stdout.strip()}", flush=True)
    else:
        log("mac", f"sleep {dur + 1}   (idle block {tag}: no controller, no marker)")
        time.sleep(dur + 1)
    txt, rec["mark_end_mono_ns"] = mark(f"{tag} end")
    print(txt, flush=True)
    if cond in CTL:
        out = board(f"bash /tmp/jn_final/scripts/mc_wait.sh {tag}")
        snaps.write(f"== {tag} mc_wait\n{out}")
        print(out.strip(), flush=True)
        rec["mc_csv"] = f"mc_{tag}.csv"
    snaps.write(f"== {tag} after\n{board(SNAP)}")
    snaps.flush()
    blocks.append(rec)
    with open(os.path.join(RUN, "raw", "P2_blocks.json"), "w") as f:
        json.dump(blocks, f, indent=1)


def main():
    what = sys.argv[1]
    bpath = os.path.join(RUN, "raw", "P2_blocks.json")
    blocks = json.load(open(bpath)) if os.path.exists(bpath) else []
    snaps = open(os.path.join(RUN, "raw", "P2_snapshots.txt"), "a")
    if what == "smoke":
        block("S", "H", 0, 10, snaps, blocks)
        return
    order = [line.split()[1:] for line in open(os.path.join(RUN, "raw", "order.txt")) if line.startswith("round")]
    for rnd, perm in enumerate(order, 1):
        for cond in perm:
            block(f"R{rnd}{cond}", cond, rnd, 60, snaps, blocks)
            log("mac", "sleep 10   (gap)")
            time.sleep(10)


if __name__ == "__main__":
    main()
