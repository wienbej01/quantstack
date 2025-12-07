# Rolling Training System - Technical Documentation

## Overview

This document provides detailed technical specifications for the rolling training system implemented for intraday ML-based trading.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     ROLLING TRAINING PIPELINE                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 1: Daily Feature Store                                      │
│ - Input: Gold 1m bars (2023-07 to 2025-09)                      │
│ - Process: Aggregate to daily, calculate gap/ATR/ADV            │
│ - Output: 350K rows × 510 symbols × 680 days                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 2: SIP Selection                                            │
│ - Input: Daily features                                          │
│ - Process: Filter (gap≥2%, ATR≥$0.70, ADV≥1M), score, top-50   │
│ - Output: 8,500 selections × 317 symbols × 680 days             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 3: Intraday Feature Store                                   │
│ - Input: SIP selections + Gold 1m bars                          │
│ - Process: Load 30-day lookback, engineer 30 ICT features       │
│ - Output: 600K bars × 30 features                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 4: Rolling Training & Backtest                              │
│ - Input: Intraday features                                       │
│ - Process: 20 iterations (6m train, 1m val, 1m OOS)            │
│ - Output: 40 models + metrics.csv                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│ Step 5: Analysis & Reporting                                     │
│ - Input: metrics.csv                                             │
│ - Process: Aggregate statistics, monthly breakdown               │
│ - Output: analysis_report.txt                                    │
└─────────────────────────────────────────────────────────────────┘
```

## Data Specifications

### Daily Features Schema

| Column | Type | Description | Calculation |
|--------|------|-------------|-------------|
| `date` | Date | Trading date | - |
| `symbol` | String | Ticker symbol | - |
| `open` | Float | Daily open price | First 1m bar open |
| `high` | Float | Daily high price | Max of 1m bar highs |
| `low` | Float | Daily low price | Min of 1m bar lows |
| `close` | Float | Daily close price | Last 1m bar close |
| `volume` | Int | Daily volume | Sum of 1m bar volumes |
| `prior_close` | Float | Previous day close | `close.shift(1)` |
| `gap_pct` | Float | Gap percentage | `(open - prior_close) / prior_close` |
| `atr14` | Float | 14-day ATR | `(high - low).rolling(14).mean()` |
| `adv20` | Float | 20-day ADV | `volume.rolling(20).mean()` |

**File**: `run/daily_features_rolling/features.parquet`  
**Size**: ~350K rows, ~50 MB  
**Format**: Parquet (columnar, compressed)

### SIP Membership Schema

| Column | Type | Description | Calculation |
|--------|------|-------------|-------------|
| `date` | Date | Trading date | - |
| `symbol` | String | Ticker symbol | - |
| `gap_pct` | Float | Gap percentage | From daily features |
| `atr14` | Float | 14-day ATR | From daily features |
| `adv20` | Float | 20-day ADV | From daily features |
| `abs_gap_pct` | Float | Absolute gap | `abs(gap_pct)` |
| `score` | Float | SIP score | `abs_gap_pct × atr14 × (adv20 / 1M)` |

**Filters**:
- `abs_gap_pct >= 0.02` (2% gap)
- `atr14 >= 0.70` ($0.70 ATR)
- `adv20 >= 1,000,000` (1M ADV)
- Top 50 by score per day

**File**: `run/sip_membership_rolling/sip_membership.parquet`  
**Size**: ~8,500 rows, ~1 MB

### Intraday Features Schema (30 Features)

#### Base Features (15)
| Feature | Type | Window | Description |
|---------|------|--------|-------------|
| `returns` | Float | 1 | `close.pct_change()` |
| `returns_5` | Float | 5 | `close.pct_change(5)` |
| `returns_10` | Float | 10 | `close.pct_change(10)` |
| `returns_20` | Float | 20 | `close.pct_change(20)` |
| `range_pct` | Float | 1 | `(high - low) / close` |
| `body_pct` | Float | 1 | `abs(close - open) / close` |
| `upper_wick` | Float | 1 | `(high - max(open, close)) / close` |
| `lower_wick` | Float | 1 | `(min(open, close) - low) / close` |
| `volume_ratio` | Float | 5 | `volume / volume.rolling(5).mean()` |
| `volume_ratio_20` | Float | 20 | `volume / volume.rolling(20).mean()` |
| `volatility_5` | Float | 5 | `returns.rolling(5).std()` |
| `volatility_20` | Float | 20 | `returns.rolling(20).std()` |
| `time_since_open` | Int | - | Minutes since 9:30 AM |
| `time_to_close` | Int | - | Minutes until 4:00 PM |
| `price_position` | Float | 5 | `(close - low_5) / (high_5 - low_5)` |

#### ICT Features (11)
| Feature | Type | Description |
|---------|------|-------------|
| `fvg_up` | Binary | Fair Value Gap up (prev_high < next_low) |
| `fvg_down` | Binary | Fair Value Gap down (prev_low > next_high) |
| `fvg_size_pct` | Float | FVG size as % of close |
| `displacement_up` | Binary | Bullish displacement (returns > 2×volatility_5) |
| `displacement_down` | Binary | Bearish displacement (returns < -2×volatility_5) |
| `order_block_bull` | Binary | Bullish order block (bearish candle + displacement_up) |
| `order_block_bear` | Binary | Bearish order block (bullish candle + displacement_down) |
| `liquidity_grab_high` | Binary | High liquidity grab (high > prev_high_5, close < prev_high_5) |
| `liquidity_grab_low` | Binary | Low liquidity grab (low < prev_low_5, close > prev_low_5) |
| `bos_up` | Binary | Break of structure up (close > prev_high_5) |
| `bos_down` | Binary | Break of structure down (close < prev_low_5) |

#### VPA Features (4)
| Feature | Type | Window | Description |
|---------|------|--------|-------------|
| `pressure_ratio` | Float | 5 | `up_volume_5 / down_volume_5` |
| `distance_from_vwap` | Float | 20 | `(close - vwap) / vwap` |
| `volume_momentum` | Float | 5 | `volume.pct_change(5)` |
| `pv_divergence` | Float | 5 | `price_change_5 - volume_change_5` |

#### Labels
| Label | Type | Threshold | Description |
|-------|------|-----------|-------------|
| `label_long` | Binary | +1.5% | `forward_return > 0.015` |
| `label_short` | Binary | -1.5% | `forward_return < -0.015` |
| `forward_return` | Float | 5 bars | `(close[t+5] - close[t]) / close[t]` |

**File**: `run/intraday_features_rolling/features.parquet`  
**Size**: ~600K rows, ~200 MB

## Model Specifications

### LightGBM Hyperparameters

```python
params = {
    "objective": "binary",
    "metric": "auc",
    "boosting_type": "gbdt",
    "num_leaves": 31,
    "learning_rate": 0.05,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 5,
    "verbose": -1,
}
```

### Training Configuration

- **Max iterations**: 500
- **Early stopping**: 50 rounds
- **Validation metric**: AUC
- **Separate models**: LONG and SHORT

### Model Files

**Naming**: `{YYYY-MM}_{long|short}.txt`  
**Format**: LightGBM text format  
**Location**: `run/rolling_results/models/`  
**Count**: 40 models (20 months × 2 directions)

## Rolling Window Configuration

### Date Range Calculation

```python
def get_date_ranges():
    # OOS: 2024-02 to 2025-09 (20 months)
    # For each OOS month:
    #   Train: OOS_month - 7 months to OOS_month - 1 month (6 months)
    #   Val: OOS_month - 1 month to OOS_month (1 month)
    #   OOS: OOS_month to OOS_month + 1 month (1 month)
