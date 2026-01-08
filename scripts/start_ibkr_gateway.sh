#!/bin/bash
# IBKR Gateway startup script with error handling

set -e

GATEWAY_DIR="/opt/ibkr/gateway"  # Adjust path as needed
GATEWAY_JAR="$GATEWAY_DIR/ibgateway.jar"
CONFIG_DIR="/home/jacobw/.ibkr"

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"

# Check if Gateway jar exists
if [ ! -f "$GATEWAY_JAR" ]; then
    echo "ERROR: IBKR Gateway jar not found at $GATEWAY_JAR"
    exit 1
fi

# Start Gateway with proper JVM settings
exec java -Xmx1024m -Xms512m \
    -Djava.awt.headless=false \
    -Duser.home="$CONFIG_DIR" \
    -jar "$GATEWAY_JAR" \
    -trading_mode="${IBKR_TRADING_MODE:-paper}" \
    -port="${IBKR_GATEWAY_PORT:-7497}"
