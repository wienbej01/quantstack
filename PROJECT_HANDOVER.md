# Project Handover - Intraday ML Trading System
**Date:** December 5, 2025  
**Session:** Kiro debugging and system audit  
**Status:** Critical issues identified, system not production-ready

---

## Executive Summary

### What Was Done
Conducted comprehensive debugging of intraday ML trading system showing 0.3% win rate. Identified root cause: **backtest engine does not implement stop loss or take profit monitoring**. All trades exit via timeout or EOD close, explaining poor performance.

### Current State
- ✅ System is stable and error-free (no crashes)
- ✅ ML models trained with strong AUC (0.88, 0.93)
- ✅ Data pipeline working correctly
- ❌ Backtest engine missing core trading logic
- ❌ Cannot be used for live trading
- ❌ All performance metrics invalid

### Next Steps Required
1. Implement stop/target monitoring in backtest engine (8-12 hours)
2. Add exit reason tracking and R-multiple calculation (4 hours)
3. Validate with unit and integration tests (4 hours)
4. Re-run backtests with working system (2-4 hours)
5. Optimize parameters if results promising (1-2 days)

**Total Estimated Effort:** 16-20 hours to working system

---

## Work Completed This Session

### Phase 1: Initial Investigation (2 hours)

**Objective:** Understand why system has 0.3% win rate

**Actions:**
1. Reviewed previous session summary
2. Examined trade data and fills
3. Analyzed duration patterns
4. Identified 94% of trades exit at exactly 20 minutes

**Key Finding:** Suspected early_cut timeout was killing trades

**Deliverables:**
- `scripts/analyze_stop_hits.py` - Diagnostic script
- `reports/ROOT_CAUSE_ANALYSIS.md` - Initial hypothesis

### Phase 2: Hypothesis Testing (2 hours)

**Objective:** Test if removing timeouts improves performance

**Actions:**
1. Created `policy_config_no_timeout.json` with timeouts disabled
2. Created `scripts/test_no_timeout.py` to run single backtest
3. Ran test with timeout disabled
4. Analyzed results

**Results:**
- Win rate: Still 0% (no improvement)
- Avg PnL: Still -$0.70
- Duration: Increased to 169 min but no profit
- Conclusion: Timeout was NOT the root cause

**Deliverables:**
- `configs/extensions/intraday_ml/policy_config_no_timeout.json`
- `scripts/test_no_timeout.py`
- `reports/TIMEOUT_TEST_RESULTS.md`

### Phase 3: System Audit (3 hours)

**Objective:** Deep dive into backtest engine to find real issue

**Actions:**
1. Examined `qx-backtest/src/qx_backtest/engine.py`
2. Examined `qx-backtest/src/qx_backtest/order.py`
3. Examined `qx-backtest/src/qx_backtest/fill.py`
4. Examined `extensions/intraday_ml/backtest.py`
5. Traced order execution flow
6. Checked position monitoring logic

**Critical Discovery:**
- `backtest.py` sets `order_obj.stop_loss` and `order_obj.take_profit`
- But `Order` class has NO such attributes
- Engine NEVER checks positions for stop/target hits
- Positions only exit via timeout or EOD close

**Deliverables:**
- `reports/SYSTEM_AUDIT_DEC5.md` - Comprehensive technical audit
- `reports/CRITICAL_FINDINGS_DEC5.md` - Executive summary with code evidence

### Phase 4: Documentation (1 hour)

**Objective:** Create handover documents for successor

**Actions:**
1. Compiled all findings into technical documentation
2. Created project status and next steps document
3. Documented all issues with code locations
4. Provided fix estimates and alternatives

**Deliverables:**
- `TECHNICAL_DOCUMENTATION.md` - Complete system reference
- `PROJECT_HANDOVER.md` - This document

---

## Files Created/Modified

### Analysis Scripts
```
scripts/analyze_stop_hits.py          # Diagnoses stop-hitting patterns
scripts/test_no_timeout.py            # Tests timeout hypothesis
scripts/match_fills_to_trades.py      # Matches fills to round-trips (existing)
scripts/run_sequential_sweep.py      # Parameter sweep (existing)
scripts/debug_sweep.py               # Component testing (existing)
```

### Configuration Files
```
configs/extensions/intraday_ml/
├── policy_config_no_timeout.json    # Test config with timeouts disabled
├── policy_config_bigmove_simple.json # Simplified config (existing)
└── policy_sweep_grid_test.yaml      # 8-config test grid (existing)
```

