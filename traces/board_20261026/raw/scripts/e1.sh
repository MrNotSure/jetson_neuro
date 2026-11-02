#!/bin/bash
# Throwaway (board session 2026-10-26): E1 radio off/on idle comparison, two cycles.
# Per cycle: arm auto-restore (sudo systemd-run --on-active=300 nmcli radio wifi on), radio off,
# 60 s idle sampling, radio on, wait 30 s, 60 s idle sampling. All sudo calls logged.
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(e1.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
PY=~/venvs/jn/bin/python; S=/tmp/jn_board/scripts/sampler.py; O=/tmp/jn_board/E1; mkdir -p $O
snap() { bash /tmp/jn_board/scripts/snap.sh "$1" >> /tmp/jn_board/snapshots.txt; }
echo "SSH_CONNECTION=$SSH_CONNECTION"
for cyc in 1 2; do
  sx sudo systemd-run --on-active=300 nmcli radio wifi on 2>&1 | tee -a $O/arm_${cyc}.txt
  sx sudo nmcli radio wifi off
  echo "cycle $cyc radio after off: $(nmcli radio wifi) $(nmcli -t -f DEVICE,STATE device | grep wlP1p1s0)"
  snap E1_${cyc}_off_before
  $PY $S --rate 10 --duration 60 --out $O/e1_${cyc}_off.csv
  snap E1_${cyc}_off_after
  sx sudo nmcli radio wifi on
  echo "cycle $cyc radio after on: $(nmcli radio wifi) $(nmcli -t -f DEVICE,STATE device | grep wlP1p1s0)"
  sleep 30
  snap E1_${cyc}_on_before
  $PY $S --rate 10 --duration 60 --out $O/e1_${cyc}_on.csv
  snap E1_${cyc}_on_after
done
echo "final radio: $(nmcli radio wifi)"; nmcli device | tee $O/nmcli_device_end.txt
systemctl list-timers --all --no-pager | grep -i run- | tee $O/transient_timers.txt
