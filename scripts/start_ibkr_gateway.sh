#!/bin/bash
# IBKR Gateway startup script (IBC-managed if available)

set -euo pipefail

IBC_DIR="/home/jacobw/quantstack/ibc"
IBC_CONFIG="$IBC_DIR/config.ini"
TWS_PATH="${IBKR_TWS_PATH:-/home/jacobw/Jts}"
TWS_MAJOR_VERSION="${IBKR_TWS_MAJOR_VERSION:-}"
MODE="${IBKR_TRADING_MODE:-paper}"
PORT="${IBKR_GATEWAY_PORT:-7494}"

if [ -z "$TWS_MAJOR_VERSION" ] && [ -d "$TWS_PATH/ibgateway" ]; then
    TWS_MAJOR_VERSION="$(ls -1 "$TWS_PATH/ibgateway" 2>/dev/null | grep -E '^[0-9]+$' | sort -n | tail -n 1)"
fi
TWS_MAJOR_VERSION="${TWS_MAJOR_VERSION:-1019}"

# Prefer IBC (auto-login controller) if available
if [ -x "$IBC_DIR/scripts/ibcstart.sh" ] && [ -f "$IBC_CONFIG" ]; then
    if [ -z "${DISPLAY:-}" ]; then
        export DISPLAY=:99
    fi

    exec "$IBC_DIR/scripts/ibcstart.sh" "$TWS_MAJOR_VERSION" \
        --gateway \
        --ibc-path="$IBC_DIR" \
        --ibc-ini="$IBC_CONFIG" \
        --tws-path="$TWS_PATH" \
        --mode="$MODE"
fi

GATEWAY_DIR="$TWS_PATH/ibgateway/$TWS_MAJOR_VERSION"

if [ -x "$GATEWAY_DIR/ibgateway" ]; then
    exec "$GATEWAY_DIR/ibgateway" --mode="$MODE" --port="$PORT"
fi

if [ -f "$GATEWAY_DIR/ibgateway.jar" ]; then
    exec java -Xmx1024m -Xms512m \
        -Djava.awt.headless=false \
        -Duser.home="$HOME/.ibkr" \
        -jar "$GATEWAY_DIR/ibgateway.jar" \
        -trading_mode="$MODE" \
        -port="$PORT"
fi

echo "ERROR: IBKR Gateway not found. Expected IBC at $IBC_DIR or gateway at $GATEWAY_DIR"
exit 1
