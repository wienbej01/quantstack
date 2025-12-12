# quantstack

A modular, framework-agnostic trading system with configurable universe selection, backtesting, and experiment orchestration.

## Latest: Fixed ML System Implementation (2025-12-12)

**✅ CRITICAL FIXES IMPLEMENTED: System rebuilt with timezone normalization and clean features**

### The Solution
After comprehensive root cause analysis, all critical issues have been fixed:
- **Timezone normalization**: All data now in consistent ET timestamps
- **Raw price removal**: 0 raw price features (was 24)
- **Time-stratified models**: Separate morning/afternoon models
- **Clean features**: Only relative/normalized features

### Status: SYSTEM REBUILT AND TRAINING
- ✅ Features: 153,696 rows, 49 clean features, 534 symbols
- ✅ Data quality: 76% morning data (vs 0.4% before)
- ✅ Validation: All checks passed
- 🟡 Training: Time-stratified models in progress

### Root Causes Fixed
1. **CRITICAL - Timezone inconsistency**: Mixed UTC/ET data → Normalized to ET
2. **HIGH - Raw price drift**: 24 raw features → 0 raw features  
3. **MEDIUM - ICT implementation**: Enhanced with kill zones, normalized VPA
4. **MEDIUM - Time stratification**: Single model → Morning/afternoon models

### Quick Start: Run Fixed System

```bash
# Run complete fixed pipeline
python scripts/run_fixed_pipeline.py

# Or run individual phases:
python scripts/build_intraday_features_fixed.py    # Phase 1: Clean features
python scripts/validate_fixed_features.py          # Validation
python scripts/rolling_train_fixed.py              # Phase 3: Time-stratified training

# Monitor progress
python scripts/monitor_fixed_pipeline.py

# View results
cat run/rolling_results_fixed/trades.csv
```

**Key Files**:
- [Root Cause Analysis](ROOT_CAUSE_ANALYSIS_DEC12.md) - Complete technical analysis
- [Implementation Status](FINAL_IMPLEMENTATION_STATUS_DEC10.md) - Previous system analysis
- [Pipeline Status](PIPELINE_RUNNING_DEC9.md) - Development log

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
