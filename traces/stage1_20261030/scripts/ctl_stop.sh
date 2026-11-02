#!/bin/bash
# Throwaway (board session 2026-10-26): stop the controller started by ctl_start.sh with SIGINT
# (= Ctrl-C), wait for it to exit, and confirm the port is closed.
L=/tmp/jn_board/board_cmds.log
P=$(cat /tmp/jn_board/ctl.pid 2>/dev/null)
if [ -z "$P" ] || ! kill -0 "$P" 2>/dev/null; then echo "no running controller (pid=$P)"; else
  printf '%s\t(ctl_stop.sh) kill -INT %s\n' "$(date -u +%FT%T.%3NZ)" "$P" >> "$L"
  kill -INT "$P"
  for i in $(seq 1 50); do kill -0 "$P" 2>/dev/null || break; sleep 0.1; done
  if kill -0 "$P" 2>/dev/null; then echo "pid $P still running after SIGINT"; else echo "pid $P exited"; fi
fi
ss -ltn | grep 5555 || echo "port 5555 closed"
pgrep -af 'jn_sim ctl' || echo "no jn_sim ctl process"
