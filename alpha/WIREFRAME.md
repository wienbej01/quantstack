# Alpha System Wireframe

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ALPHA BACKTESTING SYSTEM                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐         │
│  │   DATA LAYER    │    │  FEATURE LAYER  │    │  SIGNAL LAYER   │         │
│  │                 │    │                 │    │                 │         │
│  │ • Gold 1m OHLCV │───▶│ • L2 Features   │───▶│ • Order Flow    │         │
│  │ • SPY 1m OHLCV  │    │ • Price Features│    │ • Whale Detect  │         │
│  │ • Daily SIP     │    │ • Volume Feats  │    │ • Liquidity Fade│         │
│  │ • L2 Order Book │    │ • Microstructure│    │                 │         │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘         │
│           │                      │                      │                   │
│           ▼                      ▼                      ▼                   │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                      BACKTEST ENGINE                             │       │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │       │
│  │  │ Walk-Forward│  │   Regime    │  │  Execution  │              │       │
│  │  │ Validation  │  │ Stratified  │  │  Simulator  │              │       │
│  │  └─────────────┘  └─────────────┘  └─────────────┘              │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                │                                            │
│                                ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────┐       │
│  │                      METRICS & REPORTING                         │       │
│  │  • Sharpe, Expectancy, Win Rate, Profit Factor                  │       │
│  │  • Per-Regime Performance, Degradation Analysis                 │       │
│  │  • Trade-Level Attribution                                       │       │
│  └─────────────────────────────────────────────────────────────────┘       │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
~/quantstack/alpha/
├── README.md                    # Project overview
├── SPRINT_PLAN.md              # This sprint plan
├── config/
│   └── backtest_config.yaml    # Backtest parameters
├── src/
│   ├── __init__.py
│   ├── data/
│   │   ├── __init__.py
│   │   ├── gold_loader.py      # Load 1m OHLCV from ~/gcs-mount/gold
│   │   ├── sip_loader.py       # Load daily SIP from ~/intraday_stack/data/daily_sip
│   │   └── l2_loader.py        # Load L2 data from ~/quantstack/data/l2
│   ├── features/
│   │   ├── __init__.py
│   │   ├── l2_features.py      # Order book features (extend qx-l2)
│   │   ├── price_features.py   # OHLCV-based features
│   │   └── flow_features.py    # Trade flow features
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── base.py             # Signal interface
│   │   ├── order_flow.py       # H1: Order flow imbalance
│   │   ├── whale_detect.py     # H2: Institutional detection
│   │   └── liquidity_fade.py   # H3: Liquidity vacuum
│   ├── backtest/
│   │   ├── __init__.py
│   │   ├── engine.py           # Main backtest loop
│   │   ├── walk_forward.py     # Walk-forward validation
│   │   ├── regime_split.py     # Regime stratification
│   │   └── execution_sim.py    # Realistic execution model
│   └── metrics/
│       ├── __init__.py
│       ├── performance.py      # Sharpe, expectancy, etc.
│       └── diagnostics.py      # Degradation analysis
├── tests/
│   ├── __init__.py
│   ├── test_data_loaders.py
│   ├── test_features.py
│   ├── test_signals.py
│   ├── test_backtest.py
│   └── test_walk_forward.py
├── scripts/
│   ├── run_hypothesis_test.py  # Test single hypothesis
│   └── run_full_backtest.py    # Full walk-forward backtest
└── output/
    └── (generated results)
```

## Data Sources

| Source | Path | Content | Usage |
|--------|------|---------|-------|
| Gold 1m | `~/gcs-mount/gold/stocks/` | 1m OHLCV bars | Price features, targets |
| SPY 1m | `~/gcs-mount/gold/stocks/SPY/` | SPY 1m bars | Regime detection |
| Daily SIP | `~/intraday_stack/data/daily_sip/` | Daily stock selection | Universe filter |
| L2 Data | `~/quantstack/data/l2/` | Order book snapshots | L2 features |

## Existing Modules to Reuse

| Module | Path | Reuse |
|--------|------|-------|
| qx-l2 | `qx-l2/src/qx_l2/features.py` | L2FeatureEngineer class |
| qx-backtest | `qx-backtest/src/qx_backtest/` | Engine, Portfolio, Fill models |
| qx-data | `qx-data/src/qx_data/` | Data loading utilities |

## Three Hypotheses to Test

### H1: Order Flow Imbalance
```yaml
signal: order_flow_momentum
entry:
  book_imbalance: "> 0.35"
  trade_imbalance: "> 0.25"
  spread_pct: "< 0.05%"
exit:
  target: "+0.4%"
  stop: "-0.25%"
  time_limit: "10 minutes"
horizon: "5-15 minutes"
```

### H2: Whale Following
```yaml
signal: whale_detect
entry:
  large_order: "> 5x avg size"
  direction: "matches recent flow"
  stock_in_play: true
exit:
  target: "+0.8%"
  stop: "-0.4%"
  time_limit: "30 minutes"
horizon: "15-30 minutes"
```

### H3: Liquidity Fade
```yaml
signal: liquidity_fade
entry:
  depth_drop: "> 50%"
  price_spike: "opposite direction"
  no_news: true
exit:
  target: "+0.3%"
  stop: "-0.3%"
  time_limit: "5 minutes"
horizon: "3-10 minutes"
```

## Validation Framework

### Walk-Forward Protocol
```
Period 1: Train Jan-Mar 2024, Validate Apr 2024
Period 2: Train Feb-Apr 2024, Validate May 2024
Period 3: Train Mar-May 2024, Validate Jun 2024
...continue rolling...

Requirement: Profitable in >70% of validation periods
```

### Regime Stratification
```
Regimes:
  - bull_low_vol: SPY > SMA20, VIX < 20
  - bull_high_vol: SPY > SMA20, VIX >= 20
  - bear_low_vol: SPY < SMA20, VIX < 20
  - bear_high_vol: SPY < SMA20, VIX >= 20

Requirement: Works in at least 2 of 4 regimes
```

### Minimum Thresholds
```yaml
sharpe_oos: "> 0.75"
win_rate: "> 52%"
profit_factor: "> 1.2"
t_stat: "> 2.0"
min_trades: 500
```

## Execution Simulation

```python
def simulate_fill(order, book_snapshot, latency_ms=75):
    """
    Realistic fill simulation using L2 data.
    
    - Walk the book for market orders
    - Model latency (50-100ms retail)
    - Calculate slippage from book depth
    - Check if order would have filled
    """
    # Use actual L2 book depth
    fill_price = walk_book(book_snapshot, order.size, order.side)
    slippage = abs(fill_price - mid_price) / mid_price
    
    # Add latency
    execution_delay = latency_ms / 1000
    
    return Fill(price=fill_price, slippage=slippage, delay=execution_delay)
```

## Output Metrics

```yaml
per_hypothesis:
  - sharpe_ratio
  - expectancy
  - win_rate
  - profit_factor
  - avg_win
  - avg_loss
  - max_drawdown
  - n_trades

per_regime:
  - all metrics above, segmented by regime

walk_forward:
  - validation_period_results
  - degradation_analysis
  - consistency_score

execution:
  - avg_slippage
  - fill_rate
  - latency_impact
```
