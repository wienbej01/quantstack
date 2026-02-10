# Alpha System Deficiency Report

**Audit Date:** 2026-01-19
**Auditor:** Kiro
**System:** Alpha Backtesting System (built by z.ai GLM 4-7)

---

## Executive Summary

The alpha system implementation has **92 passing tests** but contains **critical runtime bugs** that prevent actual execution. The architecture is sound, but integration issues and missing data handling make the system non-functional for real backtesting.

**Severity Breakdown:**
- 🔴 Critical (blocks execution): 4
- 🟠 Major (incorrect results): 5
- 🟡 Minor (code quality): 3

---

## 🔴 Critical Deficiencies

### C1: Missing `symbol` Column in Gold Data
**File:** `scripts/run_full_backtest.py`, `scripts/run_hypothesis_test.py`
**Line:** Data loading section (~line 160)

**Problem:** Gold loader returns data without a `symbol` column, but the backtest engine expects `bars_df["symbol"]`.

**Error:**
```
KeyError: 'symbol'
File "src/backtest/engine.py", line 151
result.symbols_tested = bars_df["symbol"].unique().tolist()
```

**Fix Required:**
```python
# When loading bars, add symbol column:
bars = gold_loader.load_bars(symbol, start_date, end_date)
bars["symbol"] = symbol  # ADD THIS LINE
```

---

### C2: Trades Not Appended to Result
**File:** `src/backtest/engine.py`
**Line:** 397

**Problem:** Trade recording is commented out in `_execute_pending_exits()`:
```python
# result.trades.append(trade)  # COMMENTED OUT!
```

**Impact:** All trades are lost except those closed at end-of-data. Backtest results will show 0 trades.

**Fix Required:** Uncomment line 397 and pass `result` to the method.

---

### C3: Function Name Typo
**File:** `scripts/run_full_backtest.py`
**Line:** 207

**Problem:** Typo in function call:
```python
threshold_check = check_minimum_threshold(...)  # WRONG
# Should be:
threshold_check = check_minimum_thresholds(...)  # CORRECT
```

**Impact:** Script crashes with `NameError`.

---

### C4: Missing pandas Import
**File:** `scripts/run_hypothesis_test.py`

**Problem:** Script uses `pd.concat()` but doesn't import pandas.

**Fix Required:** Add `import pandas as pd` to imports.

---

## 🟠 Major Deficiencies

### M1: Config Key Typo
**File:** `scripts/run_full_backtest.py`
**Line:** 58

**Problem:**
```python
"spy_sama_period": 20,  # WRONG - typo
# Should be:
"spy_sma_period": 20,   # CORRECT
```

**Impact:** Regime stratification may use wrong default value.

---

### M2: L2 Data Not Passed in Walk-Forward
**File:** `src/backtest/walk_forward.py`
**Line:** 236

**Problem:** Walk-forward validation calls `engine.run(val_bars, signals=signals)` without passing L2 data.

**Impact:** All L2-based features (book_imbalance, depth_ratio, etc.) will be `None`, causing all signals to fail entry checks.

**Fix Required:**
```python
period_result = engine.run(val_bars, l2_df=l2_df, signals=signals)
```

---

### M3: L2 Data Date Mismatch
**File:** `src/data/l2_loader.py`

**Problem:** L2 data only exists for late 2025 (`date=2025-12-19`, `date=2025-12-23`), but backtests target 2024 data.

**Impact:** No L2 features available for any 2024 backtest. All hypothesis signals will fail.

**Recommendation:** Either:
1. Generate L2 data for 2024, or
2. Implement fallback to price-only features when L2 unavailable

---

### M4: Missing Import in diagnostics.py
**File:** `src/metrics/diagnostics.py`
**Line:** 17

**Problem:** Uses `check_minimum_thresholds` but doesn't import it:
```python
from .performance import compute_all_metrics  # Missing check_minimum_thresholds
```

**Impact:** `generate_summary_report()` will crash.

