#!/bin/bash
# Trade tester health check - runs every 30 minutes

LOG_DIR="$HOME/quantstack/logs"
mkdir -p "$LOG_DIR"

{
    echo "=== Trade Tester Check $(date) ==="
    
    # Check trading services
    for svc in l2-scalping l2-vwap-reversion intraday-paper; do
        status=$(systemctl is-active "$svc" 2>/dev/null || echo "not-found")
        echo "$svc: $status"
    done
    
    # Check IBKR positions
    python3 -c "
from ib_insync import IB
ib = IB()
ib.connect('127.0.0.1', 7494, clientId=99, timeout=5)
positions = ib.positions()
if positions:
    for p in positions:
        print(f'  {p.contract.symbol}: {p.position} shares')
else:
    print('  No open positions')
ib.disconnect()
" 2>/dev/null || echo "  IBKR connection failed"
    
    echo ""
} >> "$LOG_DIR/trade_tester.log" 2>&1
