#!/bin/bash
# Throwaway (board session 2026-10-26): start `jn-sim ctl` detached with nohup (no tmux on the board).
# usage: ctl_start.sh TAG CONTROLLER [extra ctl args...]
#   -> log /tmp/jn_board/ctl_TAG.log, pid /tmp/jn_board/ctl.pid
# A backgrounded command in a non-interactive shell inherits SIGINT=ignored, which would make
# Python skip its KeyboardInterrupt handler. The -c shim resets SIGINT to default and execs the
# real command, so `kill -INT` behaves exactly like Ctrl-C in a terminal.
set -e
TAG=$1; NAME=$2; shift 2
L=/tmp/jn_board/board_cmds.log
LOG=/tmp/jn_board/ctl_${TAG}.log
cd ~/jetson_neuro
PRE=()
if [ -n "$CTL_TASKSET" ]; then PRE=(taskset -c "$CTL_TASKSET"); fi
printf '%s\t(ctl_start.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "${PRE[*]} PYTHONPATH=src ~/venvs/jn/bin/python -u -m jn_sim ctl --controller $NAME --listen 192.168.55.1:5555 $*" >> "$L"
PYTHONPATH=src nohup "${PRE[@]}" ~/venvs/jn/bin/python -c 'import os, signal, sys; signal.signal(signal.SIGINT, signal.SIG_DFL); os.execv(sys.executable, [sys.executable, "-u", "-m", "jn_sim", *sys.argv[1:]])' \
  ctl --controller "$NAME" --listen 192.168.55.1:5555 "$@" > "$LOG" 2>&1 < /dev/null &
echo $! > /tmp/jn_board/ctl.pid
for i in $(seq 1 50); do
  if grep -q 'listening on' "$LOG" 2>/dev/null; then break; fi
  sleep 0.1
done
echo "pid=$(cat /tmp/jn_board/ctl.pid) $(cat "$LOG")"
ss -ltn | grep 5555 || echo "NOT LISTENING"
