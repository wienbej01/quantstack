# Pattern Backtest Module

## Overview
Backtest discovered patterns from SIP Pattern Discovery tool using qx-backtest framework.

## Architecture

### Data Flow
```
Discovered Patterns (CSV)
    ↓
Pattern Parser → Rule Evaluator
    ↓
SIP-Filtered Gold Data (1m bars)
    ↓
Feature Computation (same as discovery)
    ↓
Pattern Policy (qx-backtest.Policy)
    ↓
Backtest Engine (qx-backtest.BacktestEngine)
    ↓
Results & Reports (qx-report)
```

### Components

#### 1. Pattern Parser (`src/pattern_parser.py`)
- **Input**: `patterns_60m.csv` from discovery tool
- **Output**: List of `PatternRule` objects
- **Function**: Parse rule strings like `"atr_14_bin == 4 AND is_power_hour_bin == True"` into evaluable conditions

#### 2. Rule Evaluator (`src/rule_evaluator.py`)
- **Input**: `PatternRule` + bar data with features
- **Output**: Boolean (signal triggered or not)
- **Function**: Evaluate discretized feature conditions against current bar

#### 3. Pattern Policy (`src/pattern_policy.py`)
- **Extends**: `qx_backtest.policies.base.Policy`
- **Logic**:
  - Load pattern rules from CSV
  - For each bar: evaluate all rules
  - On signal: submit market order for 100 shares
  - Entry: Open of next bar after signal
  - Exit: Fixed time horizon (60m/120m/180m) or EOD
- **Commission**: $2 per round-turn ($1 entry + $1 exit)

#### 4. Feature Pipeline (`src/feature_pipeline.py`)
- **Reuse**: `sip_pattern_discovery/src/features.py`
- **Function**: Compute same features used in discovery
- **Features**: VWAP, RVOL, ATR, momentum, session anchors, time features
- **Discretization**: Apply same binning (5 bins) as discovery

#### 5. Backtest Runner (`src/backtest_runner.py`)
- **Input**: Pattern CSV, date range, SIP dir, gold dir
- **Process**:
  1. Load SIP-filtered data (same as discovery)
  2. Compute features
  3. Initialize PatternPolicy with rules
  4. Run qx-backtest.BacktestEngine
  5. Generate reports via qx-report
- **Output**: Trades CSV, equity curve, performance metrics

### Integration with Existing Modules

#### qx-backtest Integration
```python
from qx_backtest import BacktestEngine, BacktestConfig
from qx_backtest.policies.base import Policy

class PatternPolicy(Policy):
    def __init__(self, patterns_csv: str):
        super().__init__(name="PatternPolicy")
        self.rules = load_patterns(patterns_csv)
    
    def process_bar(self, bar: dict) -> None:
        # Evaluate rules
        for rule in self.rules:
            if rule.evaluate(bar):
                # Submit order for next bar open
                order = OrderFactory.market_order(
                    symbol=bar["symbol"],
                    quantity=100,
                    side="BUY"
                )
                self.submit_order(order)
```

#### qx-report Integration
```python
from qx_report import generate_summary_report

result = engine.run()
report = generate_summary_report(
    result.trades_history,
    result.equity_curve,
    output_path="output/backtest_report.html"
)
```

### Configuration

#### Backtest Parameters
```yaml
# config/backtest_config.yaml
backtest:
  initial_cash: 1000000
  position_size: 100  # Fixed shares
  commission: 2.0     # $2 round-turn
  slippage: 0.0       # Ignore spread
  
entry:
  timing: "next_bar_open"  # Open of bar after signal
  
exit:
  method: "time_based"
  horizons: [60, 120, 180]  # Minutes
  eod_exit: true
  
patterns:
  source: "../sip_pattern_discovery/output/patterns_60m.csv"
  min_lift: 2.0
  max_patterns: 20  # Test top N patterns
```

