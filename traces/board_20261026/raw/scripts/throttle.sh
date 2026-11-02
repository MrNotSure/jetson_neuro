#!/bin/bash
# Throwaway (board session 2026-10-26): read every throttle / over-current indicator (read-only).
# usage: throttle.sh LABEL
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(throttle.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
echo "### throttle indicators label=$1 utc=$(date -u +%FT%T.%3NZ)"
echo "## soctherm_oc hwmon (/sys/class/hwmon/hwmon3)"
for f in /sys/class/hwmon/hwmon3/oc*; do echo "$f=$(cat $f)"; done
echo "## ina3221 alarms (/sys/class/hwmon/hwmon4)"
for f in /sys/class/hwmon/hwmon4/*alarm*; do echo "$f=$(cat $f)"; done
echo "## files matching *throt*|*oc*_event*|*alarm* under the power-monitor and soctherm device trees"
for f in $(find /sys/devices/platform/soctherm-oc-event /sys/devices/platform/bus@0/c240000.i2c/i2c-1/1-0040 -maxdepth 4 -type f \( -name '*throt*' -o -name '*oc*_event*' -o -name '*alarm*' \) 2>/dev/null | sort); do
  echo "$f=$(cat $f 2>&1)"
done
echo "## throttle-alert cooling devices"
for c in /sys/class/thermal/cooling_device*; do
  t=$(cat $c/type)
  case "$t" in *throttle*|*alert*|pwm-fan|cpufreq*|devfreq*) echo "$c type=$t cur_state=$(cat $c/cur_state) max_state=$(cat $c/max_state)";; esac
done
echo "## cpufreq stats (time_in_state totals and transitions)"
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  echo "$p/stats/total_trans=$(cat $p/stats/total_trans 2>&1)"
done
echo "## bpmp debugfs throttle-related files (sudo cat, read-only)"
for f in /sys/kernel/debug/bpmp/debug/soctherm/throt_counters /sys/kernel/debug/bpmp/debug/soctherm/oc_counters; do
  echo "$f:"; sx sudo cat "$f" 2>&1 | head -40
done
