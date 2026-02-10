# Jan 23-24, 2026 Trading Issue Investigation

## Archive Contents

This directory contains files from the investigation of zero-fill issues on Jan 23, 2026.

### Files

1. **api-exported-logs.txt** (30MB)
   - IBKR API logs from Jan 23, 2026
   - Contains 3,219 IOC entry orders and 6,438 bracket order rejections

2. **gateway-exported-logs.txt** (4MB)
   - IBKR Gateway logs from Jan 23, 2026
   - Connection and order routing information

3. **verify_order_fills.py**
   - Initial verification script to check order price precision
   - Identified Error 110 (invalid price precision) on bracket orders

4. **fill_simulation_results.csv**
   - Detailed results from IOC order fill simulation
   - 3,219 orders analyzed against L2 data with latency adjustment
   - 85.9% would have filled at order price

## Issues Found

### L2-Scalping System
- **Problem**: Bracket stop/target orders had 5-6 decimal places (e.g., 187.671085)
- **Result**: 6,438 bracket orders rejected with IBKR Error 110
- **Fix**: Created `round_to_tick_size()` utility and applied to all stop/target calculations
- **File**: `/home/jacobw/quantstack/cpapi/utils.py`

### Intraday-Paper System
- **Problem 1**: Timestamp parsing failure with "2026-01-22 14:26:00-05:00" format
- **Result**: 0 orders placed (all signals rejected)
- **Fix**: Replaced `datetime.fromisoformat()` with `dateutil.parser.parse()`
- **Problem 2**: Overly aggressive 5-minute signal age limit
- **Result**: 100% of signals rejected as "stale" (6 candidates, 0 orders)
- **Fix**: New logic accepts same-day signals, rejects prior-day signals
- **File**: `/home/jacobw/intraday_stack/scripts/paper_trade.py`

## Reports Generated

- `/home/jacobw/quantstack/docs/IOC_FILL_SIMULATION_RESULTS.md`
- `/home/jacobw/quantstack/docs/INTRADAY_PAPER_FORENSIC_AUDIT.md`

## Date
2026-01-24
