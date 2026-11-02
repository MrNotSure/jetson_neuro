#!/bin/bash
# Throwaway (board session 2026-10-26): C1 sampler characterisation at 10/100/1000 Hz and max rate.
# Board idle, default DVFS. Each mode 5 s (10 Hz: 20 s so there are enough samples), 3 s gap.
PY=~/venvs/jn/bin/python; S=/tmp/jn_board/scripts/sampler.py; O=/tmp/jn_board/C1; mkdir -p $O
bash /tmp/jn_board/scripts/snap.sh C1_before >> /tmp/jn_board/snapshots.txt
$PY $S --rate 10   --duration 20 --out $O/c1_10hz.csv;   sleep 3
$PY $S --rate 100  --duration 5  --out $O/c1_100hz.csv;  sleep 3
$PY $S --rate 1000 --duration 5  --out $O/c1_1000hz.csv; sleep 3
$PY $S --rate 0    --duration 5  --out $O/c1_max.csv
bash /tmp/jn_board/scripts/snap.sh C1_after >> /tmp/jn_board/snapshots.txt
for f in $O/*.meta.json; do echo "$f: $(tr -d '\n ' < $f | head -c 400)"; done
