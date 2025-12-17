#!/bin/bash
# Live Trading System Startup Script - FIXED

set -e

echo "🚀 Starting Live Trading System..."

# Check prerequisites
if [ -z "$POLYGON_API_KEY" ]; then
    echo "❌ POLYGON_API_KEY not set"
    echo "Please run: export POLYGON_API_KEY=your_key_here"
    exit 1
fi

# Create directories
mkdir -p logs
mkdir -p data/daily_sip
mkdir -p data/live_l2

# Check IBKR connection (non-blocking)
echo "🔌 Checking IBKR connection..."
python3 scripts/check_ibkr_status.py
IBKR_STATUS=$?

if [ $IBKR_STATUS -ne 0 ]; then
    echo "⚠️  IBKR not available - system will run without L2 collection and paper trading"
    echo "   L2 collection and paper trading will be disabled"
    echo "   System will continue with SIP analysis only"
    echo ""
    read -p "Continue anyway? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Startup cancelled. Please setup IBKR first."
        exit 1
    fi
else
    echo "✅ IBKR ready for L2 collection and paper trading"
fi

# Test Polygon API
echo "🌐 Testing Polygon API..."
python3 -c "
import requests
import os
url = 'https://api.polygon.io/v2/aggs/ticker/AAPL/prev'
params = {'apikey': os.getenv('POLYGON_API_KEY')}
response = requests.get(url, params=params, timeout=10)
if response.status_code == 200:
    print('✅ Polygon API connected')
else:
    print(f'❌ Polygon API failed: {response.status_code}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ Polygon API test failed"
    exit 1
fi

echo "✅ All prerequisites checked"
echo ""
echo "📋 System Configuration:"
echo "   - SIP Universe: 40 symbols (daily selection)"
echo "   - L2 Collection: Top 6 NYSE symbols (if IBKR available)"
echo "   - Paper Trading: All SIP symbols (if IBKR available)"
echo "   - Collection Windows: 9:30-10:30, 15:00-16:00 ET"
echo ""

# Start the system (NO TIMEOUT)
echo "🎯 Starting live trading system..."
cd /home/jacobw/quantstack
source .venv/bin/activate
python scripts/live_trading_system.py
