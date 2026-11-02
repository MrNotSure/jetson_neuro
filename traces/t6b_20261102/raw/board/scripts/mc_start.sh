#!/bin/bash
# T6 (2 Nov 2026), board side: start mark_ctl.py detached with nohup, pinned to cpu 2, wait for "listening".
# usage: mc_start.sh TAG CONTROLLER   -> /tmp/jn_t6b/mc_TAG.{log,csv,pid}   (T6b: copied from T6, path only)
# From traces/stage1_20261031_final/scripts/mc_start.sh. Changes: /tmp/jn_t6; `taskset -c 2` in front of the
# python (spec R9.2); `taskset -cp PID` reported after "listening". The -c shim resets SIGINT to default before
# exec, so `kill -INT` (if ever needed) raises KeyboardInterrupt and mark_ctl's finally writes its CSV.
# taskset and the shim both exec, so the pid in mc_TAG.pid is the controller's.
set -e
TAG=$1; NAME=$2
D=/tmp/jn_t6b   # T6b, 2 Nov 2026 (T6: /tmp/jn_t6); nothing else changed
L=$D/board_cmds.log
LOG=$D/mc_${TAG}.log
OUT=$D/mc_${TAG}.csv
cd ~/jetson_neuro
printf '%s\t(mc_start.sh) cd ~/jetson_neuro && PYTHONPATH=src nohup taskset -c 2 ~/venvs/jn/bin/python -u %s --controller %s --listen 192.168.55.1:5555 --out %s\n' \
  "$(date -u +%FT%T.%3NZ)" "$D/scripts/mark_ctl.py" "$NAME" "$OUT" >> "$L"
PYTHONPATH=src nohup taskset -c 2 ~/venvs/jn/bin/python -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execv(sys.executable, [sys.executable, "-u", *sys.argv[1:]])' \
  "$D/scripts/mark_ctl.py" --controller "$NAME" --listen 192.168.55.1:5555 --out "$OUT" > "$LOG" 2>&1 < /dev/null &
echo $! > $D/mc_${TAG}.pid
for i in $(seq 1 100); do
  if grep -q '^listening' "$LOG" 2>/dev/null; then break; fi
  sleep 0.1
done
P=$(cat $D/mc_${TAG}.pid)
echo "pid=$P log: $(cat "$LOG")"
echo "affinity: $(taskset -cp $P 2>&1)"
echo "cmdline: $(tr '\0' ' ' < /proc/$P/cmdline 2>&1)"
if ss -ltn | grep -q ':5555 '; then echo "port 5555 listening"; else echo "NOT LISTENING"; fi
