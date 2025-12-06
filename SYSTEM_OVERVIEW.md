# QuantStack Trading System - Technical Overview

**Last Updated**: 2025-12-06 14:02 SGT  
**Version**: v4 (SMB Universe Expansion)

---

## System Architecture

### Core Components

1. **Data Layer** (`/home/jacobw/gcs-mount/gold/stocks/1m`)
   - 1-minute OHLCV bars for 1,108 US stocks
   - Organized as: `{SYMBOL}/{YEAR}/{YEAR-MM}.parquet`
   - Coverage: Multi-year history
   - **Limitation**: No premarket data (market hours only)

2. **Feature Store** (`run/daily_features/`)
   - Precomputed daily metrics: gap%, ATR14, ADV20, OHLCV
   - Built once, reused for all experiments
   - Enables fast SIP selection (seconds vs hours)

3. **SIP (Stocks In Play)** (`run/sip_membership_smb_*/`)
   - Daily universe selection using SMB-inspired filters
   - Filters: gap ≥ 2%, ATR ≥ $2, ADV ≥ 10M
   - Top-20 stocks per day based on catalyst score
   - Dynamic: different stocks each day

4. **ML Models** (`models/`)
   - Separate LONG and SHORT LightGBM classifiers
   - Trained on intraday features + labels
   - Current: v3 (27 symbols), Target: v4 (1,108 symbols)

5. **Backtest Engine** (`qx-backtest/`)
   - Order → Fill → Position → P&L pipeline
   - Dynamic position sizing (2% risk per trade)
   - ATR-based stops and targets

---

## Trading Strategy

### Philosophy
**Intraday momentum trading on catalyst-driven stocks**

- Trade stocks with significant gaps and volatility (SMB Capital approach)
- Use ML to predict profitable intraday moves
- Enter on high-confidence signals (prob ≥ 0.75)
- Exit on ATR-based targets (2.5x) or stops (1.0x)

### Universe Selection (SIP)

**Original (v3)**: 97 static symbols (liquidity filter)
- Fixed universe, no catalyst focus
- Result: 42.3% win rate, 2.1 trades/day

**Target (v4)**: 1,108 symbols → top 20/day (SMB filter)
- Gap ≥ 2% (catalyst event)
- ATR ≥ $2 (sufficient volatility)
- ADV ≥ 10M (liquidity)
- Score = |gap%| × ATR × (ADV/1M)
- Result: Expected 55%+ win rate, 3-5 trades/day

**Why SMB Approach?**
- Focuses on "stocks in play" with catalysts
- Higher win rates on momentum moves
- Better risk/reward on volatile stocks
- Aligns with professional day trading methodology

### ML Model

**Architecture**: LightGBM binary classifier (separate LONG/SHORT)

**Features** (from `extensions/intraday_ml/data_prep.py`):
- Volume momentum (top feature, 0.1764 correlation)
- Price action (gaps, ranges, VWAP distance)
- Volatility (ATR, Bollinger Bands)
- Time-of-day patterns

**Labels**:
- LONG: +2% move within next 2 hours
- SHORT: -2% move within next 2 hours

**Training Data**:
- Intraday 1m bars aggregated to features
- Only SIP members (stocks in play)
- Balanced classes

**Prediction**:
- Prob ≥ 0.75 threshold (high confidence only)
- Generates 2-3% of bars as signals (high selectivity)

### Risk Management

**Position Sizing**: 2% account risk per trade
- Calculate ATR-based stop distance
- Size = (Account × 0.02) / (ATR × multiplier)
- Max 5 concurrent positions

**Exits**:
- Target: 2.5 ATR profit (R = 2.5)
- Stop: 1.0 ATR loss (R = -1.0)
- Time-based: Close at 3:55 PM

**Expected R-Multiple**: 2.5+ (win rate × 2.5 - loss rate × 1.0)

---

## Data Pipeline