### Reports
```
reports/
├── ROOT_CAUSE_ANALYSIS.md           # Initial investigation
├── TIMEOUT_TEST_RESULTS.md          # Hypothesis test results
├── SYSTEM_AUDIT_DEC5.md            # Comprehensive technical audit
├── CRITICAL_FINDINGS_DEC5.md       # Executive summary
├── STATUS_DEC5_FINAL.md            # Session status update
├── FIXES_APPLIED.md                # Previous fixes summary
└── no_timeout_test.log             # Test output
```

### Documentation
```
TECHNICAL_DOCUMENTATION.md           # Complete system reference
PROJECT_HANDOVER.md                  # This document
```

### Data Artifacts
```
artefacts/extensions/intraday_ml/phaseA_full_sip/
├── matched_trades.parquet           # Original matched trades
└── matched_trades_no_timeout.parquet # Test results
```

---

## Critical Issues Identified

### Issue 1: Stop Loss Not Implemented ⚠️ CRITICAL

**Location:** `qx-backtest/src/qx_backtest/engine.py`

**Problem:**
- Engine processes orders bar-by-bar
- But NEVER checks existing positions for stop/target hits
- Missing `_check_position_exits()` function entirely

**Code Evidence:**
```python
# In engine.py run() method (line 291-350):
for timestamp, group in data.groupby("ts"):
    # Update portfolio
    # Call strategy
    strategy_func(self, bar_dict)
    # Process pending orders
    self._process_pending_orders(group)
    # ← NO CODE HERE TO CHECK POSITIONS
    # Record state
    self._record_portfolio_state()
```

**Impact:**
- Stops never trigger
- Targets never trigger
- All exits via timeout or EOD
- Risk management broken

**Fix Required:**
```python
def _check_position_exits(self, bar_data):
    """Check positions for stop/target hits."""
    for symbol, position in self.portfolio.positions.items():
        if hasattr(position, 'stop_loss'):
            if bar_data['low'] <= position.stop_loss:
                self._generate_stop_exit(symbol, position)
        if hasattr(position, 'take_profit'):
            if bar_data['high'] >= position.take_profit:
                self._generate_target_exit(symbol, position)
```

**Estimated Effort:** 6-8 hours

### Issue 2: Order Class Missing Attributes ⚠️ CRITICAL

**Location:** `qx-backtest/src/qx_backtest/order.py`

**Problem:**
- `backtest.py` sets `order_obj.stop_loss` and `order_obj.take_profit`
- But Order class has no such attributes (see line 48-70)
- Attributes silently added but never used

**Fix Required:**
```python
@dataclass
class Order:
    # ... existing fields ...
    stop_loss: float | None = None
    take_profit: float | None = None
```

**Estimated Effort:** 1 hour

### Issue 3: R-Multiple Not Calculated ⚠️ HIGH

**Location:** Trade analysis

**Problem:**
- `r_multiple` column always 0.0
- Not calculated from actual entry/exit
- Cannot measure risk-adjusted performance

**Fix Required:**
```python
def calculate_r_multiple(entry_price, exit_price, stop_distance, side):
    if side == 'LONG':
        return (exit_price - entry_price) / stop_distance
    else:
        return (entry_price - exit_price) / stop_distance
```

**Estimated Effort:** 2 hours

### Issue 4: Risk Metrics Not Recorded ⚠️ HIGH

**Location:** `qx-backtest/src/qx_backtest/fill.py`

**Problem:**
- `stop_dist_ps` always 0.0
- `slippage_est` always 0.0
- `exit_reason` doesn't exist
- Cannot diagnose issues

**Fix Required:**
```python
@dataclass
class Fill:
    # ... existing fields ...
    stop_dist_ps: float = 0.0
    slippage_est: float = 0.0
    exit_reason: str | None = None
```

**Estimated Effort:** 2 hours

### Issue 5: ATR Multiple Incorrect ⚠️ MEDIUM

**Location:** Risk calculation

**Problem:**
- Configured: 1.0 ATR
- Actual: 0.69 ATR
- Cause unknown

**Investigation Needed:** Check stop calculation in policy

**Estimated Effort:** 2 hours

### Issue 6: Commission Dominates Edge ⚠️ MEDIUM

**Location:** Position sizing

**Problem:**
- $0.70 commission on $18 stock = 3.9% breakeven
- 1-share position size triggers minimum commission
- Edge cannot overcome costs

**Fix Options:**
1. Increase position size to 10+ shares
2. Trade higher-priced stocks
3. Reduce commission rate (if possible)

**Estimated Effort:** 1 hour

---

## Performance Data

