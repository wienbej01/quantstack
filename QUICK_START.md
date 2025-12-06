# Quick Start - Resume v4 Implementation

**Last Updated**: 2025-12-06 14:02 SGT

---

## Current Status: Feature Store Building

**Process**: Parallel feature store build (1,108 symbols)  
**Started**: 13:56 SGT  
**ETA**: 17:00 SGT (~3 hours remaining)

---

## Check Status

```bash
# Is feature store complete?
ls -lh run/daily_features/features.parquet

# Monitor progress
tail -f /tmp/build_features_parallel.log

# Check if running
ps aux | grep "build_daily_feature_store_parallel" | grep python
```

---

## Next Steps (When Feature Store Completes)

### 1. SIP Selection (< 1 min)
```bash
python scripts/generate_smb_sip_from_features_no_pm.py
```

**Validate**:
```bash
python -c "
import pandas as pd
df = pd.read_parquet('run/sip_membership_smb_1month/sip_membership.parquet')
print(f'Rows: {len(df)}, Symbols: {df[\"symbol\"].nunique()}, Avg/day: {len(df)/df[\"date\"].nunique():.1f}')
"
```
**Expected**: 400-500 rows, 100-200 symbols, 15-25 avg/day

---

### 2. Training Data (30-60 min)
```bash
python scripts/generate_training_data_subset.py
```

---

### 3. Train Models (15 min)
```bash
python scripts/train_v4_subset.py
```

---

### 4. Generate Predictions (10 min)
```bash
python scripts/generate_v4_predictions.py
```

---

### 5. Backtest (15 min)
```bash
python scripts/backtest_v4_smb.py
```

---

### 6. Compare Results (5 min)
```bash
python scripts/compare_v3_v4.py
cat run/v3_v4_comparison.txt
```

---

## Full Documentation

- **System Overview**: `SYSTEM_OVERVIEW.md`
- **Project Status**: `PROJECT_STATUS.md`
- **Troubleshooting**: See `PROJECT_STATUS.md` → Troubleshooting section

---

## Key Metrics to Track

### v3 Baseline
- Trades: 2.1/day
- Win rate: 42.3%
- Monthly PnL: $18.94

### v4 Target
- Trades: 3-5/day
- Win rate: 55%+
- Monthly PnL: $150+

---

## If Session Interrupted

1. Check `PROJECT_STATUS.md` for current phase
2. Run validation commands for completed phases
3. Continue from next incomplete phase
4. All scripts are idempotent (safe to rerun)
