#!/bin/bash
# L2 Scalping System Launcher
cd /home/jacobw/quantstack/l2_scalping

export TZ="America/New_York"
export PATH="/home/jacobw/quantstack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/quantstack:/home/jacobw/quantstack/l2_scalping/src"

# Market hours check (09:25 - 16:00 ET)
current_hour=$(date +%H)
current_min=$(date +%M)
if [ $current_hour -lt 9 ] || [ $current_hour -gt 16 ]; then
    echo "Outside market hours ($current_hour:$current_min ET) - exiting"
    exit 0
fi
if [ $current_hour -eq 9 ] && [ $current_min -lt 25 ]; then
    echo "Before market prep time (09:25 ET) - exiting"
    exit 0
fi

# SIP dependency check
SIP_FILE="/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json"
if [ ! -f "$SIP_FILE" ]; then
    echo "SIP universe not found: $SIP_FILE - exiting"
    exit 0
fi

exec /home/jacobw/quantstack/.venv/bin/python -u src/main.py --config config
