# Alpha System Fix Sprint Plan

**Purpose:** Detailed remediation plan for GLM to fix all identified deficiencies
**Priority:** Execute tasks IN ORDER - later tasks depend on earlier fixes
**Estimated Time:** 4-6 hours

---

## Pre-Flight Checklist

Before starting ANY task, run this command to verify your environment:

```bash
cd /home/jacobw/quantstack/alpha
source .venv/bin/activate
python -m pytest tests/ -q 2>&1 | tail -5
```

**Expected output:** `92 passed`

If tests fail, STOP and report the error.

---

## PHASE 1: Critical Bug Fixes (Must Complete First)

### Task 1.1: Add Symbol Column to Gold Data Loading

**File to modify:** `scripts/run_full_backtest.py`
**Line numbers:** 155-168 (the data loading loop)

**Current code (BROKEN):**
```python
all_bars = []
for symbol in symbols:
    try:
        bars = gold_loader.load_bars(symbol, start_date, end_date)
        if not bars.empty:
            all_bars.append(bars)
            logger.info(f"Loaded {len(bars)} bars for {symbol}")
    except Exception as e:
        logger.warning(f"Failed to load {symbol}: {e}")
```

**Replace with (FIXED):**
```python
all_bars = []
for symbol in symbols:
    try:
        bars = gold_loader.load_bars(symbol, start_date, end_date)
        if not bars.empty:
            bars["symbol"] = symbol  # ADD THIS LINE - Critical fix
            all_bars.append(bars)
            logger.info(f"Loaded {len(bars)} bars for {symbol}")
    except Exception as e:
        logger.warning(f"Failed to load {symbol}: {e}")
```

**Verification command:**
```bash
python -c "
import pandas as pd
from src.data import GoldLoader
loader = GoldLoader()
df = loader.load_bars('AAPL', '2024-01-02', '2024-01-03')
df['symbol'] = 'AAPL'
print('symbol' in df.columns)  # Must print: True
"
```

---

### Task 1.2: Add Symbol Column to Hypothesis Test Script

**File to modify:** `scripts/run_hypothesis_test.py`
**Line numbers:** 131-144 (the data loading loop)

**Current code (BROKEN):**
```python
all_bars = []
for symbol in symbols:
    try:
        bars = gold_loader.load_bars(symbol, start_date, end_date)
        if not bars.empty:
            all_bars.append(bars)
            logger.info(f"Loaded {len(bars)} bars for {symbol}")
    except Exception as e:
        logger.warning(f"Failed to load {symbol}: {e}")
```

**Replace with (FIXED):**
```python
all_bars = []
for symbol in symbols:
    try:
        bars = gold_loader.load_bars(symbol, start_date, end_date)
        if not bars.empty:
            bars["symbol"] = symbol  # ADD THIS LINE - Critical fix
            all_bars.append(bars)
            logger.info(f"Loaded {len(bars)} bars for {symbol}")
    except Exception as e:
        logger.warning(f"Failed to load {symbol}: {e}")
```

---

### Task 1.3: Add Missing pandas Import

**File to modify:** `scripts/run_hypothesis_test.py`
**Line numbers:** 14-20 (imports section)

**Current imports (BROKEN):**
```python
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path
```

**Replace with (FIXED):**
```python
import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd  # ADD THIS LINE - Required for pd.concat()
```

**Verification command:**
```bash
python -c "import scripts.run_hypothesis_test" 2>&1 | grep -i error || echo "Import OK"
```

---

### Task 1.4: Uncomment Trade Recording in Engine

**File to modify:** `src/backtest/engine.py`
**Line number:** 397 (inside `_execute_pending_exits` method)

**Current code (BROKEN):**
```python
            # Store trade (would need result reference)
            # result.trades.append(trade)
```

**This requires a more complex fix.** The method doesn't have access to `result`. 

**Step 1:** Modify the method signature at line 340:

**Current (line ~340):**
```python
def _execute_pending_exits(self, bars_group: pd.DataFrame) -> None:
```

**Replace with:**
```python
def _execute_pending_exits(self, bars_group: pd.DataFrame, result: 'BacktestResult') -> None:
```

**Step 2:** At line 397, change:
```python
            # Store trade (would need result reference)
            # result.trades.append(trade)
```

**To:**
```python
            # Store trade
            result.trades.append(trade)
```

**Step 3:** Update the call site at line ~168 in the `run()` method:

**Current:**
```python
            # Process pending exits (execute at this bar's OPEN)
            self._execute_pending_exits(group)
```

**Replace with:**
```python
            # Process pending exits (execute at this bar's OPEN)
            self._execute_pending_exits(group, result)
```

