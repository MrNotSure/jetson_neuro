#!/bin/zsh
# T5: one 60 s realtime track-sine-v1 run against `classical` on the Jetson.
#   run_one.sh LABEL plain|diag
# plain: `python -m jn_sim ctl --controller classical --once`, pinned to cpu 2.
# diag:  steplog_ctl.py (every step timed on the board), pinned to cpu 2.
# A 10 Hz frequency log runs on cpu 5 alongside. Board files: /tmp/jn_t5/.
set -u
LABEL=$1; MODE=$2
SESS=runs/t5_20261102
B=/tmp/jn_t5
PY='~/venvs/jn/bin/python'
if [[ $MODE == plain ]]; then
  CTL="$PY -u -m jn_sim ctl --controller classical --listen 192.168.55.1:5555 --once"
else
  CTL="$PY -u $B/scripts/steplog_ctl.py --listen 192.168.55.1:5555 --out $B/steps_$LABEL.csv"
fi
echo "$(date -u +%FT%TZ) $LABEL ($MODE): start controller"
# `cd X; cmd &`, not `cd X && cmd &`: the latter backgrounds a subshell that
# keeps the ssh session's stdout open until the controller exits.
ssh -n jetson-usb "cd ~/jetson_neuro || exit 1; PYTHONPATH=src nohup taskset -c 2 $CTL > $B/ctl_$LABEL.log 2>&1 < /dev/null & echo \$! > $B/ctl_$LABEL.pid"
for i in {1..40}; do
  ssh jetson-usb "grep -q listening $B/ctl_$LABEL.log" && break
  sleep 0.25
done
ssh jetson-usb "cat $B/ctl_$LABEL.log; taskset -cp \$(cat $B/ctl_$LABEL.pid)"
ssh -n jetson-usb "nohup taskset -c 5 $PY -u $B/scripts/freqlog.py 64 $B/freq_$LABEL.csv > $B/freq_$LABEL.log 2>&1 < /dev/null &"
sleep 1
echo "$(date -u +%FT%TZ) $LABEL: sim run"
.venv/bin/jn-sim run --scenario track-sine-v1 --controller tcp://192.168.55.1:5555 \
  --mode realtime --duration 60 --out $SESS/sim 2>&1 | tee $SESS/raw/sim_$LABEL.txt
echo "$(date -u +%FT%TZ) $LABEL: sim done; waiting for the controller and the frequency log"
for i in {1..40}; do
  ssh jetson-usb "! kill -0 \$(cat $B/ctl_$LABEL.pid) 2>/dev/null && ! pgrep -f freqlog.py > /dev/null" && break
  sleep 0.5
done
ssh jetson-usb "cat $B/ctl_$LABEL.log $B/freq_$LABEL.log"
rsync -a jetson-usb:$B/ $SESS/raw/board/
echo "$(date -u +%FT%TZ) $LABEL: done"
