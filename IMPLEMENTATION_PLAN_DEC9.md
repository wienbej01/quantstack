# Implementation Plan - December 9, 2025

## Overview
Transform the current 1-minute rolling system into a production-ready 10-minute system with proper signal-to-execution delay, stop loss/take profit logic, and comprehensive trade reporting.

---

## Phase 1: 10-Minute Data Pipeline (2-3 hours)

### 1.1 Modify Feature Building Script

**File**: `scripts/build_intraday_features_rolling.py`

**Changes**:

```python
# After loading 1m bars, add resampling function
def resample_to_10m(df_1m):
    """Resample 1-minute bars to 10-minute OHLCV."""
    df_pd = df_1m.to_pandas()
    df_pd = df_pd.set_index('timestamp')
    
    resampled = df_pd.resample('10T', label='right', closed='right').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()
    
    resampled = resampled.reset_index()
    return pl.from_pandas(resampled)

# In load_intraday_bars(), after loading and filtering:
def load_intraday_bars(symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    # ... existing code to load 1m bars ...
    
    # NEW: Resample to 10m
    df = resample_to_10m(df)
    
    return df.sort("timestamp") if len(df) > 0 else None
```

**Update Label Calculation**:
```python
# In engineer_features(), update forward return calculation
# OLD: 5-bar on 1m = 5 minutes
# NEW: 5-bar on 10m = 50 minutes

df_pd["future_close"] = df_pd["close"].shift(-5)  # Now 50 minutes ahead
df_pd["exit_timestamp"] = df_pd["timestamp"].shift(-5)
```

**Update Feature Windows**:
```python
# Adjust rolling windows for 10m granularity
# OLD: 5-bar = 5 minutes
# NEW: 5-bar = 50 minutes

# These features now represent longer time periods:
df_pd["returns_5"] = df_pd["close"].pct_change(5)    # 50 min return
df_pd["returns_10"] = df_pd["close"].pct_change(10)  # 100 min return
df_pd["returns_20"] = df_pd["close"].pct_change(20)  # 200 min return
```

### 1.2 Validation Script

**New File**: `scripts/validate_10m_features.py`

```python
#!/usr/bin/env python3
"""Validate 10m feature generation."""

import polars as pl
from pathlib import Path

def validate():
    features = pl.read_parquet("run/intraday_features_rolling/features.parquet")
    
    # Check 1: Timestamps are 10-minute aligned
    df = features.to_pandas()
    df['minute'] = df['timestamp'].dt.minute
    valid_minutes = df['minute'].isin([0, 10, 20, 30, 40, 50])
    print(f"10m aligned: {valid_minutes.mean():.2%}")
    
    # Check 2: No cross-day exits
    df['entry_date'] = df['timestamp'].dt.date
    df['exit_date'] = df['exit_timestamp'].dt.date
    same_day = (df['entry_date'] == df['exit_date']).mean()
    print(f"Same-day exits: {same_day:.2%}")
    
    # Check 3: Exit timestamps are valid
    df['exit_hour'] = df['exit_timestamp'].dt.hour
    before_close = (df['exit_hour'] < 16).mean()
    print(f"Exits before 16:00: {before_close:.2%}")
    
    # Check 4: Feature distributions
    print(f"\nFeature ranges:")
    print(f"returns_5: [{df['returns_5'].min():.4f}, {df['returns_5'].max():.4f}]")
    print(f"volatility_5: [{df['volatility_5'].min():.4f}, {df['volatility_5'].max():.4f}]")
    print(f"volume_ratio: [{df['volume_ratio'].min():.2f}, {df['volume_ratio'].max():.2f}]")

if __name__ == "__main__":
    validate()
```

### 1.3 Rebuild Features

**Command**:
```bash
# Clear old features
rm -rf run/intraday_features_rolling/

# Rebuild with 10m resampling
nohup python scripts/build_intraday_features_rolling.py \
  > /tmp/build_intraday_10m.log 2>&1 &

# Monitor progress
tail -f /tmp/build_intraday_10m.log

# Validate when complete
python scripts/validate_10m_features.py
```