### File Structure
```
pattern_backtest/
├── README.md                    # This file
├── src/
│   ├── __init__.py
│   ├── pattern_parser.py        # Parse pattern CSV
│   ├── rule_evaluator.py        # Evaluate rule conditions
│   ├── pattern_policy.py        # qx-backtest Policy implementation
│   ├── feature_pipeline.py      # Feature computation + discretization
│   └── backtest_runner.py       # Main backtest orchestrator
├── config/
│   └── backtest_config.yaml     # Backtest parameters
├── tests/
│   └── test_pattern_policy.py   # Unit tests
├── scripts/
│   └── run_backtest.py          # CLI entry point
└── output/                      # Results directory
    ├── trades.csv
    ├── equity_curve.csv
    ├── performance_metrics.json
    └── backtest_report.html
```

### Usage

#### 1. Run Pattern Discovery (already done)
```bash
cd /home/jacobw/quantstack/sip_pattern_discovery
python3 discover.py --start-date 2024-06-01 --end-date 2024-07-31 --horizons 60,120,180
```

#### 2. Run Backtest on Discovered Patterns
```bash
cd /home/jacobw/quantstack/pattern_backtest
python3 scripts/run_backtest.py \
  --patterns ../sip_pattern_discovery/output/patterns_60m.csv \
  --start-date 2024-06-01 \
  --end-date 2024-07-31 \
  --output-dir output/in_sample

# Out-of-sample test
python3 scripts/run_backtest.py \
  --patterns ../sip_pattern_discovery/output/patterns_60m.csv \
  --start-date 2024-08-01 \
  --end-date 2024-08-31 \
  --output-dir output/out_of_sample
```

#### 3. Compare Results
```bash
python3 scripts/compare_results.py \
  --in-sample output/in_sample \
  --out-of-sample output/out_of_sample
```

### Key Design Decisions

1. **Fixed Position Size**: 100 shares per trade (simple, no position sizing complexity)
2. **Entry Timing**: Open of next bar after signal (realistic, avoids look-ahead bias)
3. **Commission Model**: $2 flat per round-turn (simple, conservative)
4. **No Slippage**: Ignore spread as requested
5. **Exit Strategy**: Time-based (60m/120m/180m) matching discovery horizons
6. **Feature Reuse**: Exact same feature computation as discovery (no train-test leakage)
7. **SIP Filtering**: Use same daily SIP lists as discovery (realistic universe)

### Performance Metrics

The backtest will report:
- **Total Return**: Cumulative P&L
- **Sharpe Ratio**: Risk-adjusted return
- **Win Rate**: % profitable trades
- **Max Drawdown**: Largest peak-to-trough decline
- **Profit Factor**: Gross profit / gross loss
- **Per-Pattern Performance**: Individual rule P&L breakdown
- **Trade Distribution**: By time-of-day, symbol, pattern

### Next Steps

1. ✅ Research qx-backtest and qx-report architecture
2. ✅ Design pattern backtest module
3. ⏳ Implement pattern parser and rule evaluator
4. ⏳ Implement PatternPolicy (qx-backtest integration)
5. ⏳ Implement feature pipeline with discretization
6. ⏳ Implement backtest runner and CLI
7. ⏳ Test on small dataset
8. ⏳ Run full in-sample backtest
9. ⏳ Run out-of-sample validation
10. ⏳ Generate comparative reports

### Dependencies

- `qx-backtest`: Order execution, portfolio management
- `qx-report`: Performance reporting
- `qx-features`: Feature computation (via sip_pattern_discovery)
- `pandas`, `numpy`: Data manipulation
- `pyyaml`: Configuration parsing

### Notes

- Pattern rules are discretized (binned features), so we must apply same binning in backtest
- Each pattern has a specific horizon (60m/120m/180m) - exit timing must match
- SIP universe changes daily - backtest must handle symbol rotation
- Features require lookback (5 days default) - ensure sufficient warmup data
