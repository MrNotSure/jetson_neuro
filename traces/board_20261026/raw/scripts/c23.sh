#!/bin/bash
# Throwaway (board session 2026-10-26): C2 idle noise (300 s at 10 Hz) then C3 sampler cost
# (10 Hz vs 1000 Hz requested, 60 s each, alternated twice: 10,1000,10,1000). Board idle.
PY=~/venvs/jn/bin/python; S=/tmp/jn_board/scripts/sampler.py; O=/tmp/jn_board/C23; mkdir -p $O
snap() { bash /tmp/jn_board/scripts/snap.sh "$1" >> /tmp/jn_board/snapshots.txt; }
snap C2_before
$PY $S --rate 10 --duration 300 --out $O/c2_idle_10hz_300s.csv
snap C2_after
sleep 5
i=0
for r in 10 1000 10 1000; do
  i=$((i+1))
  snap C3_${i}_${r}hz_before
  $PY $S --rate $r --duration 60 --out $O/c3_${i}_${r}hz.csv
  snap C3_${i}_${r}hz_after
  sleep 3
done
echo "c23 done $(date -u +%FT%T.%3NZ)" > $O/done.txt