### 1. Feature Store Generation

**Script**: `scripts/build_daily_feature_store_parallel.py`

**Process**:
1. Load 1m bars for each symbol (monthly parquets)
2. Compute daily OHLCV
3. Calculate rolling metrics (ATR14, ADV20)
4. Compute gap% from prior close
5. Save to `run/daily_features/features.parquet`

**Performance**:
- Parallel: 8 workers, ~3-4 hours for 1,108 symbols
- Sequential: ~27 hours (not recommended)

**Output Schema**:
```
date, symbol, open, high, low, close, volume, 
prior_close, gap_pct, adv20, atr14
```

### 2. SIP Selection

**Script**: `scripts/generate_smb_sip_from_features_no_pm.py`

**Process**:
1. Load feature store
2. Apply SMB filters (gap, ATR, ADV)
3. Score = |gap%| × ATR × (ADV/1M)
4. Select top-20 per day
5. Save to `run/sip_membership_smb_*/sip_membership.parquet`

**Performance**: < 1 second (vectorized pandas operations)

### 3. Training Data Generation

**Script**: `scripts/generate_training_data_subset.py`

**Process**:
1. Load SIP membership
2. For each (date, symbol) in SIP:
   - Load 1m bars
   - Compute intraday features
   - Label bars (±2% moves)
3. Save to `artefacts/extensions/intraday_ml/phaseA_*_v4/training_data.parquet`

**Performance**: ~30-60 minutes for 100 symbols

### 4. Model Training

**Script**: `scripts/train_v4_subset.py`

**Process**:
1. Load training data
2. Split train/validation
3. Train separate LONG/SHORT LightGBM models
4. Validate ROC AUC ≥ 0.95
5. Save models to `models/v4_subset_long.txt`, `models/v4_subset_short.txt`

**Performance**: ~15 minutes

### 5. Prediction Generation

**Script**: `scripts/generate_v4_predictions.py`

**Process**:
1. Load models
2. Load test data (OOS period)
3. Predict probabilities
4. Filter prob ≥ 0.75
5. Save to `run/predictions_v4_subset.parquet`

**Performance**: ~10 minutes

### 6. Backtesting

**Script**: `scripts/backtest_v4_smb.py`

**Process**:
1. Load predictions
2. For each signal:
   - Size position (2% risk)
   - Enter at signal bar close
   - Track to 2.5 ATR target or 1.0 ATR stop
3. Calculate metrics (win rate, R-multiple, PnL)
4. Save to `run/backtest_v4_subset_results.txt`

**Performance**: ~15 minutes

---

## Current Status (v4 Implementation)

### Completed
- ✅ SMB scanner created (`smb_scanner_monthly.py`)
- ✅ Feature store approach validated (10-symbol test)
- ✅ SIP selection logic working (gap + ATR + ADV)
- ✅ Parallel feature store builder created
- ✅ All training/backtest scripts created

### In Progress
- ⏳ Parallel feature store build (1,108 symbols) - Started 13:56 SGT, ETA 17:00 SGT
- ⏸️ 100-symbol training data generation - FAILED (needs restart)

### Blocked
- ⏸️ Model training - Waiting for training data
- ⏸️ Backtesting - Waiting for models
- ⏸️ v3 vs v4 comparison - Waiting for backtest results

### Next Steps
1. Wait for feature store completion (~3 hours)
2. Run SIP selection (< 1 min)
3. Generate training data for 100-symbol subset (30-60 min)
4. Train v4 models (15 min)
5. Generate predictions (10 min)
6. Backtest (15 min)
7. Compare v3 vs v4 performance

**Total ETA**: ~5-6 hours from feature store completion

---

## Performance Targets

### v3 Baseline (27 symbols, liquidity filter)
- Trades: 2.1/day
- Win rate: 42.3%
- Monthly PnL: $18.94 (at 1-share scale)
- Universe: Static 27 symbols

