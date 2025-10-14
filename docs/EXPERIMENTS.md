# Experiments Framework

Comprehensive experimentation framework for QuantStack strategy development, testing, and validation.

## Overview

The experiments framework provides a structured approach to testing trading strategies with reproducible results, fair comparisons, and comprehensive analytics. It supports various experiment types from simple A/B tests to complex workflow orchestration.

## Experiment Types

### 1. Entry/Exit A/B Testing (`entry-ab`)

Compare entry and exit policy variations while keeping all other factors constant.

```bash
# Basic A/B test
qx exp entry-ab \
  --cfg experiments/configs/base_strategy.yaml \
  --variants experiments/overlays/policy_*.yaml \
  --name vwap_revert_ab_test

# With custom parameters
qx exp entry-ab \
  --cfg experiments/configs/base_strategy.yaml \
  --variants experiments/overlays/entry_params.yaml \
  --name entry_timing_test \
  --seed 42
```

**Use Cases:**
- Testing different entry criteria (VWAP reversion, momentum, mean reversion)
- Comparing exit timing strategies (fixed bars, VWAP touch, stop loss)
- Evaluating signal strength thresholds
- Optimizing position sizing parameters

### 2. Risk Grid Analysis (`risk-grid`)

Systematically test risk management parameters across a grid.

```bash
# Risk fraction grid
qx exp risk-grid \
  --cfg experiments/configs/base_strategy.yaml \
  --grid max_risk_frac=0.005,0.01,0.02,0.03 \
  --name risk_fraction_grid

# Multi-parameter grid
qx exp risk-grid \
  --cfg experiments/configs/base_strategy.yaml \
  --grid max_risk_frac=0.01,0.02 atr_mult=1.5,2.0,2.5 \
  --name risk_atr_grid

# Risk with stop loss variants
qx exp risk-grid \
  --cfg experiments/configs/base_strategy.yaml \
  --grid max_risk_frac=0.01,0.02 stop_type=atr,percent,trailing \
  --name comprehensive_risk_grid
```

**Use Cases:**
- Finding optimal risk per trade
- Testing ATR multiplier combinations
- Comparing stop loss methodologies
- Balancing risk vs. reward profiles

### 3. Cost Analysis Sweep (`cost-sweep`)

Evaluate strategy performance across different cost assumptions.

```bash
# Commission and slippage sweep
qx exp cost-sweep \
  --cfg experiments/configs/base_strategy.yaml \
  --grid bps=0.5,1,2 slippage_ticks=0,1,2 \
  --name cost_sensitivity_analysis

# Comprehensive cost analysis
qx exp cost-sweep \
  --cfg experiments/configs/base_strategy.yaml \
  --grid commission_bps=0.5,1,2,3 slippage_bps=0,1,2,5 \
  --name full_cost_impact
```

**Use Cases:**
- Understanding cost sensitivity
- Evaluating strategy robustness to costs
- Setting realistic performance expectations
- Broker selection criteria

### 4. Workflow Orchestration (`wf`)

Execute complex multi-stage experiment workflows.

```bash
# Sequential workflow
qx exp wf \
  --cfg experiments/configs/base_strategy.yaml \
  --plan experiments/workflows/60_20_workflow.yaml \
  --name strategy_60_20_workflow

# Custom workflow
qx exp wf \
  --cfg experiments/configs/base_strategy.yaml \
  --plan experiments/workflows/custom_optimization.yaml \
  --name custom_workflow
```

**Workflow Definition Example:**
```yaml
# experiments/workflows/60_20_workflow.yaml
stages:
  - name: "screening"
    type: "screener"
    params:
      top_n: 100
      metric: "relative_volume"

  - name: "feature_analysis"
    type: "feature_test"
    depends_on: "screening"
    params:
      features: ["core_basics", "vpa_patterns"]

  - name: "strategy_test"
    type: "entry_ab"
    depends_on: "feature_analysis"
    params:
      variants: ["conservative", "aggressive"]
```

**Use Cases:**
- Multi-stage strategy development
- Complex optimization pipelines
- Feature engineering workflows
- End-to-end strategy validation

### 5. Regime Analysis (`regime-slice`)

Test strategy performance across different market regimes.

```bash
# Volatility regime analysis
qx exp regime-slice \
  --cfg experiments/configs/base_strategy.yaml \
  --regimes vol_tercile,session,dow \
  --name regime_volatility_analysis

# Custom regime definition
qx exp regime-slice \
  --cfg experiments/configs/base_strategy.yaml \
  --regimes custom_regime.yaml \
  --name custom_regime_analysis
```