**Expected Output**:
- 10m aligned: 100%
- Same-day exits: 100%
- Exits before 16:00: 100%

---

## Phase 2: Signal-to-Execution Delay (4-6 hours)

### 2.1 Create Execution Price Loader

**New File**: `scripts/load_execution_prices.py`

```python
#!/usr/bin/env python3
"""Load 1-minute execution prices for 10-minute signals."""

from pathlib import Path
from datetime import timedelta
import polars as pl
import pandas as pd

def load_1m_bars_for_execution(symbols, start_date, end_date, 
                                data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load 1m bars for execution pricing."""
    all_bars = []
    
    for symbol in symbols:
        symbol_path = Path(data_root) / symbol
        if not symbol_path.exists():
            continue
            
        # Load all months in range
        # ... (similar to existing load logic)
        
        df = pl.read_parquet(files)
        df = df.filter(
            (pl.col("timestamp").dt.date() >= start_date) &
            (pl.col("timestamp").dt.date() <= end_date)
        )
        df = df.with_columns(pl.lit(symbol).alias("symbol"))
        all_bars.append(df)
    
    return pl.concat(all_bars).sort(["symbol", "timestamp"])

def get_execution_price(signal_timestamp, symbol, bars_1m):
    """Get execution price at next 1m bar after signal."""
    # Signal at 10m close (e.g., 09:40:00)
    # Execute at next 1m close (e.g., 09:41:00)
    
    next_bar = bars_1m.filter(
        (pl.col("symbol") == symbol) &
        (pl.col("timestamp") > signal_timestamp)
    ).sort("timestamp").head(1)
    
    if len(next_bar) == 0:
        return None, None
    
    return next_bar["close"][0], next_bar["timestamp"][0]
```

### 2.2 Modify Backtest Script

**File**: `scripts/rolling_train_and_backtest.py`

**Add after model training**:

```python
def backtest_with_execution_delay(
    model_long,
    model_short,
    test_df_10m,      # 10m bars with features
    bars_1m,          # 1m bars for execution
    feature_cols,
    threshold=0.30,
    equity=10_000.0,
    risk_fraction=0.01,
    stop_pct=0.015,
):
    """Backtest with signal-to-execution delay."""
    
    # Generate signals on 10m bars
    X_test = test_df_10m[feature_cols]
    test_df_10m["prob_long"] = model_long.predict(X_test)
    test_df_10m["prob_short"] = model_short.predict(X_test)
    
    test_df_10m["prediction"] = 0
    test_df_10m.loc[test_df_10m["prob_long"] >= threshold, "prediction"] = 1
    test_df_10m.loc[test_df_10m["prob_short"] >= threshold, "prediction"] = -1
    
    signals = test_df_10m[test_df_10m["prediction"] != 0].copy()
    signals = signals.sort_values("timestamp")
    
    if len(signals) == 0:
        return None
    
    trades = []
    
    for _, signal in signals.iterrows():
        signal_ts = signal["timestamp"]
        symbol = signal["symbol"]
        direction = signal["prediction"]
        
        # Get execution price from next 1m bar
        symbol_bars = bars_1m[bars_1m["symbol"] == symbol]
        next_bars = symbol_bars[symbol_bars["timestamp"] > signal_ts].sort_values("timestamp")
        
        if len(next_bars) == 0:
            continue
        
        entry_bar = next_bars.iloc[0]
        entry_price = entry_bar["close"]
        entry_ts = entry_bar["timestamp"]
        
        # Calculate position size
        per_trade_risk = equity * risk_fraction
        stop_distance = stop_pct * entry_price
        shares = int(per_trade_risk // stop_distance)
        
        if shares <= 0:
            continue
        
        # Calculate stop and target
        if direction == 1:  # LONG
            stop_loss = entry_price * (1 - stop_pct)
            take_profit = entry_price * (1 + stop_pct * 2)  # 2R target
        else:  # SHORT
            stop_loss = entry_price * (1 + stop_pct)
            take_profit = entry_price * (1 - stop_pct * 2)
        
        # Find exit (for now, use 5-bar time exit on 1m)
        exit_bars = next_bars.iloc[1:6]  # Next 5 bars after entry
        if len(exit_bars) == 0:
            continue
        
        exit_bar = exit_bars.iloc[-1]
        exit_price = exit_bar["close"]
        exit_ts = exit_bar["timestamp"]
        
        # Calculate P&L
        trade_pnl = shares * (exit_price - entry_price) * direction
        equity += trade_pnl
        
        trades.append({
            "signal_timestamp": signal_ts,
            "entry_timestamp": entry_ts,
            "exit_timestamp": exit_ts,
            "symbol": symbol,
            "side": "LONG" if direction == 1 else "SHORT",
            "shares": shares,
            "entry_price": entry_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "exit_price": exit_price,
            "exit_reason": "time_exit",  # Will update in Phase 3
            "gross_pnl": trade_pnl,
            "spread": 0.0,
            "fee": 0.0,
            "net_pnl": trade_pnl,
        })
    
    # Calculate metrics
    wins = sum(1 for t in trades if t["gross_pnl"] > 0)
    
    return {
        "total_signals": len(trades),
        "combined_win_rate": wins / len(trades) if trades else 0,
        "total_pnl": (equity - 10_000) / 10_000,
        "equity_end": equity,
        "trades": trades,
    }
```

