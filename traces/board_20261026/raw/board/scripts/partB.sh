#!/bin/bash
# Throwaway (board session 2026-10-26): Part B system facts. READ-ONLY.
# Every sudo call goes through sx() and is logged to /tmp/jn_board/board_cmds.log.
# Allowed sudo here: sudo cat <debugfs file>, sudo nvpmodel -q --verbose, sudo jetson_clocks --show,
# sudo ufw status, sudo tegrastats.
L=/tmp/jn_board/board_cmds.log
sx() { printf '%s\t(partB.sh) %s\n' "$(date -u +%FT%T.%3NZ)" "$*" >> "$L"; "$@"; }
O=/tmp/jn_board/B; mkdir -p $O
dumpdir() { # dumpdir DIR : every regular file in DIR (non-recursive) with its value
  for f in "$1"/*; do [ -f "$f" ] || continue; printf '%s\t%s\t%s\n' "${f##*/}" "$(stat -c %A "$f")" "$(cat "$f" 2>&1 | head -c 2000 | tr '\n' ' ')"; done
}
PY=~/venvs/jn/bin/python

{ echo "## /etc/nv_tegra_release"; cat /etc/nv_tegra_release
  echo "## uname -a"; uname -a
  echo "## lscpu"; lscpu
  echo "## /sys/devices/system/cpu/{online,offline,possible,present}"
  for f in online offline possible present; do echo "$f=$(cat /sys/devices/system/cpu/$f)"; done
  echo "## cpuidle driver/governor"
  dumpdir /sys/devices/system/cpu/cpuidle
  echo "## cpuidle states per cpu (name desc latency residency disable usage time_us)"
  for c in /sys/devices/system/cpu/cpu[0-9]*; do
    for s in $c/cpuidle/state*; do [ -d "$s" ] || continue
      echo "${c##*/} ${s##*/} name=$(cat $s/name) desc=\"$(cat $s/desc)\" latency=$(cat $s/latency) residency=$(cat $s/residency) disable=$(cat $s/disable) usage=$(cat $s/usage) time=$(cat $s/time)"
    done
  done
  echo "## free -m"; free -m
  echo "## df -h /"; df -h /
  echo "## venv python"; $PY -c 'import sys, platform, time, numpy; print(sys.version); print(sys.executable); print(platform.platform()); print("numpy", numpy.__version__); print("monotonic", time.get_clock_info("monotonic")); print("perf_counter", time.get_clock_info("perf_counter")); print("clock_getres(CLOCK_MONOTONIC)", time.clock_getres(time.CLOCK_MONOTONIC))'
  echo "## /proc/cmdline"; cat /proc/cmdline
  echo "## clocksource"; cat /sys/devices/system/clocksource/clocksource0/current_clocksource /sys/devices/system/clocksource/clocksource0/available_clocksource
  echo "## uptime"; uptime
} > $O/B1_system.txt 2>&1

{ echo "## sudo nvpmodel -q --verbose"; sx sudo nvpmodel -q --verbose
  echo "## nvpmodel.conf location"; ls -la /etc/nvpmodel.conf; readlink -f /etc/nvpmodel.conf; ls -la /etc/nvpmodel/ 2>&1
  echo "## /var/lib/nvpmodel"; ls -la /var/lib/nvpmodel; cat /var/lib/nvpmodel/status; echo; cat /var/lib/nvpmodel/conf_file_path 2>&1; echo
} > $O/B2_nvpmodel.txt 2>&1
cp -L /etc/nvpmodel.conf $O/nvpmodel.conf