**Regime Types:**
- `vol_tercile`: Volatility-based tertiles (low/medium/high)
- `session`: Trading session (regular/after-hours/pre-market)
- `dow`: Day of week patterns
- `custom`: User-defined regime classifications

**Use Cases:**
- Understanding strategy behavior in different conditions
- Identifying strategy strengths/weaknesses by regime
- Adaptive strategy development
- Risk management by regime

### 6. Portfolio Testing (`portfolio`)

Test multi-asset portfolio strategies and allocation methods.

```bash
# Portfolio A/B test
qx exp portfolio \
  --cfg experiments/configs/portfolio_base.yaml \
  --variants experiments/overlays/portfolio_*.yaml \
  --name portfolio_allocation_test

# Multi-strategy portfolio
qx exp portfolio \
  --cfg experiments/configs/multi_strategy.yaml \
  --variants experiments/overlays/strategy_weights.yaml \
  --name multi_strategy_portfolio
```

**Use Cases:**
- Asset allocation optimization
- Strategy combination testing
- Correlation analysis
- Portfolio risk management

### 7. Comparison Analysis (`compare`)

Generate detailed comparisons between experiment results.

```bash
# Compare experiment results
qx exp compare \
  --exp experiments/vwap_revert_ab_test \
  --output reports/vwap_comparison

# Compare multiple experiments
qx exp compare \
  --exp experiments/risk_grid_test \
  --exp experiments/cost_sweep_test \
  --output reports/comprehensive_analysis
```

**Comparison Metrics:**
- Risk-adjusted returns (Sharpe, Sortino)
- Drawdown analysis
- Win rate and profit factor
- Trade statistics
- Regime-specific performance

## Configuration Structure

### Base Configuration

```yaml
# experiments/configs/base_strategy.yaml
experiment:
  type: "entry_ab"
  description: "Base VWAP reversion strategy"

data_slice:
  gold_root: "/home/jacobw/gcs-mount/gold"
  family: "bars_1m"
  symbols: ["AAPL", "MSFT", "GOOG", "AMZN", "META"]
  dates: ["2024-01-01", "2024-03-31"]

features:
  - type: "core_basics"
    params:
      vwap_window_m: 30
      rel_vol_window_m: 30
      atr_window_m: 14
  - type: "vpa"
    params:
      volume_window_m: 20
      price_window_m: 10

policy:
  name: "vwap_revert"
  base_params:
    rvol_min: 1.0
    max_position_bars: 50
    position_size_pct: 0.1

risk:
  max_risk_frac: 0.02
  atr_mult: 2.0

execution:
  slippage_bps: 1.0
  commission_bps: 0.5

seed: 42
```

### Variant Configuration

```yaml
# experiments/overlays/aggressive_variant.yaml
policy:
  base_params:
    rvol_min: 0.8
    max_position_bars: 30
    position_size_pct: 0.15

risk:
  max_risk_frac: 0.03
  atr_mult: 1.5
```

## Artifacts and Outputs

### Experiment-Level Artifacts

```
experiments/<exp_id>/
├── manifest.json              # Experiment configuration and metadata
├── inputs_checksum.json       # Reproducibility hashes
├── compare.json               # Quantitative comparison results
├── compare.md                 # Human-readable comparison report
└── runs/                      # Individual run directories
    ├── <run_id_1>/
    ├── <run_id_2>/
    └── ...
```

### Run-Level Artifacts

```
runs/<run_id>/
├── signals.parquet            # Trading signals
├── orders.parquet             # Generated orders
├── fills.parquet              # Order executions
├── positions.parquet          # Position tracking
├── equity.parquet             # Equity curve
├── trades.parquet             # Individual trades
├── risk_rejects.parquet       # Rejected trades (risk limits)
├── allocation_log.parquet     # Position allocation decisions
├── metrics.json               # Performance metrics
└── inputs_checksum.json       # Run-specific reproducibility data
```

### Key Artifacts Explained

**manifest.json**
```json
{
  "exp_id": "vwap_revert_ab_test",
  "name": "VWAP Reversion A/B Test",
  "type": "entry_ab",
  "created_at": "2024-01-15T10:30:00Z",
  "data_slice": {
    "gold_root": "/home/jacobw/gcs-mount/gold",
    "symbols": ["AAPL", "MSFT"],
    "dates": ["2024-01-01", "2024-03-31"]
  },
  "run_ids": ["run_abc123", "run_def456"],
  "resolved_config": { /* Merged configuration */ }
}
```

