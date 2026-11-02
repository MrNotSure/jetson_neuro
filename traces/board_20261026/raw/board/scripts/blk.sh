#!/bin/bash
# Throwaway (board session 2026-10-26): pilot block helper (board side).
# usage: blk.sh begin TAG COND   (COND = I | H | C)
#        blk.sh end   TAG COND
# begin: snapshot, start a fresh --once controller for H/C, then append the start mark.
# end:   append the end mark, wait for the --once controller to exit, snapshot.
# Marks: /tmp/jn_board/marks.csv  tag,cond,edge,mono_ns,utc   (board CLOCK_MONOTONIC)
PY=~/venvs/jn/bin/python
M=/tmp/jn_board/marks.csv
[ -f $M ] || echo "tag,cond,edge,mono_ns,utc" > $M
mark() { echo "$1,$2,$3,$($PY -c 'import time; print(time.monotonic_ns())'),$(date -u +%FT%T.%3NZ)" >> $M; }
act=$1; TAG=$2; COND=$3
if [ "$act" = begin ]; then
  bash /tmp/jn_board/scripts/snap.sh "${TAG}_pre" | tee -a /tmp/jn_board/snapshots.txt
  case $COND in
    H) bash /tmp/jn_board/scripts/ctl_start.sh "$TAG" hold --once > /dev/null ;;
    C) bash /tmp/jn_board/scripts/ctl_start.sh "$TAG" centroid --once > /dev/null ;;
  esac
  if [ "$COND" != I ]; then ss -ltn | grep -q '192.168.55.1:5555' && echo "listening" || echo "NOT LISTENING"; fi
  mark "$TAG" "$COND" start
else
  mark "$TAG" "$COND" end
  if [ "$COND" != I ]; then
    P=$(cat /tmp/jn_board/ctl.pid)
    for i in $(seq 1 50); do kill -0 "$P" 2>/dev/null || break; sleep 0.1; done
    if kill -0 "$P" 2>/dev/null; then echo "ctl $P still running; sending SIGINT"; kill -INT "$P"; sleep 1; fi
    kill -0 "$P" 2>/dev/null && echo "ctl $P STILL RUNNING" || echo "ctl exited"
  fi
  bash /tmp/jn_board/scripts/snap.sh "${TAG}_post" | tee -a /tmp/jn_board/snapshots.txt
fi
