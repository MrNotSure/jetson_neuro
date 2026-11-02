#!/bin/bash
# Stage 1 run, D4 (board side, no sudo): drive pin 29 (gpiochip0 line 105) high for HOLD s, then low
# for HOLD s, then release it to input with gpioget. Timestamps to /tmp/jn_run1/d4.log.
# usage: nohup bash /tmp/jn_run1/scripts/d4.sh 60 > /tmp/jn_run1/d4.out 2>&1 &
HOLD=${1:-60}
L=/tmp/jn_run1/d4.log
ts() { date -u +%FT%T.%3NZ; }
echo "$(ts) start; before: $(gpioinfo gpiochip0 | grep 'line 105:')" >> $L
echo "$(ts) HIGH: gpioset --mode=time --sec=$HOLD gpiochip0 105=1" >> $L
gpioset --mode=time --sec=$HOLD gpiochip0 105=1; echo "$(ts) gpioset high rc=$?" >> $L
echo "$(ts) after high, line: $(gpioinfo gpiochip0 | grep 'line 105:')" >> $L
echo "$(ts) LOW: gpioset --mode=time --sec=$HOLD gpiochip0 105=0" >> $L
gpioset --mode=time --sec=$HOLD gpiochip0 105=0; echo "$(ts) gpioset low rc=$?" >> $L
echo "$(ts) RELEASE: gpioget gpiochip0 105 -> $(gpioget gpiochip0 105) rc=$?" >> $L
echo "$(ts) end; line: $(gpioinfo gpiochip0 | grep 'line 105:')" >> $L
