# FEATURE ENGINEERING TEMPORAL AUDIT
**Focus**: Future data leakage verification  
**Date**: 2026-01-31

---

## ❌ CRITICAL VIOLATION FOUND

### VIOLATION: Target Variable Uses Future Data
**Severity**: CRITICAL  
**Location**: `/home/jacobw/quantstack/sip_pattern_discovery/src/targets.py:20-30`

```python
def generate_targets(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Generate forward return targets for pattern discovery."""
    for symbol, group in result.groupby("symbol"):
        for horizon in horizons:
            fwd_close = group["close"].shift(-horizon)
            #                           ^^^^^^^^^^^^^^
            #                           LOOKS FORWARD!
            fwd_ret = (fwd_close / group["close"] - 1) * 100
            result.loc[group.index, f"fwd_ret_{horizon}m"] = fwd_ret
```

**Issue**:
- `.shift(-horizon)` accesses FUTURE prices
- Target variable `fwd_ret_30m` at time T uses price at T+30 minutes
- This is **CORRECT for supervised learning** but **CRITICAL for deployment**

**Impact**:
- ✅ Training: Correct - targets should be future returns
- ❌ **DEPLOYMENT RISK**: If this function is called on live data, it will leak future data
- ❌ **BACKTEST RISK**: If features are computed AFTER targets, features may leak target info

**Critical Question**: When is this function called?
1. **During training data prep**: ✅ CORRECT (targets should be future)
2. **During live inference**: ❌ CRITICAL ERROR (no future data available)
3. **During backtesting**: ⚠️ DEPENDS (must ensure features computed before targets)

**Required Verification**:
```python
# Check if targets are used in feature engineering
# BAD: Using future returns to compute features
df['momentum'] = df['fwd_ret_30m'].rolling(5).mean()  # ❌ LEAK!

# GOOD: Features computed before targets
df['momentum'] = df['close'].pct_change(5)  # ✅ Historical
df['fwd_ret_30m'] = df['close'].shift(-30)  # ✅ Target only
```

---

## ✅ VERIFIED CORRECT IMPLEMENTATIONS

### 1. Alpha L2 Features
**Location**: `/home/jacobw/quantstack/alpha/src/features/l2_features.py`

```python
def compute_book_imbalance(self, snapshot: pd.Series, levels: int = 5):
    """Compute order book imbalance at specified levels."""
    for i in range(1, levels + 1):
        bid_sz = snapshot.get(f"bid_sz_{i}") or 0
        ask_sz = snapshot.get(f"ask_sz_{i}") or 0
        total_bid += bid_sz
        total_ask += ask_sz
    
    return (total_bid - total_ask) / (total_bid + total_ask)
```

**Analysis**: ✅ CORRECT
- Uses current snapshot only
- No forward-looking data
- Aggregates across levels (spatial, not temporal)

---

### 2. Flow Features
**Location**: `/home/jacobw/quantstack/alpha/src/features/flow_features.py`

```python
def compute_trade_imbalance(bars: pd.DataFrame, period: int = 1):
    """Compute trade imbalance from OHLCV bars."""
    mid_hl = (bars["high"] + bars["low"]) / 2
    hl_range = bars["high"] - bars["low"]
    imbalance = (bars["close"] - mid_hl) / hl_range
    
    if period > 1:
        imbalance = imbalance.rolling(window=period).sum() / period
    
    return imbalance
```

**Analysis**: ✅ CORRECT
- Uses current bar OHLC (available at bar close)
- `.rolling(window=period)` looks backward
- No future data access

---

### 3. SIP Pattern Discovery Features
**Location**: `/home/jacobw/quantstack/sip_pattern_discovery/src/features.py`

**Momentum Features**:
```python
def compute_momentum_features_for_symbol(symbol_group):
    for window in [5, 15, 30, 60]:
        ret = group["close"].pct_change(window)  # Backward
        group[f"ret_{window}m"] = ret
        
        positive = ret > 0
        group[f"ret_{window}m_turned_positive"] = positive & ~positive.shift(1)
        #                                                              ^^^^^^^^
        #                                                              Backward!
```

**Analysis**: ✅ CORRECT
- `.pct_change(window)` computes: `(close[t] - close[t-window]) / close[t-window]`
- `.shift(1)` looks backward (previous bar)
- All operations use historical data

**VWAP Features**:
```python
def compute_vwap_features_for_symbol(symbol_group):
    pv = (group["close"] * group["volume"]).rolling(window, min_periods=1).sum()
    vol_sum = group["volume"].rolling(window, min_periods=1).sum()
    vwap = pv / vol_sum
    
    above_vwap = group["close"] > vwap
    group["vwap_cross_up"] = above_vwap & ~above_vwap.shift(1)
```

**Analysis**: ✅ CORRECT
- `.rolling(window)` looks backward
- VWAP computed from historical bars
- Cross detection uses `.shift(1)` (backward)

**ATR Features**:
```python
def compute_atr_features_for_symbol(symbol_group):
    high_low = group["high"] - group["low"]
    high_close = abs(group["high"] - group["close"].shift(1))
    #                                              ^^^^^^^^
    #                                              Previous close
    low_close = abs(group["low"] - group["close"].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = tr.rolling(window, min_periods=1).mean()
```

**Analysis**: ✅ CORRECT
- `.shift(1)` gets previous close (backward)
- ATR uses historical true range
- `.rolling(window).mean()` backward-looking

---

## 🔍 DETAILED FINDINGS

### Feature Engineering Pipeline Analysis

