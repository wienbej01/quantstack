#!/bin/bash
# Gateway Failure Alert Script
# Called by systemd when Gateway stops/fails

SERVICE_RESULT="${SERVICE_RESULT:-unknown}"
EXIT_CODE="${EXIT_CODE:-unknown}"

# Only alert on failures, not clean stops
if [ "$SERVICE_RESULT" != "success" ]; then
    curl -s -X POST "https://ntfy.sh/jacobw-trading-alerts" \
        -H "Title: CRITICAL: IBKR Gateway Failed" \
        -H "Priority: urgent" \
        -H "Tags: rotating_light" \
        -d "Gateway stopped unexpectedly
Result: $SERVICE_RESULT
Exit code: $EXIT_CODE
Time: $(TZ=America/New_York date '+%H:%M ET')

Systemd will attempt auto-restart in 30s"
fi