**Update main() to load 1m bars**:

```python
def main():
    # ... existing code ...
    
    # Load 10m features
    features_path = Path("run/intraday_features_rolling/features.parquet")
    df_10m = pl.read_parquet(features_path).to_pandas()
    
    # NEW: Load 1m bars for execution
    symbols = df_10m["symbol"].unique()
    bars_1m = load_1m_bars_for_execution(
        symbols, 
        start_date="2024-02-01",
        end_date="2025-09-30"
    ).to_pandas()
    
    # ... rest of rolling loop ...
    
    # In backtest call:
    metrics = backtest_with_execution_delay(
        model_long,
        model_short,
        test_df.copy(),
        bars_1m,  # Pass 1m bars
        feature_cols,
        equity=equity,
    )
```

---

## Phase 3: Stop Loss / Take Profit (6-8 hours)

### 3.1 Implement Intrabar Exit Logic

**Add to backtest function**:

```python
def find_exit_with_stops(
    entry_ts,
    entry_price,
    stop_loss,
    take_profit,
    direction,
    symbol,
    bars_1m,
    max_bars=390,  # Max 6.5 hours
):
    """Find exit based on stop/target/time."""
    
    # Get bars after entry
    symbol_bars = bars_1m[
        (bars_1m["symbol"] == symbol) &
        (bars_1m["timestamp"] > entry_ts)
    ].sort_values("timestamp").head(max_bars)
    
    if len(symbol_bars) == 0:
        return None, None, "no_data"
    
    for idx, bar in symbol_bars.iterrows():
        if direction == 1:  # LONG
            # Check stop loss (intrabar low)
            if bar["low"] <= stop_loss:
                return stop_loss, bar["timestamp"], "stop_hit"
            
            # Check take profit (intrabar high)
            if bar["high"] >= take_profit:
                return take_profit, bar["timestamp"], "target_hit"
        
        else:  # SHORT
            # Check stop loss (intrabar high)
            if bar["high"] >= stop_loss:
                return stop_loss, bar["timestamp"], "stop_hit"
            
            # Check take profit (intrabar low)
            if bar["low"] <= take_profit:
                return take_profit, bar["timestamp"], "target_hit"
    
    # Time exit if no stop/target hit
    last_bar = symbol_bars.iloc[-1]
    return last_bar["close"], last_bar["timestamp"], "time_exit"
```

**Update trade execution**:

```python
# In backtest_with_execution_delay(), replace exit logic:

# OLD:
# exit_bars = next_bars.iloc[1:6]
# exit_bar = exit_bars.iloc[-1]
# exit_price = exit_bar["close"]

# NEW:
exit_price, exit_ts, exit_reason = find_exit_with_stops(
    entry_ts,
    entry_price,
    stop_loss,
    take_profit,
    direction,
    symbol,
    bars_1m,
    max_bars=390,
)

if exit_price is None:
    continue  # Skip trade if no valid exit

# Update trade record
trades.append({
    # ... existing fields ...
    "exit_price": exit_price,
    "exit_timestamp": exit_ts,
    "exit_reason": exit_reason,
    # ... rest of fields ...
})
```