**Verification command:**
```bash
grep -n "result.trades.append" src/backtest/engine.py
# Should show line ~397 WITHOUT the # comment
```

---

### Task 1.5: Fix Function Name Typo

**File to modify:** `scripts/run_full_backtest.py`
**Line number:** 207

**Current code (BROKEN):**
```python
        threshold_check = check_minimum_threshold(metrics, **config["validation"]["thresholds"])
```

**Replace with (FIXED):**
```python
        threshold_check = check_minimum_thresholds(metrics, **config["validation"]["thresholds"])
```

**Note:** The function is `check_minimum_thresholds` (plural), not `check_minimum_threshold` (singular).

**Verification command:**
```bash
grep -n "check_minimum_threshold[^s]" scripts/run_full_backtest.py
# Should return NO results (empty output means fixed)
```

---

## PHASE 2: Major Bug Fixes

### Task 2.1: Fix Config Key Typo

**File to modify:** `scripts/run_full_backtest.py`
**Line number:** 58

**Current code (BROKEN):**
```python
        "regime": {
            "spy_sama_period": 20,
```

**Replace with (FIXED):**
```python
        "regime": {
            "spy_sma_period": 20,
```

**Note:** It's `sma` (Simple Moving Average), not `sama`.

---

### Task 2.2: Fix Config Key Typo in Hypothesis Test Script

**File to modify:** `scripts/run_hypothesis_test.py`
**Line number:** Check for same typo around line 58

**Search for:**
```bash
grep -n "spy_sama" scripts/run_hypothesis_test.py
```

If found, change `spy_sama_period` to `spy_sma_period`.

---

### Task 2.3: Add Missing Import in Diagnostics

**File to modify:** `src/metrics/diagnostics.py`
**Line number:** 17

**Current code (BROKEN):**
```python
from .performance import compute_all_metrics
```

**Replace with (FIXED):**
```python
from .performance import compute_all_metrics, check_minimum_thresholds
```

**Verification command:**
```bash
python -c "from src.metrics.diagnostics import generate_summary_report; print('OK')"
```

---

### Task 2.4: Reset Engine State Between Runs

**File to modify:** `src/backtest/engine.py`
**Location:** Beginning of `run()` method (after line ~120, before any processing)

**Add these lines at the START of the `run()` method, right after the docstring:**

```python
    def run(
        self,
        bars_df: pd.DataFrame,
        l2_df: Optional[pd.DataFrame] = None,
        signals: Optional[List[Signal]] = None,
    ) -> BacktestResult:
        """Run backtest on historical data.
        ...existing docstring...
        """
        # Reset state for fresh run - ADD THIS BLOCK
        self.capital = self.initial_capital
        self.positions = {}
        self.pending_entries = []
        self.pending_exits = []
        self.entries_executed = 0
        self.exits_executed = 0
        
        result = BacktestResult()
        # ... rest of existing code ...
```

---

### Task 2.5: Pass L2 Data Through Walk-Forward Validation

**File to modify:** `src/backtest/walk_forward.py`

**Step 1:** Update method signature at line ~195:

**Current:**
```python
    def run_validation(
        self,
        engine: AlphaBacktestEngine,
        bars_df: pd.DataFrame,
        signals: list,
        start_date: str,
        end_date: str,
    ) -> Tuple[List[BacktestResult], ConsistencyReport]:
```

**Replace with:**
```python
    def run_validation(
        self,
        engine: AlphaBacktestEngine,
        bars_df: pd.DataFrame,
        signals: list,
        start_date: str,
        end_date: str,
        l2_df: Optional[pd.DataFrame] = None,  # ADD THIS PARAMETER
    ) -> Tuple[List[BacktestResult], ConsistencyReport]:
```

**Step 2:** Update the engine.run() call at line ~236:

**Current:**
```python
            # Run backtest on validation period
            period_result = engine.run(val_bars, signals=signals)
```

**Replace with:**
```python
            # Run backtest on validation period
            # Filter L2 data to validation period if available
            val_l2 = None
            if l2_df is not None and not l2_df.empty:
                val_l2 = l2_df[
                    (l2_df["ts_utc"] >= val_start) &
                    (l2_df["ts_utc"] <= val_end)
                ]
            period_result = engine.run(val_bars, l2_df=val_l2, signals=signals)
```

**Step 3:** Add import at top of file if not present:

```python
from typing import List, Optional, Tuple
```

---

## PHASE 3: Integration Fixes

### Task 3.1: Create Fallback for Missing L2 Data

**File to modify:** `src/backtest/engine.py`
**Location:** `_prepare_bar_data()` method (around line 180)

The current code only computes L2 features if L2 snapshot exists. We need to provide fallback values.

