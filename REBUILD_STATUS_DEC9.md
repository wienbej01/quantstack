# Full Rebuild Status - December 9, 2025

## Pipeline Started: 10:33 SGT

### Configuration

**Date Range**: 2023-01-01 to 2025-09-30 (33 months)
**Training Periods**: 26 months (2023-08 to 2025-09)
**Universe**: 1,108 symbols (full gold universe)
**SIP Selection**: Top 50 stocks per day (daily selection)

### Pipeline Steps

1. **Daily Features** (2-3 hours)
   - Load 1m bars for all symbols
   - Aggregate to daily OHLCV
   - Calculate gap, ATR, ADV
   - Output: `run/daily_features_rolling/features.parquet`

2. **SIP Membership** (< 1 minute)
   - Filter: gap ≥ 2%, ATR ≥ $0.70, ADV ≥ 1M
   - Score: gap × ATR × (ADV/1M)
   - Select top 50 per day
   - Output: `run/sip_membership_rolling/sip_membership.parquet`

3. **Intraday Features** (4-6 hours)
   - Load 1m bars for SIP symbols only
   - Calculate 30 ICT + VPA features
   - Entry delay: signal + 1 bar
   - Same-day exits enforced
   - ATR calculation included
   - Output: `run/intraday_features_rolling/features.parquet`

4. **Validation** (< 1 minute)
   - Check entry > signal timestamps
   - Check same-day entries/exits
   - Check exits before 16:00
   - Verify ATR calculation

5. **Rolling Training** (3-4 hours)
   - 26 iterations (2023-08 to 2025-09)
   - Each iteration:
     - Train: 6 months
     - Validation: 1 month
     - OOS: 1 month
   - Models: LightGBM (LONG + SHORT)
   - Output: `run/rolling_results/models/`

6. **Backtest** (included in step 5)
   - Entry: Next bar after signal
   - Stops: 1.5x ATR
   - Targets: 2R
   - Position sizing: 1% risk
   - Cost model: $0.0035/share + 5bps spread
   - Output: `run/rolling_results/trades.csv`

7. **Report** (< 1 minute)
   - Overall metrics
   - By direction (LONG/SHORT)
   - By exit reason
   - Cost analysis
   - Monthly breakdown

### Timeline

| Step | Duration | Status |
|------|----------|--------|
| Daily Features | 2-3 hours | 🟡 RUNNING |
| SIP Membership | < 1 min | ⏳ PENDING |
| Intraday Features | 4-6 hours | ⏳ PENDING |
| Validation | < 1 min | ⏳ PENDING |
| Rolling Training | 3-4 hours | ⏳ PENDING |
| Report | < 1 min | ⏳ PENDING |
| **TOTAL** | **10-12 hours** | **5% DONE** |

### Monitoring

**Check Status**:
```bash
./scripts/monitor_rebuild.sh
```

**Watch Logs**:
```bash
# Daily features
tail -f /tmp/build_daily_features.log

# Intraday features (when started)
tail -f /tmp/build_intraday_features.log

# Full pipeline
tail -f /tmp/full_rebuild_pipeline.log
```

**Check Processes**:
```bash
ps aux | grep -E "build_daily|build_intraday|rolling_train"
```

### Expected Outputs

**Daily Features**:
- Rows: ~700k (1,108 symbols × 650 trading days)
- Size: ~100-200 MB
- Columns: date, symbol, open, high, low, close, volume, gap_pct, atr14, adv20

**SIP Membership**:
- Rows: ~32,500 (50 symbols × 650 days)
- Size: ~5-10 MB
- Columns: date, symbol, score

**Intraday Features**:
- Rows: ~5-10M (50 symbols × 650 days × 150 bars/day)
- Size: ~500MB-1GB
- Columns: 31 features + labels + entry/exit timestamps

**Trades**:
- Rows: ~5,000-15,000 (26 months × 200-600 trades/month)
- Columns: 15 fields (timestamps, prices, P&L, costs, etc.)

### Key Improvements

1. **Full Date Range**: 2023-01 to 2025-09 (was 2023-07 to 2025-09)
2. **More Training Periods**: 26 months (was 20 months)
3. **Daily SIP Selection**: Top 50 stocks selected fresh each day
4. **Entry Delay**: No data leakage (entry on bar after signal)
5. **ATR Stops**: Adaptive risk management
6. **Full Tracking**: All trade details captured

