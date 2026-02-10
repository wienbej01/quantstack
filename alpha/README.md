# Alpha System - L2 Order Flow Backtesting

Level 2 Order Flow Alpha Backtesting System for testing three hypotheses:

1. **Order Flow Imbalance** - Book/trade imbalance predicts short-term direction
2. **Whale Following** - Large institutional orders signal informed trading
3. **Liquidity Fade** - Sudden liquidity withdrawal creates mean-reversion opportunity

## Status: System Operational, Signal Tuning Required

**Last Run:** 2026-01-21
- ✅ Data pipeline: Bronze → Gold conversion working
- ✅ Backtest engine: Runs on all L2 dates
- ✅ 17 symbols with L2 data processed
- ✅ 9 trading dates (Dec 23, Jan 8-9, 13-16, 19-20)
- ❌ 0 trades generated - signal thresholds too strict

## Quick Start

```bash
# Run full backtest on all L2 dates
cd ~/quantstack/alpha
python scripts/run_full_backtest.py --start 2025-12-23 --end 2026-01-20

# Run single hypothesis test
python scripts/run_hypothesis_test.py --hypothesis order_flow --start 2025-12-23 --end 2026-01-20

# Run tests
pytest tests/ -v
```

## Data Pipeline

### 1. Download from Polygon
```bash
cd ~/data_download
source .venv/bin/activate
export POLYGON_API_KEY='your_key'
python download_l2_tickers.py  # Downloads Dec 16 - Jan 19 for L2 symbols
```

### 2. Bronze → Gold Migration
```bash
cd ~/data_download
python fix_migration.py  # Converts all bronze to gold with checkpoint/resume
```

### 3. Data Sources

| Source | Path | Content | Status |
|--------|------|---------|--------|
| Gold 1m | `~/gcs-mount/gold/stocks/` | 1m OHLCV bars | ✅ Through Jan 20 |
| L2 Data | `~/quantstack/data/l2_maximum/raw/` | Order book snapshots | ✅ 9 dates |
| Bronze | `~/gcs-mount/bronze/stocks/` | Raw Polygon data | ✅ Archived |

**L2 Coverage:**
- Dec 23: 390 minutes (full day) - 3 symbols (HAL, LUV, PFE)
- Jan 8-9, 13-16, 19-20: 338-390 minutes each - 2-3 symbols per day
- Total: 17 unique symbols with L2 data

## Signal Configuration

Current thresholds (in `config/backtest_config.yaml`):

```yaml
order_flow:
  book_imbalance_threshold: 0.35    # 35% bid/ask imbalance
  trade_imbalance_threshold: 0.25   # 25% buy/sell imbalance
  max_spread_pct: 0.05              # 0.05% max spread
  
whale_detect:
  large_order_multiplier: 5.0       # 5x average order size
  min_relative_volume: 1.5          # 1.5x normal volume
  min_flow_imbalance: 0.1           # 10% flow imbalance
  
liquidity_fade:
  depth_drop_threshold: 0.50        # 50% depth drop
  price_spike_pct: 0.002            # 0.2% price spike
```

**Note:** These thresholds are currently too strict - no trades generated. Requires tuning.

## Validation Framework

- **Date Selection**: Only runs on dates with L2 data (no continuous date requirement)
- **Symbol Selection**: Automatically filters to symbols with both L2 and Gold data
- **Minimum Thresholds**: Sharpe > 0.75, Win Rate > 52%, Profit Factor > 1.2, Min Trades > 500

## Project Structure

```
alpha/
├── config/backtest_config.yaml    # Signal parameters
├── src/
│   ├── data/                      # Gold, L2, SIP loaders
│   ├── features/                  # L2 + price features
│   ├── signals/                   # 3 hypothesis signals
│   ├── backtest/                  # Engine + execution sim
│   └── metrics/                   # Performance metrics
├── tests/                         # 92 tests (all passing)
├── scripts/
│   ├── run_full_backtest.py      # Main entry point
│   └── run_hypothesis_test.py    # Single hypothesis
└── output/                        # Results + reports
```

## Known Issues

1. **Zero Trades**: Signal thresholds too strict for current L2 data patterns
2. **Sparse L2 Coverage**: Only 9 dates with L2 data (IBKR 3-symbol limit)
3. **Date Gaps**: No L2 data for Jan 2-7, 10-12, 17-18

## Next Steps

1. Relax signal thresholds to generate trades
2. Analyze L2 data patterns to calibrate thresholds
3. Collect more full-day L2 data
4. Validate signal logic with synthetic data

See `SPRINT_PLAN.md` for detailed implementation plan and `VERIFICATION_REPORT.md` for system validation.