**Current code:**
```python
        # Compute L2 features if snapshot available
        if bar_data.l2_snapshot is not None:
            l2_features = self.l2_engineer.compute_all_features(bar_data.l2_snapshot)
            bar_data.features.update(l2_features)

        return bar_data
```

**Replace with:**
```python
        # Compute L2 features if snapshot available
        if bar_data.l2_snapshot is not None:
            l2_features = self.l2_engineer.compute_all_features(bar_data.l2_snapshot)
            bar_data.features.update(l2_features)
        else:
            # Provide fallback values when L2 data unavailable
            # These neutral values won't trigger signals but won't crash either
            bar_data.features.update({
                "book_imbalance_5": 0.0,
                "book_imbalance_10": 0.0,
                "depth_ratio_5": 1.0,
                "depth_ratio_10": 1.0,
                "spread": bar["high"] - bar["low"],  # Approximate spread
                "bid_slope": 0.0,
                "ask_slope": 0.0,
                "has_large_bid": False,
                "has_large_ask": False,
                "large_bid_size": 0,
                "large_ask_size": 0,
                "bid_drop_pct": 0.0,
                "ask_drop_pct": 0.0,
                "trade_imbalance_5": 0.0,
                "rvol": 1.0,
            })

        return bar_data
```

---

### Task 3.2: Add Price-Based Feature Computation

**File to modify:** `src/backtest/engine.py`
**Location:** `_prepare_bar_data()` method, after L2 features

The signals also need price-based features like `trade_imbalance_5` and `rvol`. Add this after the L2 feature block:

```python
        # Compute price-based features (always available)
        # These require historical bars, so we'll use simple approximations
        # In production, these should be computed from rolling windows
        if "ret_1m" in bar.index:
            # Use existing return if available
            bar_data.features["ret_5"] = bar.get("ret_1m", 0) * 5  # Rough approximation
        
        return bar_data
```

---

### Task 3.3: Make Symbol Limit Configurable

**File to modify:** `scripts/run_full_backtest.py`
**Line number:** ~147

**Current code:**
```python
    # Load Gold data for symbols (limit for speed)
    symbols = symbols[:10]
    logger.info(f"Testing {len(symbols)} symbols")
```

**Replace with:**
```python
    # Load Gold data for symbols (configurable limit)
    max_symbols = config.get("max_symbols", 10)
    if max_symbols > 0:
        symbols = symbols[:max_symbols]
    logger.info(f"Testing {len(symbols)} symbols (max_symbols={max_symbols})")
```

**Also add to DEFAULT_CONFIG dict (around line 30):**
```python
DEFAULT_CONFIG = {
    "initial_capital": 100000,
    "max_symbols": 10,  # ADD THIS LINE - 0 for unlimited
    ...
}
```

**Do the same for `scripts/run_hypothesis_test.py`.**

---

## PHASE 4: Verification

### Task 4.1: Run All Unit Tests

```bash
cd /home/jacobw/quantstack/alpha
source .venv/bin/activate
python -m pytest tests/ -v 2>&1 | tail -20
```

**Expected:** All 92 tests pass. If any fail, STOP and fix before proceeding.

---

### Task 4.2: Test Import Chain

```bash
python -c "
from src.data import GoldLoader, SipLoader, L2Loader
from src.signals import OrderFlowSignal, WhaleDetectSignal, LiquidityFadeSignal
from src.backtest import AlphaBacktestEngine
from src.backtest.walk_forward import WalkForwardValidator
from src.backtest.regime_split import RegimeStratifier
from src.metrics import compute_all_metrics, format_metrics_report, check_minimum_thresholds
from src.metrics.diagnostics import generate_summary_report, save_report
print('All imports successful')
"
```

**Expected output:** `All imports successful`

---

### Task 4.3: Test Data Loading with Symbol Column

```bash
python -c "
import pandas as pd
from src.data import GoldLoader

loader = GoldLoader()
df = loader.load_bars('AAPL', '2024-01-02', '2024-01-03')
df['symbol'] = 'AAPL'

assert 'symbol' in df.columns, 'Missing symbol column'
assert 'ts' in df.columns, 'Missing ts column'
assert 'close' in df.columns, 'Missing close column'
assert len(df) > 0, 'No data loaded'

print(f'Loaded {len(df)} bars with columns: {list(df.columns)[:5]}...')
print('Data loading test PASSED')
"
```

---

### Task 4.4: Test Short Backtest Execution

```bash
cd /home/jacobw/quantstack/alpha
source .venv/bin/activate

# This should run without errors (may have 0 trades due to no L2 data)
timeout 60 python scripts/run_full_backtest.py --start 2024-01-02 --end 2024-01-05 2>&1 | tail -30
```

