#!/bin/bash
# Stage 1 final (31 Oct 2026), board side: start mark_ctl.py detached with nohup, wait for "listening".
# usage: mc_start.sh TAG CONTROLLER   -> /tmp/jn_final/mc_TAG.{log,csv,pid}
# Based on traces/stage1_20261029/scripts/ctl_start.sh: the -c shim resets SIGINT to default before
# exec, so `kill -INT` (if ever needed) raises KeyboardInterrupt and mark_ctl's finally writes its CSV.
set -e
TAG=$1; NAME=$2
D=/tmp/jn_final
L=$D/board_cmds.log
LOG=$D/mc_${TAG}.log
OUT=$D/mc_${TAG}.csv
cd ~/jetson_neuro
printf '%s\t(mc_start.sh) cd ~/jetson_neuro && PYTHONPATH=src nohup ~/venvs/jn/bin/python -u %s --controller %s --listen 192.168.55.1:5555 --out %s\n' \
  "$(date -u +%FT%T.%3NZ)" "$D/scripts/mark_ctl.py" "$NAME" "$OUT" >> "$L"
PYTHONPATH=src nohup ~/venvs/jn/bin/python -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execv(sys.executable, [sys.executable, "-u", *sys.argv[1:]])' \
  "$D/scripts/mark_ctl.py" --controller "$NAME" --listen 192.168.55.1:5555 --out "$OUT" > "$LOG" 2>&1 < /dev/null &
echo $! > $D/mc_${TAG}.pid
for i in $(seq 1 100); do
  if grep -q '^listening' "$LOG" 2>/dev/null; then break; fi
  sleep 0.1
done
echo "pid=$(cat $D/mc_${TAG}.pid) log: $(cat "$LOG")"
if ss -ltn | grep -q ':5555 '; then echo "port 5555 listening"; else echo "NOT LISTENING"; fi
