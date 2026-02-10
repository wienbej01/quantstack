# End-of-Day Trade Performance Report

**Script**: `scripts/eod_report.py`  
**Purpose**: Unified daily performance report covering all systems and strategies

## Usage

```bash
# Today's report
python3 scripts/eod_report.py

# Specific date
python3 scripts/eod_report.py --date 2026-01-28

# Export to CSV
python3 scripts/eod_report.py --date 2026-01-28 --csv report.csv
```

## Report Sections

### 1. Executive Summary
- Total trades, P&L, fees
- Win rate, average P&L per trade
- Average hold time

### 2. Performance by System
- Breakdown by system (l2-scalping, intraday-paper, l2-vwap-reversion)
- Includes: trades, P&L, fees, win rate, hold time, slippage

### 3. Performance by Strategy
- Breakdown by strategy (l2_scalping_high_obi_depth, reversal, etc.)
- Same metrics as system breakdown

### 4. Performance by Symbol
- Which tickers performed best/worst
- Trades, P&L, win rate per symbol

### 5. Performance by Direction
- Long vs Short effectiveness
- Trades, P&L, win rate per direction

### 6. Exit Reason Analysis
- Which exit logic is working (STOP_LOSS, PROFIT_TARGET, MAX_HOLD, etc.)
- Count, P&L, win rate per exit reason

### 7. Intraday Time Analysis
- Morning (before 12:00) vs Afternoon (12:00+) performance
- Identifies time-of-day patterns

### 8. Risk Metrics
- Max drawdown
- Sharpe ratio (annualized)
- Profit factor
- Expectancy
- Best/worst trades

### 9. Signal vs Execution Analysis
- Compares signal prices to actual execution prices
- Measures signal slippage (how much price moved between signal and entry)

### 10. Trade Details
- Full trade-by-trade breakdown
- Time, symbol, system, strategy, direction, prices, P&L, exit reason, hold time

## CSV Export

When using `--csv`, exports all closed trades with full details including:
- All trade fields from database
- Calculated fields (winner, hour, period)
- Suitable for further analysis in Excel/Python

## Notes

- Report only includes **closed trades** (status='CLOSED')
- SYNC exits are included in win rate calculations (flagged in exit reason)
- Slippage is measured as actual price - expected price
- Hold times are in seconds
- Morning/Afternoon split at 12:00 (noon)

## Deprecated Scripts

The following scripts are deprecated in favor of `eod_report.py`:
- `query_positions.py.deprecated` - Position-focused report
- `trading_report.py.deprecated` - Trade-by-trade report

Use `eod_report.py` for all daily performance reporting.
