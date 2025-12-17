# Live Trading System Upgrade Plan

**Date**: 2025-12-16  
**Status**: PHASE 2 COMPLETE - Testing Required  
**Priority**: CRITICAL

## Executive Summary

Current live trading system uses **mock data** instead of real IBKR market data. This document outlines the plan to fix this critical issue and upgrade to 1-minute trading frequency.

## Critical Issue Discovered

**Implementation Progress:**

### Phase 1: Real IBKR Data ✅ COMPLETE
- ✅ **Step 1.1**: Created `IBKRMarketDataManager` (qx-data/qx_data/live/ibkr_data.py)
  - Real-time streaming data subscription
  - Historical bars retrieval
  - Cross-sectional feature computation
  - Batch symbol management
- ✅ **Step 1.2**: Updated ML Predictor (qx-data/qx_data/live/ml_predictor.py)
  - Real cross-sectional feature extraction (11 features)
  - Proper regime detection (bull/bear/sideways)
  - Removed mock feature generation
- ✅ **Step 1.3**: Updated Live Trading System (scripts/live_trading_system.py)
  - Integrated IBKRMarketDataManager
  - Subscribe to 40 symbols at market open
  - Fetch real-time prices and volumes
  - Compute historical lookback features (rel_strength_5/10/20)
  - Compute cross-sectional features for all symbols
  - Pass real data to ML predictor
  - **REMOVED LINE 207 MOCK DATA**

### Phase 2: 1-Minute Trading ✅ COMPLETE
- ✅ **Step 2.1**: Created `PerformanceMonitor` (qx-data/qx_data/live/performance_monitor.py)
  - Track cycle timing (features, predictions, orders)
  - Monitor skip rate
  - Alert on timeout (>60s)
  - Performance statistics logging
- ✅ **Step 2.2**: Optimized Feature Computation (qx-data/qx_data/live/ibkr_data.py)
  - Parallel historical bars fetching (ThreadPoolExecutor)
  - Vectorized cross-sectional features (NumPy)
  - Batch processing for 40 symbols
  - Target: <10s for all features
- ✅ **Step 2.3**: Updated Trading Loop (scripts/live_trading_system.py)
  - Changed frequency from 300s to 60s
  - Integrated performance monitoring
  - Optimized data fetching pipeline
  - Added cycle timeout detection
  - Performance stats logging every 2 minutes

**Status: BOTH PHASES COMPLETE - Ready for Testing**

**Current System Behavior:**
```python
# Line 207 in live_trading_system.py
mock_data = {
    "volatility": 0.25,
    "volume": 2000000,
    "price_momentum": 0.02,
}
```

**Impact:**
- ❌ Trading decisions based on fake data
- ❌ Models not receiving real market information
- ❌ No actual price/volume/volatility data
- ❌ System cannot respond to real market conditions

## Data Source Architecture

### Current (BROKEN)
```
Polygon (daily) → SIP universe selection (40 symbols)
                ↓
Mock Data → ML Models → Paper Trades (IBKR)
```

### Correct Architecture
```
Polygon (daily) → SIP universe selection (40 symbols)
                ↓
IBKR Real-time → Feature Computation → ML Models → Paper Trades (IBKR)
     ↓
  L2 Data (opening/power hours)
```

## Phase 1: Fix Real IBKR Data Integration

### Objective
Replace mock data with real IBKR streaming market data.

### IBKR Capabilities Verified

✅ **Real-time Streaming Data:**
- Last price, bid, ask, spread
- Real-time volume
- Automatic updates via callbacks
- No rate limits

✅ **Batch Subscriptions:**
- Subscribe to 40 symbols simultaneously
- Single connection handles all symbols
- Tested with AAPL, MSFT, GOOGL, TSLA, NVDA

✅ **Historical Bars:**
- 1-minute bars for lookback features
- 20-minute history available
- Supports rel_strength_5/10/20 computation

### Implementation Tasks

**1. Create IBKR Market Data Manager** (`qx-data/qx_data/live/ibkr_data.py`)
```python
class IBKRMarketDataManager:
    - subscribe_symbols(symbols: List[str])
    - get_current_data(symbol: str) -> Dict
    - get_historical_bars(symbol: str, periods: int) -> DataFrame
    - compute_cross_sectional_features(all_data: Dict) -> Dict
```

**2. Update ML Predictor** (`qx-data/qx_data/live/ml_predictor.py`)
```python
class RegimeAwarePredictor:
    - Remove mock feature extraction
    - Accept real IBKR data
    - Compute 11 cross-sectional features
    - Detect regime from real market data
```

**3. Update Live Trading System** (`scripts/live_trading_system.py`)
```python
class LiveTradingSystem:
    - Initialize IBKR data manager
    - Subscribe to SIP universe at market open
    - Fetch real data every cycle
    - Pass real data to ML predictor
```

### Data Flow (Phase 1)

```
Market Open (9:30 AM ET)
  ↓
Subscribe to 40 NYSE symbols (IBKR)
  ↓
Every 5 minutes (current frequency):
  1. Fetch current prices/volumes for all 40 symbols
  2. Fetch 20-bar history for lookback features
  3. Compute cross-sectional features:
     - cross_rank_ret, cross_rank_vol
     - sector_momentum, cross_dispersion
     - market_breadth, up_down_ratio
     - rel_strength_5/10/20
     - market_ret_5/10
  4. Run ML predictions (3 regime models)
  5. Place paper trades (confidence > 0.65 or < 0.35)
  6. Log all activity
```

