# System Analysis - December 9, 2025

## Requirements vs Current Implementation

### Requirement 1: Fix Data Leakage ✅ FIXED
**Status**: FIXED (Dec 8, 2025)

**Issue**: 5-bar forward return and exit timestamp computed before filtering to target date, allowing last bars of each day to peek into next day.

**Fix Applied**: In `scripts/build_intraday_features_rolling.py` lines 158-168:
```python
# Filter to target date first, then compute forward-looking labels within the day
df_pd["date"] = df_pd["timestamp"].dt.date
df_pd = df_pd[df_pd["date"] == target_date_obj]

# Labels and exits: 5-bar horizon within the same day; drop rows without a valid exit
df_pd["future_close"] = df_pd["close"].shift(-5)
df_pd["exit_timestamp"] = df_pd["timestamp"].shift(-5)
df_pd["forward_return"] = (df_pd["future_close"] - df_pd["close"]) / df_pd["close"]
df_pd["label_long"] = (df_pd["forward_return"] > 0.015).astype(int)
df_pd["label_short"] = (df_pd["forward_return"] < -0.015).astype(int)
df_pd = df_pd.dropna(subset=["future_close", "exit_timestamp"])
```

**Action Required**: Rebuild features from scratch (data not yet rebuilt).

---

### Requirement 2: Full Trades List ⚠️ PARTIAL
**Status**: PARTIAL - Missing stop loss and take profit columns

**Current Implementation**: `scripts/rolling_train_and_backtest.py` lines 134-152
```python
trades.append({
    "timestamp_entry": row["timestamp"],
    "timestamp_exit": exit_ts,
    "symbol": row["symbol"],
    "side": "LONG" if sign == 1 else "SHORT",
    "shares": shares,
    "entry_price": price,
    "exit_price": exit_price,
    "gross_pnl": trade_pnl,
    "spread": 0.0,
    "fee": 0.0,
    "net_pnl": trade_pnl,
})
```

**Missing Fields**:
- `stop_loss` (price level)
- `take_profit` (price level)

**Current**: Trades exit after fixed 5-bar horizon (5 minutes on 1m data)
**Issue**: No actual stop loss or take profit logic implemented

---

### Requirement 3: Train on 10m Data ❌ NOT IMPLEMENTED
**Status**: CURRENTLY USING 1-MINUTE DATA

**Current Implementation**: 
- `scripts/build_intraday_features_rolling.py` loads 1-minute bars directly
- No resampling to 10-minute bars
- Features computed on 1-minute granularity

**Evidence**:
```python
def load_intraday_bars(symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    # Loads 1m data directly, no resampling
```

**Required Change**: Add 10-minute resampling before feature engineering

---

### Requirement 4: Intraday Position Entry ✅ IMPLEMENTED
**Status**: WORKING

**Current Implementation**: 
- System processes every bar in the dataset
- No fixed time restrictions
- Can enter positions at any time during market hours (09:30-16:00)

**Evidence**: `scripts/build_intraday_features_rolling.py` lines 73-80
```python
# Market hours filter
df = df.filter(
    ((pl.col("timestamp").dt.hour() > 9)
     | ((pl.col("timestamp").dt.hour() == 9) & (pl.col("timestamp").dt.minute() >= 30)))
    & (pl.col("timestamp").dt.hour() < 16)
)
```

---

### Requirement 5: Entry on 10m Close, Execute on Next 1m Close ❌ NOT IMPLEMENTED
**Status**: NOT IMPLEMENTED

**Current Implementation**:
- Decision and execution happen on same bar
- No separation between signal generation and execution
- Currently using 1-minute bars (not 10-minute)

**Required Architecture**:
```
10m bar closes → Generate signal → Wait for next 1m bar → Execute at 1m close
```

**Current Architecture**:
```
1m bar closes → Generate signal → Execute immediately on same bar
```

---

### Requirement 6: Position Sizing (1% Equity Risk) ✅ IMPLEMENTED
**Status**: WORKING

**Current Implementation**: `scripts/rolling_train_and_backtest.py` lines 119-124
```python
per_trade_risk = equity * risk_fraction  # risk_fraction = 0.01 (1%)
stop_distance = stop_pct * price         # stop_pct = 0.015 (1.5%)
shares = int(per_trade_risk // stop_distance)
if shares <= 0:
    continue
```

**Example**:
- Equity: $10,000
- Risk per trade: $100 (1%)
- Entry price: $50
- Stop distance: $0.75 (1.5%)
- Shares: 100 / 0.75 = 133 shares

---

## Critical Issues Summary

### 🔴 CRITICAL: Data Must Be Rebuilt
- Leakage fix is in code but features not regenerated
- All previous results are invalid
- Must run: `python scripts/build_intraday_features_rolling.py`