{ echo "## hwmon names"; for h in /sys/class/hwmon/hwmon*; do echo "$h name=$(cat $h/name) -> $(readlink -f $h)"; done
  D=/sys/bus/i2c/drivers/ina3221/1-0040/hwmon/hwmon4
  echo "## ls -la $D"; ls -la $D/
  echo "## $D files (name perms value)"; dumpdir $D
  echo "## device: /sys/bus/i2c/drivers/ina3221/1-0040"; ls -la /sys/bus/i2c/drivers/ina3221/1-0040/; dumpdir /sys/bus/i2c/drivers/ina3221/1-0040
  echo "## device-tree node (of_node) properties"
  N=$(readlink -f /sys/bus/i2c/drivers/ina3221/1-0040/of_node)
  echo "of_node=$N"
  find "$N" -type f | sort | while read f; do printf '%s\t' "${f#$N/}"; od -An -c "$f" | tr -s ' ' | tr '\n' ' ' | head -c 300; printf '\t|hex '; od -An -tx1 "$f" | tr -s ' ' | tr '\n' ' ' | head -c 200; echo; done
  echo "## power/ runtime"; dumpdir $D/power 2>/dev/null; dumpdir /sys/bus/i2c/drivers/ina3221/1-0040/power
  echo "## i2c adapter"; cat /sys/bus/i2c/devices/i2c-1/name 2>&1
} > $O/B3_ina3221.txt 2>&1

{ echo "## which tegrastats"; which tegrastats; ls -la $(which tegrastats); readlink -f $(which tegrastats)
  echo "## tegrastats --help"; tegrastats --help 2>&1
  echo "## tegrastats --version"; tegrastats --version 2>&1
  echo "## dpkg owner"; dpkg -S $(readlink -f $(which tegrastats)) 2>&1; dpkg -l nvidia-l4t-tools 2>&1 | tail -2
} > $O/B4_tegrastats_help.txt 2>&1
{ echo "## tegrastats --interval 100 | head -10 (no sudo) start $(date -u +%FT%T.%3NZ)"; tegrastats --interval 100 | head -10; echo "end $(date -u +%FT%T.%3NZ)"; } > $O/B4_tegrastats_100_nosudo.txt 2>&1
{ echo "## tegrastats --interval 1000 | head -10 (no sudo) start $(date -u +%FT%T.%3NZ)"; tegrastats --interval 1000 | head -10; echo "end $(date -u +%FT%T.%3NZ)"; } > $O/B4_tegrastats_1000_nosudo.txt 2>&1
{ echo "## sudo tegrastats --interval 100 | head -10 start $(date -u +%FT%T.%3NZ)"; sx sudo tegrastats --interval 100 | head -10; echo "end $(date -u +%FT%T.%3NZ)"; } > $O/B4_tegrastats_100_sudo.txt 2>&1
{ echo "## sudo tegrastats --interval 1000 | head -10 start $(date -u +%FT%T.%3NZ)"; sx sudo tegrastats --interval 1000 | head -10; echo "end $(date -u +%FT%T.%3NZ)"; } > $O/B4_tegrastats_1000_sudo.txt 2>&1
sleep 1; pgrep -a tegrastats > $O/B4_tegrastats_leftover.txt 2>&1 || echo "no tegrastats process left" > $O/B4_tegrastats_leftover.txt