### 3.2 Add ATR-Based Stops

**Add ATR calculation to features**:

```python
# In build_intraday_features_rolling.py, add to engineer_features():

def calculate_atr(df_pd, period=14):
    """Calculate Average True Range."""
    df_pd["prev_close"] = df_pd["close"].shift(1)
    
    df_pd["tr1"] = df_pd["high"] - df_pd["low"]
    df_pd["tr2"] = abs(df_pd["high"] - df_pd["prev_close"])
    df_pd["tr3"] = abs(df_pd["low"] - df_pd["prev_close"])
    
    df_pd["tr"] = df_pd[["tr1", "tr2", "tr3"]].max(axis=1)
    df_pd["atr"] = df_pd["tr"].rolling(period, min_periods=1).mean()
    
    return df_pd

# Add to feature engineering:
df_pd = calculate_atr(df_pd, period=14)
```

**Update stop calculation**:

```python
# In backtest, use ATR for stop distance:

atr = signal["atr"]
stop_distance = atr * 1.5  # 1.5x ATR stop

if direction == 1:
    stop_loss = entry_price - stop_distance
    take_profit = entry_price + (stop_distance * 2)  # 2R target
else:
    stop_loss = entry_price + stop_distance
    take_profit = entry_price - (stop_distance * 2)

# Position sizing based on ATR stop
per_trade_risk = equity * risk_fraction
shares = int(per_trade_risk // stop_distance)
```

---

## Phase 4: Enhanced Reporting (2-3 hours)

### 4.1 Add Fee and Spread Model

**Add to backtest**:

```python
def calculate_costs(shares, entry_price, exit_price):
    """Calculate fees and spread."""
    
    # Commission: $0.0035 per share, min $0.35
    commission_per_share = 0.0035
    commission_min = 0.35
    
    entry_fee = max(shares * commission_per_share, commission_min)
    exit_fee = max(shares * commission_per_share, commission_min)
    total_fee = entry_fee + exit_fee
    
    # Spread: 5 bps (0.05%)
    spread_bps = 5
    spread_cost = shares * entry_price * (spread_bps / 10000)
    
    return total_fee, spread_cost

# In trade execution:
fee, spread = calculate_costs(shares, entry_price, exit_price)
net_pnl = gross_pnl - fee - spread

trades.append({
    # ... existing fields ...
    "fee": fee,
    "spread": spread,
    "net_pnl": net_pnl,
})
```

### 4.2 Add R-Multiple Calculation

```python
# In trade record:
r_multiple = (exit_price - entry_price) / stop_distance * direction

trades.append({
    # ... existing fields ...
    "r_multiple": r_multiple,
    "stop_distance": stop_distance,
})
```

### 4.3 Enhanced Trade Report

**New File**: `scripts/generate_trade_report.py`

