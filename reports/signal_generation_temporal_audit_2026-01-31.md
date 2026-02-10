# SIGNAL GENERATION TEMPORAL AUDIT
**Focus**: Historical data usage verification  
**Date**: 2026-01-31

---

## ❌ CRITICAL VIOLATION FOUND

### VIOLATION: Swing Point Detection Uses Future Data
**Severity**: CRITICAL  
**Location**: `/home/jacobw/intraday_stack/src/signals/candidate_generator.py:305-330`

```python
def _is_swing_low(self, df: pd.DataFrame, idx: int) -> bool:
    """Check if index is a swing low."""
    if idx < self.swing_lookback or idx >= len(df) - self.swing_lookback:
        return False
    low = float(df.iloc[idx]['low'])
    for offset in range(-self.swing_lookback, self.swing_lookback + 1):
        #                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
        #                   LOOKS FORWARD: idx + positive offset
        if offset == 0:
            continue
        if float(df.iloc[idx + offset]['low']) <= low:
            return False
    return True
```

**Issue**:
- `range(-self.swing_lookback, self.swing_lookback + 1)` includes POSITIVE offsets
- `df.iloc[idx + offset]` when offset > 0 accesses FUTURE bars
- Swing low at bar `i` requires knowing bars `i+1, i+2, ..., i+5` (future data)

**Impact**:
- **SEVERE LOOK-AHEAD BIAS** in backtests
- Signals generated using information not available at decision time
- Backtest results will be unrealistically optimistic
- Live trading will underperform backtests

**Example**:
```python
# At bar 100 (10:00 AM), checking if it's a swing low
idx = 100
swing_lookback = 5

# Checks bars 95-105:
for offset in range(-5, 6):  # -5, -4, -3, -2, -1, 0, 1, 2, 3, 4, 5
    df.iloc[100 + offset]
    # When offset = 1,2,3,4,5 → bars 101,102,103,104,105
    # These bars occur AFTER 10:00 AM (future data!)
```

**Correct Implementation**:
```python
def _is_swing_low(self, df: pd.DataFrame, idx: int) -> bool:
    """Check if index is a swing low (CAUSAL VERSION)."""
    # Need lookback bars BEFORE and AFTER to confirm swing
    # But we can only use PAST data at decision time
    
    # Option 1: Only look backward (conservative)
    if idx < self.swing_lookback * 2:
        return False
    
    low = float(df.iloc[idx]['low'])
    
    # Check if current bar is lowest in PAST window
    for offset in range(-self.swing_lookback * 2, 1):  # Only past bars
        if offset == 0:
            continue
        if float(df.iloc[idx + offset]['low']) <= low:
            return False
    
    return True

# Option 2: Delay signal by lookback period (wait for confirmation)
def _is_swing_low_confirmed(self, df: pd.DataFrame, idx: int) -> bool:
    """Check if bar (idx - lookback) was a swing low (now confirmed)."""
    check_idx = idx - self.swing_lookback
    
    if check_idx < self.swing_lookback or check_idx >= len(df):
        return False
    
    low = float(df.iloc[check_idx]['low'])
    
    # Now we can look forward from check_idx because we're at idx
    for offset in range(-self.swing_lookback, self.swing_lookback + 1):
        if offset == 0:
            continue
        if float(df.iloc[check_idx + offset]['low']) <= low:
            return False
    
    return True
```

---

## ✅ VERIFIED CORRECT IMPLEMENTATIONS

### 1. L2 Scalping Signals
**Location**: `/home/jacobw/quantstack/l2_scalping/src/signals/`

```python
# l2_signals.py - Uses current snapshot only
def generate_signal(self, snapshot: L2Snapshot) -> TradingSignal:
    signal_type = self._obi_momentum_signal(snapshot.obi_1)
    # Uses only current snapshot data ✅

# pattern_rules.py - Delta features backward-looking
def _get_delta(self, symbol: str, timestamp: float, window_sec: int):
    target_ts = timestamp - window_sec  # Looks BACKWARD ✅
    for ts, obi, mid in reversed(hist):
        if ts <= target_ts:  # Only past data ✅
            return current_obi - obi
```

**Analysis**: ✅ CORRECT - No future data access

---

### 2. Alpha Signals
**Location**: `/home/jacobw/quantstack/alpha/src/signals/`

```python
# order_flow.py
def check_entry(self, features: dict, bar: pd.Series, timestamp: pd.Timestamp):
    book_imb = features.get("book_imbalance_5")  # Current features
    trade_imb = features.get("trade_imbalance_5")
    
    if book_imb > self.book_imb_threshold:
        return SignalEvent(...)  # Uses current bar only ✅

# whale_detect.py
def check_entry(self, features: dict, bar: pd.Series, timestamp: pd.Timestamp):
    has_large_bid = features.get("has_large_bid", False)  # Current
    trade_imb = features.get("trade_imbalance_5")
    
    if has_large_bid and trade_imb > self.min_flow_imb:
        return SignalEvent(...)  # Uses current bar only ✅
```

