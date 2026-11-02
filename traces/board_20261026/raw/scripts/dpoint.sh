#!/bin/bash
# Throwaway (board session 2026-10-26): Part D per-point measurements (board side).
# usage: dpoint.sh idle LABEL        -> clock state + 30 s idle sampling (10 Hz), nothing else running
#        dpoint.sh loadbegin LABEL   -> start 40 s sampler, 1 Hz sysfs freq log, `sudo tegrastats
#                                       --interval 1000 | head -40`, then a fresh --once centroid
#        dpoint.sh loadend LABEL     -> end mark, wait for the loggers, clock state
L=/tmp/jn_board/board_cmds.log
O=/tmp/jn_board/D; mkdir -p $O
PY=~/venvs/jn/bin/python
act=$1; LB=$2
freqlog() { # 1 Hz, sysfs only (no sudo)
  echo "utc,mono_s,p0_cur,p4_cur,cpu0,cpu1,cpu2,cpu3,cpu4,cpu5,gpu_cur,bwmgr_cur,cpu_temp,gpu_temp,tj_temp,fan_pwm"
  for i in $(seq 1 $1); do
    echo "$(date -u +%T.%3N),$(cut -d' ' -f1 /proc/uptime),$(cat /sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq),$(cat /sys/devices/system/cpu/cpufreq/policy4/scaling_cur_freq),$(for c in 0 1 2 3 4 5; do printf '%s,' $(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_cur_freq); done)$(cat /sys/class/devfreq/17000000.gpu/cur_freq),$(cat /sys/class/devfreq/bwmgr/cur_freq),$(cat /sys/class/thermal/thermal_zone0/temp),$(cat /sys/class/thermal/thermal_zone1/temp),$(cat /sys/class/thermal/thermal_zone8/temp),$(cat /sys/class/hwmon/hwmon0/pwm1)"
    sleep 1
  done
}
case $act in
  idle)
    bash /tmp/jn_board/scripts/clkstate.sh "${LB}_idle_pre" > $O/${LB}_state_pre.txt
    $PY /tmp/jn_board/scripts/sampler.py --rate 10 --duration 30 --out $O/${LB}_idle_10hz.csv
    grep -E '^L (rails|/sys/kernel/debug/bpmp)|^L temp tj|^S .*policy[04]/scaling_(min|max)|^S /sys/class/devfreq/17000000.gpu/(min|max)' $O/${LB}_state_pre.txt
    ;;
  loadbegin)
    nohup $PY /tmp/jn_board/scripts/sampler.py --rate 10 --duration 40 --out $O/${LB}_load_10hz.csv > /dev/null 2>&1 < /dev/null &
    nohup bash -c "$(declare -f freqlog); freqlog 40" > $O/${LB}_load_freqlog.csv 2>&1 < /dev/null &
    printf '%s\t(dpoint.sh) sudo tegrastats --interval 1000 | head -40\n' "$(date -u +%FT%T.%3NZ)" >> "$L"
    nohup bash -c "sudo tegrastats --interval 1000 | head -40" > $O/${LB}_load_tegrastats.txt 2>&1 < /dev/null &
    sleep 1
    bash /tmp/jn_board/scripts/blk.sh begin "D_${LB}" C
    ;;
  loadend)
    bash /tmp/jn_board/scripts/blk.sh end "D_${LB}" C
    for i in $(seq 1 15); do pgrep -f "sampler.py --rate 10 --duration 40" > /dev/null || break; sleep 1; done
    sleep 2
    pgrep -a tegrastats || echo "tegrastats exited"
    bash /tmp/jn_board/scripts/clkstate.sh "${LB}_load_post" > $O/${LB}_state_post.txt
    grep -E '^L (rails|/sys/kernel/debug/bpmp)|^L temp tj|^S .*policy[04]/scaling_(min|max)|^S /sys/class/devfreq/17000000.gpu/(min|max)' $O/${LB}_state_post.txt
    echo "freqlog distinct values per column:"
    $PY -c "
import csv,sys
r=list(csv.DictReader(open('$O/${LB}_load_freqlog.csv')))
for c in ('p0_cur','p4_cur','cpu0','cpu4','gpu_cur','bwmgr_cur'):
    print(' ',c,sorted(set(x[c] for x in r)), 'n=',len(r))
print('  tj_temp max', max(int(x['tj_temp']) for x in r))
"
    ;;
esac
