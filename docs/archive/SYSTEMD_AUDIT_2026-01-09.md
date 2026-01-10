# Systemd Service Forensic Audit - 2026-01-09

## Issues Found and Fixed

### 1. l2-scalping: Missing Typing Imports ❌→✅ FIXED
**Error**: `NameError: name 'List' is not defined`
**Root Cause**: `order_manager.py` used `List` and `Dict` type hints without importing them
**Fix**: Added `from typing import Dict, List, Optional` to imports

### 2. trading-orchestrator: Failed State ❌→✅ RESET
**Error**: Service in "failed" state from previous run
**Root Cause**: SIP generation timeout/interrupt
**Fix**: `sudo systemctl reset-failed trading-orchestrator`

### 3. Async Event Loop Bug ❌→✅ FIXED (earlier)
**Error**: `There is no current event loop in thread`
**Root Cause**: `ib_insync` async methods called in threads without event loops
**Fix**: Wrapped `self.ib.sleep()` with `util.run()` in both `l2_feed.py` and `order_manager.py`

## Current Service Status (2026-01-09 10:18 Manila)

| Service | Status | Notes |
|---------|--------|-------|
| l2-collector | 🟢 active | Completed 90,837 records yesterday |
| l2-scalping | 🟢 active | Waiting for market hours (21:17 ET) |
| l2-watchdog | 🟢 active | Monitoring healthy |
| intraday-paper | ⚪ inactive | Timer-triggered at 22:25 Manila |
| intraday-sip | ⚪ inactive | Timer-triggered at 21:45 Manila |
| trading-orchestrator | ⚪ inactive | Timer-triggered at 21:00 Manila |

## Timer Schedule (Manila Time = PST+16h)

| Timer | Next Run (Manila) | Purpose |
|-------|-------------------|---------|
| trading-orchestrator | 21:00 (9:00 PM) | Pre-market SIP generation |
| intraday-sip | 21:45 (9:45 PM) | SIP refresh |
| intraday-paper | 22:25 (10:25 PM) | Paper trading start |

## Test Suite Created

New test script: `scripts/test_systemd_services.py`

Run before market hours to catch silent failures:
```bash
python scripts/test_systemd_services.py
```

Tests performed:
- Service file exists
- Service syntax valid
- Service loadable
- Working directory exists
- ExecStart binary exists
- Environment file exists (if specified)
- Python imports work

## Recommendations

1. **Run test suite daily** before market hours (add to orchestrator)
2. **Add NTFY alerts** for service failures
3. **Monitor restart counts** - high counts indicate problems
4. **Check logs after each session** - don't assume "active" means "working"

## Files Modified

- `/home/jacobw/quantstack/l2_scalping/src/execution/order_manager.py` - Added typing imports
- `/home/jacobw/quantstack/l2_scalping/src/data/l2_feed.py` - Fixed async event loop (earlier)
- `/home/jacobw/quantstack/scripts/test_systemd_services.py` - NEW test suite