**inputs_checksum.json**
```json
{
  "bars_norm_hash": "a1b2c3d4e5f67890",
  "features_hash": "b2c3d4e5f67890a1",
  "sip_hash": "c3d4e5f67890a1b2",
  "config_hash": "d4e5f67890a1b2c3",
  "seed": 42,
  "model_hash": "e5f67890a1b2c3d4"  // For ML experiments
}
```

**metrics.json**
```json
{
  "trades": 156,
  "avg_R": 0.85,
  "sharpe_CI_high": 1.45,
  "sharpe_CI_low": 0.92,
  "win_rate": 0.62,
  "total_pnl": 12500.0,
  "max_drawdown": 0.08,
  "total_return": 0.15,
  "avg_trade_pnl": 80.13,
  "ES_95": -250.0,
  "policy": "vwap_revert_aggressive",
  "risk_config": {
    "max_risk_frac": 0.03,
    "atr_mult": 1.5
  }
}
```

## Reproducibility and Fair Comparison

### Reproducibility Guarantees

1. **Deterministic Hashing**: All inputs are hashed for exact reproducibility
2. **Fixed Seeds**: Random seeds control all stochastic processes
3. **Stable Sorting**: Data sorting ensures consistent processing order
4. **Version Control**: Code and configuration versions tracked

### Fair Comparison Rules

For A/B comparisons, the following must be identical across variants:

```json
{
  "identical_components": [
    "bars_norm_hash",    // Same input data
    "features_hash",     // Same feature engineering
    "sip_hash",         // Same universe screening
    "seed"              // Same random seed
  ],
  "varying_components": [
    "config_hash"       // Only policy/risk parameters differ
  ]
}
```

### Override Mechanisms

```bash
# Force comparison with different inputs (not recommended)
qx exp compare \
  --exp experiments/test_1 \
  --exp experiments/test_2 \
  --force

# Compare with tolerance for minor differences
qx exp compare \
  --exp experiments/test_1 \
  --exp experiments/test_2 \
  --tolerance 0.01
```

## Best Practices

### Experiment Design

1. **Start Simple**: Begin with basic A/B tests before complex workflows
2. **Isolate Variables**: Change only one parameter at a time
3. **Sufficient Data**: Use adequate time periods for statistical significance
4. **Control Environment**: Keep non-test parameters constant

### Sample Size and Statistics

```bash
# Power analysis for trade count
python scripts/calculate_sample_size.py \
  --expected_win_rate 0.55 \
  --min_detectable_edge 0.02 \
  --confidence 0.95
```

### Multiple Testing Correction

When running many variants, apply statistical corrections:

```yaml
# Multiple testing configuration
statistics:
  correction_method: "bonferroni"  # or "benjamini_hochberg"
  significance_level: 0.05
  min_trades_per_variant: 50
```

### Documentation Standards

1. **Clear Naming**: Use descriptive experiment and variant names
2. **Comprehensive Configs**: Document all parameters and rationale
3. **Results Logging**: Maintain detailed experiment logs
4. **Version Control**: Track all configuration changes

## Analysis and Reporting

### Automated Report Generation

```bash
# Generate comprehensive report
qx exp report \
  --exp experiments/vwap_revert_ab_test \
  --format html \
  --output reports/vwap_analysis.html

# Quick summary
qx exp summary \
  --exp experiments/risk_grid_test \
  --metric sharpe_ratio
```

### Custom Analysis

```python
# Python API for custom analysis
from qx_report.analysis import ExperimentAnalyzer

analyzer = ExperimentAnalyzer("experiments/vwap_revert_ab_test")
results = analyzer.compare_variants()
analyzer.plot_equity_curves()
analyzer.generate_risk_report()
```

## Troubleshooting

### Common Issues

**Reproducibility Failures**
```bash
# Check hash mismatches
qx exp validate \
  --exp experiments/test_experiment \
  --check-hashes

# Regenerate missing hashes
qx exp repair \
  --exp experiments/test_experiment \
  --regenerate-hashes
```

**Performance Issues**
```bash
# Profile experiment execution
qx exp profile \
  --cfg experiments/configs/test.yaml \
  --detailed

# Optimize for speed
qx exp run \
  --cfg experiments/configs/test.yaml \
  --parallel-workers 4
```

**Data Issues**
```bash
# Validate data slice
qx exp validate-data \
  --cfg experiments/configs/test.yaml

# Check data quality
qx exp data-quality \
  --gold-root /home/jacobw/gcs-mount/gold \
  --symbols AAPL,MSFT \
  --dates 2024-01-01,2024-01-31
```

This experiments framework provides a robust foundation for systematic strategy development and validation with strong reproducibility guarantees and comprehensive analysis capabilities.
