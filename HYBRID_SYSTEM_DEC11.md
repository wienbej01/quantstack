# Hybrid ML + ATR Stops System - December 11, 2025

## System Overview

**Approach**: ML predicts direction/timing, backtest applies ATR-based stops/targets with time exit backup.

## ⭐ RECOMMENDED Configuration

```python
# ML Parameters
threshold = 0.60          # Probability threshold for signals

# Risk Management  
atr_stop_mult = 3.0       # Stop = 3x ATR from entry (wider stops)
r_target = 2.0            # Take profit = 2R (2x stop distance)
max_hold_bars = 60        # Maximum hold = 60 minutes

# Position Sizing - USE FIXED, NOT PERCENTAGE
risk_per_trade = 200      # Fixed $200 risk per trade ⭐ RECOMMENDED
# risk_pct = 0.02         # DON'T USE - causes 87% drawdowns
```

## Why Fixed Sizing?

| Metric | % Sizing (2%) | Fixed ($200) |
|--------|---------------|--------------|
| Sharpe | 0.24 | **0.67** |
| Max DD | -87% | **-50%** |
| PnL | $13,284 | $10,504 |

Percentage sizing compounds losses during drawdowns, creating a death spiral.

## Performance Summary (26 months: Aug 2023 - Sep 2025)

### Fixed Position Sizing ($200 risk/trade) - RECOMMENDED

| Metric | Value |
|--------|-------|
| Total Trades | 1,016 |
| Win Rate | 45.2% |
| Total PnL | +$10,504 |
| Return | 105% |
| Sharpe Ratio | **0.67** |
| Max Drawdown | -$19,156 (-49.6%) |

### Percentage Position Sizing (2% equity risk)

| Metric | Value |
|--------|-------|
| Total Trades | 1,016 |
| Win Rate | 45.3% |
| Total PnL | +$13,284 |
| Return | 133% |
| Sharpe Ratio | 0.24 |
| Max Drawdown | -$144,970 (-87.2%) |

## Exit Reason Analysis (Fixed Sizing)

| Exit Type | Count | % | Win Rate | PnL |
|-----------|-------|---|----------|-----|
| Stop Loss | 322 | 31.7% | 0.0% | -$65,719 |
| Take Profit | 135 | 13.3% | 100.0% | +$53,151 |
| Time Exit | 489 | 48.1% | 58.1% | +$23,070 |
| End of Day | 70 | 6.9% | 57.1% | +$1 |

**Key Insight**: Time exits (60-bar max hold) generate most of the profit. Stops provide downside protection but are net negative.

## Direction Analysis

| Direction | Trades | Win Rate | PnL |
|-----------|--------|----------|-----|
| LONG | 412 | 44.9% | -$4,000 |
| SHORT | 604 | 45.4% | +$14,504 |

**Key Insight**: SHORT side significantly outperforms LONG.

## Monthly Performance (Fixed Sizing)

### Best Months
- 2023-08: +$21,234 (248 trades, 56% win)
- 2024-05: +$1,543 (15 trades, 60% win)
- 2025-07: +$1,400 (22 trades, 59% win)

### Worst Months
- 2024-12: -$4,787 (37 trades, 16% win)
- 2024-11: -$3,629 (139 trades, 42% win)
- 2025-01: -$3,210 (39 trades, 21% win)

## Comparison: Hybrid vs Simple Hold

| Metric | Simple 10-bar | Hybrid 2x ATR | Hybrid 3x ATR |
|--------|---------------|---------------|---------------|
| Trades | 536 | 1,031 | 1,016 |
| Win Rate | 49.4% | 42.5% | 45.3% |
| Total PnL | $210 | $6,217 | $13,284 |
| Sharpe | 0.10 | 0.16 | 0.24 |

**Conclusion**: Hybrid 3x ATR significantly outperforms simple hold.

## Why Wider Stops (3x ATR) Work Better

| ATR Multiple | Stop Hit % | Target Hit % | PnL |
|--------------|------------|--------------|-----|
| 2.0x | 44% | 21% | $6,217 |
| 2.5x | 36% | 18% | $44,917 |
| 3.0x | 30% | 14% | $62,052 |

Wider stops:
1. Reduce premature stop-outs
2. Allow trades more room to develop
3. Time exits capture more profit
4. Lower stop hit rate = less drag

## Implementation

### Run Optimal Backtest
```bash
python scripts/rolling_hybrid_optimal.py
```

### Key Files
- `scripts/rolling_hybrid_optimal.py` - Production backtest
- `scripts/matrix_hybrid_stops.py` - Parameter optimization
- `run/rolling_hybrid_optimal/trades.csv` - Trade log
- `run/rolling_hybrid_optimal/metrics.csv` - Monthly metrics

## Recommendations

### For Production
1. **Use fixed position sizing** ($200 risk/trade for $10k account)
2. **Use 3x ATR stops** - reduces stop-outs
3. **60-bar max hold** - time exits are profitable
4. **Consider SHORT-only** - better performance

### Risk Management
- Max 2% equity risk per trade
- Unlimited concurrent positions (signals cluster)
- Same-day exits only (no overnight)
- End-of-day forced exit

### Future Improvements
1. Test SHORT-only variant
2. Add regime filter (avoid bad months like Nov-Dec 2024)
3. Test different R-targets (1.5R, 2.5R)
4. Add volatility filter (skip low-ATR setups)

## Technical Details

### Features Used
- 55 ICT + VPA features on 1-minute bars
- Separate LONG and SHORT LightGBM models
- Rolling 6-month training window
- 1-month validation, 1-month OOS

### Entry Logic
1. ML model predicts direction (prob >= 0.60)
2. Entry on bar AFTER signal (no leakage)
3. Position size = Risk / Stop Distance

### Exit Logic (Priority Order)
1. **Stop Loss**: If price hits stop (3x ATR from entry)
2. **Take Profit**: If price hits target (2R = 6x ATR from entry)
3. **Time Exit**: After 60 bars (1 hour)
4. **End of Day**: Before market close

### Cost Model
- Commission: $0.0035/share (min $0.35/side)
- Spread: 5 bps (0.05%)

---

**System Status**: Production Ready
**Last Updated**: December 11, 2025
**Best Config**: thresh=0.60, atr=3.0, R=2.0, hold=60, fixed $200 risk
