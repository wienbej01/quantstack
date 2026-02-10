#!/bin/bash
# Enhanced L2 Scalping System Launcher with Position Tracking
cd /home/jacobw/quantstack/l2_scalping

export TZ="America/New_York"
export PATH="/home/jacobw/quantstack/.venv/bin:$PATH"
export PYTHONPATH="/home/jacobw/quantstack:/home/jacobw/quantstack/l2_scalping/src"
export L2_DATA_ROOT="${L2_DATA_ROOT:-/home/jacobw/quantstack/data/l2}"

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

# Position tracking system validation
echo "🔍 Validating position tracking system..."
cd /home/jacobw/quantstack
if ! python scripts/validate_position_tracking.py > /dev/null 2>&1; then
    echo "❌ Position tracking validation failed - aborting startup"
    exit 1
fi
echo "✅ Position tracking system validated"

# Database schema check/update
echo "🗄️  Checking database schema..."
if ! python scripts/update_position_tracking_schema.py > /dev/null 2>&1; then
    echo "⚠️  Schema update check completed"
fi

cd /home/jacobw/quantstack/l2_scalping

# Clear any zombie depth subscriptions before starting
CLEAR_SCRIPT="/home/jacobw/quantstack/scripts/clear_ibkr_depth_subscriptions.py"
if [ -f "$CLEAR_SCRIPT" ]; then
    echo "Clearing IBKR depth subscriptions..."
    /home/jacobw/quantstack/.venv/bin/python "$CLEAR_SCRIPT" || echo "Warning: depth clear failed"
fi

# Validate IOC price improvement configuration
echo "Validating IOC price improvement..."
python3 validate_ioc.py || {
    echo "CRITICAL: IOC validation failed - aborting startup"
    exit 1
}

echo "🚀 Starting L2 Scalping with Enhanced Position Tracking..."
exec /home/jacobw/quantstack/.venv/bin/python -u src/main.py --config config