{ for p in /sys/devices/system/cpu/cpufreq/policy*; do echo "## $p"; dumpdir $p; echo "# $p/stats"; dumpdir $p/stats; done
  echo "## cpufreq boost"; cat /sys/devices/system/cpu/cpufreq/boost 2>&1
  for c in 0 1 2 3 4 5; do echo "cpu$c cpufreq -> $(readlink -f /sys/devices/system/cpu/cpu$c/cpufreq)"; done
} > $O/B5_cpufreq.txt 2>&1
{ for d in /sys/class/devfreq/*; do echo "## $d -> $(readlink -f $d)"; dumpdir $d; done
  G=$(readlink -f /sys/class/devfreq/17000000.gpu)/../..
  echo "## GPU device dir $(readlink -f $G)"; dumpdir $(readlink -f $G)
} > $O/B5_devfreq.txt 2>&1
{ E=/sys/kernel/debug/bpmp/debug/clk/emc
  for f in rate max_rate min_rate mrq_rate_locked state flags parent refcount vdd_core dvfs dvfs_table hz_off mrqcount pto_counter; do
    echo "## sudo cat $E/$f"; sx sudo cat $E/$f 2>&1 | head -60; echo
  done
  echo "## nvpmodel EMC cap"; ls -la /sys/kernel/nvpmodel_emc_cap/ 2>&1; for f in /sys/kernel/nvpmodel_emc_cap/*; do echo "$f=$(cat $f 2>&1)"; done
  echo "## bwmgr devfreq"; dumpdir /sys/class/devfreq/bwmgr
  echo "## sudo jetson_clocks --show"; sx sudo jetson_clocks --show
} > $O/B5_emc_jetson_clocks.txt 2>&1

{ for z in /sys/class/thermal/thermal_zone*; do
    echo "## $z type=$(cat $z/type) temp=$(cat $z/temp 2>&1) mode=$(cat $z/mode 2>&1) policy=$(cat $z/policy 2>&1)"
    for t in $z/trip_point_*_type; do [ -f "$t" ] || continue; n=${t%_type}; echo "  ${n##*/}: type=$(cat $t) temp=$(cat ${n}_temp) hyst=$(cat ${n}_hyst 2>&1)"; done
    for cd in $z/cdev*; do [ -L "$cd" ] && echo "  ${cd##*/} -> $(readlink -f $cd | xargs basename) trip=$(cat ${cd}_trip_point 2>&1) weight=$(cat ${cd}_weight 2>&1)"; done
  done
  echo "## cooling devices"
  for c in /sys/class/thermal/cooling_device*; do echo "$c type=$(cat $c/type) cur_state=$(cat $c/cur_state) max_state=$(cat $c/max_state)"; done
  echo "## fan hwmon /sys/class/hwmon/hwmon0 (pwmfan)"; ls -la /sys/class/hwmon/hwmon0/; dumpdir /sys/class/hwmon/hwmon0
  echo "## tach hwmon /sys/class/hwmon/hwmon2 (pwm_tach)"; dumpdir /sys/class/hwmon/hwmon2
  echo "## pwm-fan of_node"; N=$(readlink -f /sys/devices/platform/pwm-fan/of_node); find $N -maxdepth 1 -type f | sort | while read f; do printf '%s\t' "${f##*/}"; od -An -tx1 "$f" | tr -s ' ' | tr '\n' ' ' | head -c 300; echo; done
  echo "## systemctl status nvfancontrol"; systemctl status nvfancontrol --no-pager -l 2>&1 | head -30
  echo "## systemctl cat nvfancontrol"; systemctl cat nvfancontrol --no-pager 2>&1
  echo "## /var/lib/nvfancontrol"; ls -la /var/lib/nvfancontrol 2>&1; for f in /var/lib/nvfancontrol/*; do echo "--- $f"; cat $f 2>&1; done
  echo "## /etc/nvfancontrol.conf"; ls -la /etc/nvfancontrol.conf; readlink -f /etc/nvfancontrol.conf
} > $O/B6_thermal_fan.txt 2>&1
cp -L /etc/nvfancontrol.conf $O/nvfancontrol.conf 2>/dev/null

{ echo "## ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -25"; ps -eo pid,comm,%cpu,%mem --sort=-%cpu | head -25
  echo "## top -bn1 (instantaneous)"; top -bn1 -w 200 | head -30
  echo "## running services"; systemctl list-units --type=service --state=running --no-pager --no-legend
  echo "## all enabled units"; systemctl list-unit-files --state=enabled --no-pager --no-legend
  echo "## timers"; systemctl list-timers --all --no-pager
  echo "## get-default"; systemctl get-default
  echo "## loginctl"; loginctl list-sessions --no-pager; loginctl list-users --no-pager
  for s in $(loginctl list-sessions --no-legend | awk '{print $1}'); do echo "# session $s"; loginctl show-session $s --no-pager 2>&1 | grep -E '^(Type|Class|Service|TTY|Remote|State|Display|Desktop|Name)='; done
  echo "## who"; who -a
  echo "## display manager / desktop"; for u in gdm gdm3 lightdm sddm display-manager gnome-shell; do echo "$u: $(systemctl is-active $u 2>&1)"; done; pgrep -a -f 'Xorg|Xwayland|gnome-shell|gdm' || echo "no X/gnome processes"
  echo "## docker / snapd / apt / unattended"
  for u in docker.service docker.socket containerd.service snapd.service snapd.socket apt-daily.timer apt-daily-upgrade.timer unattended-upgrades.service packagekit.service fwupd.service ModemManager.service whoopsie.service apport.service avahi-daemon.service cups.service bluetooth.service nvargus-daemon.service nvphs.service nvzramconfig.service nv-l4t-usb-device-mode.service jtop.service; do
    printf '%s\tactive=%s\tenabled=%s\n' "$u" "$(systemctl is-active $u 2>&1)" "$(systemctl is-enabled $u 2>&1)"; done
  echo "## /etc/apt/apt.conf.d/20auto-upgrades"; cat /etc/apt/apt.conf.d/20auto-upgrades 2>&1
  echo "## cron"; ls /etc/cron.d /etc/cron.hourly /etc/cron.daily 2>&1; crontab -l 2>&1
  echo "## zram/swap"; swapon --show; cat /proc/swaps
  echo "## load"; cat /proc/loadavg
} > $O/B8_background.txt 2>&1

{ echo "## ip -br addr"; ip -br addr
  echo "## ip -br link"; ip -br link
  echo "## ip route"; ip route
  echo "## nmcli general"; nmcli general
  echo "## nmcli radio"; nmcli radio
  echo "## nmcli device"; nmcli device
  echo "## nmcli connection"; nmcli -f NAME,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show
  echo "## ethernet carrier"; for i in enP8p1s0 wlP1p1s0 usb0 l4tbr0; do echo "$i operstate=$(cat /sys/class/net/$i/operstate 2>&1) carrier=$(cat /sys/class/net/$i/carrier 2>&1) speed=$(cat /sys/class/net/$i/speed 2>&1)"; done
  echo "## bridge members of l4tbr0"; ls /sys/class/net/l4tbr0/brif/
  echo "## usb0 driver / gadget"; readlink -f /sys/class/net/usb0/device 2>&1; ls /sys/kernel/config/usb_gadget/*/functions 2>&1
  echo "## who owns 192.168.55.1"; ip -o addr show | grep 192.168.55.1
  echo "## sudo ufw status"; sx sudo ufw status verbose
  echo "## listening sockets"; ss -ltnup 2>&1
} > $O/B9_network.txt 2>&1

