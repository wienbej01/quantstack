#!/bin/bash
# Trading Service Failure Alert
# Usage: service_failure_alert.sh <service_name>
#
# This script is called by systemd OnFailure= directive
# It distinguishes between orderly shutdown (no alert) and unexpected failure (alert)

SERVICE_NAME="${1:-unknown}"
SERVICE_RESULT="${SERVICE_RESULT:-unknown}"
SERVICE_INVOCATION_ID="${INVOCATION_ID:-unknown}"

# Get current hour in ET (for EOD detection)
CURRENT_HOUR=$(TZ=America/New_York date +%H)
CURRENT_DAY=$(TZ=America/New_York date +%u)  # 1=Monday, 7=Sunday

# Skip alert if:
# 1. Weekend (Saturday=6, Sunday=7)
# 2. After 16:00 ET (likely EOD orderly shutdown)
# 3. Before 09:00 ET (outside trading hours)
SKIP_ALERT=false

if [ "$CURRENT_DAY" -ge 6 ]; then
    # Weekend - likely scheduled maintenance
    SKIP_ALERT=true
    REASON="weekend"
elif [ "$CURRENT_HOUR" -ge 16 ]; then
    # EOD or after - likely orderly shutdown
    SKIP_ALERT=true
    REASON="EOD"
elif [ "$CURRENT_HOUR" -lt 9 ]; then
    # Before trading hours
    SKIP_ALERT=true
    REASON="pre-market"
fi

# Only send alert if this is an unexpected failure during trading hours
if [ "$SERVICE_RESULT" != "success" ] && [ "$SKIP_ALERT" = false ]; then
    curl -s -X POST "https://ntfy.sh/jacobw-trading-alerts" \
        -H "Title: Service Crashed: $SERVICE_NAME" \
        -H "Priority: urgent" \
        -H "Tags: rotating_light" \
        -d "$SERVICE_NAME crashed during trading hours
Result: $SERVICE_RESULT
Time: $(TZ=America/New_York date '+%H:%M:%S ET')
Invocation: ${SERVICE_INVOCATION_ID:0:8}"

    # Log the alert for debugging
    echo "[$(TZ=America/New_York date)] FAILURE_ALERT sent for $SERVICE_NAME (result=$SERVICE_RESULT)" >> /var/log/service_failures.log
elif [ "$SKIP_ALERT" = true ]; then
    # Log skip for debugging (no alert sent)
    echo "[$(TZ=America/New_York date)] FAILURE_ALERT skipped for $SERVICE_NAME (reason=$REASON, result=$SERVICE_RESULT)" >> /var/log/service_failures.log
fi
