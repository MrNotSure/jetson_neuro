#!/bin/bash
# Throwaway (board session 2026-10-26): Part D clock point. Locks every CPU policy to CPU_KHZ
# (scaling_min_freq = scaling_max_freq) and the GPU devfreq to GPU_HZ (min_freq = max_freq).
# Only these four kinds of file are written; each write is `echo V | sudo tee FILE`, logged,
# and read back immediately. Order keeps min <= max: if the target is <= the current max,
# min is written first, otherwise max first.
# usage: setclk.sh CPU_KHZ GPU_HZ
set -u
L=/tmp/jn_board/board_cmds.log
CPU=$1; GPU=$2
CPU_CAP=1344000; GPU_CAP=918000000   # 25 W mode caps from /etc/nvpmodel.conf (POWER_MODEL ID=1)
die() { echo "REFUSED: $*"; exit 2; }
grep -qw "$CPU" /sys/devices/system/cpu/cpufreq/policy0/scaling_available_frequencies || die "cpu $CPU not in available list"
grep -qw "$GPU" /sys/class/devfreq/17000000.gpu/available_frequencies || die "gpu $GPU not in available list"
[ "$CPU" -le $CPU_CAP ] || die "cpu $CPU above 25 W cap"
[ "$GPU" -le $GPU_CAP ] || die "gpu $GPU above 25 W cap"
wr() { # wr VALUE FILE
  case "$2" in
    /sys/devices/system/cpu/cpufreq/policy[0-9]*/scaling_min_freq|/sys/devices/system/cpu/cpufreq/policy[0-9]*/scaling_max_freq|/sys/class/devfreq/17000000.gpu/min_freq|/sys/class/devfreq/17000000.gpu/max_freq) ;;
    *) die "write target not allowed: $2" ;;
  esac
  printf '%s\t(setclk.sh) echo %s | sudo tee %s\n' "$(date -u +%FT%T.%3NZ)" "$1" "$2" >> "$L"
  echo "$1" | sudo tee "$2" > /dev/null
  rc=$?
  echo "  write $2 <- $1 rc=$rc readback=$(cat $2)"
}
pair() { # pair DIR MINFILE MAXFILE TARGET
  local cur_max; cur_max=$(cat "$3")
  if [ "$4" -le "$cur_max" ]; then wr "$4" "$2"; wr "$4" "$3"; else wr "$4" "$3"; wr "$4" "$2"; fi
}
echo "# setclk cpu=$CPU kHz gpu=$GPU Hz utc=$(date -u +%FT%T.%3NZ)"
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  pair cpu $p/scaling_min_freq $p/scaling_max_freq "$CPU"
done
G=/sys/class/devfreq/17000000.gpu
pair gpu $G/min_freq $G/max_freq "$GPU"
sleep 1
ok=1
for p in /sys/devices/system/cpu/cpufreq/policy*; do
  mn=$(cat $p/scaling_min_freq); mx=$(cat $p/scaling_max_freq); cu=$(cat $p/scaling_cur_freq)
  echo "  verify ${p##*/}: min=$mn max=$mx cur=$cu"
  [ "$mn" = "$CPU" ] && [ "$mx" = "$CPU" ] || ok=0
done
mn=$(cat $G/min_freq); mx=$(cat $G/max_freq); cu=$(cat $G/cur_freq)
echo "  verify gpu: min=$mn max=$mx cur=$cu"
[ "$mn" = "$GPU" ] && [ "$mx" = "$GPU" ] || ok=0
echo "  setclk result: $([ $ok = 1 ] && echo OK || echo MISMATCH)"