```

### Example Iterations

| Iter | OOS Month | Train Period | Val Period | OOS Period |
|------|-----------|--------------|------------|------------|
| 1 | 2024-02 | 2023-07 to 2023-12 | 2024-01 | 2024-02 |
| 2 | 2024-03 | 2023-08 to 2024-01 | 2024-02 | 2024-03 |
| 10 | 2024-11 | 2024-04 to 2024-09 | 2024-10 | 2024-11 |
| 20 | 2025-09 | 2025-02 to 2025-07 | 2025-08 | 2025-09 |

## Backtesting Methodology

### Signal Generation

```python
# Predict probabilities
prob_long = model_long.predict(X)
prob_short = model_short.predict(X)

# Apply threshold
threshold = 0.30
signal_long = (prob_long >= threshold)
signal_short = (prob_short >= threshold)

# Combine (LONG=1, SHORT=-1, NEUTRAL=0)
prediction = 0
if signal_long: prediction = 1
if signal_short: prediction = -1
```

### Performance Metrics

| Metric | Formula | Description |
|--------|---------|-------------|
| **Win Rate (LONG)** | `sum(forward_return > 0.015) / count(LONG)` | % of LONG signals that hit +1.5% |
| **Win Rate (SHORT)** | `sum(forward_return < -0.015) / count(SHORT)` | % of SHORT signals that hit -1.5% |
| **Combined Win Rate** | `(LONG_wins + SHORT_wins) / total_signals` | Overall win rate |
| **Total P&L** | `sum(LONG_returns) - sum(SHORT_returns)` | Cumulative return |
| **Avg P&L** | `total_pnl / total_signals` | Average return per signal |
| **Signals/Day** | `total_signals / trading_days` | Daily signal frequency |

### Metrics CSV Schema

| Column | Type | Description |
|--------|------|-------------|
| `oos_month` | String | OOS test month (YYYY-MM) |
| `auc_long` | Float | LONG model validation AUC |
| `auc_short` | Float | SHORT model validation AUC |
| `total_signals` | Int | Total signals in OOS month |
| `long_signals` | Int | LONG signals |
| `short_signals` | Int | SHORT signals |
| `long_win_rate` | Float | LONG win rate (0-1) |
| `short_win_rate` | Float | SHORT win rate (0-1) |
| `combined_win_rate` | Float | Combined win rate (0-1) |
| `total_pnl` | Float | Total P&L (as decimal) |
| `avg_pnl` | Float | Average P&L per signal |

**File**: `run/rolling_results/metrics.csv`

## Performance Benchmarks

### Expected Results (Based on 6-Month Baseline)

| Metric | 6-Month Baseline | 20-Month Rolling (Expected) |
|--------|------------------|----------------------------|
| **Win Rate** | 66.4% | 60-65% |
| **Total P&L** | +1,554% | +4,000-5,000% |
| **Total Signals** | 1,040 | 3,000-3,500 |
| **Signals/Month** | 173 | 150-175 |
| **Avg P&L/Signal** | 1.49% | 1.3-1.5% |
| **LONG Win Rate** | 71.6% | 65-70% |
| **SHORT Win Rate** | 61.7% | 55-60% |

### Model Quality Thresholds

| Metric | Threshold | Status |
|--------|-----------|--------|
| Validation AUC | > 0.90 | ✅ Good discrimination |
| Train/Val AUC Gap | < 0.05 | ✅ Not overfitting |
| Positive Rate | 0.5-1.5% | ✅ Selective signals |
| Win Rate | > 55% | ✅ Edge exists |
| Signals/Month | 100-200 | ✅ Tradeable volume |

## Computational Requirements

### Memory Usage

| Step | Peak Memory | Notes |
|------|-------------|-------|
| Daily Features | ~2 GB | Loading 27 months × 510 symbols |
| SIP Generation | ~500 MB | Filtering daily features |
| Intraday Features | ~4 GB | Loading 1m bars with lookback |
| Model Training | ~2 GB | LightGBM training |
| Backtesting | ~1 GB | Prediction generation |

### Processing Time

| Step | Time | Parallelizable |
|------|------|----------------|
| Daily Features | ~30 min | Yes (by symbol batch) |
| SIP Generation | ~1 min | No |
| Intraday Features | ~2-3 hours | Yes (by date) |
| Model Training (1 iter) | ~3-5 min | No |
| Rolling Training (20 iter) | ~1-2 hours | Yes (by iteration) |
| Analysis | ~1 min | No |
| **Total** | **4-6 hours** | - |

### Disk Usage

| Component | Size | Compressed |
|-----------|------|------------|
| Daily Features | ~50 MB | Parquet |
| SIP Membership | ~1 MB | Parquet |
| Intraday Features | ~200 MB | Parquet |
| Models (40 files) | ~40 MB | Text |
| Metrics CSV | ~10 KB | CSV |
| **Total** | **~300 MB** | - |

## Error Handling

### Common Issues

1. **Missing Data Files**
   - **Symptom**: Symbol returns None
   - **Solution**: Check file structure, verify date range
   - **Prevention**: Validate data availability before processing

2. **Memory Errors**
   - **Symptom**: OOM during feature engineering
   - **Solution**: Reduce batch size, process in chunks
   - **Prevention**: Monitor memory usage, use streaming

3. **Date Parsing Errors**
   - **Symptom**: TypeError on date operations
   - **Solution**: Normalize date types (str vs date vs datetime)
   - **Prevention**: Consistent date handling across scripts

4. **Insufficient Training Data**
   - **Symptom**: len(train_df) == 0
   - **Solution**: Check date range, verify SIP selections
   - **Prevention**: Validate data splits before training

### Logging

All scripts log to:
- **Console**: INFO level
- **File**: `/tmp/build_*.log` or `/tmp/rolling_pipeline.log`

Log format: `%(asctime)s | %(message)s`

## Validation Checks

### Data Quality

```python
# Daily features
assert df['symbol'].n_unique() >= 500, "Insufficient symbols"
assert df['date'].n_unique() >= 600, "Insufficient dates"
assert df['gap_pct'].notna().all(), "Missing gap values"

