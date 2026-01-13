# BACKTESTING ENGINE

## Responsibilities
- Consume signals → generate orders → simulate fills → update positions → compute PnL.
- Emit standardized parquet and json artifacts (see Experiments doc).

## Requirements
- Deterministic with a given config and seed.
- No data lake writes; read Gold only (or sample) for smoke/integration tests.

## Core Components

The backtesting engine is located in the `qx-backtest` module. The main class is `BacktestEngine`.

*   **`BacktestEngine`**: The main engine class that orchestrates the backtest. It takes a `BacktestConfig` object in its constructor.
*   **`BacktestConfig`**: A dataclass that holds configuration for the backtest, such as initial cash, start/end dates, and a `filler` object.
*   **`Filler`**: The `filler` object is responsible for simulating order fills. `DefaultFiller` is the default implementation, which supports configurable slippage and commissions.
*   **`OrderFactory`**: A factory class for creating `Order` objects.

## Usage

The `BacktestEngine` is designed to be used with a `strategy_func`.

```python
from qx_backtest.engine import BacktestEngine, BacktestConfig
from qx_backtest.fill import DefaultFiller

def my_strategy(engine, bar):
    # Your trading logic here
    # e.g., engine.submit_order(...)
    pass

# Configure the backtest
bt_config = BacktestConfig(
    initial_cash=100000.0,
    filler=DefaultFiller(slippage_bps=5),
)

# Instantiate the engine
engine = BacktestEngine(bt_config)

# Run the backtest
results = engine.run(data, my_strategy)
```

The `strategy_func` is called for each bar of data and receives the `engine` instance and the current `bar` as arguments. This function is where you implement your trading logic, such as generating signals and submitting orders using `engine.submit_order()`.