### 🔴 CRITICAL: Not Training on 10m Data
- Currently using 1-minute bars
- Need to resample to 10-minute before feature engineering
- This changes the entire feature space

### 🔴 CRITICAL: No Stop Loss / Take Profit Logic
- Trades exit after fixed 5-bar horizon only
- No actual risk management
- Stop/TP fields missing from trades output

### 🟡 IMPORTANT: No Signal-to-Execution Delay
- Decision and execution on same bar
- Need 10m signal → 1m execution architecture
- Requires two-stage data pipeline

---

## Recommended Implementation Plan

### Phase 1: Fix Data Pipeline (10m Training Data)
**Goal**: Train models on 10-minute bars

**Changes Required**:
1. Modify `build_intraday_features_rolling.py`:
   - Load 1m bars
   - Resample to 10m OHLCV
   - Compute features on 10m bars
   - Generate labels on 10m bars (5-bar = 50 minutes)

2. Update feature engineering:
   - All rolling windows scale to 10m (e.g., 5-bar = 50 min, not 5 min)
   - Time-based features remain same (time_since_open, etc.)

**Estimated Effort**: 2-3 hours

---

### Phase 2: Implement Signal-to-Execution Delay
**Goal**: Generate signals on 10m close, execute on next 1m close

**Architecture**:
```
Step 1: Train on 10m data → Generate 10m signals
Step 2: For each 10m signal:
   - Signal timestamp: 10m bar close (e.g., 09:40:00)
   - Execution timestamp: Next 1m bar close (e.g., 09:41:00)
   - Entry price: 1m bar close price at 09:41:00
```

**Changes Required**:
1. Modify `rolling_train_and_backtest.py`:
   - Load 10m predictions (signal timestamps)
   - Load 1m bars (execution prices)
   - For each signal at time T:
     - Find next 1m bar after T
     - Execute at that 1m close price
   - Calculate exit on 1m bars (5 bars after entry on 1m = 5 minutes)

2. Update backtest logic:
   - Separate signal generation from execution
   - Track signal_timestamp vs execution_timestamp
   - Use 1m bars for entry/exit prices

**Estimated Effort**: 4-6 hours

---

### Phase 3: Implement Stop Loss / Take Profit
**Goal**: Exit trades when stop or target hit, not just time-based

**Changes Required**:
1. Add stop/target calculation to signal generation:
   ```python
   stop_loss = entry_price * (1 - stop_pct) if LONG else entry_price * (1 + stop_pct)
   take_profit = entry_price * (1 + tp_pct) if LONG else entry_price * (1 - tp_pct)
   ```

2. Modify backtest to check every 1m bar:
   ```python
   for each 1m bar after entry:
       if LONG:
           if low <= stop_loss: exit at stop_loss
           if high >= take_profit: exit at take_profit
       if SHORT:
           if high >= stop_loss: exit at stop_loss
           if low <= take_profit: exit at take_profit
       if bars_since_entry >= max_hold_bars: exit at close
   ```

3. Update trades output:
   - Add stop_loss and take_profit columns
   - Add exit_reason column (stop_hit, target_hit, time_exit)
   - Calculate actual exit price based on which level hit

**Estimated Effort**: 6-8 hours

---

### Phase 4: Enhanced Trades Reporting
**Goal**: Complete trades list with all required fields

**Changes Required**:
1. Add to trades output:
   ```python
   {
       "instrument": symbol,
       "datetime_entry": timestamp_entry,
       "entry_price": entry_price,
       "direction": "LONG" or "SHORT",
       "shares": shares,
       "stop_loss": stop_loss_price,
       "take_profit": take_profit_price,
       "datetime_exit": timestamp_exit,
       "exit_price": exit_price,
       "exit_reason": "stop_hit" | "target_hit" | "time_exit",
       "gross_pnl": gross_pnl,
       "fee": fee,
       "spread": spread,
       "net_pnl": net_pnl,
       "r_multiple": (exit_price - entry_price) / (entry_price - stop_loss),
   }
   ```

2. Implement fee/spread model:
   - Fee: $0.0035 per share (min $0.35)
   - Spread: 0.05% of entry price (5 bps)

**Estimated Effort**: 2-3 hours

---

## Total Implementation Effort

| Phase | Description | Effort | Priority |
|-------|-------------|--------|----------|
| 1 | 10m data pipeline | 2-3 hours | 🔴 CRITICAL |
| 2 | Signal-to-execution delay | 4-6 hours | 🔴 CRITICAL |
| 3 | Stop loss / take profit | 6-8 hours | 🔴 CRITICAL |
| 4 | Enhanced reporting | 2-3 hours | 🟡 IMPORTANT |
| **TOTAL** | | **14-20 hours** | |

---

## Recommended Execution Order

