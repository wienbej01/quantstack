# Alpha System - L2 Order Flow Backtesting

Level 2 Order Flow Alpha Backtesting System for testing three hypotheses:

1. **Order Flow Imbalance** - Book/trade imbalance predicts short-term direction
2. **Whale Following** - Large institutional orders signal informed trading
3. **Liquidity Fade** - Sudden liquidity withdrawal creates mean-reversion opportunity

## Status: System Operational, Multi-Location L2 Support Added

**Last Update:** 2026-03-10
- ✅ Data pipeline: Bronze → Gold conversion working
- ✅ Backtest engine: Runs on all L2 dates
- ✅ L2 loader: Multi-location support (quantstack + quantstack-v2)
- ✅ **100+ symbols** with L2 data across **34 dates**
- ✅ Pre-computed feature support for faster backtesting
- ❌ 0 trades generated - signal thresholds too strict (needs tuning)

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
| Gold 1m | `~/gcs-mount/gold/stocks/` | 1m OHLCV bars | ✅ Through Mar 2026 |
| L2 Data (multi) | `~/quantstack-v2/data/l2/` + `~/quantstack/data/l2/` | Order book snapshots + features | ✅ 34 dates |
| Bronze | `~/gcs-mount/bronze/stocks/` | Raw Polygon data | ✅ Archived |

**L2 Coverage (Combined Locations):**
- **34 unique dates** from 2025-12-19 to 2026-03-09
- **100+ unique symbols** including: ACHR, ACLX, AMPX, BE, CCL, DDOG, F, FCX, GM, HAL, HIMS, INTC, KO, LUV, NVDA, PFE, PLTR, SBUX, SMR, T, VST, XOM, etc.
- **Two data types:**
  - **Raw**: Full order book depth (10 levels bid/ask)
  - **Features**: Pre-computed (obi_1, obi_5, mid, spread, pressure) for faster loading

**L2 Loader automatically tries these sources in order:**
1. `~/quantstack-v2/data/l2/l2_maximum/features` (pre-computed, fastest)
2. `~/quantstack-v2/data/l2/l2_maximum/raw` (full depth, newer)
3. `~/quantstack/data/l2/l2_maximum/raw` (full depth, legacy)

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
2. **Signal Tuning**: Need to analyze L2 data patterns and calibrate thresholds
3. **Date Gaps**: No L2 data for some periods (IBKR symbol limits during collection)

## Recent Enhancements (2026-03-10)

- ✅ **Multi-location L2 support**: Loader now searches both `~/quantstack-v2/data/l2/` and `~/quantstack/data/l2/`
- ✅ **Pre-computed features**: Faster loading when features are available
- ✅ **Expanded coverage**: 34 dates and 100+ symbols vs original 9 dates / 17 symbols
- ✅ **Backward compatibility**: Existing code continues to work unchanged

## Next Steps

1. Relax signal thresholds to generate trades
2. Analyze L2 data patterns to calibrate thresholds
3. Collect more full-day L2 data
4. Validate signal logic with synthetic data

See `SPRINT_PLAN.md` for detailed implementation plan and `VERIFICATION_REPORT.md` for system validation.