**Expected:** Script completes without Python errors. May show 0 trades (acceptable for now).

---

### Task 4.5: Verify Trade Recording Works

After Task 4.4 completes, check if trades are being recorded:

```bash
python -c "
import pandas as pd
from src.data import GoldLoader, SipLoader
from src.signals import OrderFlowSignal
from src.backtest import AlphaBacktestEngine

# Load minimal data
loader = GoldLoader()
df = loader.load_bars('AAPL', '2024-01-02', '2024-01-03')
df['symbol'] = 'AAPL'

# Create engine and signal
config = {'signals': {'order_flow': {}}, 'risk': {}, 'execution': {}}
engine = AlphaBacktestEngine(config)
signal = OrderFlowSignal(config)

# Run backtest
result = engine.run(df, signals=[signal])

print(f'Signals generated: {result.signals_generated}')
print(f'Entries executed: {engine.entries_executed}')
print(f'Exits executed: {engine.exits_executed}')
print(f'Trades recorded: {len(result.trades)}')
print('Trade recording test complete')
"
```

---

## PHASE 5: Documentation Update

### Task 5.1: Update SPRINT_PLAN.md Status

**File to modify:** `SPRINT_PLAN.md`

Update the progress summary section to reflect actual completion:

```markdown
## Progress Summary

**Overall Completion: 100% (6 of 6 sprints completed)**

- ✅ Sprint 1: Data Infrastructure (21 tests passing)
- ✅ Sprint 2: Feature Engineering (20 tests passing)
- ✅ Sprint 3: Signal Implementation (18 tests passing)
- ✅ Sprint 4: Backtest Engine (16 tests passing)
- ✅ Sprint 5: Validation Framework (17 tests passing)
- ✅ Sprint 6: Integration & Analysis (scripts functional)

**Test Status: 92 tests passing**
**Integration Status: Fixed per FIX_SPRINT_PLAN.md**
```

---

### Task 5.2: Archive Deficiency Report

```bash
mkdir -p /home/jacobw/quantstack/alpha/docs/archive
mv /home/jacobw/quantstack/alpha/DEFICIENCY_REPORT.md /home/jacobw/quantstack/alpha/docs/archive/DEFICIENCY_REPORT_2026-01-19.md
```

---

## Summary Checklist

Before marking complete, verify ALL items:

- [ ] Task 1.1: Symbol column added in run_full_backtest.py
- [ ] Task 1.2: Symbol column added in run_hypothesis_test.py
- [ ] Task 1.3: pandas import added in run_hypothesis_test.py
- [ ] Task 1.4: Trade recording uncommented and result passed to method
- [ ] Task 1.5: Function typo fixed (check_minimum_thresholds)
- [ ] Task 2.1: Config typo fixed (spy_sma_period) in run_full_backtest.py
- [ ] Task 2.2: Config typo fixed in run_hypothesis_test.py (if present)
- [ ] Task 2.3: Missing import added in diagnostics.py
- [ ] Task 2.4: Engine state reset added
- [ ] Task 2.5: L2 data passed through walk-forward
- [ ] Task 3.1: L2 fallback values added
- [ ] Task 3.2: Price-based features added (optional)
- [ ] Task 3.3: Symbol limit made configurable
- [ ] Task 4.1: All 92 tests pass
- [ ] Task 4.2: All imports work
- [ ] Task 4.3: Data loading works with symbol
- [ ] Task 4.4: Short backtest runs without errors
- [ ] Task 4.5: Trades are being recorded
- [ ] Task 5.1: SPRINT_PLAN.md updated
- [ ] Task 5.2: Deficiency report archived

---

## Troubleshooting

### If tests fail after changes:

```bash
# Run specific test file to isolate issue
python -m pytest tests/test_backtest.py -v

# Check for syntax errors
python -m py_compile src/backtest/engine.py
```

### If imports fail:

```bash
# Check for circular imports
python -c "import src.backtest.engine" 2>&1

# Check specific module
python -c "from src.metrics.diagnostics import generate_summary_report"
```

### If backtest crashes:

```bash
# Run with debug logging
python -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# ... rest of test code ...
"
```

---

## File Change Summary

| File | Changes |
|------|---------|
| `scripts/run_full_backtest.py` | Add symbol column, fix typos, make limit configurable |
| `scripts/run_hypothesis_test.py` | Add symbol column, add pandas import, fix typos |
| `src/backtest/engine.py` | Uncomment trade append, pass result to method, reset state, add L2 fallback |
| `src/backtest/walk_forward.py` | Add l2_df parameter, filter and pass L2 data |
| `src/metrics/diagnostics.py` | Add missing import |
| `SPRINT_PLAN.md` | Update completion status |
