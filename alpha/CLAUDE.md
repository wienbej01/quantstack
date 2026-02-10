# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Level 2 Order Flow Alpha Backtesting System - a research framework for testing three order flow hypotheses using L2 market data and rigorous walk-forward validation.

### Three Hypotheses
1. **Order Flow Imbalance** - Book/trade imbalance predicts short-term direction
2. **Whale Following** - Large institutional orders signal informed trading
3. **Liquidity Fade** - Sudden liquidity withdrawal creates mean-reversion opportunity

## Common Commands

```bash
# Run single hypothesis test
python scripts/run_hypothesis_test.py --hypothesis order_flow --start 2024-01-01 --end 2024-12-31

# Run full backtest
python scripts/run_full_backtest.py --start 2024-01-01 --end 2024-12-31

# Run tests
pytest tests/ -v

# Run specific test
pytest tests/test_features.py::test_book_imbalance_range -v
```

## Architecture

This is a **new project in early development** - the directory structure and `__init__.py` files exist but most implementation files are empty (stubs only). The project is designed to reuse components from sibling `qx-*` modules in the quantstack monorepo.

### Data Pipeline Flow
```
Data Sources (external) → Data Loaders → Features → Signals → Backtest Engine → Metrics
                                                    ↓
                                            Execution Simulator (uses L2)
```

### Module Dependencies (from quantstack sibling repos)
- **qx-l2**: `L2FeatureEngineer` class (`/home/jacobw/quantstack/qx-l2/src/qx_l2/features.py`)
  - Computes: OBI (order book imbalance), depth ratio, microprice, spread, pressure
  - Method: `compute(snapshot: dict, levels: int) -> Optional[dict]`

- **qx-backtest**:
  - `Portfolio` class (`/home/jacobw/quantstack/qx-backtest/src/qx_backtest/portfolio.py`)
  - `Fill` dataclass (`/home/jacobw/quantstack/qx-backtest/src/qx_backtest/fill.py`)
  - `Order` and `OrderSide` enums (`/home/jacobw/quantstack/qx-backtest/src/qx_backtest/order.py`)

### Data Sources (read-only mounts)
| Source | Path | Content |
|--------|------|---------|
| Gold 1m | `~/gcs-mount/gold/stocks/` | 1m OHLCV bars |
| SPY 1m | `~/gcs-mount/gold/stocks/SPY/` | SPY for regime classification |
| Daily SIP | `~/intraday_stack/data/daily_sip/` | Stock universe selection |
| L2 Data | `~/quantstack/data/l2/` | Order book snapshots |

### Directory Structure
```
src/
├── data/          # Data loaders (gold_loader.py, sip_loader.py, l2_loader.py)
├── features/      # L2 (l2_features.py), price (price_features.py), flow (flow_features.py)
├── signals/       # Three hypothesis signals (order_flow.py, whale_detect.py, liquidity_fade.py)
├── backtest/      # Engine (engine.py), walk-forward (walk_forward.py), regime (regime_split.py), execution sim (execution_sim.py)
└── metrics/       # Performance (performance.py), diagnostics (diagnostics.py)

config/
└── backtest_config.yaml  # All parameters for validation, execution, signals, risk

scripts/
├── run_hypothesis_test.py  # Test single hypothesis
└── run_full_backtest.py    # Full pipeline
```

## Signal Interface Pattern

All signals inherit from `base.Signal`:
```python
class Signal(ABC):
    @abstractmethod
    def check_entry(self, features: dict) -> Optional[SignalEvent]

    @abstractmethod
    def check_exit(self, position: Position, features: dict) -> Optional[ExitEvent]
```

## Validation Framework

### Walk-Forward Protocol
- Train 3 months, validate 1 month, roll forward
- Must be profitable in >70% of validation periods

### Regime Stratification
- 4 regimes: bull/bear × high/low vol (based on SPY > SMA20, VIX < 20)
- Must work in at least 2 regimes

### Minimum Thresholds
- Sharpe > 0.75, Win Rate > 52%, Profit Factor > 1.2, t-stat > 2.0, min 500 trades

## Configuration

`config/backtest_config.yaml` contains all parameters organized by section:
- `data.*`: Data source paths
- `validation.*`: Walk-forward and regime settings, thresholds
- `execution.*`: Latency (75ms), slippage model ("book_walk")
- `signals.{order_flow,whale_detect,liquidity_fade}.*`: Entry/exit thresholds
- `risk.*`: Position sizing, exposure limits

## Key Implementation Notes

1. **No synthetic data for performance** - Only real market data from `~/gcs-mount/gold`
2. **L2-based execution simulation** - `execution_sim.py` must walk the order book to calculate realistic slippage
3. **Timezone handling** - All timestamps in UTC, with ET session boundaries
4. **SIP universe filtering** - Daily SIP from intraday_stack provides the stock universe
5. **Reuse qx-backtest components** - Don't reimplement Portfolio/Fill, import from `qx_backtest`

## Sprint Status

This is Sprint 1 of a 6-sprint implementation plan (see SPRINT_PLAN.md). Current directory structure is a skeleton awaiting implementation.