# SIP membership
assert len(sip) >= 8000, "Insufficient SIP selections"
assert sip['symbol'].n_unique() >= 300, "Insufficient unique symbols"

# Intraday features
assert len(df) >= 500000, "Insufficient bars"
assert df[feature_cols].notna().all().all(), "Missing feature values"
```

### Model Quality

```python
# Validation AUC
assert auc_long > 0.90, f"LONG AUC too low: {auc_long}"
assert auc_short > 0.90, f"SHORT AUC too low: {auc_short}"

# Overfitting check
train_auc_long = roc_auc_score(y_train_long, model_long.predict(X_train))
assert abs(train_auc_long - auc_long) < 0.05, "Overfitting detected"
```

### Backtest Quality

```python
# Signal volume
assert metrics['total_signals'] >= 50, "Too few signals"
assert metrics['total_signals'] <= 500, "Too many signals"

# Win rate
assert metrics['combined_win_rate'] > 0.55, "No edge detected"

# P&L
assert metrics['total_pnl'] > 0, "Negative P&L"
```

## Maintenance

### Monthly Retraining

```bash
# Add new month of data
# Update date ranges in rolling_train_and_backtest.py
# Run pipeline
./scripts/run_rolling_pipeline.sh
```

### Model Versioning

Models are versioned by OOS month:
- `2024-02_long.txt` - February 2024 LONG model
- `2024-02_short.txt` - February 2024 SHORT model

### Data Archival

Old data can be archived after 12 months:
```bash
# Archive old daily features
tar -czf daily_features_2023.tar.gz run/daily_features_rolling/
mv daily_features_2023.tar.gz archive/
```

## References

### Code Files
- `scripts/build_daily_features_rolling.py`
- `scripts/generate_sip_rolling.py`
- `scripts/build_intraday_features_rolling.py`
- `scripts/rolling_train_and_backtest.py`
- `scripts/analyze_rolling_results.py`
- `scripts/run_rolling_pipeline.sh`

### Documentation
- `ROLLING_TRAINING_STRATEGY.md` - Strategy overview
- `ROLLING_IMPLEMENTATION_STATUS.md` - Implementation status
- `SESSION_2025_12_07_SUMMARY.md` - Session summary
- `docs/ROLLING_TRAINING_TECHNICAL.md` - This document

### External References
- LightGBM: https://lightgbm.readthedocs.io/
- Polars: https://pola-rs.github.io/polars/
- SMB Capital: https://www.smbcapital.com/

---

**Document Version**: 1.0  
**Last Updated**: 2025-12-07  
**Author**: Kiro AI Assistant
