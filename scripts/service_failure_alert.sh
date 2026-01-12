#!/bin/bash
# Trading Service Failure Alert
# Usage: service_failure_alert.sh <service_name>

SERVICE_NAME="${1:-unknown}"
SERVICE_RESULT="${SERVICE_RESULT:-unknown}"

if [ "$SERVICE_RESULT" != "success" ]; then
    curl -s -X POST "https://ntfy.sh/jacobw-trading-alerts" \
        -H "Title: Service Failed: $SERVICE_NAME" \
        -H "Priority: high" \
        -H "Tags: warning" \
        -d "$SERVICE_NAME stopped unexpectedly
Result: $SERVICE_RESULT
Time: $(TZ=America/New_York date '+%H:%M ET')"
fi
