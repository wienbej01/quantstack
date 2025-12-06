# Next Session Build Plan: SMB-Inspired SIP Implementation

**Session Date**: TBD (After 2025-12-06)  
**Objective**: Implement catalyst-driven stock selection to improve from 42% → 55%+ win rate and 3-5 trades/day

---

## Context Summary

### Current State
- **SIP Coverage**: 97 symbols (8.8% of 1,108 gold universe) ❌
- **Performance**: 42.3% win rate, 65 trades/month, $18.94/month profit
- **Issue**: Liquidity filter, not catalyst-driven "stocks in play"
- **Top ML Feature**: Volume momentum (0.1764 correlation) ✅

### Target State
- **SIP Coverage**: 1,108 symbols (100% gold universe) → filter to top 20/day
- **Performance**: 55%+ win rate, 3-5 trades/day, $5K-10K/month on $10K account
- **Method**: SMB Capital catalyst-driven + ML confirmation

### Key Files
- `/home/jacobw/quantstack/SMB_SIP_COMPARISON.md` - Analysis and recommendations
- `/home/jacobw/quantstack/run/sip_membership/` - Existing SIP data (175 days)
- `qx-screener/` - SIP implementation package
- `scripts/train_separate_models.py` - Current v3 LONG/SHORT models

---

## Implementation Steps

### Step 1: Expand Gold Universe Scanning (30 min)
**Goal**: Scan all 1,108 symbols instead of 97

**Files to modify**:
- `qx-screener/qx_screener/sip.py` - Remove hardcoded 97-symbol restriction
- `config/sip_config.yaml` - Update universe source to full gold

**Validation**:
```bash
# Verify all 1,108 symbols scanned
python -c "from qx_screener import get_sip_universe; print(len(get_sip_universe()))"
# Expected: 1108
```

---

### Step 2: Implement SMB Catalyst Filters (60 min)
**Goal**: Add gap, premarket RVOL, ATR, intraday RVOL filters

**New module**: `qx-screener/qx_screener/smb_filters.py`
```python
def calculate_gap_pct(symbol: str, date: str) -> float:
    """Gap % = (open - prev_close) / prev_close"""
    
def calculate_premarket_rvol(symbol: str, date: str) -> float:
    """PM volume / 20-day ADV"""
    
def calculate_atr(symbol: str, date: str, window: int = 14) -> float:
    """14-day ATR"""
    
def calculate_intraday_rvol(symbol: str, ts: datetime) -> float:
    """Current volume / typical volume at this time"""
    
def apply_smb_filters(
    symbols: list[str],
    date: str,
    min_gap_pct: float = 3.0,
    min_pm_rvol: float = 0.10,
    min_atr: float = 0.70,
    top_k: int = 20
) -> list[str]:
    """Filter to top-k stocks in play"""
```

**Files to modify**:
- `qx-screener/qx_screener/sip.py` - Integrate SMB filters into daily selection
- `config/sip_config.yaml` - Add SMB filter parameters

**Validation**:
```bash
# Test on single day
python -c "
from qx_screener.smb_filters import apply_smb_filters
symbols = apply_smb_filters(['AAPL', 'TSLA', ...], '2024-01-15')
print(f'Stocks in play: {len(symbols)}')  # Expected: 15-25
"
```

---

### Step 3: Generate New SIP Membership Data (45 min)
**Goal**: Regenerate SIP data with SMB filters for full backtest period

**Script**: `scripts/regenerate_sip_with_smb.py`
```python
# Scan 1,108 symbols daily
# Apply SMB filters (gap, RVOL, ATR)
# Save top 20/day to run/sip_membership_smb/
# Partition by date
```

**Validation**:
```bash
python scripts/regenerate_sip_with_smb.py
# Check output
python -c "
import polars as pl
df = pl.scan_parquet('run/sip_membership_smb/**/*.parquet').collect()
print(f'Total rows: {len(df)}')  # Expected: ~3,500 (20 symbols × 175 days)
print(f'Unique symbols: {df['symbol'].n_unique()}')  # Expected: 200-400
print(f'Avg per day: {len(df) / df['date'].n_unique():.1f}')  # Expected: 20
"
```

---

### Step 4: Retrain Models on SMB Universe (60 min)
**Goal**: Train LONG/SHORT models on catalyst-driven stocks

**Script**: `scripts/train_v4_smb_models.py`
```python
# Load SMB SIP membership (not old 97-symbol SIP)
# Use daily-varying universe (not fixed 27 symbols)
# Train separate LONG/SHORT models
# Include volume momentum + price action features
```