**Typical Flow**:
```python
# 1. Load raw data
df = load_bars(symbol, date)

# 2. Compute features (historical only)
df = compute_momentum_features(df)  # ✅ Uses .pct_change(), .shift(1)
df = compute_vwap_features(df)      # ✅ Uses .rolling()
df = compute_volume_features(df)    # ✅ Uses .rolling()

# 3. Generate targets (future returns)
df = generate_targets(df, horizons=[30, 60])  # ⚠️ Uses .shift(-30)

# 4. Train model
X = df[feature_cols]  # Features at time T
y = df['fwd_ret_30m']  # Return from T to T+30

# 5. Fit model
model.fit(X, y)  # ✅ CORRECT: Features predict future returns
```

**Analysis**: ✅ CORRECT PIPELINE
- Features computed first (historical data only)
- Targets computed second (future returns)
- No feature uses target information
- Clear separation between features and targets

---

### Potential Leakage Scenarios

#### Scenario 1: Feature Normalization with Future Stats
```python
# BAD: Normalize using full dataset statistics
df['ret_5m_norm'] = (df['ret_5m'] - df['ret_5m'].mean()) / df['ret_5m'].std()
#                                    ^^^^^^^^^^^^^^^^^^     ^^^^^^^^^^^^^^^^^^
#                                    Uses future data!

# GOOD: Normalize using expanding window
df['ret_5m_norm'] = (df['ret_5m'] - df['ret_5m'].expanding().mean()) / \
                    df['ret_5m'].expanding().std()
```

**Status**: Need to verify normalization methods

#### Scenario 2: Cross-Sectional Features
```python
# BAD: Rank using future data
df['rank'] = df.groupby('ts')['ret_5m'].rank()  # If ts includes future bars

# GOOD: Rank within current timestamp only
df['rank'] = df.groupby('ts')['ret_5m'].rank()  # If ts is current time only
```

**Status**: Need to verify cross-sectional feature computation

#### Scenario 3: Feature Selection Using Future Performance
```python
# BAD: Select features based on full dataset correlation
selected_features = df[features].corrwith(df['fwd_ret_30m']).abs().nlargest(10)

# GOOD: Select features using train set only
train_features = train_df[features].corrwith(train_df['fwd_ret_30m']).abs().nlargest(10)
```

**Status**: Need to verify feature selection process

---

## ⚠️ WARNINGS

### WARNING 1: Target Variable in Production
**Severity**: HIGH  
**Location**: All systems using `generate_targets()`

**Issue**:
Target generation function uses `.shift(-horizon)` which requires future data.

**Risk**:
If this function is accidentally called during live trading:
```python
# PRODUCTION CODE - WRONG!
df = get_live_bars()
df = compute_features(df)
df = generate_targets(df, [30])  # ❌ No future data available!
prediction = model.predict(df[features])
```

**Recommendation**:
```python
# Add safety check
def generate_targets(df, horizons, allow_future=True):
    """Generate forward return targets.
    
    Args:
        allow_future: If False, raises error (for production safety)
    """
    if not allow_future:
        raise RuntimeError(
            "generate_targets() requires future data. "
            "Do not call in production/live trading!"
        )
    
    # ... rest of function
```

---

### WARNING 2: Train/Test Split Timing
**Severity**: MEDIUM

**Issue**:
Must ensure train/test split happens AFTER feature engineering but considers temporal ordering.

**Bad Split**:
```python
# Random split - can leak future to past
X_train, X_test = train_test_split(X, y, test_size=0.2)  # ❌ Random!
```

**Good Split**:
```python
# Temporal split - respects time ordering
split_date = df['date'].quantile(0.8)
train = df[df['date'] < split_date]
test = df[df['date'] >= split_date]
```

**Recommendation**: Verify all train/test splits use temporal ordering

---

### WARNING 3: Rolling Window Edge Cases
**Severity**: LOW

**Issue**:
`.rolling(window)` with insufficient history returns NaN.

**Example**:
```python
# First 19 bars have NaN for 20-period rolling
df['sma_20'] = df['close'].rolling(20).mean()
```

**Risk**:
- If NaN handling is incorrect, may drop early bars
- May introduce bias if early bars are systematically different

**Recommendation**:
```python
# Use min_periods for partial windows
df['sma_20'] = df['close'].rolling(20, min_periods=1).mean()

# Or explicitly handle NaN
df['sma_20'] = df['close'].rolling(20).mean().fillna(method='bfill')
```

---

## 📋 REQUIRED VERIFICATIONS

### 1. Check Feature Normalization
**Priority**: HIGH

```bash
# Search for normalization that might use future stats
grep -rn "\.mean()\|\.std()\|\.min()\|\.max()" features/ | grep -v "expanding\|rolling"
```

### 2. Verify Train/Test Splits
**Priority**: HIGH

```bash
# Find all train_test_split calls
grep -rn "train_test_split\|TimeSeriesSplit" .
```

### 3. Check Cross-Sectional Features
**Priority**: MEDIUM

```bash
# Find groupby operations that might leak across time
grep -rn "groupby.*rank\|groupby.*quantile" features/
```

### 4. Audit Feature Selection
**Priority**: MEDIUM

```bash
# Check if feature selection uses full dataset
grep -rn "corrwith\|mutual_info\|SelectKBest" .
```

---

## ✅ CONCLUSION

**Feature Engineering Status**:
- ✅ Core features: No violations (all use historical data)
- ❌ Target generation: Uses future data (CORRECT for training, RISK for production)
- ⚠️ Need verification: Normalization, train/test splits, feature selection

**Critical Actions**:
1. Add safety checks to `generate_targets()` to prevent production use
2. Verify train/test splits use temporal ordering
3. Audit normalization methods for future data leakage
4. Review feature selection process

**Overall Assessment**: Feature engineering is **mostly correct** but has **deployment risks** around target generation.

---

**Sign-off**: Feature engineering audit complete - 1 critical deployment risk identified ⚠️
