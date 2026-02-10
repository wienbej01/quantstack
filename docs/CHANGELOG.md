# Quantstack Change Log

## 2026-02-10

### Documentation Consolidation
- Reduced docs/ from 40+ files to 9 active documents
- Created `OPERATIONS.md` — consolidated ops runbook (pre-market, health checks, monitoring, EOD, recovery)
- Created `INFRASTRUCTURE.md` — consolidated IBKR, Trade DB, audit logging reference
- Created `INCIDENT_LOG.md` — chronological incident history and post-mortems
- Rewrote `README.md` as documentation entry point with quick start and doc map
- Updated `SYSTEM_GUIDE.md` to v10 with Feb 9 incident fix references
- Archived 38 outdated/redundant docs to `archive/2026-02-consolidation/`
- Fixed stale cross-references in L2_VWAP_SYSTEM.md and SYSTEM_GUIDE.md

### Feb 9 Incident Fixes (P0–P3 Complete)
- Exit retry circuit breaker, margin checks, shared position ledger
- CPU spike alerting, EOD flatten hardening, startup reconciliation
- Cross-service position awareness wired into live trading flows
- 75 tests passing — see SPRINT_FEB9_INCIDENT_FIX.md

## 2026-02-04

### Trade DB v2 Remediation Implemented
- **Implemented peer-auth/no-password DB defaults** for Trade DB v2 integration
  - `cpapi/trade_integration.py` now defaults to Unix socket host `/var/run/postgresql`
- **Added durable order-to-trade mapping**
  - New table `trade_order_links` added in `cpapi/schema.sql`
  - `cpapi/trade_database.py` now writes mapping rows and backfills existing executions
- **Improved execution linkage and attribution**
  - `cpapi/unified_fill_processor.py` now resolves `trade_id` and `system` from `trade_order_links` at insert time
  - Executions are inserted with mapped `trade_id` where available
- **Linked exit orders across strategies**
  - `l2_scalping/src/main.py` links bracket child orders (stop/target) to trade records
  - `l2_scalping/src/execution/order_manager.py` now exposes bracket child IDs
  - `l2_vwap_reversion/src/main.py` links parent + stop-loss + take-profit IDs
- **Integrated intraday-paper into Trade DB v2**
  - `/home/jacobw/intraday_stack/scripts/paper_trade.py` now initializes `TradeIntegration`
  - Opens Trade DB v2 trades and links entry/exit/EOD close orders

### Validation and Database Maintenance
- **Trade DB test suites executed**
  - `scripts/quick_test_trade_db_v2.sh` completed
  - `scripts/run_trade_db_v2_tests.py` passed `13/13` tests
  - `scripts/verify_trade_db_v2.py` rerun after maintenance
- **Collation mismatch maintenance completed**
  - Ran `ALTER DATABASE trading REFRESH COLLATION VERSION;`
  - Ran `REINDEX DATABASE trading;`
  - Warning cleared

### Clean Start Reset (User Requested)
- Created backup before reset:
  - `backups/trading_pre_reset_2026-02-04_1115.dump`
- Performed full Option B reset for next market open:
  - Truncated `executions`, `trades_v2`, `positions`, `trade_order_links`
  - Truncated `decisions`, `orders`, `fills`, `trades`, `risk_events`, `trades_old_backup`
  - Verified all reset tables are at `0` rows

## 2026-01-31

### L2-VWAP Event Loop Fix
- **Fixed "event loop already running" error** that blocked all order submissions
  - Root cause: Direct `ib.placeOrder()` calls in async context
  - Fix: Changed to `session.call(ib.placeOrder, ...)` wrapper
  - All bracket orders now submit correctly

### Client ID Management System
- **Created `cpapi/client_id_manager.py`** - shared client ID manager
  - Dynamic allocation within assigned ranges
  - Auto-increment on reconnect (avoids Gateway caching)
  - State persisted to `~/.quantstack/client_ids/{service}.json`
- **Updated L2-VWAP config** to use `_base` and `_max` keys
- **Created `~/.quantstack/client_id_ranges.yaml`** - central registry

### Timer Cleanup
- **Removed duplicate** `/etc/systemd/system/l2-vwap-reversion.timer`
- **User-level timer** at 09:20 ET is now the only l2-vwap timer
- **Added `l2-vwap-reversion-stop.timer`** at 17:00 ET

### L2-Collector Archived
- **Moved to `archive/l2-collector-deprecated/`**:
  - qx-l2 config files
  - l2-collector.service
  - l2-collector.timer
- L2 data collection handled by l2-scalping (confirmed in docs)

### Files Modified
- `l2_vwap_reversion/src/execution/order_manager.py` - session.call() fix
- `l2_vwap_reversion/src/main.py` - ClientIDManager integration
- `l2_vwap_reversion/config/ibkr.yaml` - client ID range config
- `cpapi/client_id_manager.py` - NEW
- `~/.quantstack/client_id_ranges.yaml` - NEW
- `/etc/systemd/system/l2-vwap-reversion-stop.*` - NEW
- `docs/SYSTEM_GUIDE.md` - Updated to v9.0

---

## 2026-01-29

### NTFY Notification Improvements
- **Trade notifications now include position IDs** for better tracking
  - Entry: `"Opening {symbol} position [{position_id}]"`
  - Exit: `"Closing position {position_id} ${pnl}"`
- **Strategy names now use space formatting** (e.g., "l2-scalping vwap" instead of "l2-scalping:vwap")
- **System lifecycle events now clearly distinguished**:
  - **Startup**: "{service} Starting" - scheduled morning startup at 09:26 ET
  - **Recovery**: "{service} Recovered" - after unexpected failure during trading hours
  - **API Events**: "Gateway Reconnected", "Gateway API Timeout"
  - **Orderly Shutdown**: No alert (after 16:00 ET or weekend)
- **Service failure alerts now smarter**:
  - Only alerts during trading hours (09:00-16:00 ET)
  - Skips alerts on weekends, EOD, and pre-market
  - Changed title from "Service Failed" to "Service Crashed"
- **Position close notifications now explicitly show PnL** instead of opposite direction

### Files Modified
- `qx-broker/src/qx_broker/notify/ntfy.py` - Core notification functions with position_id support
- `qx-broker/src/qx_broker/notify/__init__.py` - Export new lifecycle functions
- `l2_scalping/src/reporting/trade_journal.py` - Use qx-broker notify with position IDs
- `l2_scalping/src/execution/order_manager.py` - Removed redundant notifications
- `system_health_monitor.py` - Startup vs recovery detection logic
- `scripts/service_failure_alert.sh` - EOD and weekend detection

## 2026-01-28

### Trading System Updates
- L2 scalping now supports market entries via `orders.entry_order_type`.
- Exit pricing can be fill-based via `orders.exit_price_source=fill`.
- OCA exits are submitted after fills and resized on partial fills.
- Exit orders are now market-only; IOC exit path removed.
- Partial exit fills reduce positions without re-averaging entry price.
- EOD flattening cancels open orders then submits market exits.

### Reliability and Tests
- Integration test now asserts instead of returning values.
- Lint/type targets updated to use labeling package entry.
- Lint fix applied to labeling session filter logic.

### Documentation
- Incident report updated with remediation status and verification results.
- Documentation index updated with Jan 27 incident.
