# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: Rolling Training System (2025-12-07)

**Intraday ML trading system with 6-month rolling training windows**

- **Universe**: 505 symbols (full gold universe)
- **Features**: 30 ICT + VPA features (FVG, displacement, order blocks, VWAP, pressure ratio)
- **Performance**: 66.4% win rate, +1,554% P&L (6-month baseline)
- **Rolling**: 20 OOS months (2024-02 to 2025-09), monthly retraining
- **Expected**: 60-65% win rate, +4,000-5,000% P&L over 20 months

See [ROLLING_TRAINING_STRATEGY.md](ROLLING_TRAINING_STRATEGY.md) for details.

### Quick Start: Rolling Training

```bash
# Run full pipeline (4-6 hours)
./scripts/run_rolling_pipeline.sh

# Or run steps individually:
python scripts/build_daily_features_rolling.py      # Step 1: Daily features
python scripts/generate_sip_rolling.py              # Step 2: SIP selection
python scripts/build_intraday_features_rolling.py   # Step 3: Intraday features
python scripts/rolling_train_and_backtest.py        # Step 4: Rolling training
python scripts/analyze_rolling_results.py           # Step 5: Analysis

# View results
cat run/rolling_results/metrics.csv
cat run/rolling_results/analysis_report.txt
```

**Documentation**:
- [Rolling Training Strategy](ROLLING_TRAINING_STRATEGY.md) - Overview and rationale
- [Technical Documentation](docs/ROLLING_TRAINING_TECHNICAL.md) - Detailed specifications
- [Implementation Status](ROLLING_IMPLEMENTATION_STATUS.md) - Current status
- [Session Summary](SESSION_2025_12_07_SUMMARY.md) - Development log

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
