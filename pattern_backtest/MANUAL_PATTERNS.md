# Manual Patterns Implementation

## Overview
Hand-coded implementation of top patterns from LLM analysis of 180-minute horizon patterns.

## Patterns Implemented

### Pattern 1: High ATR + Power Hour
- **Rule:** `atr_14_bin == 4 AND is_power_hour_bin == True`
- **Lift:** 5.86x
- **Support:** 2.30% (151,449 samples)
- **Logic:** High volatility (ATR bin 4) during power hour (3-4 PM ET) suggests continuation into close
- **Rationale:** Volatility expansion in final hour often indicates institutional positioning

### Pattern 2: Strong 60m Momentum + Power Hour
- **Rule:** `ret_60m_bin == 4.0 AND is_power_hour_bin == True`
- **Lift:** 5.40x
- **Support:** 2.59% (170,720 samples)
- **Logic:** Strong 60-minute momentum (bin 4) during power hour
- **Rationale:** Momentum continuation into close, institutional end-of-day positioning

### Pattern 15: Elevated Volume + Power Hour
- **Rule:** `rvol_bin == 3 AND is_power_hour_bin == True`
- **Lift:** 4.02x
- **Support:** 3.76% (247,244 samples)
- **Logic:** Above-average relative volume (bin 3) during power hour
- **Rationale:** Increased participation suggests institutional interest and continuation

## Common Theme
All three patterns share the **power hour** (3-4 PM ET) timing, suggesting:
- End-of-day institutional positioning
- Momentum continuation **overnight**
- Higher probability of moves into **next trading day**

## CRITICAL: Overnight Hold Strategy

**The 180-minute horizon is NOT intraday:**
- Entry: Power hour (3:00-4:00 PM)
- Hold: **Overnight** (market close to next day open)
- Exit: ~180 bars forward = **Next day ~12:00 PM**

**Example:**
- Entry signal: 3:30 PM Monday
- Market close: 4:00 PM Monday (30 minutes later)
- Overnight gap: 4:00 PM Monday → 9:30 AM Tuesday
- Exit: 12:00 PM Tuesday (180 bars from entry)

**This captures:**
- Final 30 minutes of current day
- Overnight gap (15.5 hours)
- First 2.5 hours of next trading day
- **Total calendar time: ~20 hours**

**Risk Considerations:**
- Overnight gap risk
- News/earnings announcements
- Market regime changes
- Extended exposure vs intraday

## Usage

### Test Pattern Evaluation
```bash
cd /home/jacobw/quantstack
.venv/bin/python3 pattern_backtest/test_manual_patterns.py
```

### Run Backtest
```bash
cd /home/jacobw/quantstack
.venv/bin/python3 pattern_backtest/test_manual_backtest.py
```

### Integration with Backtest Framework
```python
from pattern_backtest.src.manual_pattern_policy import ManualPatternPolicy

policy = ManualPatternPolicy(
    position_size=100,
    horizon_minutes=180,
    method_id="manual_patterns_180m",
)

# Run backtest
engine = BacktestEngine(config)
result = engine.run(df, policy)
```

## Files
- `src/manual_patterns.py` - Pattern definitions and evaluators
- `src/manual_pattern_policy.py` - qx-backtest Policy implementation
- `test_manual_patterns.py` - Unit tests for pattern evaluation
- `test_manual_backtest.py` - Full backtest test

## Performance Tracking
All trades are tagged with `method_id="manual_patterns_180m"` for comparison with:
- Automated pattern discovery
- Other manual rule sets
- Alternative strategies

## Exit Strategy
- **Time-based:** Exit after 180 bars (next day ~noon for power hour entries)
- **Overnight holds:** Positions held through market close and overnight gap
- **No intraday stops:** Fixed time horizon only
- **Gap risk:** Exposed to overnight news and market moves

## Position Sizing
- **Fixed:** 100 shares per trade
- **Commission:** $2 per round-turn ($0.01 per share per side)
- **No leverage:** One position per symbol at a time
- **Overnight margin:** Requires overnight buying power