### SIP Selection Logic

**Filters**:
- Minimum gap: 2% (absolute)
- Minimum ATR: $0.70
- Minimum ADV: $1M

**Scoring**:
```python
score = abs(gap_pct) × atr14 × (adv20 / 1_000_000)
```

**Selection**:
- Top 50 stocks per day by score
- Fresh selection each day
- Captures "stocks in play" dynamically

### Training Schedule

| OOS Month | Train Period | Val Period | OOS Period |
|-----------|--------------|------------|------------|
| 2023-08 | 2023-01 to 2023-06 | 2023-07 | 2023-08 |
| 2023-09 | 2023-02 to 2023-07 | 2023-08 | 2023-09 |
| 2023-10 | 2023-03 to 2023-08 | 2023-09 | 2023-10 |
| ... | ... | ... | ... |
| 2025-09 | 2025-02 to 2025-07 | 2025-08 | 2025-09 |

**Total**: 26 training iterations

### Performance Expectations

**Realistic Targets**:
- Win rate: 50-60%
- Avg R-multiple: 0.3-0.8R
- Trades per month: 200-600
- Stop hit rate: 40-60%
- Target hit rate: 10-20%
- Monthly return: 5-15% (on 1% risk)

**Total Performance (26 months)**:
- Total trades: 5,000-15,000
- Expected return: 130-390% (5-15% × 26)
- Max drawdown: 15-25%
- Sharpe ratio: 1.5-2.5

### Files Generated

```
run/
├── daily_features_rolling/
│   └── features.parquet          (~150 MB)
├── sip_membership_rolling/
│   └── sip_membership.parquet    (~8 MB)
├── intraday_features_rolling/
│   └── features.parquet          (~800 MB)
└── rolling_results/
    ├── metrics.csv               (26 rows)
    ├── trades.csv                (5k-15k rows)
    └── models/
        ├── 2023-08_long.txt
        ├── 2023-08_short.txt
        ├── ...
        ├── 2025-09_long.txt
        └── 2025-09_short.txt     (52 models total)
```

### Checkpointing

All scripts support checkpointing:
- Daily features: Saves every 50 symbols
- Intraday features: Saves every 10 dates
- Can resume from checkpoint if interrupted

### Troubleshooting

**If Pipeline Stops**:
```bash
# Check logs
tail -100 /tmp/full_rebuild_pipeline.log

# Check which step failed
./scripts/monitor_rebuild.sh

# Resume from failed step
# (Each step checks for existing output and skips if present)
```

**If Out of Memory**:
```bash
# Check memory usage
free -h

# Kill and restart with smaller batches
# (Edit batch size in respective script)
```

**If Data Missing**:
```bash
# Check GCS mount
ls ~/gcs-mount/gold/stocks/1m/ | head

# Remount if needed
# (See startup_after_reboot.sh)
```

### Next Steps After Completion

1. **Review Metrics**:
   ```bash
   cat run/rolling_results/metrics.csv
   ```

2. **Generate Report**:
   ```bash
   python scripts/generate_trade_report.py
   ```

3. **Analyze Results**:
   - Check win rate by month
   - Review exit reason distribution
   - Analyze stop hit rates
   - Identify best/worst periods

4. **Optimize Parameters** (if needed):
   - Adjust SIP filters
   - Tune ML thresholds
   - Modify stop/target multiples
   - Change position sizing

### Estimated Completion

**Started**: 10:33 SGT
**Expected Completion**: 20:33-22:33 SGT (10-12 hours)

**Milestones**:
- 12:33-13:33: Daily features complete
- 12:33-13:33: SIP membership complete
- 16:33-19:33: Intraday features complete
- 16:33-19:33: Validation complete
- 19:33-23:33: Rolling training complete
- 19:33-23:33: Report complete

### Current Status

**Time**: 10:33 SGT
**Step**: Daily Features (batch 1/23)
**Progress**: ~4% (50/1108 symbols)
**ETA**: 12:33-13:33 SGT

---

**Monitor Command**: `./scripts/monitor_rebuild.sh`
**Pipeline PID**: 131564
**Daily Features PID**: 131572
