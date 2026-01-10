# Intraday ML Trading System - Overview

## System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    DATA PIPELINE                            │
├─────────────────────────────────────────────────────────────┤
│  Gold Data (OHLCV) → Feature Engineering → ML Models        │
│       ↓                    ↓                  ↓             │
│  493 symbols         11 cross-sectional   Per-regime        │
│  1-min bars          features             GBM models        │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  REGIME DETECTION                           │
├─────────────────────────────────────────────────────────────┤
│  Market Return (20-bar) → Bull / Bear / Sideways            │
│  Market Volatility      → High Vol / Normal Vol             │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  SIGNAL GENERATION                          │
├─────────────────────────────────────────────────────────────┤
│  Regime-specific model → Probability > threshold → Signal   │
│  Threshold: 0.55 (high vol) / 0.58 (normal)                │
└─────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────┐
│                  POSITION SIZING                            │
├─────────────────────────────────────────────────────────────┤
│  Risk per trade: 1% of equity                               │
│  Vol adjustment: 0.7x in high volatility                    │
│  Max position: 20% of equity                                │
└─────────────────────────────────────────────────────────────┘
```

## Performance Summary

### Validated Results (2023-2024)
| Metric | Value |
|--------|-------|
| Total Return | +29.3% |
| Win Rate | 50.1% |
| Max Drawdown | -18.2% |
| Total Trades | 5,689 |
| Sharpe Ratio | ~0.4 |

### Year-by-Year
| Year | Return | Win Rate | Trades |
|------|--------|----------|--------|
| 2023 | +6.0% | 49.0% | 2,304 |
| 2024 | +21.5% | 50.8% | 3,385 |

## Feature Set (11 Cross-Sectional Features)

```python
FEATURES = [
    "cross_rank_ret",      # Percentile rank of returns vs peers
    "cross_rank_vol",      # Percentile rank of volume vs peers
    "sector_momentum",     # Average return of sector peers
    "cross_dispersion",    # Cross-sectional return dispersion
    "market_breadth",      # Number of active symbols
    "up_down_ratio",       # Fraction of stocks with positive returns
    "rel_strength_5",      # 5-bar relative strength vs market
    "rel_strength_10",     # 10-bar relative strength vs market
    "rel_strength_20",     # 20-bar relative strength vs market
    "market_ret_5",        # 5-bar market return
    "market_ret_10",       # 10-bar market return
]
```

## Universe

- **Total Symbols**: 493
- **NYSE/ARCA**: 287 (58%)
- **NASDAQ**: 201 (41%)
- **ETFs**: 5 (1%)

## Key Files

| File | Description |
|------|-------------|
| `scripts/regime_aware_strategy.py` | Main strategy implementation |
| `scripts/build_500_features_v2.py` | Feature engineering (502 features) |
| `scripts/roll_forward_test.py` | Roll-forward backtesting |
| `run/cross_sectional_features/` | Pre-computed features |
| `run/regime_aware_backtest.csv` | Trade log |

## Configuration

```yaml
# Regime detection
regime:
  trend_lookback: 20        # Bars for trend detection
  vol_lookback: 20          # Bars for volatility detection
  bull_threshold: 0.67      # Percentile for bull market
  bear_threshold: 0.33      # Percentile for bear market
  high_vol_threshold: 0.67  # Percentile for high volatility

# Model
model:
  type: GradientBoostingClassifier
  n_estimators: 50
  max_depth: 3
  learning_rate: 0.1

# Trading
trading:
  signal_threshold_normal: 0.58
  signal_threshold_high_vol: 0.55
  risk_per_trade: 0.01      # 1% of equity
  max_position_pct: 0.20    # 20% of equity
  vol_adjustment: 0.70      # Reduce size in high vol

# Backtesting
backtest:
  train_days: 60
  test_days: 20
  initial_equity: 10000
```

## Run Commands

```bash
# Activate environment
cd /home/jacobw/quantstack
source .venv/bin/activate

# Run regime-aware backtest
python scripts/regime_aware_strategy.py

# Build features
python scripts/build_500_features_v2.py

# Roll-forward test
python scripts/roll_forward_test.py
```
