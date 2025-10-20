# qx-backtest

Event-driven backtesting engine and entry/exit AB testing framework for QuantStack.

## Overview

qx-backtest provides a comprehensive backtesting framework with:

- **Event-driven engine** for realistic order execution simulation
- **Portfolio management** with position tracking and P&L calculation
- **Order management** with multiple order types and execution logic
- **Fill simulation** with realistic slippage and commission models
- **Trading policies** including VWAP revert strategy
- **AB testing framework** for systematic strategy optimization
- **Performance analysis** with comprehensive metrics

## Features

### Core Engine
- Event-driven backtesting architecture
- Realistic order execution simulation
- Portfolio and position management
- Configurable fill simulation (slippage, commission)
- Performance metrics calculation

### Trading Policies
- VWAP revert policy with configurable parameters
- Enhanced policy with ATR-based stops
- Extensible policy framework for custom strategies

### AB Testing Framework
- Entry/exit variant testing
- Statistical significance analysis
- Combination optimization
- Comprehensive reporting

## Quick Start

### Basic Backtest

```python
from qx_backtest.engine import BacktestEngine, BacktestConfig
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
import pandas as pd

# Load your data with features
data = pd.read_csv('your_data.csv')  # Must have ts, symbol, OHLCV + features

# Create configuration
config = BacktestConfig(initial_cash=1_000_000.0)

# Create engine and add policy
engine = BacktestEngine(config)
policy = VwapRevertPolicy(
    vwap_window=30,
    min_rvol=1.0,
    max_position_bars=50,
    position_size_pct=0.1
)
engine.add_policy(policy)

# Define strategy function
def strategy_func(engine, bar):
    # Policy will process bars automatically
    pass

# Run backtest
result = engine.run(data, strategy_func)

# View results
print(f"Total Return: {result.total_return:.2%}")
print(f"Sharpe Ratio: {result.sharpe_ratio:.2f}")
print(f"Max Drawdown: {result.max_drawdown:.2%}")
```

### AB Testing

```python
from qx_backtest.ab_testing import EntryExitABTest, create_default_ab_test_config

# Create AB test configuration
config = create_default_ab_test_config()

# Create and run AB test
ab_test = EntryExitABTest(config)
result = ab_test.run_tests(data)

# Generate report
report = ab_test.generate_report(result)
print(report)

# Get best configurations
print(f"Best Entry: {result.best_entry}")
print(f"Best Exit: {result.best_exit}")
```

## Data Requirements

Your data must include:

### Required Columns
- `ts`: UTC nanosecond timestamps
- `symbol`: Symbol identifier
- `open`, `high`, `low`, `close`: OHLC prices
- `volume`: Trading volume

### Feature Columns (for VWAP policy)
- `f__ta__vwap_{window}`: VWAP values (e.g., `f__ta__vwap_30`)
- `f__vol__rel_volume_{window}`: Relative volume (e.g., `f__vol__rel_volume_30`)
- `f__vol__atr_{window}`: ATR values (e.g., `f__vol__atr_14`)
- `f__warmup_ok`: Boolean indicating feature warmup status

## Configuration

### BacktestConfig
```python
config = BacktestConfig(
    initial_cash=1_000_000.0,      # Starting capital
    benchmark="SPY",               # Benchmark for comparison
    filler=DefaultFiller(),         # Fill simulation engine
    show_progress=True,             # Show progress during backtest
)
```

### VWAP Policy Parameters
- `vwap_window`: VWAP lookback window (default: 30)
- `min_rvol`: Minimum relative volume for entry (default: 1.0)
- `max_position_bars`: Maximum bars to hold position (default: 50)
- `position_size_pct`: Position size as % of equity (default: 0.1)
- `max_positions`: Maximum concurrent positions (default: 5)

## Performance Metrics

The engine calculates comprehensive performance metrics:

### Return Metrics
- Total return
- Annualized return
- Volatility
- Sharpe ratio

### Risk Metrics
- Maximum drawdown
- Drawdown duration

### Trading Metrics
- Win rate
- Profit factor
- Average trade P&L
- Win/loss averages

## Order Types

Supported order types:
- **Market Orders**: Immediate execution at current price
- **Limit Orders**: Execute at specified price or better
- **Stop Orders**: Trigger when price crosses stop level
- **Stop Limit**: Combination of stop and limit orders

## Fill Simulation

Realistic fill simulation includes:
- **Slippage**: Price impact based on order size and volatility
- **Commission**: Per-share and minimum commission structures
- **Partial Fills**: Realistic fill rate modeling
- **Fill Probability**: Market order execution probability

## Testing

Run tests with:

```bash
pytest tests/test_s5_backtest_basic.py -v
```

## Integration with QuantStack

qx-backtest integrates seamlessly with other QuantStack packages:

- **qx-features**: For technical indicator computation
- **qx-screener**: For universe selection
- **qx-data**: For data loading
- **qx-core**: For shared types and utilities

## Examples

See the `tests/` directory for comprehensive usage examples including:

- Basic backtesting workflows
- Policy implementation patterns
- AB testing configurations
- Performance analysis techniques