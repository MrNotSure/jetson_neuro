#!/bin/bash
# Throwaway (board session 2026-10-26): E2 fan pinned vs auto, idle, 60 s each.
# auto (60 s) -> stop nvfancontrol, write the current pwm (never 0) -> pinned (60 s)
# -> start nvfancontrol, verify -> auto again (60 s). A 1 Hz logger watches temperatures and
# restarts the fan service at once if any zone reaches 85 C.
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(e2.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
PY=~/venvs/jn/bin/python; S=/tmp/jn_board/scripts/sampler.py; O=/tmp/jn_board/E2; mkdir -p $O
F=/sys/class/hwmon/hwmon0
TJ=/sys/class/thermal/thermal_zone8
state() { echo "$1: nvfancontrol=$(systemctl is-active nvfancontrol) pwm1=$(cat $F/pwm1) pwm1_enable=$(cat $F/pwm1_enable) rpm=$(cat /sys/class/hwmon/hwmon2/rpm) tj_policy=$(cat $TJ/policy) fan_cdev=$(cat /sys/class/thermal/cooling_device2/cur_state) tj=$(cat $TJ/temp)"; }
fanlog() { # fanlog N OUT
  echo "utc,pwm1,rpm,cpu,gpu,tj" > $2
  for i in $(seq 1 $1); do
    m=0; for z in 0 1 5 6 7 8; do t=$(cat /sys/class/thermal/thermal_zone$z/temp); [ $t -gt $m ] && m=$t; done
    echo "$(date -u +%T),$(cat $F/pwm1),$(cat /sys/class/hwmon/hwmon2/rpm),$(cat /sys/class/thermal/thermal_zone0/temp),$(cat /sys/class/thermal/thermal_zone1/temp),$(cat $TJ/temp)" >> $2
    if [ $m -ge 85000 ]; then echo "TEMP LIMIT $m"; sx sudo systemctl start nvfancontrol; return 1; fi
    sleep 1
  done
}
state before | tee $O/state.txt
fanlog 62 $O/fan_auto1.csv & FL=$!
$PY $S --rate 10 --duration 60 --out $O/e2_auto1.csv; wait $FL
P=$(cat $F/pwm1)
state "before stop (pin value P=$P)" | tee -a $O/state.txt
if [ "$P" -le 0 ]; then echo "REFUSED: pwm is 0"; exit 2; fi
sx sudo systemctl stop nvfancontrol
state "right after stop" | tee -a $O/state.txt
printf '%s\t(e2.sh) echo %s | sudo tee %s\n' "$(date -u +%FT%T.%3NZ)" "$P" "$F/pwm1" >> "$L"
echo "$P" | sudo tee $F/pwm1 > /dev/null
state "after pin write" | tee -a $O/state.txt
fanlog 62 $O/fan_pinned.csv & FL=$!
$PY $S --rate 10 --duration 60 --out $O/e2_pinned.csv; wait $FL
state "end of pinned" | tee -a $O/state.txt
sx sudo systemctl start nvfancontrol
sleep 5
state "after start" | tee -a $O/state.txt
fanlog 62 $O/fan_auto2.csv & FL=$!
$PY $S --rate 10 --duration 60 --out $O/e2_auto2.csv; wait $FL
state "end" | tee -a $O/state.txt