{ echo "## which gpio tools"; which gpiodetect gpioinfo gpioget gpioset gpiomon; gpiodetect --version 2>&1 | head -2; dpkg -l gpiod libgpiod2 libgpiod3 python3-libgpiod 2>&1 | tail -n +6
  echo "## gpiodetect"; gpiodetect 2>&1
  echo "## gpioinfo"; gpioinfo 2>&1
  echo "## /dev/gpiochip* permissions"; ls -la /dev/gpiochip*
  echo "## id / groups"; id; groups
  echo "## udev rules mentioning gpio"; grep -ls gpio /etc/udev/rules.d/* /lib/udev/rules.d/* 2>/dev/null
  echo "## jetson-io"; ls -la /opt/nvidia/jetson-io/ 2>&1 | head -20
  echo "## Jetson.GPIO (dpkg, system dist-packages, venv)"; dpkg -l python3-jetson-gpio 2>&1 | tail -1
  ls -d /usr/lib/python3/dist-packages/Jetson* /usr/local/lib/python3*/dist-packages/Jetson* 2>&1
  ~/venvs/jn/bin/pip list 2>/dev/null | grep -i -E 'jetson|gpio' || echo "venv: no Jetson.GPIO / gpiod package"
  echo "## venv pip list"; ~/venvs/jn/bin/pip list 2>&1
  echo "## /sys/class/gpio"; ls /sys/class/gpio 2>&1
} > $O/B10_gpio.txt 2>&1

{ for t in tmux screen rsync taskset chrt nohup setsid perf stress stress-ng iperf3 tcpdump numactl cyclictest jtop; do printf '%s\t%s\n' "$t" "$(command -v $t || echo MISSING)"; done
  echo "## taskset without sudo"; taskset -c 0 true; echo "taskset -c 0 true -> exit $?"; taskset -cp $$; echo "exit $?"
  echo "## chrt"; chrt -m; chrt -f 1 true; echo "chrt -f 1 true (no sudo) -> exit $?"; ulimit -r; echo "ulimit -r above"
  echo "## nice"; nice -n -5 true; echo "nice -n -5 true -> exit $?"
} > $O/B11_tools.txt 2>&1
echo "partB done $(date -u +%FT%T.%3NZ)"