```python
#!/usr/bin/env python3
"""Generate comprehensive trade report."""

import pandas as pd
from pathlib import Path

def generate_report():
    trades = pd.read_csv("run/rolling_results/trades.csv")
    
    print("=" * 80)
    print("TRADE REPORT")
    print("=" * 80)
    
    # Overall metrics
    print(f"\nTotal Trades: {len(trades)}")
    print(f"Win Rate: {(trades['net_pnl'] > 0).mean():.2%}")
    print(f"Total Net P&L: ${trades['net_pnl'].sum():,.2f}")
    print(f"Avg Net P&L: ${trades['net_pnl'].mean():.2f}")
    print(f"Avg R-Multiple: {trades['r_multiple'].mean():.2f}R")
    
    # By direction
    print("\nBy Direction:")
    for side in ["LONG", "SHORT"]:
        side_trades = trades[trades["side"] == side]
        print(f"  {side}:")
        print(f"    Trades: {len(side_trades)}")
        print(f"    Win Rate: {(side_trades['net_pnl'] > 0).mean():.2%}")
        print(f"    Avg P&L: ${side_trades['net_pnl'].mean():.2f}")
    
    # By exit reason
    print("\nBy Exit Reason:")
    for reason in trades["exit_reason"].unique():
        reason_trades = trades[trades["exit_reason"] == reason]
        print(f"  {reason}:")
        print(f"    Count: {len(reason_trades)} ({len(reason_trades)/len(trades):.1%})")
        print(f"    Win Rate: {(reason_trades['net_pnl'] > 0).mean():.2%}")
        print(f"    Avg R: {reason_trades['r_multiple'].mean():.2f}R")
    
    # Cost analysis
    print("\nCost Analysis:")
    print(f"  Total Fees: ${trades['fee'].sum():,.2f}")
    print(f"  Total Spread: ${trades['spread'].sum():,.2f}")
    print(f"  Total Costs: ${(trades['fee'] + trades['spread']).sum():,.2f}")
    print(f"  Avg Cost per Trade: ${(trades['fee'] + trades['spread']).mean():.2f}")
    
    # Top/Bottom trades
    print("\nTop 5 Trades:")
    print(trades.nlargest(5, "net_pnl")[["symbol", "side", "net_pnl", "r_multiple"]])
    
    print("\nBottom 5 Trades:")
    print(trades.nsmallest(5, "net_pnl")[["symbol", "side", "net_pnl", "r_multiple"]])

if __name__ == "__main__":
    generate_report()
```

---

## Testing Checklist

### Phase 1: 10m Data
- [ ] Timestamps are 10-minute aligned (0, 10, 20, 30, 40, 50)
- [ ] No cross-day exits in labels
- [ ] All exits before 16:00
- [ ] Feature distributions reasonable
- [ ] Label balance (LONG/SHORT) reasonable

### Phase 2: Execution Delay
- [ ] Entry timestamp > signal timestamp
- [ ] Entry timestamp is 1m bar close
- [ ] Entry price from 1m bar, not 10m bar
- [ ] All entries have valid execution prices

### Phase 3: Stops/Targets
- [ ] Stop loss and take profit calculated correctly
- [ ] Exit reason tracked (stop_hit, target_hit, time_exit)
- [ ] Exit prices match intrabar highs/lows when stop/target hit
- [ ] No exits after 16:00

### Phase 4: Reporting
- [ ] All required fields present in trades.csv
- [ ] Fees calculated correctly (min $0.35)
- [ ] Spread calculated correctly (5 bps)
- [ ] Net P&L = Gross P&L - Fee - Spread
- [ ] R-multiple calculated correctly

---

## Rollback Plan

If issues arise, rollback to previous version:

```bash
# Backup current code
git stash

# Restore previous version
git checkout <previous-commit>

# Or restore specific file
git checkout HEAD~1 scripts/build_intraday_features_rolling.py
```

---

## Performance Expectations

### Before Changes (1m system):
- Bars per day: ~390 (1m bars)
- Signals per day: ~50-100
- Avg hold time: 5 minutes
- Win rate: Unknown (data leakage)

### After Changes (10m system):
- Bars per day: ~39 (10m bars)
- Signals per day: ~5-15 (fewer opportunities)
- Avg hold time: 50 minutes (5-bar on 10m)
- Win rate: 55-65% (expected with stops/targets)
- Avg R: 0.5-1.0R (with 2R targets and stops)

---

## Timeline

| Day | Phase | Tasks | Hours |
|-----|-------|-------|-------|
| 1 | Phase 1 | 10m resampling, rebuild features | 3 |
| 2 | Phase 2 | Signal-to-execution delay | 5 |
| 3 | Phase 3 | Stop/target logic | 6 |
| 4 | Phase 4 | Enhanced reporting, testing | 3 |
| **Total** | | | **17 hours** |

---

## Next Actions

1. **Review and approve** this implementation plan
2. **Confirm design decisions**:
   - Exit horizon: Stop/target only (no time exit)?
   - Stop calculation: ATR-based (1.5x ATR)?
   - Take profit: 2R target?
3. **Begin Phase 1**: Modify `build_intraday_features_rolling.py`
4. **Test on small dataset** before full rebuild

---

**Document Status**: Ready for Implementation
**Date**: December 9, 2025
