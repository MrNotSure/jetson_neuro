#!/bin/bash
# T6 (2 Nov 2026), board side: wait for mark_ctl TAG to exit (serve(once=True) returns when the simulator closes
# the connection), then report its log, row count and the port. From the 31 Oct mc_wait.sh; path /tmp/jn_t6.
# usage: mc_wait.sh TAG
TAG=$1; D=/tmp/jn_t6
printf '%s\t(mc_wait.sh) wait for pid %s to exit\n' "$(date -u +%FT%T.%3NZ)" "$(cat $D/mc_${TAG}.pid)" >> $D/board_cmds.log
P=$(cat $D/mc_${TAG}.pid)
for i in $(seq 1 100); do kill -0 "$P" 2>/dev/null || break; sleep 0.1; done
if kill -0 "$P" 2>/dev/null; then echo "pid $P STILL RUNNING"; else echo "pid $P exited"; fi
echo "log: $(cat $D/mc_${TAG}.log)"
if [ -f $D/mc_${TAG}.csv ]; then echo "rows: $(($(wc -l < $D/mc_${TAG}.csv) - 1))"; head -2 $D/mc_${TAG}.csv | tail -1; tail -1 $D/mc_${TAG}.csv; else echo "NO CSV"; fi
if ss -ltn | grep -q ':5555 '; then echo "port 5555 STILL OPEN"; else echo "port 5555 closed"; fi