### v4 Target (1,108 symbols, SMB filter)
- Trades: 3-5/day (+90%)
- Win rate: 55%+ (+30%)
- Monthly PnL: $150+ (+692%)
- Universe: Dynamic 20 stocks/day (catalyst-driven)

### Success Criteria
- ✅ Win rate ≥ 55%
- ✅ Trades ≥ 3/day
- ✅ R-multiple ≥ 2.5
- ✅ Monthly PnL ≥ $150 (1-share scale)

---

## Key Discoveries

### 1. No Premarket Data
- Gold data only contains market hours (9:30-16:00)
- Cannot use premarket volume (PM RVOL) in SMB filters
- Modified approach: gap + ATR + ADV only

### 2. Symbol Case Mismatch
- Existing training data: lowercase symbols ('aapl')
- Gold universe: uppercase symbols ('AAPL')
- Solution: Regenerate all training data with uppercase

### 3. Feature Store Critical
- Original approach: O(days × symbols) parquet reads
- Feature store: O(symbols) one-time build + O(1) selection
- Speedup: 500+ hours → 3 hours + seconds

### 4. Parallel Processing Essential
- Sequential: 27 hours for 1,108 symbols
- Parallel (8 workers): 3-4 hours
- 8x speedup from multiprocessing

---

## File Structure

```
quantstack/
├── extensions/intraday_ml/
│   ├── smb_scanner_monthly.py          # SMB premarket scanner
│   ├── data_prep.py                    # Training data generation
│   └── backtest.py                     # Backtest utilities
├── scripts/
│   ├── build_daily_feature_store_parallel.py    # Feature store builder
│   ├── generate_smb_sip_from_features_no_pm.py  # SIP selection
│   ├── generate_training_data_subset.py         # Training data (100 symbols)
│   ├── train_v4_subset.py                       # Model training
│   ├── generate_v4_predictions.py               # Prediction generation
│   ├── backtest_v4_smb.py                       # Backtesting
│   └── compare_v3_v4.py                         # Performance comparison
├── run/
│   ├── daily_features/                 # Feature store
│   ├── sip_membership_smb_*/           # SIP membership
│   ├── predictions_v4_*.parquet        # Predictions
│   └── backtest_v4_*_results.txt       # Backtest results
├── models/
│   ├── v3_long.txt                     # v3 LONG model
│   ├── v3_short.txt                    # v3 SHORT model
│   ├── v4_subset_long.txt              # v4 LONG model (100 symbols)
│   └── v4_subset_short.txt             # v4 SHORT model (100 symbols)
└── artefacts/extensions/intraday_ml/
    ├── phaseA_full_sip_v2/             # v3 training data (27 symbols)
    └── phaseA_100_subset_v4/           # v4 training data (100 symbols)
```

---

## Configuration

### SMB Filter Thresholds
```python
min_gap_pct = 0.02      # 2% gap
min_atr = 2.0           # $2 ATR
min_adv = 10_000_000    # 10M average daily volume
top_k = 20              # Top 20 stocks per day
```

### ML Thresholds
```python
prob_threshold = 0.75   # High confidence only
label_threshold = 0.02  # ±2% move for labels
```

### Risk Parameters
```python
risk_per_trade = 0.02   # 2% account risk
atr_stop = 1.0          # 1.0 ATR stop loss
atr_target = 2.5        # 2.5 ATR profit target
max_positions = 5       # Max concurrent positions
```

---

## References

- **SMB Capital**: Professional day trading methodology (gap, RVOL, ATR filters)
- **Feature Engineering**: `extensions/intraday_ml/data_prep.py`
- **Model Training**: `extensions/intraday_ml_models/bigmove_training_utils.py`
- **Backtest Engine**: `qx-backtest/` package
- **Original Plan**: `NEXT_SESSION_PLAN.md`
- **Implementation Summary**: `SMB_IMPLEMENTATION_SUMMARY.md`
