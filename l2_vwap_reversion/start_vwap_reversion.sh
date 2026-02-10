#!/bin/bash
# L2 VWAP Reversion Startup Script
cd /home/jacobw/quantstack/l2_vwap_reversion

export TZ="America/New_York"
export PATH="/home/jacobw/quantstack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/quantstack/l2_vwap_reversion/src:/home/jacobw/quantstack"
export IBKR_GATEWAY_HOST="${IBKR_GATEWAY_HOST:-127.0.0.1}"
export IBKR_GATEWAY_PORT="${IBKR_GATEWAY_PORT:-7494}"

# Fast fail if the gateway isn't listening yet. A non-zero exit is intentional so
# systemd can retry instead of idling silently through the open.
if ! IBKR_GATEWAY_WAIT_TIMEOUT="${IBKR_GATEWAY_WAIT_TIMEOUT:-30}" \
    IBKR_GATEWAY_STABLE_SLEEP="${IBKR_GATEWAY_STABLE_SLEEP:-2}" \
    /home/jacobw/quantstack/scripts/wait_for_ibkr_gateway.sh; then
    echo "IBKR Gateway not ready on ${IBKR_GATEWAY_HOST}:${IBKR_GATEWAY_PORT} - exiting"
    exit 1
fi

# Market hours check (09:20 - 16:00 ET)
current_hour=$(date +%H)
current_min=$(date +%M)
if [ $current_hour -lt 9 ] || [ $current_hour -gt 16 ]; then
    echo "Outside market hours ($current_hour:$current_min ET) - exiting"
    exit 0
fi
if [ $current_hour -eq 9 ] && [ $current_min -lt 20 ]; then
    echo "Before market prep time (09:20 ET) - exiting"
    exit 0
fi

# SIP dependency check
SIP_FILE="/home/jacobw/intraday_stack/data/daily_sip/date=$(date +%F)/sip_universe.json"
if [ ! -f "$SIP_FILE" ]; then
    echo "SIP universe not found: $SIP_FILE - exiting"
    exit 0
fi

echo "🚀 Starting L2 VWAP Mean Reversion..."
exec /home/jacobw/quantstack/.venv/bin/python -u src/main.py --config config
