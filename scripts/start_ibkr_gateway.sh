#!/bin/bash
# IBKR Gateway startup script with error handling and optional IBC login

set -e

GATEWAY_DIR="/opt/ibkr/gateway"  # Adjust path as needed
GATEWAY_JAR="$GATEWAY_DIR/ibgateway.jar"
CONFIG_DIR="/home/jacobw/.ibkr"
IBC_DIR="/home/jacobw/quantstack/ibc"
IBC_CONFIG="$IBC_DIR/config.ini"
IBC_CRED_INI="$IBC_DIR/IBController.ini"
TWS_PATH="${IBKR_TWS_PATH:-/home/jacobw/Jts}"
TWS_MAJOR_VERSION="${IBKR_TWS_MAJOR_VERSION:-}"
STATUS_URL="${IBKR_STATUS_URL:-https://www.interactivebrokers.com/en/software/systemStatus.php}"
STATUS_CHECK="${IBKR_STATUS_CHECK:-1}"
STATUS_BACKOFF_SECONDS="${IBKR_STATUS_BACKOFF_SECONDS:-900}"
STATUS_MAX_RETRIES="${IBKR_STATUS_MAX_RETRIES:-0}"

if [ -z "$TWS_MAJOR_VERSION" ] && [ -d "$TWS_PATH/ibgateway" ]; then
    TWS_MAJOR_VERSION="$(ls -1 "$TWS_PATH/ibgateway" \
        | grep -E '^[0-9]+$' \
        | sort -n \
        | tail -n 1)"
fi

TWS_MAJOR_VERSION="${TWS_MAJOR_VERSION:-1019}"

status_retry_count=0
check_ibkr_status() {
    if [ "$STATUS_CHECK" != "1" ]; then
        return 0
    fi

    if ! command -v curl >/dev/null 2>&1; then
        echo "WARN: curl not available, skipping IBKR status check."
        return 0
    fi

    # Only check status outside ET trading hours (09:30-16:00, Mon-Fri)
    if command -v date >/dev/null 2>&1; then
        et_hm="$(TZ=America/New_York date +%H%M)"
        et_dow="$(TZ=America/New_York date +%u)"
        if [ "$et_dow" -lt 6 ] && [ "$et_hm" -ge 0830 ] && [ "$et_hm" -le 1700 ]; then
            return 0
        fi
    fi

    status_html="$(curl -fsSL "$STATUS_URL" || true)"
    if [ -z "$status_html" ]; then
        echo "WARN: IBKR status page unreachable; proceeding."
        return 0
    fi

    if echo "$status_html" | grep -qiE "scheduled maintenance|maintenance|unable to connect"; then
        echo "IBKR status indicates maintenance. Delaying Gateway start."
        return 1
    fi

    return 0
}

while ! check_ibkr_status; do
    status_retry_count=$((status_retry_count + 1))
    if [ "$STATUS_MAX_RETRIES" -gt 0 ] && [ "$status_retry_count" -ge "$STATUS_MAX_RETRIES" ]; then
        echo "ERROR: IBKR status check failed after ${STATUS_MAX_RETRIES} retries."
        exit 2
    fi
    sleep "$STATUS_BACKOFF_SECONDS"
done

# Create config directory if it doesn't exist
mkdir -p "$CONFIG_DIR"

# Prefer IBC if available (handles auto-login)
if [ -x "$IBC_DIR/scripts/ibcstart.sh" ]; then
    if [ ! -f "$IBC_CONFIG" ]; then
        echo "ERROR: IBC config not found at $IBC_CONFIG"
        echo "Ensure IBC is installed and config.ini exists."
        exit 1
    fi

    # If legacy IBController.ini exists, sync credentials into config.ini once.
    if [ -f "$IBC_CRED_INI" ]; then
        ib_user="$(awk -F= '/^IbLoginId=/{print $2}' "$IBC_CRED_INI" | tail -n 1)"
        ib_pass="$(awk -F= '/^IbPassword=/{print $2}' "$IBC_CRED_INI" | tail -n 1)"
        if [ -n "$ib_user" ] && [ -n "$ib_pass" ]; then
            sed -i "s/^IbLoginId=.*/IbLoginId=$ib_user/" "$IBC_CONFIG"
            sed -i "s/^IbPassword=.*/IbPassword=$ib_pass/" "$IBC_CONFIG"
        fi
    fi

    if [ -z "${DISPLAY:-}" ]; then
        if ! command -v Xvfb >/dev/null 2>&1; then
            echo "ERROR: DISPLAY not set and Xvfb not installed."
            echo "Install Xvfb or export DISPLAY to a running X server."
            exit 1
        fi
        export DISPLAY=:1
        if ! pgrep -f "Xvfb :1" >/dev/null 2>&1; then
            Xvfb :1 -ac -screen 0 1024x768x24 &
            sleep 1
        fi
    fi

    cd "$IBC_DIR"
    exec "$IBC_DIR/scripts/ibcstart.sh" "$TWS_MAJOR_VERSION" \
        --gateway \
        --ibc-path="$IBC_DIR" \
        --ibc-ini="$IBC_CONFIG" \
        --tws-path="$TWS_PATH" \
        --mode="${IBKR_TRADING_MODE:-paper}"
fi

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
