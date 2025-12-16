# Live Trading System Status

**Last Updated**: 2025-12-16 20:27 SGT (07:27 ET)

## System Status: ✅ RUNNING

The live intraday ML trading system is operational and monitoring markets.

### Current Configuration

- **Models**: Regime-aware GradientBoostingClassifier (bull/bear/sideways)
- **Training Data**: Last 6 months (2024-07-04 to 2024-12-31)
- **Validation Performance**: +1.3% on 30-day holdout
- **SIP Universe**: 40 NYSE symbols (live Polygon filtering)
- **L2 Symbols**: 6 top symbols for Level 2 data collection
- **Trading Mode**: IBKR Paper Trading (Account: DUN575068, Port: 7497)

### Model Details

| Regime | Samples | Top Feature | Importance |
|--------|---------|-------------|------------|
| Bull | 4,588 | sector_momentum | 0.334 |
| Bear | 3,303 | sector_momentum | 0.312 |
| Sideways | 6,100 | sector_momentum | 0.268 |

### Trading Schedule (ET)

- **Market Hours**: 9:30 AM - 4:00 PM (Monday-Friday)
- **L2 Collection Windows**:
  - Opening Hour: 9:30 AM - 10:30 AM
  - Power Hour: 3:00 PM - 4:00 PM
- **Paper Trading**: Every 5 minutes during market hours
- **Status Logging**: Every 2 minutes

### System Behavior

**Outside Market Hours** (Current):
- System runs in monitoring mode
- Checks IBKR availability every 5 minutes
- No trading or L2 collection
- Logs status periodically

**During L2 Windows**:
- Connects to IBKR for Level 2 data
- Collects order book data for top 6 NYSE symbols
- Saves to `data/live_l2/run_id=live_YYYYMMDD/`

**During Market Hours**:
- Generates ML predictions using regime-aware models
- Places paper trades when confidence > 0.65 (BUY) or < 0.35 (SELL)
- Position size: 100 shares per trade
- Logs all trades to `logs/live_trading.log`

### Files and Locations

- **Models**: `models/regime_aware/{bull,bear,sideways}_model.pkl`
- **SIP Universe**: `data/daily_sip/sip_universe_2025-12-16.txt`
- **L2 Symbols**: `data/daily_sip/l2_symbols_2025-12-16.txt`
- **Live Logs**: `logs/live_trading.log`
- **L2 Data**: `data/live_l2/run_id=live_20251216/`
- **PID File**: `live_trading.pid`

### Management Commands

```bash
# Check system status
tail -f logs/live_trading.log

# Stop system
kill $(cat live_trading.pid)

# Restart system
./start_live_system.sh

# Regenerate SIP universe
python scripts/daily_sip_scheduler.py

# Retrain models
python scripts/train_and_save_regime_models.py
```

### Key Fix Applied (2025-12-16)

**Issue**: System appeared to disconnect from IBKR immediately after startup.

**Root Cause**: The initial IBKR connection is a connectivity test that intentionally disconnects. The system then enters a monitoring loop and only reconnects to IBKR when needed (during L2 windows or for trading).

**Solution**: This is correct behavior. The system:
1. Tests IBKR connectivity on startup (connects + disconnects)
2. Enters main monitoring loop
3. Reconnects to IBKR only during:
   - L2 collection windows (9:30-10:30, 15:00-16:00 ET)
   - Paper trading execution (every 5 min during market hours)

### Performance Expectations

Based on backtest results:
- **Annual Return**: +13.0%
- **Win Rate**: 49.7%
- **Max Drawdown**: -19.6%
- **Trade Frequency**: ~5,000 trades/year
- **Regime Distribution**: 40% bull, 33% bear, 27% sideways

### Next Market Open

The system will activate trading at **9:30 AM ET Monday, December 16, 2025**.

At market open, expect:
1. L2 collection starts for 6 NYSE symbols
2. Paper trades execute every 5 minutes
3. Regime detection updates continuously
4. Full status logs every 2 minutes

---

**System is healthy and ready for market open.**
