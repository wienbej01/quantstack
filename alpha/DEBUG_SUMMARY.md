# Alpha System Debug Summary - 2026-01-21

## System Status: Operational but No Trades Generated

### Data Pipeline ✅
- Bronze → Gold conversion: Working
- 17 symbols with L2 data loaded
- 9,340 bars across 9 trading dates
- L2 data: 45,758 snapshots for HAL on Dec 23 (full day)

### Bugs Fixed ✅
1. **Spread Calculation**: Added bid_px_1/ask_px_1 support in L2 feature engineer
2. **L2 Snapshot Matching**: Fixed timezone mismatch (ET bars vs UTC L2 timestamps)
3. **Symbol Selection**: Changed from SIP-based to L2-based symbol filtering

### Verified Working ✅
- L2 data has valid prices (bid_px_1: 28.34, ask_px_1: 28.43)
- Features compute correctly (spread: 0.09, book_imbalance: -0.27)
- Signal thresholds are met in raw data (16.5% of snapshots have |imbalance| > 0.20)

### Root Cause: Unknown ❌

Despite all fixes, 0 trades generated. Possible remaining issues:

1. **trade_imbalance_5 feature missing**: Signal requires BOTH book_imbalance AND trade_imbalance, but trade imbalance may not be computed
2. **L2 snapshot still not loading**: The timezone fix may not work if bars are already tz-aware
3. **Signal logic bug**: The check_entry() method may have additional conditions not being met

### Next Steps

1. Add debug logging to engine to verify L2 snapshots are actually loaded
2. Check if trade_imbalance_5 feature is being computed
3. Add logging to signal.check_entry() to see why conditions fail
4. Test with synthetic data to isolate signal logic from data issues

### Files Modified

- `/home/jacobw/quantstack/alpha/src/features/l2_features.py` - Added spread calculation
- `/home/jacobw/quantstack/alpha/src/backtest/engine.py` - Fixed L2 snapshot matching
- `/home/jacobw/quantstack/alpha/scripts/run_full_backtest.py` - Changed to L2-based symbol selection
- `/home/jacobw/quantstack/alpha/README.md` - Updated documentation

### Threshold Matrix Results

All 9 threshold combinations (3 per hypothesis × 3 hypotheses) generated 0 trades, confirming this is not a calibration issue.

### Recommendation

The system infrastructure is working. The issue is either:
- A subtle bug in signal generation logic
- Missing features (trade_imbalance)
- L2 snapshots still not being matched to bars

Requires step-by-step debugging with print statements in the engine's bar processing loop to see exactly what's happening.
