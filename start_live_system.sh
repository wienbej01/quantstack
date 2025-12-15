#!/bin/bash
# Live Trading System Startup Script

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

# Check IBKR connection
echo "🔌 Testing IBKR connection..."
python3 -c "
from ib_insync import IB
ib = IB()
try:
    ib.connect('127.0.0.1', 7497, clientId=999, readonly=True, timeout=5)
    print('✅ IBKR connected')
    ib.disconnect()
except Exception as e:
    print(f'❌ IBKR connection failed: {e}')
    exit(1)
"

if [ $? -ne 0 ]; then
    echo "❌ IBKR connection test failed"
    echo "Please ensure TWS/Gateway is running on port 7497"
    exit 1
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

echo "✅ All prerequisites met"
echo ""
echo "📋 System Configuration:"
echo "   - SIP Universe: 40 symbols (daily selection)"
echo "   - L2 Collection: Top 6 NYSE symbols"
echo "   - Paper Trading: All SIP symbols"
echo "   - Collection Windows: 9:30-10:30, 15:00-16:00 ET"
echo ""

# Start the system
echo "🎯 Starting live trading system..."
cd /home/jacobw/quantstack
source ~/.bashrc
python3 scripts/live_trading_system.py
