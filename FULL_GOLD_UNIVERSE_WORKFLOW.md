# Full Gold Universe Testing Workflow

**Started**: 2025-12-07 00:38 SGT  
**Universe**: 510 symbols (full gold universe available in gcs-mount)  
**Period**: Jan 2 - Jun 28, 2024 (6 months, same as v4_6months)  
**Goal**: Test 15 Optimal features on full universe with daily SIP selection

---

## Current Status

### ✅ Step 1: Feature Store Build (IN PROGRESS)
**Command**: `python scripts/build_daily_feature_store_full_gold_6months.py`  
**Status**: RUNNING (started 00:38 SGT)  
**Progress**: Batch 1/11 (50 symbols per batch)  
**Duration**: ~2-3 hours (510 symbols × 6 months)  
**Output**: `run/daily_features_full_gold_6months/features.parquet`

**Monitor**:
```bash
# Watch progress
tail -f /tmp/build_features_full_gold.log

# Check batch progress
grep 'Processing batch' /tmp/build_features_full_gold.log | tail -5

# Check heartbeat (every 60 seconds)
grep 'HEARTBEAT' /tmp/build_features_full_gold.log | tail -3
```

**Expected Output**:
- Total rows: ~60,000-80,000 (510 symbols × ~124 trading days)
- Unique symbols: ~500 (some may not have data)
- Features: date, symbol, open, high, low, close, volume, gap_pct, adv20, atr14

---

## Next Steps (Execute After Step 1 Completes)

### Step 2: Generate SIP Membership (5 min)
```bash
python scripts/generate_smb_sip_full_gold_6months.py
```

**What it does**:
- Applies SMB filters daily: gap≥2%, ATR≥$2, ADV≥10M
- Selects top 50 stocks per day based on score
- **Daily variation**: Different stocks selected each day based on criteria

**Output**: `run/sip_membership_full_gold_6months/sip_membership.parquet`

**Expected**:
- Total selections: ~6,000 (50 stocks × 124 days)
- Unique symbols: 200-300 (stocks that meet criteria at least once)
- Avg stocks/day: 45-50

---

### Step 3: Generate Training Data (30-60 min)
```bash
python scripts/generate_training_data_full_gold_6months.py
```

**What it does**:
- Loads 1-minute bars for SIP-selected stocks
- Engineers 15 optimal features
- Generates labels (±2% threshold)
- Splits: 60% train, 20% val, 20% OOS

**Output**: 
- `artefacts/extensions/intraday_ml/v4_full_gold_6months/train.parquet`
- `artefacts/extensions/intraday_ml/v4_full_gold_6months/val.parquet`
- `artefacts/extensions/intraday_ml/v4_full_gold_6months/oos.parquet`

**Expected**:
- Total bars: 2-5M (depends on SIP selection)
- Labeled bars: 2-3% (±2% threshold)
- Symbols: 200-300

---

### Step 4: Train Models (15 min)
```bash
python scripts/train_v4_full_gold_15optimal.py
```

**Features** (15 Optimal):
- is_last_30min, sma_200, time_to_close
- obv_ema_10, liquidity_grab_high, volatility_30
- liquidity_grab_low, range_pct, volatility_5
- volume_momentum_50, bb_width_10, bb_width_20
- volume_std_50, atr_7

**Output**:
- `models/v4_full_gold_15optimal_long.txt`
- `models/v4_full_gold_15optimal_short.txt`

**Expected**:
- LONG AUC: 0.92-0.94
- SHORT AUC: 0.90-0.92

---

### Step 5: Backtest on OOS (10 min)
```bash
python scripts/backtest_v4_full_gold_15optimal.py
```

**Parameters**:
- Threshold: 0.30
- Position size: 1% of account per trade

**Output**: `run/backtest_full_gold_results.parquet`

**Expected** (vs 23-symbol baseline):
- Trades/day: 250-300 (vs 9.6 on 23 symbols)
- Win rate: 50-55% (may decrease with more symbols)
- Daily P&L: $200-500 on $100K (vs $8.61 on 23 symbols)

---

## Comparison: 23 Symbols vs Full Universe

| Metric | 23 Symbols | Full Universe (Expected) | Change |
|--------|------------|--------------------------|--------|
| **Universe** | 23 (3.8%) | 510 (100%) | +22x |
| **SIP Stocks/Day** | 23 (fixed) | 45-50 (daily varying) | +2x |
| **Trades/Day** | 9.6 | 250-300 | +26x |
| **Win Rate** | 56.0% | 50-55% | -1 to -6 points |
| **Daily P&L ($100K)** | $8.61 | $200-500 | +23x to +58x |

