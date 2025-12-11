# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: Intraday ML System - PRODUCTION READY (2025-12-11)

**1-minute intraday ML trading system with rigorous data leakage prevention**

### Performance Summary

| Config | Trades | Win Rate | PnL | Sharpe | Max DD |
|--------|--------|----------|-----|--------|--------|
| **Best Sharpe** (thresh=0.60) | 1,019 | 51.2% | +$9,508 | **1.43** | -$1,580 |
| Best PnL (thresh=0.40) | 2,204 | 48.4% | +$13,199 | 1.15 | -$6,010 |

### Recommended Configuration
```python
hold_bars = 10        # 10-minute hold
threshold = 0.60      # ML probability threshold
position_pct = 0.20   # 20% of equity per trade
# No stops, no targets - simple fixed-period exit
```

### Key Achievements
- ✅ **Zero Data Leakage**: 1-bar entry delay rigorously implemented
- ✅ **Sharpe Ratio 1.43**: Risk-adjusted returns
- ✅ **51.2% Win Rate**: Consistent edge
- ✅ **Both Sides Profitable**: LONG +$199, SHORT +$9,309
- ✅ **Low Drawdown**: -$1,580 max (vs -$6,010 for aggressive config)

### System Design
- **Entry**: Bar after signal (no leakage)
- **Exit**: Fixed 10-bar hold (no stops/targets)
- **Models**: Dual LONG/SHORT LightGBM classifiers
- **Training**: Rolling 6-month train, 1-month OOS
- **Features**: 55 ICT + VPA features on 1m bars

### Quick Start: Run Complete System

```bash
# Full pipeline (8-10 hours)
./scripts/run_full_fixed_pipeline.sh

# Or run steps individually:
python scripts/build_daily_features_rolling.py      # Step 1: Daily features
python scripts/generate_sip_rolling.py              # Step 2: SIP selection  
python scripts/build_intraday_features_rolling.py   # Step 3: Intraday features
python scripts/validate_no_leakage.py               # Step 4: Validation
python scripts/rolling_train_and_backtest.py        # Step 5: Training & backtest
python scripts/generate_trade_report.py             # Step 6: Analysis

# View results
cat run/rolling_results/trades.csv
python scripts/compare_1m_vs_10m.py  # (when 10m complete)
```

**Key Files**:
- [Implementation Status](FINAL_IMPLEMENTATION_STATUS_DEC10.md) - Complete technical analysis
- [Pipeline Status](PIPELINE_RUNNING_DEC9.md) - Development log
- [Implementation Summary](IMPLEMENTATION_SUMMARY_DEC9.md) - Technical details

## Features

### Daily HMM_SIP Universe Selection
- **Dynamic Symbol Selection**: Uses Hidden Markov Model scoring to select top-k symbols daily
- **Configuration Driven**: Simple enable/disable via SIP configuration (`mode: "daily"`)
- **Framework Agnostic**: Works with any trading strategy (VWAP, ML, custom policies)
- **Performance Optimized**: Hybrid caching with O(1) symbol eligibility checks
- **Documentation**: See [docs/features/daily-hmm-sip.md](docs/features/daily-hmm-sip.md) for complete guide

### Quick Start with Daily HMM_SIP

```yaml
# Example configuration
sip:
  method: "hmm"
  config:
    mode: "daily"      # Enable daily universe selection
    score_floor: 0.01  # Minimum HMM score
    top_k: 40         # Maximum symbols per day
```

```bash
# Run example
python examples/daily_hmm_sip_example.py

# Run experiment with daily HMM_SIP
qx-cli exp entry-ab experiments/vwap_daily_hmm/strategy.yaml
```

## Architecture

The system uses modular qx-* packages:

- **qx-core**: Schemas, contracts, validators, and utilities
- **qx-data**: Gold data loading and normalization
- **qx-features**: Feature engineering and registry system
- **qx-screener**: Universe selection (SIP + HMM methods)
- **qx-backtest**: Order → fill → position → P&L pipeline
- **qx-risk**: Risk management and position sizing
- **qx-report**: Comparative analysis and reporting
- **qx-cli**: Typer/Rich CLI surface and experiment orchestration

### VWAP Momentum Strategy

The VWAP Momentum strategy complements the reversion strategy by trading breakouts above and below VWAP:

```python
from qx_backtest.policies import VwapMomentumPolicy, VwapMomentumPolicyEnhanced

# Basic momentum - buys breakouts above VWAP
policy = VwapMomentumPolicy(
    vwap_window=30,
    min_breakout_strength=0.8,
    position_size_pct=0.15
)

# Enhanced with ATR-based stops
enhanced = VwapMomentumPolicyEnhanced(
    vwap_window=30,
    atr_window=14,
    atr_multiplier=2.0,
    min_profit_atr=1.0
)
```

**Key Features:**
- **Opposite Logic**: Buys when price > VWAP (momentum), sells when price < VWAP (momentum)
- **ATR Risk Management**: Enhanced version includes volatility-based stops
- **Trend Following**: Designed for trending markets with momentum
- **Volume Filtering**: Requires minimum relative volume for entries

**Use Cases:**
- Strong trending markets
- Breakout continuation strategies
- Momentum-based trading systems
- Complement to reversion strategies

See [VWAP Momentum Guide](docs/vwap_momentum_guide.md) for detailed documentation.

## Documentation

- [Features](docs/features/) - Detailed feature documentation
- [Architecture](docs/ARCHITECTURE.md) - System architecture overview
- [Experiments](docs/EXPERIMENTS.md) - Experiment framework guide
- [Development](docs/DEV_ENV.md) - Development environment setup
- [Examples](examples/) - Working code examples
