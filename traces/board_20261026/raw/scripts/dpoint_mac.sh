#!/bin/zsh
# Throwaway (board session 2026-10-26): Part D point driver (Mac). Assumes the point is set.
# usage: dpoint_mac.sh LABEL
B=/private/tmp/jn_board_scripts/b
LB=$1
cd /Users/<user>/Documents/code/jetson_neuro
echo "== $LB idle (30 s)"
$B "bash /tmp/jn_board/scripts/dpoint.sh idle $LB"
echo "== $LB load (30 s centroid realtime)"
$B "bash /tmp/jn_board/scripts/dpoint.sh loadbegin $LB" | grep -v '^label='
.venv/bin/jn-sim run --scenario track-sine-v1 --controller tcp://192.168.55.1:5555 --mode realtime --out runs/board_20261026/runs 2>&1 | head -3
$B "bash /tmp/jn_board/scripts/dpoint.sh loadend $LB" | grep -v '^label='
