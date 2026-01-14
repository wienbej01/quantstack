#!/bin/bash
# Gateway Authentication Reminder
# Sends NTFY alert and displays desktop notification when Gateway starts

# Send NTFY alert
curl -s -X POST "https://ntfy.sh/jacobw-trading-alerts" \
  -H "Title: 🔐 IBKR Gateway Started - Authentication Required" \
  -H "Priority: urgent" \
  -H "Tags: key,warning" \
  -d "Gateway started at $(TZ=America/New_York date '+%H:%M ET')

ACTION REQUIRED:
1. Open: https://localhost:5000
2. Login with IBKR credentials
3. Enter 2FA code

System will NOT trade until authenticated!"

# Desktop notification (if DISPLAY available)
if [ -n "$DISPLAY" ]; then
    notify-send -u critical -t 0 \
        "🔐 IBKR Authentication Required" \
        "Gateway started. Login at https://localhost:5000"
fi

# Console alert
echo "================================================================"
echo "🔐 IBKR GATEWAY STARTED - AUTHENTICATION REQUIRED"
echo "================================================================"
echo "Time: $(TZ=America/New_York date '+%H:%M ET')"
echo ""
echo "ACTION REQUIRED:"
echo "1. Open browser: https://localhost:5000"
echo "2. Login with IBKR credentials"
echo "3. Enter 2FA code"
echo ""
echo "System will NOT trade until authenticated!"
echo "================================================================"