**Key Differences**:
1. **Daily SIP Selection**: Full universe selects different stocks each day based on SMB criteria
2. **More Opportunities**: 22x more symbols = 26x more trades
3. **Potential Noise**: More symbols may reduce win rate slightly
4. **Scalability**: Can handle larger account sizes

---

## Scripts Created

### Completed ✅
1. `scripts/build_daily_feature_store_full_gold_6months.py` - Feature store (RUNNING)

### To Create ⏳
2. `scripts/generate_smb_sip_full_gold_6months.py` - SIP selection with daily variation
3. `scripts/generate_training_data_full_gold_6months.py` - Training data with 15 optimal features
4. `scripts/train_v4_full_gold_15optimal.py` - Train LONG/SHORT models
5. `scripts/backtest_v4_full_gold_15optimal.py` - Backtest on OOS
6. `scripts/compare_23_vs_full_universe.py` - Performance comparison

---

## Key Differences from 23-Symbol Test

### 1. **Daily SIP Selection** ✅
- **23 symbols**: Fixed list (AAPL, AMD, AMZN, etc.)
- **Full universe**: Daily selection based on SMB criteria
  - Gap ≥2%
  - ATR ≥$2
  - ADV ≥10M
  - Top 50 per day

### 2. **Universe Coverage** ✅
- **23 symbols**: 3.8% of gold universe
- **Full universe**: 100% of available symbols (510)

### 3. **Trade Volume** ✅
- **23 symbols**: ~10 trades/day
- **Full universe**: ~250-300 trades/day (26x more)

### 4. **Scalability** ✅
- **23 symbols**: Limited to small accounts ($10K-100K)
- **Full universe**: Can scale to $1M+ accounts

---

## Monitoring Commands

### Check Feature Store Progress
```bash
# Watch live
tail -f /tmp/build_features_full_gold.log

# Check current batch
grep 'Processing batch' /tmp/build_features_full_gold.log | tail -1

# Check completion
grep 'Feature Store Build Complete' /tmp/build_features_full_gold.log

# Check output size
ls -lh run/daily_features_full_gold_6months/features.parquet
```

### Verify Feature Store Output
```bash
python -c "
import pandas as pd
df = pd.read_parquet('run/daily_features_full_gold_6months/features.parquet')
print(f'Rows: {len(df):,}')
print(f'Symbols: {df[\"symbol\"].nunique()}')
print(f'Dates: {df[\"date\"].nunique()}')
print(f'Date range: {df[\"date\"].min()} to {df[\"date\"].max()}')
print(f'Avg rows/symbol: {len(df) / df[\"symbol\"].nunique():.1f}')
"
```

---

## Expected Timeline

| Step | Duration | ETA |
|------|----------|-----|
| 1. Feature Store | 2-3 hours | 03:00 SGT |
| 2. SIP Selection | 5 min | 03:05 SGT |
| 3. Training Data | 30-60 min | 04:00 SGT |
| 4. Model Training | 15 min | 04:15 SGT |
| 5. Backtest | 10 min | 04:25 SGT |
| **Total** | **3-4 hours** | **04:30 SGT** |

---

## Success Criteria

### Feature Store ✅
- Rows: 60,000-80,000
- Symbols: 450-510
- Dates: ~124
- No errors in log

### SIP Selection ✅
- Total selections: 5,000-7,000
- Unique symbols: 200-300
- Avg stocks/day: 40-50
- Daily variation (not same stocks every day)

### Training Data ✅
- Total bars: 2-5M
- Labeled: 2-3%
- Train/Val/OOS split: 60/20/20

### Model Performance ✅
- Val AUC: 0.90-0.94
- OOS Win Rate: 50-55%
- OOS Trades/Day: 200-300
- OOS Daily P&L: $200-500 on $100K

---

## Rollback Plan

If full universe underperforms 23-symbol test:
1. Keep 23-symbol model as production
2. Use full universe for research only
3. Investigate why performance degraded:
   - Too much noise?
   - SIP selection too broad?
   - Features don't generalize?
4. Consider hybrid: 50-100 symbol subset

---

## Files Generated

### Data
- `run/daily_features_full_gold_6months/features.parquet` - Feature store
- `run/sip_membership_full_gold_6months/sip_membership.parquet` - SIP selections
- `artefacts/extensions/intraday_ml/v4_full_gold_6months/*.parquet` - Training data

### Models
- `models/v4_full_gold_15optimal_long.txt` - LONG model
- `models/v4_full_gold_15optimal_short.txt` - SHORT model

### Results
- `run/backtest_full_gold_results.parquet` - Backtest results
- `run/comparison_23_vs_full.csv` - Performance comparison

---

**Next Action**: Wait for feature store build to complete (~2-3 hours), then proceed to Step 2.