### Current Results (Broken System)

**Test Period:** May 1-31, 2024 (22 trading days)

**Overall:**
- Total trades: 343
- Win rate: 0.3% (1 win, 342 losses)
- Avg PnL: -$0.70 per trade
- Total PnL: -$241.69
- Sharpe: -50 to -80

**Duration Analysis:**
- < 10 min: 0 trades
- 10-20 min: 0 trades
- 20-30 min: 322 trades (94%)
- > 30 min: 21 trades (6%)
- Avg: 23.8 minutes

**PnL Distribution:**
- < -$1.00: 9 trades
- -$1.00 to -$0.50: 311 trades
- -$0.50 to $0.00: 22 trades
- $0.00 to $0.50: 1 trade
- > $0.50: 0 trades

**Exit Pattern:**
- 94% exit at exactly 20 minutes (early_cut timeout)
- 6% exit at 60 minutes (max_hold timeout) or EOD
- 0% exit at stop loss (not implemented)
- 0% exit at take profit (not implemented)

### ML Model Performance

**Stage 1 (Volatility Prediction):**
- AUC: 0.88
- Training: Phase A data
- Target: Binary (big move yes/no)

**Stage 2 (Direction Prediction):**
- AUC: 0.93
- Training: Conditional on big moves
- Target: Ternary (long/short/none)

**Note:** High AUC does not translate to trading profitability when execution is broken

### Risk Metrics

**Stop Loss:**
- Configured: 1.0 ATR
- Actual: 0.69 ATR (bug suspected)
- Avg distance: $0.108
- Avg as %: 0.6% of entry price

**Take Profit:**
- Configured: 2.0 R
- Avg distance: $0.216
- Avg as %: 1.2% of entry price

**Commission:**
- Per fill: $0.35 (minimum)
- Per round-trip: $0.70
- As % of $18 stock: 3.9%

---

## Diagnostic Tools Created

### 1. analyze_stop_hits.py

**Purpose:** Analyze why trades are hitting stops

**Usage:**
```bash
python scripts/analyze_stop_hits.py
```

**Output:**
- Trade count and win rate
- Duration distribution
- PnL distribution
- Sample losing trades
- Stop distance statistics

**Key Insight:** Revealed 94% exit at 20 minutes (timeout, not stop)

### 2. test_no_timeout.py

**Purpose:** Test hypothesis that timeouts are killing trades

**Usage:**
```bash
python scripts/test_no_timeout.py
```

**Output:**
- Backtest results with timeouts disabled
- Matched trades analysis
- Duration and PnL distributions

**Key Insight:** Removing timeouts didn't help (still 0% win rate)

### 3. match_fills_to_trades.py

**Purpose:** Match entry/exit fills into completed round-trips

**Usage:**
```bash
python scripts/match_fills_to_trades.py
```

**Output:**
- `matched_trades.parquet` with completed trades
- Win rate, avg PnL, duration statistics

**Key Insight:** Revealed actual 0.3% win rate (vs assumed 45%)

---

## Configuration Files

### policy_config_bigmove_simple.json

**Purpose:** Simplified policy config with TOD profiles disabled

**Key Settings:**
- Thresholds: 0.60 for both long and short
- TOD filter: Disabled
- Max entries per day: 10
- Stop: 1.0 ATR
- Target: 2.0 R
- Early cut: 20 minutes at 0.5R
- Max hold: 60 minutes

**Status:** Used in testing, but timeouts too aggressive

### policy_config_no_timeout.json

**Purpose:** Test config with all timeouts disabled

**Changes from simple:**
- early_loss_cut_minutes: 999 (was 20)
- dead_trade_exit_minutes: 999 (was 30)
- max_hold_minutes_flat_or_loser: 60 (unchanged)

**Test Result:** No improvement in win rate

### policy_sweep_grid_test.yaml

**Purpose:** 8-config test grid for fast iteration

**Parameters:**
- prob_threshold: [0.50, 0.60]
- stop_atr_multiple: [1.0, 2.0]
- 2×2×2 = 8 combinations

**Runtime:** ~3 minutes (vs 4 hours for full 576-config grid)

---

## Code Locations Reference

### Core Trading Logic
```
extensions/intraday_ml/
├── backtest.py                      # Backtest wrapper, order generation
├── policy/
│   └── bigmove_policy.py           # BigMove trading logic
└── experiments/
    └── policy_sweep.py             # Parameter sweep orchestration

extensions/intraday_ml_policies/
└── intraday_ml_decision_policy.py  # Main policy class
```

