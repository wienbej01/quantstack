# VWAP Momentum Breakout Strategy Guide

## Overview

The VWAP Momentum strategy is the complement to the VWAP Reversion strategy. Instead of buying dips below VWAP and selling rallies above VWAP, the momentum strategy buys breakouts above VWAP and sells breakdowns below VWAP.

This strategy is designed for trending markets where price tends to continue moving in the direction of the breakout, rather than reverting to the mean.

## Strategy Logic

### Entry Signals
- **Long Entry**: Price closes above VWAP AND relative volume >= minimum AND breakout strength >= threshold
- **Short Entry**: Price closes below VWAP AND relative volume >= minimum AND breakdown strength >= threshold

### Exit Signals
- **Long Exit**: Price closes at or below VWAP OR timeout after maximum bars
- **Short Exit**: Price closes at or above VWAP OR timeout after maximum bars

## Parameters

### Basic Parameters
- `vwap_window`: VWAP lookback period in minutes (default: 30)
- `min_rvol`: Minimum relative volume for entry (default: 1.0)
- `max_position_bars`: Maximum bars to hold position (default: 50)
- `position_size_pct`: Position size as % of equity (default: 0.1)
- `max_positions`: Maximum concurrent positions (default: 5)
- `min_breakout_strength`: Minimum breakout strength % (default: 0.5)

### Enhanced Parameters (ATR-based)
- `atr_window`: ATR lookback period for volatility calculation (default: 14)
- `atr_multiplier`: Stop loss distance as ATR multiple (default: 2.0)
- `min_profit_atr`: Minimum profit target in ATR multiples (default: 0.5)

## Usage

### Basic Momentum Policy

```python
from qx_backtest.policies import VwapMomentumPolicy

# Basic momentum policy
policy = VwapMomentumPolicy(
    vwap_window=30,
    min_breakout_strength=0.8,
    position_size_pct=0.15,
    max_positions=3
)
```

### Enhanced Policy with ATR Stops

```python
from qx_backtest.policies import VwapMomentumPolicyEnhanced

# Enhanced policy with ATR-based risk management
policy_enhanced = VwapMomentumPolicyEnhanced(
    vwap_window=30,
    min_breakout_strength=0.8,
    atr_window=14,
    atr_multiplier=2.0,
    min_profit_atr=1.0,
    position_size_pct=0.15
)
```

### Configuration-Based Usage

```yaml
# strategy.yaml
policy:
  type: "VwapMomentum"
  params:
    vwap_window: 30
    min_rvol: 1.2
    min_breakout_strength: 0.7
    max_position_bars: 40
    position_size_pct: 0.1
    max_positions: 5
```

## Enhanced Version Features

The enhanced version adds sophisticated risk management:

### ATR-Based Stop Losses
- Dynamic stop loss placement based on market volatility
- Stop loss distance = `entry_price ± (ATR × atr_multiplier)`

### Volatility Filtering
- Avoids entries during extreme volatility periods
- Reduces position size during high volatility
- Volatility ratio = `ATR / price`

### Profit Targets
- Minimum profit target = `entry_price ± (ATR × min_profit_atr)`
- Ensures trades have sufficient profit potential relative to risk

## Comparison with VWAP Reversion

| Aspect | VWAP Reversion | VWAP Momentum |
|--------|----------------|---------------|
| **Entry Logic** | Price < VWAP (buy dip) | Price > VWAP (buy breakout) |
| **Exit Logic** | Price ≥ VWAP (take profit) | Price ≤ VWAP (stop) |
| **Market Type** | Range-bound, mean-reverting | Trending, momentum |
| **Risk Profile** | Quick profits, frequent trades | Larger moves, fewer trades |
| **Best Conditions** | Sideways markets, oscillations | Strong trends, breakouts |
| **Stop Loss** | Below entry (long) | ATR-based dynamic |
| **Profit Target** | VWAP level | ATR-based or VWAP |

## When to Use Each Strategy

### VWAP Momentum - Use When:
- Market is in a strong trend
- Breakouts tend to continue
- Volume supports price moves
- You want to ride momentum

### VWAP Reversion - Use When:
- Market is range-bound
- Price tends to return to VWAP
- Mean reversion patterns dominate
- You want to fade extremes

## Performance Considerations

### Momentum Strategy Strengths:
- Captures large trending moves
- Benefits from volatility expansion
- Can generate significant profits in strong trends
- Fewer, higher-quality trades

### Momentum Strategy Weaknesses:
- Can suffer in choppy/sideways markets
- Risk of buying at trend tops
- Requires wider stop losses
- May have lower win rate but higher average win

## Risk Management Tips

1. **Position Sizing**: Use smaller position sizes due to higher volatility
2. **Stop Losses**: Always use ATR-based stops in trending markets
3. **Profit Targets**: Take partial profits at key levels
4. **Market Regime**: Switch to reversion strategy in sideways markets
5. **Volume Confirmation**: Require high volume for breakouts

## Troubleshooting

### No Trades Generated?
- Check if `min_breakout_strength` is too high
- Verify `min_rvol` threshold isn't too restrictive
- Ensure sufficient volatility in the test period
- Confirm VWAP window is appropriate for timeframe

### Too Many Trades?
- Increase `min_breakout_strength` threshold
- Raise `min_rvol` requirement
- Reduce `max_positions` limit
- Consider using enhanced version with ATR filters

### Large Losses?
- Decrease `position_size_pct`
- Use enhanced version with ATR stops
- Reduce `max_position_bars` timeout
- Add volatility filters

## Integration Examples

### Backtest Integration
```python
from qx_backtest.engine import BacktestEngine
from qx_backtest.policies import VwapMomentumPolicy

# Create engine and policy
engine = BacktestEngine()
policy = VwapMomentumPolicy(vwap_window=30, min_breakout_strength=0.6)
engine.set_policy(policy)

# Run backtest
results = engine.run(bars_with_features)
print(f"Generated {len(results['trades'])} trades")
```

### Experiment Framework
```python
# Using the experiment framework
from qx_cli.experiments.entry_ab import run_experiment

results = run_experiment(
    base_config="experiments/vwap_momentum_test/strategy.yaml",
    variants=["momentum_overlay.yaml"]
)
```

## Advanced Configuration

### Multi-Timeframe Strategy
```python
# Combine different VWAP windows
fast_momentum = VwapMomentumPolicy(vwap_window=15, min_breakout_strength=0.3)
slow_momentum = VwapMomentumPolicy(vwap_window=60, min_breakout_strength=0.8)
```

### Adaptive Parameters
```python
# Adjust parameters based on market conditions
class AdaptiveMomentumPolicy(VwapMomentumPolicy):
    def process_bar(self, bar):
        # Adjust breakout strength based on volatility
        atr = bar.get('f__vol__atr_14', 0)
        if atr > 0:
            volatility_ratio = atr / bar['close']
            self.min_breakout_strength = 0.5 + volatility_ratio * 2

        super().process_bar(bar)
```

This documentation provides comprehensive guidance for using the VWAP momentum breakout strategy effectively in various market conditions.