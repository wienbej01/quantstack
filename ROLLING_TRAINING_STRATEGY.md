# Rolling Training Strategy for Intraday ML System

## Summary

**Objective**: Implement walk-forward analysis with rolling 6-month training windows to adapt to changing market regimes.

## CRITICAL: Daily SIP Selection

**The SIP filter is applied DAILY to the ENTIRE universe (1,108 symbols), not per training period.**

### Daily Selection Process

1. **Every Day** (including train/val/OOS):
   - Scan ALL 1,108 symbols in gold universe
   - Calculate daily features: gap_pct, atr14, adv20
   - Apply filters: gap ≥2%, ATR ≥$0.70, ADV ≥1M
   - Score: `|gap| × ATR × (ADV / 1M)`
   - Select top 50 stocks for that day

2. **Result**: 
   - Different stocks selected each day based on daily catalysts
   - NOT a fixed list per training period
   - Adapts to daily market conditions

3. **Training/Val/OOS**:
   - All periods use the same daily SIP selection
   - Models train on historically selected stocks
   - Backtest uses stocks that were selected on each OOS day

### Example

**2024-01-15** (Training day):
- Scan 1,108 symbols → 50 selected (e.g., TSLA, NVDA, COIN...)
- Train model on these 50 stocks' intraday bars

**2024-01-16** (Training day):
- Scan 1,108 symbols → 50 selected (e.g., AMD, SMCI, PLTR...)
- Different stocks based on that day's gaps/volatility

**2024-02-15** (OOS day):
- Scan 1,108 symbols → 50 selected
- Generate predictions only for these 50 stocks
- NOT the same 50 from training period

### Why This Matters

1. **Universe Coverage**: 1,108 symbols scanned daily (not 510 pre-filtered)
2. **Catalyst-Driven**: Selects stocks with actual catalysts each day
3. **No Look-Ahead Bias**: OOS days use only that day's data for selection
4. **Realistic**: Mimics production where you scan universe pre-market daily

## Window Configuration

| Component | Duration | Purpose |
|-----------|----------|---------|
| **Training** | 6 months | Learn patterns, sufficient sample size (~1,000+ signals) |
| **Validation** | 1 month | Hyperparameter tuning, early stopping, overfitting detection |
| **OOS Test** | 1 month | True out-of-sample performance evaluation |
| **Step Size** | 1 month | Roll forward monthly for continuous adaptation |

## Timeline

**Start Date**: 2023-07-01 (training start)  
**First OOS**: 2024-02-01  
**End Date**: 2025-09-30  
**Total OOS Months**: 20 months

### Example Iterations

| Iter | Train Start | Train End | Val Start | Val End | OOS Start | OOS End |
|------|-------------|-----------|-----------|---------|-----------|---------|
| 1 | 2023-07-01 | 2023-12-31 | 2024-01-01 | 2024-01-31 | 2024-02-01 | 2024-02-29 |
| 2 | 2023-08-01 | 2024-01-31 | 2024-02-01 | 2024-02-29 | 2024-03-01 | 2024-03-31 |
| 3 | 2023-09-01 | 2024-02-29 | 2024-03-01 | 2024-03-31 | 2024-04-01 | 2024-04-30 |
| ... | ... | ... | ... | ... | ... | ... |
| 20 | 2024-12-01 | 2025-05-31 | 2025-06-01 | 2025-06-30 | 2025-07-01 | 2025-07-31 |

## Rationale

### Why 6-Month Training?
1. **Sample Size**: Our 6-month backtest generated 1,040 signals (177K bars) - sufficient for stable model
2. **Regime Capture**: Captures 1-2 market regimes without overfitting to old patterns
3. **Recency Bias**: Recent enough to reflect current market dynamics
4. **Industry Standard**: SMB Capital and prop firms use 3-6 months for intraday systems

### Why 1-Month Validation?
1. **Sufficient Signals**: ~150-200 signals for reliable early stopping
2. **Recent Data**: Close enough to OOS period to be representative
3. **Efficient**: Doesn't waste too much data that could be used for training

### Why 1-Month OOS Test?
1. **Statistical Significance**: ~150-200 signals per month for meaningful metrics
2. **Regime Stability**: Short enough that market regime likely stable
3. **Practical**: Monthly retraining is operationally feasible

