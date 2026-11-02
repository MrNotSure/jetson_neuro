#!/bin/bash
# Throwaway (board session 2026-10-26): probe READ-ONLY debugfs sources for clock rates and
# DVFS voltages (sudo cat of files under /sys/kernel/debug only; missing files just error).
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(dprobe.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
echo "# dprobe utc=$(date -u +%FT%T.%3NZ)"
echo "## /sys/kernel/debug/clk/clk_summary (grep cpu|gpc|gpu|emc|nafll|cluster)"
sx sudo cat /sys/kernel/debug/clk/clk_summary 2>&1 | grep -i -E 'clock|----|cpu|gpc|gpu|emc|nafll|cluster|ccplex' | head -60
echo "## /sys/kernel/debug/regulator/regulator_summary"
sx sudo cat /sys/kernel/debug/regulator/regulator_summary 2>&1 | head -60
for c in nafll_cluster0 nafll_cluster1 nafll_cluster2 nafll_gpc0 nafll_gpc1 gpc0clk gpc1clk gpusysclk nafll_gpusys; do
  for f in rate dvfs; do
    echo "## /sys/kernel/debug/bpmp/debug/clk/$c/$f"
    sx sudo cat /sys/kernel/debug/bpmp/debug/clk/$c/$f 2>&1 | head -30
  done
done