**Analysis**: ✅ CORRECT - Uses only current bar and features

---

### 3. L2 VWAP Reversion
**Location**: `/home/jacobw/quantstack/l2_vwap_reversion/src/strategy.py`

```python
def _check_entry(self, bar: Bar, vwap: float, current_time: time):
    deviation = bar.close / vwap  # Current bar close ✅
    
    if deviation <= self.deviation_long:
        signal = Signal(
            price=bar.close,  # Current bar ✅
            timestamp=bar.timestamp,
            vwap=vwap,  # Cumulative up to current bar ✅
        )
```

**Analysis**: ✅ CORRECT - Uses current bar and cumulative VWAP

---

## 🔍 ADDITIONAL FINDINGS

### Intraday Candidate Generator - Other Issues

**Location**: `/home/jacobw/intraday_stack/src/signals/candidate_generator.py:130-180`

```python
for i in range(30, len(df) - 5):  # Stops 5 bars before end
    ts = df.iloc[i]['timestamp']
    
    # Uses i-1 (past) ✅
    ema_fast_prev = df.iloc[i-1]['ema_fast']
    
    # Uses i-5 (past) ✅
    if close > df.iloc[i-5]['close']:
```

**Analysis**: ✅ CORRECT - Uses only past bars (i-1, i-5)

**BUT**: Swing point detection (`_is_swing_low`, `_is_swing_high`) called from:
```python
if self._is_swing_low(df, i):  # ❌ USES FUTURE DATA
    signal = ...
```

---

## 📋 REQUIRED FIXES

### Fix 1: Delay Swing Signals (Recommended)
**Priority**: CRITICAL

```python
class CandidateGenerator:
    def _generate_reversal_candidates(self, df, symbol, sip_score):
        candidates = []
        
        # Delay by lookback to allow confirmation
        for i in range(self.swing_lookback + 5, len(df) - 5):
            ts = df.iloc[i]['timestamp']
            
            # Check if bar (i - lookback) was a swing point
            check_idx = i - self.swing_lookback
            
            if self._is_swing_low_confirmed(df, check_idx, i):
                # Signal at current bar i, but for swing at check_idx
                strength = self._calc_reversal_strength(df, check_idx, 'long', sip_score)
                if strength > 0.3:
                    candidates.append(Candidate(
                        symbol=symbol,
                        timestamp=ts,  # Current time
                        strategy='reversal',
                        direction='long',
                        entry_price=float(df.iloc[i]['close']),  # Current price
                        atr=df.iloc[i]['atr'],
                        signal_strength=strength,
                        features=self._extract_features(df, i)
                    ))
        
        return candidates
    
    def _is_swing_low_confirmed(self, df, check_idx, current_idx):
        """Check if check_idx was a swing low (confirmed at current_idx)."""
        if check_idx < self.swing_lookback:
            return False
        
        low = float(df.iloc[check_idx]['low'])
        
        # Look backward and forward from check_idx
        # But only up to current_idx (no future data)
        for offset in range(-self.swing_lookback, min(self.swing_lookback + 1, current_idx - check_idx + 1)):
            if offset == 0:
                continue
            idx = check_idx + offset
            if idx >= current_idx:
                break
            if float(df.iloc[idx]['low']) <= low:
                return False
        
        return True
```

### Fix 2: Backward-Only Detection (Alternative)
**Priority**: CRITICAL

```python
def _is_swing_low(self, df, idx):
    """Check if idx is lowest in PAST window (no future data)."""
    lookback = self.swing_lookback * 2  # Double lookback for confirmation
    
    if idx < lookback:
        return False
    
    low = float(df.iloc[idx]['low'])
    
    # Only check PAST bars
    for offset in range(-lookback, 1):
        if offset == 0:
            continue
        if float(df.iloc[idx + offset]['low']) <= low:
            return False
    
    return True
```

---

## ✅ CONCLUSION

**CRITICAL ISSUE FOUND**: Intraday swing point detection uses future data

**Status by System**:
- ✅ L2 Scalping: No violations
- ✅ Alpha Signals: No violations  
- ✅ L2 VWAP: No violations
- ❌ Intraday Stack: **CRITICAL VIOLATION** in swing detection

**Required Action**: Fix swing point detection immediately before any backtest results are trusted.

---

**Sign-off**: Signal generation audit complete - 1 critical violation found ❌
