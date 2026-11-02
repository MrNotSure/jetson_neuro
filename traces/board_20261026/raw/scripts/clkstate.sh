#!/bin/bash
# Throwaway (board session 2026-10-26): full clock state dump, READ-ONLY.
# usage: clkstate.sh LABEL  -> stdout. Static lines are prefixed "S " (compared in the restore
# diff); live values (current frequencies, temperatures, rail readings) are prefixed "L ".
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(clkstate.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
echo "# clkstate label=$1 utc=$(date -u +%FT%T.%3NZ)"
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  for f in affected_cpus scaling_governor scaling_min_freq scaling_max_freq; do echo "S $p/$f=$(cat $p/$f)"; done
  echo "L $p/scaling_cur_freq=$(cat $p/scaling_cur_freq)"
done
for c in /sys/devices/system/cpu/cpu[0-9]*; do
  echo "S $c/online=$(cat $c/online 2>/dev/null || echo NA)"
  echo "S $c/cpufreq/scaling_min_freq=$(cat $c/cpufreq/scaling_min_freq) scaling_max_freq=$(cat $c/cpufreq/scaling_max_freq)"
  for s in $c/cpuidle/state*; do echo "S $s/disable=$(cat $s/disable) ($(cat $s/name))"; done
  echo "L $c/cpufreq/scaling_cur_freq=$(cat $c/cpufreq/scaling_cur_freq)"
done
G=/sys/class/devfreq/17000000.gpu
for f in governor min_freq max_freq polling_interval; do echo "S $G/$f=$(cat $G/$f)"; done
for f in cur_freq target_freq; do echo "L $G/$f=$(cat $G/$f)"; done
echo "S /sys/devices/platform/gpu.0/railgate_enable=$(cat /sys/devices/platform/gpu.0/railgate_enable 2>&1)"
echo "S /sys/devices/platform/gpu.0/power/control=$(cat /sys/devices/platform/gpu.0/power/control 2>&1)"
echo "L /sys/devices/platform/gpu.0/power/runtime_status=$(cat /sys/devices/platform/gpu.0/power/runtime_status 2>&1)"
W=/sys/class/devfreq/bwmgr
for f in governor min_freq max_freq; do echo "S $W/$f=$(cat $W/$f)"; done
for f in cur_freq target_freq; do echo "L $W/$f=$(cat $W/$f)"; done
E=/sys/kernel/debug/bpmp/debug/clk/emc
for f in min_rate max_rate mrq_rate_locked; do echo "S $E/$f=$(sx sudo cat $E/$f)"; done
echo "L $E/rate=$(sx sudo cat $E/rate)"
for c in nafll_cluster0_core nafll_cluster1_core gpc0clk; do
  echo "L /sys/kernel/debug/bpmp/debug/clk/$c/rate=$(sx sudo cat /sys/kernel/debug/bpmp/debug/clk/$c/rate)"
done
TJ=$(grep -il tj-thermal /sys/class/thermal/thermal_zone*/type | xargs dirname)
echo "S $TJ/policy=$(cat $TJ/policy)"
echo "S nvfancontrol=$(systemctl is-active nvfancontrol)"
echo "S /sys/class/hwmon/hwmon0/pwm1_enable=$(cat /sys/class/hwmon/hwmon0/pwm1_enable)"
echo "L /sys/class/hwmon/hwmon0/pwm1=$(cat /sys/class/hwmon/hwmon0/pwm1) rpm=$(cat /sys/class/hwmon/hwmon2/rpm)"
echo "S nvpmodel=$(nvpmodel -q 2>/dev/null | head -1)"
echo "S cpu_online=$(cat /sys/devices/system/cpu/online)"
H=/sys/class/hwmon/hwmon4
echo "L rails in1=$(cat $H/in1_input)mV curr1=$(cat $H/curr1_input)mA in2=$(cat $H/in2_input)mV curr2=$(cat $H/curr2_input)mA in3=$(cat $H/in3_input)mV curr3=$(cat $H/curr3_input)mA"
for z in /sys/class/thermal/thermal_zone*; do t=$(cat $z/temp 2>/dev/null) && echo "L temp $(cat $z/type)=$t"; done
echo "## sudo jetson_clocks --show"
sx sudo jetson_clocks --show | sed 's/^/L jc /'
