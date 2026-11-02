#!/bin/bash
# Throwaway (board session 2026-10-26): C1 step-response test. Sampler at max rate for 11 s,
# 6-core busy bursts of 1000/300/100/30/10 ms at known monotonic times.
PY=~/venvs/jn/bin/python; O=/tmp/jn_board/C1; mkdir -p $O
bash /tmp/jn_board/scripts/snap.sh C1step_before >> /tmp/jn_board/snapshots.txt
$PY /tmp/jn_board/scripts/sampler.py --rate 0 --duration 11 --out $O/c1_step_max.csv &
SP=$!
sleep 0.3
$PY /tmp/jn_board/scripts/step.py $O/c1_step_marks.csv
wait $SP
bash /tmp/jn_board/scripts/snap.sh C1step_after >> /tmp/jn_board/snapshots.txt
# same at a 100 Hz sampler, to see what a realistic logger rate sees
$PY /tmp/jn_board/scripts/sampler.py --rate 100 --duration 11 --out $O/c1_step_100hz.csv &
SP=$!
sleep 0.3
$PY /tmp/jn_board/scripts/step.py $O/c1_step_marks_100hz.csv
wait $SP
bash /tmp/jn_board/scripts/snap.sh C1step100_after >> /tmp/jn_board/snapshots.txt
tail -3 /tmp/jn_board/snapshots.txt
