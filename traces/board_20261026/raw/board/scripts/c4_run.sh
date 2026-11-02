#!/bin/zsh
# Throwaway (board session 2026-10-26): C4 pilot driver (Mac). Starts the continuous board
# sampler, waits 20 s, runs the 12 blocks via pilot.py, waits 10 s, stops the sampler.
# usage: c4_run.sh ORDER_FILE OUT_JSON TAG RATE
B=/private/tmp/jn_board_scripts/b
ORDER=$1; OUT=$2; TAG=$3; RATE=${4:-10}
cd /Users/<user>/Documents/code/jetson_neuro
$B "mkdir -p /tmp/jn_board/C4; nohup ~/venvs/jn/bin/python /tmp/jn_board/scripts/sampler.py --rate $RATE --duration 0 --out /tmp/jn_board/C4/${TAG}_sampler_${RATE}hz.csv > /tmp/jn_board/C4/${TAG}_sampler.log 2>&1 < /dev/null & echo \$! > /tmp/jn_board/C4/${TAG}_sampler.pid; bash /tmp/jn_board/scripts/snap.sh ${TAG}_sampler_start | tee -a /tmp/jn_board/snapshots.txt"
sleep 20
.venv/bin/python /private/tmp/jn_board_scripts/pilot.py "$ORDER" "$OUT" --tag=$TAG
sleep 10
$B "kill -TERM \$(cat /tmp/jn_board/C4/${TAG}_sampler.pid); sleep 1; cat /tmp/jn_board/C4/${TAG}_sampler_${RATE}hz.csv.meta.json | head -c 600; bash /tmp/jn_board/scripts/snap.sh ${TAG}_sampler_stop | tee -a /tmp/jn_board/snapshots.txt"
