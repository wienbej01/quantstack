#!/bin/bash
# Visual Authentication Reminder
# Displays persistent warning until Gateway is authenticated

while true; do
    # Check if Gateway is authenticated
    AUTH_STATUS=$(curl -k -s https://localhost:5000/v1/api/iserver/auth/status 2>/dev/null | grep -o '"authenticated":true')
    
    if [ -z "$AUTH_STATUS" ]; then
        # Not authenticated - show warning
        clear
        echo ""
        echo "╔════════════════════════════════════════════════════════════════╗"
        echo "║                                                                ║"
        echo "║  🔐 IBKR GATEWAY AUTHENTICATION REQUIRED                       ║"
        echo "║                                                                ║"
        echo "╚════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "  Time: $(TZ=America/New_York date '+%H:%M:%S ET')"
        echo ""
        echo "  ⚠️  TRADING SYSTEM BLOCKED - AUTHENTICATION NEEDED"
        echo ""
        echo "  ACTION REQUIRED:"
        echo "  1. Open browser: https://localhost:5000"
        echo "  2. Login with IBKR credentials"
        echo "  3. Enter 2FA code"
        echo ""
        echo "  Checking every 10 seconds..."
        echo ""
        
        # Desktop notification every 5 minutes
        MINUTE=$(date +%M)
        if [ $((10#$MINUTE % 5)) -eq 0 ]; then
            if [ -n "$DISPLAY" ]; then
                notify-send -u critical "🔐 IBKR Auth Required" "Login at https://localhost:5000"
            fi
        fi
        
        sleep 10
    else
        # Authenticated - show success and exit
        clear
        echo ""
        echo "╔════════════════════════════════════════════════════════════════╗"
        echo "║                                                                ║"
        echo "║  ✅ IBKR GATEWAY AUTHENTICATED                                 ║"
        echo "║                                                                ║"
        echo "╚════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "  Time: $(TZ=America/New_York date '+%H:%M:%S ET')"
        echo ""
        echo "  ✅ Trading system ready"
        echo ""
        
        if [ -n "$DISPLAY" ]; then
            notify-send -u normal "✅ IBKR Authenticated" "Trading system ready"
        fi
        
        exit 0
    fi
done