### Session 1 (3-4 hours): Data Pipeline
1. Modify `build_intraday_features_rolling.py` to resample to 10m
2. Rebuild features from scratch
3. Verify no leakage (check last bars of each day)
4. Validate feature distributions

### Session 2 (4-6 hours): Signal-to-Execution
1. Modify `rolling_train_and_backtest.py` for two-stage execution
2. Load 10m signals + 1m execution bars
3. Implement 1-bar delay logic
4. Test on small date range

### Session 3 (6-8 hours): Risk Management
1. Implement stop loss / take profit monitoring
2. Add exit reason tracking
3. Calculate actual exit prices based on intrabar highs/lows
4. Add max hold time logic

### Session 4 (2-3 hours): Reporting & Validation
1. Add all required fields to trades output
2. Implement fee/spread model
3. Generate comprehensive trade report
4. Validate against requirements

---

## Key Design Decisions Required

### Decision 1: Exit Horizon on 10m or 1m?
**Current**: 5-bar exit on 1m data = 5 minutes
**Options**:
- A) 5-bar exit on 10m data = 50 minutes
- B) Keep 5-minute exit but monitor on 1m bars
- C) Use stop/target only, no time-based exit

**Recommendation**: Option C (stop/target only) for cleaner risk management

### Decision 2: Stop Loss Calculation
**Current**: Fixed 1.5% stop
**Options**:
- A) Keep fixed 1.5%
- B) ATR-based (e.g., 1.5x ATR)
- C) Volatility-adjusted (e.g., 2x recent volatility)

**Recommendation**: Option B (ATR-based) for adaptive risk

### Decision 3: Take Profit Calculation
**Current**: None
**Options**:
- A) Fixed R-multiple (e.g., 2R)
- B) Fixed percentage (e.g., 3%)
- C) Trailing stop after 1R

**Recommendation**: Option A (2R target) for consistent risk/reward

---

## Files to Modify

### Primary Changes
1. `scripts/build_intraday_features_rolling.py` - Add 10m resampling
2. `scripts/rolling_train_and_backtest.py` - Two-stage execution + stop/TP logic

### Supporting Changes
3. `scripts/analyze_rolling_results.py` - Update for new trade fields
4. `scripts/run_rolling_pipeline.sh` - Update documentation

### New Files Needed
5. `scripts/validate_no_leakage.py` - Verify same-day exits only
6. `scripts/backtest_with_stops.py` - Standalone stop/TP testing

---

## Testing Strategy

### Unit Tests
1. Test 10m resampling preserves OHLCV correctly
2. Test signal-to-execution delay (1-bar offset)
3. Test stop loss hit detection (intrabar)
4. Test take profit hit detection (intrabar)
5. Test position sizing calculation

### Integration Tests
1. Run on 1 symbol, 1 day → verify trades output
2. Run on 5 symbols, 1 week → verify no leakage
3. Run on full dataset → verify performance metrics

### Validation Checks
1. No exit timestamps after 16:00 (EOD)
2. No exit timestamps on different day than entry
3. All trades have stop_loss and take_profit set
4. Position sizes respect 1% risk rule
5. Net PnL = Gross PnL - Fees - Spread

---

## Risk Assessment

### High Risk
- 10m resampling may reduce signal count significantly
- Signal-to-execution delay adds slippage
- Stop losses may get hit more frequently than time exits

### Medium Risk
- Feature distributions may change on 10m data
- Model performance may degrade on coarser granularity
- Position sizing may result in very small positions for low-priced stocks

### Low Risk
- Data leakage fix is straightforward
- Trades reporting is cosmetic
- Fee/spread model is well-defined

---

## Success Criteria

### Phase 1 Complete When:
- ✅ Features generated on 10m bars
- ✅ No cross-day exits in labels
- ✅ Feature distributions look reasonable

### Phase 2 Complete When:
- ✅ Signals generated on 10m close
- ✅ Execution happens on next 1m close
- ✅ Entry prices from 1m bars, not 10m bars

### Phase 3 Complete When:
- ✅ Trades exit when stop or target hit
- ✅ Exit prices reflect intrabar highs/lows
- ✅ Exit reasons tracked correctly

### Phase 4 Complete When:
- ✅ All required fields in trades output
- ✅ Fees and spread calculated correctly
- ✅ Net PnL matches gross PnL - costs

---

## Next Steps

1. **Review this analysis** - Confirm requirements understanding
2. **Approve design decisions** - Choose options for exit horizon, stop calculation, TP calculation
3. **Begin Phase 1** - Implement 10m resampling
4. **Rebuild features** - Generate clean dataset
5. **Proceed to Phase 2** - Signal-to-execution delay

---

**Document Status**: Draft for Review
**Date**: December 9, 2025
**Author**: System Analysis
