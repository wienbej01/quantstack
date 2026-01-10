# Live Trading System Status

**Last Updated**: 2025-12-17 08:41 SGT

## System Overview

Live trading system with IBKR integration for paper trading and L2 data collection.

### Components
- **Paper Trading**: ML-based regime-aware predictions on 40 NYSE symbols
- **L2 Collection**: Order book data during opening hour (9:30-10:30 AM ET) and power hour (15:00-16:00 PM ET)
- **Universe**: Daily SIP selection via Polygon API

## Recent Session: 2025-12-16

### Data Collected
- ✅ **L2 Data**: 1.2 MB, 24 parquet files, 12 symbols
- ✅ **Time Window**: Opening hour only (9:09-9:10 AM ET, ~4 minutes)
- ✅ **Data Quality**: 76 columns, full 10-level DOM with market makers
- ❌ **Power Hour**: Missed due to system crash

### Issues Fixed (2025-12-17)

#### 1. date_et Bug in L2 Features
**Problem**: Feature computation failed with "date_et missing from rows; bug."
**Root Cause**: Feature dictionary in `~/transalpha/l2/l2_features.py` didn't include `date_et` field
**Fix**: Added `date_et` to feature dict at line 142
**Status**: ✅ Fixed

#### 2. System Crash During Market Hours
**Problem**: System stopped at 10:20 AM ET with no error message
**Root Cause**: Missing `disconnect()` method in `IBKRMarketDataManager` caused AttributeError in finally block
**Fix**: 
- Added `disconnect()` method to `qx-data/src/qx_data/live/ibkr_data.py`
- Added try/except blocks around cleanup operations
- Added `exc_info=True` to exception logging
**Status**: ✅ Fixed

#### 3. Verbose Logging
**Problem**: Excessive INFO logs filled context window
**Fix**: Changed logging level to ERROR only in `scripts/live_trading_system.py`
**Status**: ✅ Fixed

### Outstanding Issues

#### Paper Trading Market Data
**Problem**: Market data subscription fails with "Not connected" despite IBKR gateway running
**Symptoms**:
- Subscriptions fail immediately after connect
- `get_all_current_data()` returns empty dict
- All trading cycles skipped

**Investigation**:
- IBKR gateway confirmed running on port 7497
- L2 collector successfully connects and receives data
- Test scripts confirm snapshot data works with `snapshot=True` flag
- Issue appears to be connection timing or client ID conflict

**Workaround**: L2 collection continues to work; paper trading disabled

**Status**: ⚠️ Needs investigation

## System Configuration

### Logging
- **Level**: ERROR only
- **Files**: 
  - `logs/live_trading.log` - Main application log
  - `logs/live_system.out` - Startup and library logs

### IBKR Connections
- **Gateway**: 127.0.0.1:7497
- **Client IDs**:
  - L2 Collector: 500
  - Paper Trader: 400
  - Market Data: 3

### Trading Schedule
- **Market Hours**: 9:30-16:00 ET
- **L2 Windows**: 9:30-10:30 AM, 15:00-16:00 PM ET
- **Trading Frequency**: Every 1 minute during market hours
- **Loop Interval**: 5 seconds

## Monitoring

### Check System Status
```bash
# Check if running
ps aux | grep "[l]ive_trading_system.py"

# Monitor errors
tail -f logs/live_trading.log | grep ERROR

# Check L2 data
du -sh data/live_l2/run_id=live_$(date +%Y%m%d)/
```

### Start System
```bash
cd /home/jacobw/quantstack
nohup python scripts/live_trading_system.py > logs/live_system.out 2>&1 &
```

### Stop System
```bash
pkill -f live_trading_system.py
```

## Next Steps

1. ⚠️ **Debug paper trading market data issue**
   - Investigate client ID conflicts
   - Check connection timing/sequencing
   - Consider using historical bars instead of snapshots

2. 📋 **Restart for next session**
   - System needs manual restart before market open
   - Verify IBKR gateway is running
   - Confirm Polygon API key is set

3. 🔍 **Monitor full session**
   - Verify both L2 windows collect data
   - Check system stays running through market close
   - Validate feature data is written

## Data Locations

- **L2 Raw Data**: `data/live_l2/run_id=live_YYYYMMDD/raw/date=YYYY-MM-DD/symbol=*/`
- **L2 Features**: `data/live_l2/run_id=live_YYYYMMDD/feat/date=YYYY-MM-DD/symbol=*/`
- **Daily SIP**: `data/daily_sip/YYYY-MM-DD/`
- **Models**: `models/regime_aware/`

## Code Changes

### Files Modified
1. `~/transalpha/l2/l2_features.py` - Added date_et to features
2. `qx-data/src/qx_data/live/ibkr_data.py` - Added disconnect(), fixed get_all_current_data()
3. `scripts/live_trading_system.py` - ERROR logging, better exception handling