### Backtest Engine
```
qx-backtest/src/qx_backtest/
├── engine.py                        # Main backtest engine (NEEDS FIX)
├── order.py                         # Order class (NEEDS FIX)
├── fill.py                          # Fill simulation (NEEDS FIX)
├── portfolio.py                     # Position tracking
└── policies/                        # Strategy policies
```

### ML Pipeline
```
qx-features/src/qx_features/
└── intraday_ml_feature_pack.py     # Feature engineering

extensions/intraday_ml/
├── training/                        # Model training
└── scoring/                         # Prediction generation
```

### Configuration
```
configs/extensions/intraday_ml/
├── features_10m.yaml               # Feature definitions
├── policy_config_*.json            # Policy parameters
└── policy_sweep_*.yaml             # Sweep grids
```

### Data Artifacts
```
artefacts/extensions/intraday_ml/phaseA_full_sip/
├── oos_predictions_bigmove.parquet # ML predictions
├── oos_features.parquet            # Feature matrix
├── fills.parquet                   # Trade fills
├── orders.parquet                  # Generated orders
├── equity.parquet                  # Equity curve
└── matched_trades.parquet          # Completed round-trips
```

---

## Next Steps (Prioritized)

### Priority 1: Fix Stop/Target Monitoring (CRITICAL)

**Estimated Time:** 8-12 hours

**Tasks:**
1. Add `stop_loss` and `take_profit` to Order class (1 hour)
2. Add `stop_loss` and `take_profit` to Position class (1 hour)
3. Transfer from Order to Position on fill (1 hour)
4. Implement `_check_position_exits()` in engine (3 hours)
5. Generate exit orders when triggered (2 hours)
6. Add exit_reason tracking (2 hours)

**Files to Modify:**
- `qx-backtest/src/qx_backtest/order.py`
- `qx-backtest/src/qx_backtest/portfolio.py`
- `qx-backtest/src/qx_backtest/engine.py`
- `qx-backtest/src/qx_backtest/fill.py`

**Validation:**
```python
# Unit test
def test_stop_loss_triggers():
    # Create position with stop at $17.90
    # Feed bar with low=$17.85
    # Assert exit order generated at $17.90

# Integration test
def test_full_trade_with_stop():
    # Entry: $18.00 LONG, stop: $17.90
    # Feed bars: $18.00 → $17.85
    # Assert: Exit at $17.90, exit_reason='stop_hit'
```

### Priority 2: Add Risk Metrics (HIGH)

**Estimated Time:** 4 hours

**Tasks:**
1. Add fields to Fill dataclass (1 hour)
2. Calculate R-multiple on trade close (2 hours)
3. Record stop_dist_ps and slippage_est (1 hour)

**Files to Modify:**
- `qx-backtest/src/qx_backtest/fill.py`
- `extensions/intraday_ml/backtest.py`

### Priority 3: Validate and Test (HIGH)

**Estimated Time:** 4 hours

**Tasks:**
1. Write unit tests for stop/target logic (2 hours)
2. Write integration tests (1 hour)
3. Manual verification with single trade (1 hour)

**Test Cases:**
- Stop hit on long position
- Stop hit on short position
- Target hit on long position
- Target hit on short position
- Timeout with no stop/target hit
- EOD close

### Priority 4: Re-run Backtests (MEDIUM)

**Estimated Time:** 2-4 hours

**Tasks:**
1. Run single config test (30 min)
2. Analyze exit reasons distribution (30 min)
3. Run 8-config test grid (1 hour)
4. Compare results to broken system (1 hour)

**Expected Results:**
- Win rate: 30-40% (vs 0.3%)
- Mix of exit reasons: stop_hit, target_hit, timeout
- Sharpe: 1.0-2.0 (vs -50)
- Avg R: 0.5-1.0 (vs 0.0)

### Priority 5: Optimize Parameters (LOW)

**Estimated Time:** 1-2 days

**Tasks:**
1. Test stop widths: [1.0, 1.5, 2.0, 3.0] ATR (4 hours)
2. Test hold times: [60, 120, 240] minutes (4 hours)
3. Test thresholds: [0.50, 0.60, 0.70] (4 hours)
4. Run full 576-config sweep (4 hours)
5. Analyze efficient frontier (2 hours)

**Only proceed if Priority 1-4 show promising results**

---

## Alternative Approaches

### Option A: Use Proven Backtest Engine

**Recommendation:** If fixing current engine is too complex

**Options:**

1. **Backtrader**
   - Mature, well-documented
   - Built-in stop/target support
   - Integration time: 2-4 hours
   - Learning curve: Low

