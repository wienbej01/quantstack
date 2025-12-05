# Intraday ML Trading System - Complete Technical Documentation
**Last Updated:** December 5, 2025  
**Status:** System has critical bugs - see Project Status document

---

## Table of Contents
1. [System Architecture](#system-architecture)
2. [ML Pipeline](#ml-pipeline)
3. [Trading Logic](#trading-logic)
4. [Risk Management](#risk-management)
5. [Backtest Engine](#backtest-engine)
6. [Configuration](#configuration)
7. [Data Flow](#data-flow)
8. [Known Issues](#known-issues)

---

## 1. System Architecture

### Component Overview
```
Data Layer (Gold)
    ↓
Feature Engineering (IntradayMLFeaturePack)
    ↓
ML Training (LightGBM 2-Stage)
    ↓
Signal Generation (Predictions)
    ↓
Policy Layer (IntradayMLDecisionPolicy)
    ↓
Order Generation
    ↓
Backtest Engine (qx-backtest)
    ↓
Performance Analysis
```

### Key Packages
- **qx-core:** Schemas, validators, utilities
- **qx-data:** Gold data loading, normalization
- **qx-features:** Feature engineering registry
- **qx-screener:** Universe selection (SIP + HMM)
- **qx-backtest:** Order → fill → position → P&L pipeline
- **qx-risk:** Risk management, position sizing
- **extensions/intraday_ml:** ML-specific logic

### File Locations
```
configs/extensions/intraday_ml/
├── features_10m.yaml              # Feature definitions
├── policy_config_bigmove_simple.json  # Policy parameters
├── policy_config_no_timeout.json      # Test config
└── policy_sweep_grid_test.yaml        # Parameter sweep grid

extensions/intraday_ml/
├── backtest.py                    # Backtest wrapper
├── policy/                        # Trading policies
├── experiments/                   # Training & sweep logic
└── diagnostics/                   # Analysis tools

scripts/
├── analyze_stop_hits.py          # Diagnostic script
├── match_fills_to_trades.py      # Post-processing
├── test_no_timeout.py            # Hypothesis testing
└── run_sequential_sweep.py       # Parameter sweep

artefacts/extensions/intraday_ml/phaseA_full_sip/
├── oos_predictions_bigmove.parquet  # ML predictions
├── oos_features.parquet             # Feature matrix
├── fills.parquet                    # Trade fills
├── orders.parquet                   # Generated orders
└── matched_trades.parquet           # Completed round-trips
```

---

## 2. ML Pipeline

### 2.1 Universe Selection

**Method:** Stocks In Play (SIP) with HMM scoring

**Criteria:**
- Price range: $5.00 - $50.00
- Min daily volume: $10M
- HMM score > 0.01
- Top 40 symbols per day
- Static universe: ~100 liquid US equities

**Configuration:** `universe_intraday_sip_5_50.yaml`

**Symbols:** BAC, CCL, PLTR, UAL, AES, DVN, EQT, F, etc.

### 2.2 Feature Engineering

**Granularity:** 10-minute bars (resampled from 1-minute)

**Feature Families (150+ features):**

1. **Returns & Trend**
   - Simple/log returns over [1, 2, 3, 6, 12] windows
   - 10m to 2h lookback

2. **Volatility (ATR)**
   - Absolute and normalized ATR
   - Windows: 3, 6 bars
   - Key: `f__vol__atr_6` (used for stops)

3. **Volume Flow**
   - VWAP, volume sums, relative volume (RVOL)
   - Normalized by time-of-day

4. **VWAP Distance**
   - Z-scores vs 5m, 10m, 20m, 30m VWAPs

5. **Price Momentum**
   - RSI, ROC, MA ratios

6. **Microstructure**
   - Effective spread proxies
   - Volume imbalance estimators

7. **Time Seasonality**
   - Sin/Cos encoding of hour, minute, day-of-week

**Configuration:** `configs/extensions/intraday_ml/features_10m.yaml`

**Leakage Prevention:**
- Features at time T use only data from t ≤ T
- Labels at time T use only data from t > T
- Sliding window architecture

### 2.3 Target Definition

**"Big Move" Label:**

```python
threshold = max(ATR * 1.10, 0.0075)  # 1.10x ATR or 0.75% floor
horizon = 60 minutes (6 bars)

if max_forward_return > threshold:
    y_bigmove = 1
    y_bigmove_direction = +1 (long) or -1 (short)
else:
    y_bigmove = 0
    y_bigmove_direction = 0
```

**Key Parameters:**
- ATR multiplier: 1.10x
- Floor: 0.75% absolute
- Horizon: 60 minutes
- ATR source: `f__vol__atr_6`

**Historical Issue:** Earlier configs incorrectly treated dollar-ATR as percentage-ATR

### 2.4 ML Models

**Architecture:** Two-stage LightGBM pipeline

**Stage 1: Volatility Classifier**
- **Objective:** Predict P(big move will occur)
- **Target:** `y_bigmove` (binary)
- **Algorithm:** LightGBM Classifier
- **Parameters:**
  - learning_rate: 0.045
  - n_estimators: 640
  - num_leaves: 64
  - class_weight: balanced
- **Performance:** 0.88 AUC on OOS data
- **Output:** `prob_bigmove`

**Stage 2: Directional Classifier**
- **Objective:** Predict P(long) vs P(short) given big move
- **Target:** `y_bigmove_direction` (ternary: +1, -1, 0)
- **Training Data:** Only samples where `y_bigmove == 1`
- **Algorithm:** LightGBM Classifier
- **Input:** Full features + Stage 1 probability
- **Performance:** 0.93 AUC on OOS data
- **Output:** `prob_bigmove_long`, `prob_bigmove_short`

**Training Period:** Phase A (historical data)
**Scoring Period:** Out-of-sample (OOS) data for validation

---

## 3. Trading Logic

### 3.1 Signal Generation

**Policy:** `IntradayMLDecisionPolicy` (BigMove mode)

**Entry Conditions:**
1. `prob_bigmove` > threshold (default: 0.60)
2. `prob_long` > threshold OR `prob_short` > threshold (default: 0.60)
3. Time within trading window (09:35 - 15:50 ET)
4. Pass position limits and risk checks

**Signal Columns Required:**
- `prob_bigmove`
- `prob_bigmove_long`
- `prob_bigmove_short`
- `f__vol__atr_6` (for stop calculation)
- `close` (for entry price)

### 3.2 Order Generation

**Order Structure:**
```python
{
    'ts': timestamp,
    'symbol': symbol,
    'side': 'LONG' or 'SHORT',
    'qty': 1,  # Fixed for testing
    'reason': 'trade',
    'strategy': 'intraday_ml',
    'stop_loss_pct': calculated from ATR,
    'take_profit_pct': calculated from R-multiple,
    'risk_distance': stop distance in dollars,
    'risk_atr': ATR value,
    'risk_atr_multiple_stop': actual multiple used
}
```

**Position Sizing:** Currently fixed at 1 share per trade

### 3.3 Time-of-Day (TOD) Filters

**Sessions:**
- OPEN: 09:40-10:10 (high threshold: 0.70)
- MID: 10:10-14:30 (moderate: 0.65)
- LATE: 14:30-15:50 (loose: 0.62)

**Current Status:** Disabled in test configs (`tod_filter_enabled: false`)

### 3.4 Position Limits

**Per-Day Limits:**
- `max_entries_per_day`: 10
- `max_trades_per_symbol_per_day`: 2
- `max_trades_per_bar_global`: 5

**Concurrent Limits:**
- `max_open_positions_global`: 3
- Single position per symbol (no pyramiding)

**Risk Limits:**
- `max_daily_loss_R`: -10.0
- `trade_risk_R`: 1.0

---

## 4. Risk Management

### 4.1 Stop Loss Calculation

**Method:** ATR-based dynamic stops

```python
atr = features['f__vol__atr_6']
stop_distance = atr * stop_atr_multiple

if side == 'LONG':
    stop_price = entry_price - stop_distance
else:  # SHORT
    stop_price = entry_price + stop_distance

# Apply bounds
stop_pct = stop_distance / entry_price
stop_pct = max(min_stop_pct, min(stop_pct, max_stop_pct))
```

**Parameters:**
- `stop_atr_multiple`: 1.0 (configurable)
- `min_stop_pct`: 0.002 (0.2%)
- `max_stop_pct`: 0.045 (4.5%)

**Observed Values:**
- Average stop distance: $0.108
- Average ATR: $0.160
- Actual multiple: 0.69x (not 1.0x - bug suspected)

### 4.2 Take Profit Calculation

**Method:** R-multiple based

```python
target_distance = stop_distance * tp_r_multiple

if side == 'LONG':
    target_price = entry_price + target_distance
else:  # SHORT
    target_price = entry_price - target_distance
```

**Parameters:**
- `tp_r_multiple`: 2.0 (2R target)

**Example:**
```
Entry: $18.00 LONG
ATR: $0.108
Stop: $17.892 (1.0 ATR below)
Target: $18.216 (2.0 ATR above)
Risk: $0.108 (0.6%)
Reward: $0.216 (1.2%)
R:R = 1:2
```

### 4.3 Lifecycle Management

**Timeouts (Current Config):**
```json
{
    "early_loss_cut_r": 0.5,
    "early_loss_cut_minutes": 20,
    "dead_trade_exit_minutes": 30,
    "dead_trade_pnl_band_r": 0.2,
    "max_hold_minutes_flat_or_loser": 60,
    "max_hold_minutes_in_the_money": 240,
    "trail_activation_r": 1.5,
    "trail_stop_r": 0.75
}
```

**Early Cut Rule:**
- If PnL < 0.5R after 20 minutes → EXIT
- **Issue:** This killed 94% of trades in testing

**Dead Trade Rule:**
- If |PnL| < 0.2R after 30 minutes → EXIT

**Max Hold:**
- Losers: 60 minutes
- Winners: 240 minutes (4 hours)

**Trailing Stop:**
- Activates at 1.5R profit
- Trails at 0.75R below peak

### 4.4 End-of-Day Management

**Flat EOD Rule:**
- All positions closed at 15:59:59 ET
- Market orders submitted
- No overnight positions

**Implementation:** `backtest.py` line 405-420

---

## 5. Backtest Engine

### 5.1 Architecture

**Engine:** `qx-backtest` (custom event-driven)

**Flow:**
```
1. Load bars (OHLCV data)
2. Load orders (from policy)
3. For each timestamp:
   a. Update portfolio values
   b. Call strategy function
   c. Process pending orders
   d. Record state
4. Generate results
```

**Key Classes:**
- `BacktestEngine`: Main orchestrator
- `Portfolio`: Position tracking, P&L
- `Order`: Order representation
- `Fill`: Execution record
- `Filler`: Execution simulation

### 5.2 Order Execution

**Filler:** `DefaultFiller`

**Parameters:**
- `commission_per_share`: $0.0035
- `commission_min`: $0.35
- `slippage_bps`: 5 (0.05%)
- `partial_fill_probability`: 0.3
- `fill_probability`: 0.95

**Execution Logic:**
```python
# Market orders
fill_price = close_price * (1 + slippage_bps/10000)  # BUY
fill_price = close_price / (1 + slippage_bps/10000)  # SELL

# Commission
commission = max(quantity * commission_per_share, commission_min)
```

**Observed:** Commission = $0.35 per fill (minimum applies for 1-share trades)

### 5.3 Position Management

**Position Tracking:**
- Quantity (positive = long, negative = short)
- Entry price (average)
- Unrealized P&L
- Market value

**Updates:**
- Every bar: Mark-to-market
- On fill: Update quantity, entry price
- On close: Realize P&L

### 5.4 Performance Metrics

**Calculated Metrics:**
- Total return
- Annualized return
- Volatility (daily)
- Sharpe ratio
- Max drawdown
- Max drawdown duration
- Win rate
- Average R-multiple
- Total commissions
- Fill rate

**Sharpe Calculation (Intraday Fix):**
```python
# Detect intraday data
if 'datetime' in equity.columns:
    is_intraday = True
    
# Resample to daily for volatility
daily_equity = equity.resample('D').last()
daily_returns = daily_equity.pct_change()
volatility = daily_returns.std() * sqrt(252)

# Count unique trading days
trading_days = equity['datetime'].dt.date.nunique()
```

**Issue:** Earlier versions treated 10-min bars as daily data, inflating volatility

---

## 6. Configuration

### 6.1 Policy Configuration

**File:** `policy_config_bigmove_simple.json`

**Key Sections:**

**Thresholds:**
```json
{
    "prob_threshold_long": 0.6,
    "prob_threshold_short": 0.6,
    "score_margin": 0.0,
    "min_directional_gap": 0.0,
    "min_conviction_score": 0.0
}
```

**Time Filters:**
```json
{
    "min_time": "09:35:00",
    "max_time": "15:50:00",
    "tod_filter_enabled": false,
    "session_timezone": "America/New_York"
}
```

**Position Limits:**
```json
{
    "max_entries_per_day": 10,
    "max_open_positions_global": 3,
    "max_trades_per_symbol_per_day": 2,
    "max_trades_per_bar_global": 5,
    "max_daily_loss_R": -10.0
}
```

**Risk:**
```json
{
    "atr_feature": "f__vol__atr_6",
    "stop_atr_multiple": 1.0,
    "tp_r_multiple": 2.0,
    "min_stop_pct": 0.002,
    "max_stop_pct": 0.045,
    "min_expected_r": 0.5
}
```

**Lifecycle:**
```json
{
    "early_loss_cut_r": 0.5,
    "early_loss_cut_minutes": 20,
    "dead_trade_exit_minutes": 30,
    "dead_trade_pnl_band_r": 0.2,
    "max_hold_minutes_flat_or_loser": 60,
    "max_hold_minutes_in_the_money": 240
}
```

### 6.2 Sweep Configuration

**File:** `policy_sweep_grid_test.yaml`

**Parameter Grid:**
```yaml
prob_threshold_long: [0.50, 0.60, 0.70]
prob_threshold_short: [0.50, 0.60, 0.70]
stop_atr_multiple: [1.0, 2.0, 3.0]
tp_r_multiple: [2.0]
```

**Full Grid:** 576 configurations (3×3×3×... combinations)
**Test Grid:** 8 configurations (fast iteration)

### 6.3 Backtest Configuration

**Defaults:**
```python
{
    'initial_capital': 100000,
    'commission_per_share': 0.0035,
    'commission_min': 0.35,
    'slippage_bps': 5,
    'costs': {
        'per_share': 0.0035,
        'commission_min': 0.35,
        'bps': 5
    }
}
```

---

## 7. Data Flow

### 7.1 Training Phase

```
1. Load bars from Gold layer
2. Apply SIP filter → universe
3. Generate features (IntradayMLFeaturePack)
4. Calculate labels (BigMove definition)
5. Train Stage 1 model (volatility)
6. Train Stage 2 model (direction, conditional)
7. Save models
```

### 7.2 Scoring Phase

```
1. Load OOS bars
2. Apply SIP filter
3. Generate features
4. Load trained models
5. Predict Stage 1 (prob_bigmove)
6. Predict Stage 2 (prob_long, prob_short)
7. Save predictions
```

### 7.3 Backtest Phase

```
1. Load predictions (signals)
2. Load features (for ATR)
3. Prepare signals (_prepare_signals_for_policy_mode)
4. Ensure required columns (_ensure_required_columns)
5. Create policy (IntradayMLDecisionPolicy)
6. Process signals → orders
7. Run backtest (intraday_ml_run_backtest)
8. Generate fills, equity, metrics
9. Save artifacts
```

### 7.4 Analysis Phase

```
1. Load fills
2. Match fills to trades (match_fills_to_trades.py)
3. Calculate round-trip P&L
4. Analyze exit reasons, durations
5. Generate reports
```

---

## 8. Known Issues

### 8.1 CRITICAL: Stop/Target Not Implemented

**Issue:** Backtest engine does NOT monitor positions for stop loss or take profit

**Evidence:**
- `backtest.py` sets `order_obj.stop_loss` and `order_obj.take_profit`
- But `Order` class has no such attributes
- Engine never checks positions against these levels
- All exits via timeout or EOD close

**Impact:**
- 0% win rate (targets never hit)
- All trades lose commission + small adverse move
- Risk management completely broken

**Files Affected:**
- `qx-backtest/src/qx_backtest/order.py` (missing attributes)
- `qx-backtest/src/qx_backtest/engine.py` (missing position monitoring)
- `extensions/intraday_ml/backtest.py` (sets unused attributes)

**Fix Required:**
1. Add `stop_loss` and `take_profit` to Order class
2. Transfer to Position on fill
3. Add `_check_position_exits()` to engine
4. Generate exit orders when triggered
5. Record exit_reason in fills

**Estimated Effort:** 8-12 hours

### 8.2 R-Multiple Always Zero

**Issue:** `r_multiple` column always 0.0 in trades

**Cause:** Not calculated from actual entry/exit

**Fix:** Calculate on trade close:
```python
r_multiple = (exit_price - entry_price) / stop_distance  # LONG
r_multiple = (entry_price - exit_price) / stop_distance  # SHORT
```

### 8.3 Stop Distance Not Recorded

**Issue:** `stop_dist_ps` always 0.0 in fills

**Cause:** Not propagated from orders to fills

**Fix:** Add to Fill dataclass, copy from order

### 8.4 Slippage Not Recorded

**Issue:** `slippage_est` always 0.0

**Cause:** Applied to price but not saved separately

**Fix:** Record in Fill object

### 8.5 ATR Multiple Incorrect

**Issue:** Configured 1.0 ATR but actual is 0.69 ATR

**Cause:** Unknown - possible bug in risk calculation

**Investigation Needed:** Check stop calculation logic

### 8.6 Early Cut Timeout Too Aggressive

**Issue:** 94% of trades exit at 20 minutes (early_cut)

**Cause:** 0.5R threshold unrealistic for 20-minute window

**Fix:** Disable or loosen (tested: no improvement)

### 8.7 Commission Dominates Edge

**Issue:** $0.70 commission on $18 stock = 3.9% breakeven

**Cause:** 1-share position size + $0.35 minimum commission

**Fix:** Increase position size to 10+ shares

### 8.8 Sharpe Calculation Fixed

**Issue:** Treated intraday bars as daily data

**Status:** FIXED in engine.py lines 131-175

**Solution:** Detect intraday, resample to daily, count unique dates

---

## 9. Performance Baseline

### 9.1 Current Results (Broken System)

**Test Period:** 22 trading days (May 2024)
**Configurations Tested:** 8

**Metrics:**
- Win rate: 0.3% (1 win out of 343 trades)
- Avg PnL: -$0.70 per trade
- Total PnL: -$241.69
- Sharpe: -50 to -80
- Avg duration: 23.8 minutes
- Exit pattern: 94% at 20 minutes (timeout)

**Trade Distribution:**
- Total trades: 343
- Winners: 1
- Losers: 342
- Avg loss: -$0.70

**PnL Distribution:**
- < -$1.00: 9 trades
- -$1.00 to -$0.50: 311 trades
- -$0.50 to $0.00: 22 trades
- $0.00 to $0.50: 1 trade
- > $0.50: 0 trades

### 9.2 ML Model Performance

**Stage 1 (Volatility):**
- AUC: 0.88
- Precision: Unknown
- Recall: Unknown

**Stage 2 (Direction):**
- AUC: 0.93
- Precision: Unknown
- Recall: Unknown

**Note:** High AUC does not translate to trading profitability

### 9.3 Expected Performance (After Fixes)

**Realistic Targets:**
- Win rate: 30-40%
- Avg R: 0.5-1.0
- Sharpe: 1.0-2.0
- Max drawdown: -15% to -20%
- Trades per day: 10-20

---

## 10. Development Environment

### 10.1 Setup

```bash
# Install workspace
make install

# Lint
make lint

# Format
make format

# Type check
make check-types

# Test
make test

# Daily HMM smoke test
make test-daily-hmm
```

### 10.2 Key Commands

```bash
# Run backtest
python scripts/test_no_timeout.py

# Match fills to trades
python scripts/match_fills_to_trades.py

# Analyze stop hits
python scripts/analyze_stop_hits.py

# Run parameter sweep
python scripts/run_sequential_sweep.py
```

### 10.3 Dependencies

- Python 3.11+
- pandas, numpy
- lightgbm
- scikit-learn
- pyarrow (for parquet)
- pyyaml
- typer, rich (CLI)

---

## 11. References

### Key Documents
- `SYSTEM_TECH_DOC_INTRADAY_ML.md` - Original system design
- `AGENTS.md` - Development guidelines
- `README.md` - Project overview
- `docs/features/daily-hmm-sip.md` - Universe selection

### Reports
- `reports/ROOT_CAUSE_ANALYSIS.md` - 0.3% win rate investigation
- `reports/TIMEOUT_TEST_RESULTS.md` - Timeout hypothesis testing
- `reports/SYSTEM_AUDIT_DEC5.md` - Comprehensive audit
- `reports/CRITICAL_FINDINGS_DEC5.md` - Executive summary

### Code Locations
- Policy: `extensions/intraday_ml_policies/intraday_ml_decision_policy.py`
- Backtest: `extensions/intraday_ml/backtest.py`
- Engine: `qx-backtest/src/qx_backtest/engine.py`
- Features: `qx-features/src/qx_features/intraday_ml_feature_pack.py`

---

**End of Technical Documentation**