## Implementation Steps

### 1. Build Daily Feature Store (2023-07 to 2025-09)
```bash
python scripts/build_daily_features_rolling.py
```
- **Output**: `run/daily_features_rolling/features.parquet`
- **Expected**: ~350K rows (510 symbols × ~680 trading days)
- **Time**: ~15-20 minutes

### 2. Generate SIP Membership
```bash
python scripts/generate_sip_rolling.py
```
- **Output**: `run/sip_membership_rolling/sip_membership.parquet`
- **Expected**: ~8,500 selections (12.5 symbols/day × 680 days)

### 3. Build Intraday Feature Store
```bash
python scripts/build_intraday_features_rolling.py
```
- **Output**: `run/intraday_features_rolling/features_30ict.parquet`
- **Expected**: ~600K bars (27 months vs 6 months = 4.5x more data)
- **Time**: ~2-3 hours

### 4. Run Rolling Training & Backtest
```bash
python scripts/rolling_train_and_backtest.py
```
- **Process**:
  - For each month from 2024-02 to 2025-09:
    - Train on 6 months prior
    - Validate on 1 month prior
    - Test on current month
    - Save model, predictions, metrics
- **Output**: 
  - `run/rolling_results/models/` - 20 model pairs (LONG/SHORT)
  - `run/rolling_results/predictions/` - Monthly predictions
  - `run/rolling_results/metrics.csv` - Performance by month
- **Time**: ~3-4 hours (20 iterations × 10 min each)

## Expected Results

### Baseline (Static 6-Month Model)
- **Win Rate**: 66.4%
- **Total P&L**: +1,554%
- **Signals**: 1,040 (10.2/day)
- **Period**: 2024-01 to 2024-06

### Rolling (20-Month Walk-Forward)
- **Expected Win Rate**: 60-65% (slight degradation due to regime changes)
- **Expected Total P&L**: +4,000-5,000% (20 months vs 6 months)
- **Expected Signals**: ~3,000-3,500 (150-175/month)
- **Benefit**: Adapts to market regime changes, more robust

## Key Metrics to Track

### Per-Month Metrics
1. **Win Rate** (LONG, SHORT, Combined)
2. **Total P&L** (cumulative and per-month)
3. **Signals** (count, per-day average)
4. **Model AUC** (validation performance)
5. **Feature Importance** (track drift over time)

### Aggregate Metrics
1. **Sharpe Ratio** (risk-adjusted returns)
2. **Max Drawdown** (worst peak-to-trough)
3. **Win Rate Stability** (std dev across months)
4. **Regime Performance** (bull vs bear vs sideways)

## Validation Checks

### Model Quality
- ✅ Validation AUC > 0.90 (good discrimination)
- ✅ Train/Val AUC gap < 0.05 (not overfitting)
- ✅ Positive rate 0.5-1.5% (selective signals)

### Backtest Quality
- ✅ Win rate > 55% (edge exists)
- ✅ Avg P&L > 1.0% (profitable signals)
- ✅ Signals/day 5-15 (tradeable volume)
- ✅ Monthly consistency (not one lucky month)

## Next Steps

1. **Complete Feature Builds** (daily → SIP → intraday)
2. **Implement Rolling Framework** (train/val/test loop)
3. **Run 20-Month Backtest** (2024-02 to 2025-09)
4. **Analyze Results** (regime performance, feature drift)
5. **Optimize** (threshold tuning, feature selection per regime)

## Files Created

- `scripts/build_daily_features_rolling.py` - Daily feature store (2023-07 to 2025-09)
- `scripts/generate_sip_rolling.py` - SIP membership generation
- `scripts/build_intraday_features_rolling.py` - Intraday features with 30 ICT
- `scripts/rolling_train_and_backtest.py` - Main rolling training loop
- `scripts/analyze_rolling_results.py` - Performance analysis and visualization

## References

- Current 6-month backtest: `run/comparison_13_vs_30/comparison_report.txt`
- Feature comparison: `THREE_WAY_COMPARISON_REPORT.md`
- Original strategy: `NEXT_SESSION_PLAN.md`