2. **Zipline**
   - Quantopian's engine
   - Full risk management
   - Integration time: 4-8 hours
   - Learning curve: Medium

3. **VectorBT**
   - Fast vectorized backtesting
   - Good for parameter sweeps
   - Integration time: 2-4 hours
   - Learning curve: Low

**Trade-offs:**
- Pro: Proven, tested, documented
- Pro: Stop/target monitoring included
- Con: Need to adapt ML pipeline
- Con: May lose some custom features

### Option B: Simplify Strategy

**Recommendation:** If ML approach too complex

**Alternatives:**

1. **Use ML for filtering only**
   - ML predicts high-volatility periods
   - Enter on technical signals (VWAP cross, breakout)
   - Simpler risk management
   - Easier to debug

2. **Pure technical strategy**
   - VWAP reversion/momentum
   - ATR-based stops
   - No ML complexity
   - Faster iteration

3. **Hybrid approach**
   - ML for universe selection
   - Technical for entry/exit
   - Best of both worlds

---

## Key Learnings

### 1. High AUC ≠ Profitable Trading
- Stage 1: 0.88 AUC
- Stage 2: 0.93 AUC
- Trading: 0.3% win rate
- **Lesson:** Model quality doesn't guarantee execution quality

### 2. Always Validate Execution
- Assumed stops were working
- Never checked if they triggered
- Lost weeks on wrong hypothesis
- **Lesson:** Test core assumptions early

### 3. Commission Matters
- $0.70 on $18 stock = 3.9%
- Dominates edge on small moves
- Position sizing critical
- **Lesson:** Model transaction costs realistically

### 4. Timeouts Can Help or Hurt
- Early cut at 20 min killed 94% of trades
- But removing it didn't help
- Real issue was no stops/targets
- **Lesson:** Fix root cause, not symptoms

### 5. Duration Analysis is Powerful
- Clustering at 20 min revealed timeout issue
- Distribution showed no variation
- Led to deeper investigation
- **Lesson:** Look at distributions, not just averages

---

## Questions for Successor

### Immediate Decisions

1. **Fix current engine or switch to proven solution?**
   - Fix: 16 hours, keeps custom features
   - Switch: 4-8 hours, proven but less flexible

2. **Continue with ML approach or simplify?**
   - ML: High potential but complex
   - Technical: Simpler, faster iteration

3. **What's the priority?**
   - Get something working quickly?
   - Build robust long-term system?

### Technical Questions

1. **Why is ATR multiple 0.69 instead of 1.0?**
   - Check risk calculation in policy
   - May be another bug

2. **Should position size be increased?**
   - 1 share = $0.70 commission = 3.9%
   - 10 shares = $0.70 commission = 0.39%

3. **Are ML models actually predictive?**
   - High AUC but no trading profit
   - Possible overfitting or data leakage?

### Strategic Questions

1. **Is intraday trading viable?**
   - High frequency = high costs
   - Small moves = commission dominates
   - Consider daily timeframe?

2. **Is this universe appropriate?**
   - $5-$50 stocks
   - High volatility
   - May be too noisy?

3. **What's the expected Sharpe?**
   - Realistic target: 1.0-2.0
   - Current: -50
   - Gap too large?

---

## Resources

### Documentation
- `TECHNICAL_DOCUMENTATION.md` - Complete system reference
- `SYSTEM_TECH_DOC_INTRADAY_ML.md` - Original design doc
- `AGENTS.md` - Development guidelines
- `README.md` - Project overview

### Reports
- `reports/CRITICAL_FINDINGS_DEC5.md` - Executive summary
- `reports/SYSTEM_AUDIT_DEC5.md` - Technical audit
- `reports/ROOT_CAUSE_ANALYSIS.md` - Investigation details
- `reports/TIMEOUT_TEST_RESULTS.md` - Hypothesis testing

### Code
- `scripts/analyze_stop_hits.py` - Diagnostic tool
- `scripts/test_no_timeout.py` - Testing framework
- `scripts/match_fills_to_trades.py` - Analysis tool

### Data
- `artefacts/extensions/intraday_ml/phaseA_full_sip/` - All artifacts
- `reports/` - All analysis reports

---

## Contact Information

**Previous Session:** Kiro debugging session, December 5, 2025

**Key Findings:**
- Backtest engine missing stop/target monitoring
- All performance metrics invalid
- 16-20 hours to working system

**Status:** Awaiting decision on path forward

**Handover Complete:** All findings documented, code locations identified, next steps outlined

---

**End of Project Handover**