**Fix Required:**
```python
from .performance import compute_all_metrics, check_minimum_thresholds
```

---

### M5: Engine State Not Reset Between Runs
**File:** `src/backtest/engine.py`

**Problem:** Engine maintains state (`self.capital`, `self.positions`, etc.) but doesn't reset between `run()` calls.

**Impact:** Running multiple backtests with same engine instance will have corrupted state.

**Fix Required:** Add state reset at start of `run()`:
```python
def run(self, ...):
    # Reset state
    self.capital = self.initial_capital
    self.positions = {}
    self.pending_entries = []
    self.pending_exits = []
    self.entries_executed = 0
    self.exits_executed = 0
    ...
```

---

## 🟡 Minor Deficiencies

### m1: Hardcoded Symbol Limit
**File:** `scripts/run_full_backtest.py`, `scripts/run_hypothesis_test.py`
**Line:** ~145

**Problem:**
```python
symbols = symbols[:10]  # Limit for faster testing
```

**Impact:** Only tests 10 symbols regardless of SIP universe size. Should be configurable.

---

### m2: Missing Result Reference in Entry Execution
**File:** `src/backtest/engine.py`
**Line:** 330

**Problem:**
```python
result = None  # Would need result reference
```

The `_execute_pending_entries()` method doesn't have access to `result` to track entries.

---

### m3: Incomplete Sprint Plan Status
**File:** `SPRINT_PLAN.md`

**Problem:** Sprint plan shows 50% completion (3/6 sprints) but tests show 92 passing (more than 59 planned).

**Impact:** Documentation out of sync with implementation.

---

## Test Coverage Analysis

| Module | Tests | Status | Notes |
|--------|-------|--------|-------|
| Data Loaders | 21 | ✅ Pass | Unit tests pass, integration fails |
| Features | 20 | ✅ Pass | Works with synthetic data |
| Signals | 18 | ✅ Pass | Works with synthetic data |
| Backtest | 16 | ✅ Pass | Unit tests pass, integration fails |
| Walk-Forward | 17 | ✅ Pass | Unit tests pass, L2 not tested |
| **Total** | **92** | ✅ Pass | **Integration broken** |

**Key Finding:** Tests use synthetic/mock data and don't catch integration issues with real data paths and column schemas.

---

## Recommendations

### Immediate Fixes (Required for Execution)

1. **Add symbol column** when loading Gold data in scripts
2. **Uncomment trade append** in engine.py line 397
3. **Fix function typo** in run_full_backtest.py line 207
4. **Add pandas import** to run_hypothesis_test.py
5. **Fix config typo** `spy_sama_period` → `spy_sma_period`
6. **Add missing import** in diagnostics.py

### Short-Term Improvements

1. Add integration tests with real data paths
2. Implement L2 fallback when data unavailable
3. Reset engine state between runs
4. Make symbol limit configurable

### Architecture Concerns

1. **L2 Data Gap:** System designed around L2 features but L2 data doesn't exist for target date range
2. **Feature Computation:** Features computed per-bar in engine but signals expect pre-computed features
3. **No Feature Caching:** Each bar recomputes all features (performance issue)

---

## Verification Commands

After fixes, verify with:

```bash
# Test imports
python -c "from src.data import GoldLoader; from src.signals import OrderFlowSignal"

# Run short backtest
python scripts/run_full_backtest.py --start 2024-01-01 --end 2024-01-31

# Check trade count
python -c "
from src.backtest import AlphaBacktestEngine
# ... run backtest ...
print(f'Trades: {len(result.trades)}')  # Should be > 0
"
```

---

## Conclusion

The system has a solid architectural foundation with good test coverage for unit tests. However, **critical integration bugs prevent actual execution**. The primary issues are:

1. Data schema mismatches (missing symbol column)
2. Commented-out code (trade recording)
3. Typos in function names and config keys
4. Missing L2 data for target date range

**Estimated fix time:** 2-4 hours for critical bugs, 1-2 days for full integration testing.
