#!/bin/zsh
# Throwaway (board session 2026-10-26): E3 CPU pinning. 60 s centroid realtime runs with the
# board controller unpinned, under taskset -c 2, and under taskset -c 0 (the USB IRQ core).
B=/private/tmp/jn_board_scripts/b
cd /Users/<user>/Documents/code/jetson_neuro
for cfg in none 2 0; do
  if [ $cfg = none ]; then pre=""; else pre="CTL_TASKSET=$cfg"; fi
  $B "bash /tmp/jn_board/scripts/snap.sh E3_${cfg}_pre >> /tmp/jn_board/snapshots.txt; $pre bash /tmp/jn_board/scripts/ctl_start.sh E3_pin_${cfg} centroid --once; P=\$(cat /tmp/jn_board/ctl.pid); echo affinity: \$(taskset -cp \$P)"
  .venv/bin/jn-sim run --scenario track-sine-v1 --controller tcp://192.168.55.1:5555 --mode realtime --duration 60 --out runs/board_20261026/runs 2>&1 | head -3
  $B "sleep 1; pgrep -af 'jn_sim ctl' || echo 'ctl exited'; bash /tmp/jn_board/scripts/snap.sh E3_${cfg}_post | tee -a /tmp/jn_board/snapshots.txt | grep -o 'tj-thermal=[0-9]*'"
  sleep 5
done