## Phase 2: Upgrade to 1-Minute Trading

### Objective
Increase trading frequency from 5 minutes to 1 minute for faster reaction to market opportunities.

### Performance Analysis

**Feature Computation Timing:**
| Task | Time | Details |
|------|------|---------|
| Fetch historical bars (40 symbols) | 3-5s | Parallel requests |
| Compute cross-sectional features | 5-8s | Rank, aggregate, normalize |
| ML inference (40 symbols) | <1s | 3 models × 40 predictions |
| Place orders | 2-3s | Batch order placement |
| **Total Latency** | **15-20s** | Per 1-minute cycle |

**Feasibility:**
- ✅ 15-20s latency fits within 60s cycle
- ✅ 40s buffer for error handling
- ✅ No API rate limits (IBKR streaming)
- ✅ CPU/memory sufficient

### Implementation Tasks

**1. Optimize Feature Computation**
```python
class CrossSectionalFeatures:
    - Cache market-wide statistics
    - Parallel computation across symbols
    - Reuse sector mappings
    - Vectorized operations (NumPy)
```

**2. Update Trading Loop**
```python
# Change from 5-minute to 1-minute cycle
if self.is_market_hours() and current_time - last_trade_time > 60:  # Was 300
    self.execute_paper_trades()
    last_trade_time = current_time
```

**3. Add Performance Monitoring**
```python
class PerformanceMonitor:
    - Track feature computation time
    - Log cycle latency
    - Alert if >60s (skip cycle)
    - Daily performance report
```

### Data Flow (Phase 2)

```
Every 1 minute during market hours:
  00s: Trigger cycle
  03s: Historical bars fetched (40 symbols)
  11s: Cross-sectional features computed
  12s: ML predictions complete
  15s: Orders placed
  17s: Cycle complete, wait for next minute
```

## Expected Outcomes

### Phase 1 (Real Data)
- ✅ Trading decisions based on actual market conditions
- ✅ Models receive correct feature inputs
- ✅ Regime detection reflects real volatility
- ✅ Cross-sectional features computed correctly
- ✅ System responds to actual price movements

### Phase 2 (1-Minute Frequency)
- ✅ 5x faster reaction time (60s vs 300s)
- ✅ ~390 trading opportunities per day (vs 78)
- ✅ Capture short-term momentum
- ✅ Better entry/exit timing
- ✅ Improved fill prices

### Performance Metrics

**Current System (Broken):**
- Frequency: 5 minutes
- Data: Mock (fake)
- Opportunities: 78/day
- Latency: N/A (no real data)

**After Phase 1:**
- Frequency: 5 minutes
- Data: Real IBKR streaming
- Opportunities: 78/day
- Latency: 15-20s

**After Phase 2:**
- Frequency: 1 minute
- Data: Real IBKR streaming
- Opportunities: 390/day
- Latency: 15-20s

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Feature computation timeout | Medium | Low | Skip cycle, continue next minute |
| IBKR disconnection | Low | Medium | Auto-reconnect, resume trading |
| Historical data unavailable | Low | Low | Use cached data, mark stale |
| Order rejection | Low | Low | Log and analyze, no retry |
| Increased API usage | Low | None | IBKR has no rate limits |

## Resource Requirements

**No Additional Costs:**
- ✅ IBKR paper trading (free)
- ✅ IBKR market data (included)
- ✅ No Polygon usage during trading
- ✅ Existing hardware sufficient

**System Resources:**
- CPU: 20-30% during feature computation (5-8s/minute)
- Memory: <10 MB additional
- Network: ~40 requests/minute (well within limits)
- Disk: Minimal (logs only)

## Implementation Timeline

**Phase 1: Real IBKR Data**
- Development: 2-3 hours
- Testing: 1 hour
- Deployment: 30 minutes
- **Total: 3.5-4.5 hours**

**Phase 2: 1-Minute Trading**
- Development: 3-4 hours
- Testing: 1-2 hours
- Deployment: 30 minutes
- **Total: 4.5-6.5 hours**

**Combined Timeline: 8-11 hours to production**

## Testing Strategy

**Phase 1 Testing:**
1. Verify IBKR data subscription (40 symbols)
2. Validate feature computation (11 features)
3. Confirm ML predictions (3 regime models)
4. Test order placement (paper trades)
5. Run for 1 hour during market hours

**Phase 2 Testing:**
1. Measure feature computation time (target <10s)
2. Verify 1-minute cycle timing
3. Monitor for skipped cycles
4. Test error recovery
5. Run for 2 hours during market hours

## Rollback Plan

**If Phase 1 Fails:**
- Revert to mock data (current system)
- System continues running
- No trading until fixed

**If Phase 2 Fails:**
- Revert to 5-minute frequency
- Keep real IBKR data (Phase 1)
- System continues trading

## Success Criteria

**Phase 1:**
- ✅ All 40 symbols receive real IBKR data
- ✅ Cross-sectional features computed correctly
- ✅ ML predictions based on real market data
- ✅ Paper trades execute successfully
- ✅ No errors for 1 hour of trading

**Phase 2:**
- ✅ 1-minute cycles complete in <60s
- ✅ <5% cycles skipped due to timeout
- ✅ All features computed correctly
- ✅ Trading decisions made every minute
- ✅ No errors for 2 hours of trading

## Approval

**Approved By**: Chief Data Scientist  
**Date**: 2025-12-16  
**Next Steps**: Begin Phase 1 implementation

---

**CRITICAL**: Current system is trading on fake data. Phase 1 must be completed before next market open.
