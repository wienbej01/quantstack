# Incident Log

> Chronological record of incidents, fixes, and post-mortems.
> Consolidated from individual sprint/fix/error reports.
>
> Last updated: 2026-02-10

---

## 2026-02-09 — Margin Breach & CPU Spike (CRITICAL)

**Impact**: System frozen for entire session after 09:36 ET. 3 entries made, then 100% CPU for ~2 hours.

**Root cause chain**: Margin breach ($2,291 shortfall) → exit order rejection by IBKR → 100Hz cancel/resubmit loop in `_check_position_exits()` → CPU saturation → no further trading.

**Key findings**:
- `_exit_position()` with `force_market=True` cleared its own guard (`exit_order_id`), enabling the next 10ms iteration to retry immediately
- `RiskManager.check_pre_trade_risk()` never queried IBKR for actual margin — the shortfall was invisible
- Three services share one IBKR account with no cross-service margin awareness
- `monitor_vitals.py` matched on `proc.info["name"]` which is always "python3" — never identified trading processes

**Fixes implemented** (P0–P3, 75 tests):
- Exit retry circuit breaker (`l2_scalping/src/exit_guard.py`) — max 3 attempts, exponential backoff
- Order rejection detection (`PlaceOrderResult` dataclass with `is_margin_rejection`)
- Emergency NTFY alerts for exit failures, margin breaches, CPU spikes
- Pre-trade margin check via IBKR `whatIfOrder` (both services)
- Shared position ledger + global margin budget (PostgreSQL)
- CPU spike detector in vitals monitor (alert within 30s)
- EOD flatten hardening (reset guards, global cancel, retry)
- Startup position reconciliation
- Vitals process matching fixed (cmdline-based)
- Exit check rate-limited to 1/sec (was 100Hz)

**Full details**: [SPRINT_FEB9_INCIDENT_FIX.md](SPRINT_FEB9_INCIDENT_FIX.md)

---

## 2026-02-04 — Position Blocking Bug

**Impact**: All three services blocking trades based on ALL IBKR positions, not just their own.

**Root cause**: Position check queried global IBKR positions instead of service-specific tracking.

**Fix**: Each service now only checks its own `active_positions` dict, not global IBKR state.

---

## 2026-02-03 — Trade DB Recording Failure (CRITICAL)

**Impact**: Trade recording completely broken — no trades being saved to database.

**Root cause**: PostgreSQL connection string issue after migration. `trade_database.py` failing silently.

**Fixes**: Connection string fix, enhanced error logging, WAL error handling with fsync, Trade DB v2 remediation plan executed.

---

## 2026-01-29 — Order Auto-Cancel Bug + Position Tracking (CRITICAL)

**Impact**: Positions not closing at EOD → overnight risk exposure. Trade recording missing fills.

**Root cause (order cancel)**: OCA bracket orders being cancelled prematurely when one leg filled. Exit orders cancelled before they could execute.

**Root cause (position tracking)**: Fill handler not properly tracking partial fills. Position quantities drifting from actual IBKR positions.

**Fixes**:
- OCA order handling rewritten — don't cancel working exit orders
- Position tracking fix — proper partial fill accumulation
- Fill handler rewrite with `exit_filled_qty` and `exit_total_value` tracking
- Systemd integration verified and auto-start enabled

---

## 2026-01-27 — Error Report (Multiple Issues)

**Impact**: Multiple trading errors during session. Incorrect exit prices, orphaned fills.

**Root cause**: Combination of fill recording bugs, exit price using signal price instead of actual fill, and race conditions in concurrent fill processing.

**Fixes**: Exit price corrected to use IBKR fill VWAP, fill deduplication added, trade validation procedures established.

---

## 2026-01-24 — Intraday Paper Forensic Audit

**Impact**: Paper trading system generating signals but not executing trades.

**Root cause**: Signal-to-order pipeline broken — signals generated but `PaperTrader.execute()` not being called due to missing callback registration.

**Fix**: Callback registration added, end-to-end validation confirmed.

---

## 2026-01-24 — IOC Fill Analysis

**Finding**: Analyzed 3,219 IOC entry orders from Jan 23. Fill rate analysis showed price improvement ticks needed tuning. Led to IOC order type configuration changes.

---

## 2026-01-21 — PostgreSQL Migration

**Impact**: Migrated from SQLite to PostgreSQL to eliminate database lock issues during concurrent writes.

**Changes**: All production code migrated. SQLite references removed and verified. Trade DB schema created in PostgreSQL.

---

## 2026-01-20 — IBKR Gateway Outage (6 Hours)

**Impact**: Gateway down from 09:20–15:11 ET. No trading for entire session.

**Root cause**: Gateway not running, services with `Requires=ibkr-gateway-ready` kept failing. IBKR auto-logoff at 10:45 ET killed connections.

**Fixes**:
- Changed to `Wants=` (soft dependency) — services start and retry internally
- Post-outage recovery runbook created
- L2 health monitor added (auto-detects Error 309, auto-recovers)
- Zombie depth subscription clearing script

---

## 2026-01-08 — Timezone Confusion Incident

**Impact**: Days of debugging confusion — logs showed Manila time but market events in ET.

**Root cause**: System timezone Manila (UTC+8), 13-hour offset from ET. Logs ambiguous.

**Fix**: All trading services now run with `TZ=America/New_York` in systemd unit files.

---

## Archived Incidents (Pre-2026)

Historical incidents from Oct–Dec 2025 are in `docs/archive/`. These cover the ML model development phase, backtesting infrastructure, and initial deployment — not relevant to current L2 scalping/VWAP production system.
