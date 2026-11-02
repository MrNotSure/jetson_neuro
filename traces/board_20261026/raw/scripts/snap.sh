#!/bin/bash
# Throwaway (board session 2026-10-26): one-line, read-only board state snapshot.
# usage: snap.sh LABEL   -> prints one "key=value ..." line to stdout
# The only sudo used is `sudo cat` of a debugfs file; each sudo call is logged to
# /tmp/jn_board/board_cmds.log (merged into commands.log on the Mac).
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(snap.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
out="label=$1 utc=$(date -u +%FT%T.%3NZ)"
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  n=${p##*/}
  out+=" ${n}_gov=$(cat $p/scaling_governor) ${n}_cur=$(cat $p/scaling_cur_freq) ${n}_min=$(cat $p/scaling_min_freq) ${n}_max=$(cat $p/scaling_max_freq)"
done
for c in 0 1 2 3 4 5; do out+=" cpu${c}_cur=$(cat /sys/devices/system/cpu/cpu$c/cpufreq/scaling_cur_freq 2>/dev/null || echo off)"; done
G=/sys/class/devfreq/17000000.gpu
out+=" gpu_gov=$(cat $G/governor) gpu_cur=$(cat $G/cur_freq) gpu_min=$(cat $G/min_freq) gpu_max=$(cat $G/max_freq)"
out+=" bwmgr_cur=$(cat /sys/class/devfreq/bwmgr/cur_freq)"
out+=" emc_rate=$(sx sudo cat /sys/kernel/debug/bpmp/debug/clk/emc/rate)"
for z in /sys/class/thermal/thermal_zone*; do
  t=$(cat $z/temp 2>/dev/null) && out+=" $(cat $z/type)=$t"
done
out+=" fan_pwm=$(cat /sys/class/hwmon/hwmon0/pwm1) fan_pwm_enable=$(cat /sys/class/hwmon/hwmon0/pwm1_enable) fan_rpm=$(cat /sys/class/hwmon/hwmon2/rpm)"
out+=" fan_cdev=$(cat /sys/class/thermal/cooling_device2/cur_state)"
out+=" nvfancontrol=$(systemctl is-active nvfancontrol)"
out+=" pmode=\"$(nvpmodel -q 2>/dev/null | head -1 | sed 's/NV Power Mode: //')\""
out+=" wifi_radio=$(nmcli radio wifi 2>/dev/null)"
out+=" online=$(cat /sys/devices/system/cpu/online)"
echo "$out"