**Expected metrics**:
- Training symbols: 200-400 (vs 27 current)
- Feature correlation: Volume momentum >0.20 (vs 0.1764)
- ROC AUC: >0.95 (maintain quality)

**Validation**:
```bash
python scripts/train_v4_smb_models.py
# Check model outputs
ls -lh models/v4_smb_long.txt models/v4_smb_short.txt
```

---

### Step 5: Generate Predictions with Selectivity (30 min)
**Goal**: Generate signals only for high-confidence setups

**Script**: `scripts/generate_v4_predictions.py`
```python
# Load v4 models
# Predict on SMB universe only
# Filter: prob ≥ 0.75 (vs 0.50 current)
# Filter: volume_momentum ≥ 0.15
# Save predictions
```

**Expected distribution**:
- Neutral: 95%+ (high selectivity)
- Long: 2-3%
- Short: 2-3%

**Validation**:
```bash
python scripts/generate_v4_predictions.py
python -c "
import polars as pl
df = pl.read_parquet('run/predictions_v4_smb.parquet')
print(df['prediction'].value_counts())
"
```

---

### Step 6: Backtest with SMB Strategy (45 min)
**Goal**: Validate 3-5 trades/day, 55%+ win rate

**Script**: `scripts/backtest_v4_smb.py`
```python
# Use v4 predictions
# DynamicPositionSizer (2% risk per trade)
# Entry: prob ≥ 0.75 AND vol_momentum ≥ 0.15
# Exit: 2.5 ATR target, 1.0 ATR stop
# Max 5 positions
```

**Target metrics**:
- Trades: 3-5/day (vs 2.1/day current)
- Win rate: 55%+ (vs 42.3%)
- R-multiple: 2.5+ (vs 1.6)
- Monthly PnL: $150+ at 1-share (scales to $15K at 100x)

**Validation**:
```bash
python scripts/backtest_v4_smb.py
# Review output
cat run/backtest_v4_smb_results.txt
```

---

### Step 7: Compare v3 vs v4 Performance (15 min)
**Goal**: Quantify improvement from SMB approach

**Script**: `scripts/compare_v3_v4.py`
```python
# Load v3 and v4 backtest results
# Compare: trades/day, win rate, R-multiple, PnL
# Generate comparison table
```

**Expected improvements**:
- Trades: 2.1 → 4.0/day (+90%)
- Win rate: 42.3% → 55%+ (+30%)
- Monthly PnL: $18.94 → $150+ (+692%)

---

## Success Criteria

✅ **Universe**: Scanning 1,108 symbols (100% coverage)  
✅ **Filters**: Gap ≥3%, PM RVOL ≥10%, ATR ≥$0.70 implemented  
✅ **Selectivity**: 15-25 stocks/day (vs 48 current)  
✅ **Trades**: 3-5/day (vs 2.1 current)  
✅ **Win Rate**: 55%+ (vs 42.3%)  
✅ **Profitability**: $150+/month at 1-share (vs $18.94)

---

## Rollback Plan

If v4 underperforms v3:
1. Keep v3 models as production
2. Use SMB filters for universe selection only
3. Retrain v3 architecture on SMB universe
4. A/B test: v3 (liquidity filter) vs v3.5 (SMB filter)

---

## Files to Create

1. `qx-screener/qx_screener/smb_filters.py` - SMB filter logic
2. `scripts/regenerate_sip_with_smb.py` - Generate SMB SIP data
3. `scripts/train_v4_smb_models.py` - Train on SMB universe
4. `scripts/generate_v4_predictions.py` - Generate selective predictions
5. `scripts/backtest_v4_smb.py` - Backtest SMB strategy
6. `scripts/compare_v3_v4.py` - Performance comparison

## Files to Modify

1. `qx-screener/qx_screener/sip.py` - Remove 97-symbol restriction
2. `config/sip_config.yaml` - Add SMB parameters

---

## Estimated Time: 4-5 hours

**Priority Order**:
1. Step 2 (SMB filters) - Core logic
2. Step 3 (Regenerate SIP) - Data foundation
3. Step 4 (Retrain models) - ML improvement
4. Step 6 (Backtest) - Validation
5. Steps 1, 5, 7 - Supporting tasks

---

## Notes

- Existing SIP data at `run/sip_membership/` can be archived (not deleted)
- v3 models remain production until v4 validated
- SMB filters require premarket data - verify gold universe includes pre-9:30 bars
- Volume momentum feature already implemented and proven (0.1764 correlation)
- DynamicPositionSizer already implemented (2% risk per trade)

---

**Previous Session**: 2025-12-05 (SMB analysis, v3 models, SIP coverage discovery)  
**Next Session**: TBD (Implement this plan)
