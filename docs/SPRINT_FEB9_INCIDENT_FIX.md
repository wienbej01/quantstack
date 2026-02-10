# Sprint: Feb 9 Incident Fix — Margin Breach & CPU Spike

**Created:** 2026-02-10
**Incident:** Feb 9 trading day — 3 entries, margin breach at 09:36 ET, system frozen for remainder of session, sustained 100% CPU for ~2 hours.
**Root cause chain:** Margin breach → exit order rejection → 100Hz cancel/resubmit loop → CPU saturation → no further trading.

---

## Phase 1: Stop the Bleeding (Critical — must ship before next trading session)

### 1.1 Exit Retry Circuit Breaker in `_check_position_exits()`
**File:** `l2_scalping/src/main.py` — `_check_position_exits()` and `_exit_position()`
**Problem:** When a force-market exit is rejected (margin or otherwise), the position stays in `active_positions` with no `exit_order_id`. The 100Hz main loop retries immediately, creating ~100 cancel+place cycles/sec.
**Fix:**
- Add `exit_attempts` counter and `last_exit_attempt_time` to position dict
- After `place_order()` returns `None`, increment `exit_attempts` and set `last_exit_attempt_time`
- If `exit_attempts >= 3`, set position status to `EXIT_FAILED` and stop retrying
- Add exponential backoff: don't retry within `min(30, 2^attempts)` seconds
- Log CRITICAL when exit fails 3 times — this is the "system is stuck" signal

### 1.2 Order Rejection Detection
**File:** `l2_scalping/src/execution/order_manager.py` — `place_order()`
**Problem:** Returns `None` for all errors. Can't distinguish margin rejection from network error.
**Fix:**
- Catch IBKR error events that contain "margin" or "insufficient" in the message
- Return a structured result: `(order_id, error_reason)` or a dataclass `OrderResult(order_id, success, rejection_reason)`
- Propagate rejection reason to `_exit_position()` so the circuit breaker can make informed decisions
- On margin rejection specifically: immediately flag `EXIT_FAILED` (no retries — margin won't fix itself mid-session)

### 1.3 Emergency Alert on Exit Failure
**File:** `l2_scalping/src/main.py` (new method) + `cpapi/trading_notifications.py`
**Problem:** No alerting when the system is stuck. You're asleep in SGT.
**Fix:**
- When any position enters `EXIT_FAILED` state, fire a notification via existing `trading_notifications.py`
- Include: symbol, quantity, rejection reason, account equity, margin shortfall
- Rate-limit to 1 alert per symbol per 5 minutes

---

## Phase 2: Pre-Trade Margin Check (Critical — prevents recurrence)

### 2.1 IBKR Margin Query Before Entry Orders
**File:** `l2_scalping/src/risk/risk_manager.py` — `check_pre_trade_risk()`
**Problem:** Risk manager checks daily P&L, position count, and position size but never queries IBKR for actual available margin. The $2,291 shortfall was invisible.
**Fix:**
- Add `check_margin(symbol, quantity, price)` method that calls `ib.whatIfOrder()` to get margin impact before placing
- Require `available_margin > order_margin_impact * 1.5` (50% buffer)
- If margin check fails, reject the entry with actionable log message
- Cache margin data for 30s to avoid hammering IBKR with whatIf calls

### 2.2 Apply Same Margin Check to l2-vwap-reversion
**File:** `l2_vwap_reversion/src/main.py` — `_execute_signal()`
**Problem:** l2-vwap-reversion has zero pre-trade risk checks. It entered 2 HIMS longs that compounded the margin problem.
**Fix:**
- Extract the margin check into a shared module (e.g., `cpapi/margin_check.py`)
- Import and call before every entry in `_execute_signal()`
- Add basic circuit breaker (max 3 consecutive rejections → stop trading)

---

## Phase 3: Cross-Service Position Awareness (High — prevents margin stacking)

### 3.1 Shared Position Ledger via PostgreSQL
**File:** New `cpapi/shared_positions.py` + extend `cpapi/schema.sql`
**Problem:** l2-scalping, l2-vwap-reversion, and intraday-paper each track positions independently. They don't know about each other's margin consumption.
**Fix:**
- Create `shared_positions` table in existing PostgreSQL (trade_database already uses it)
- Each service writes its positions on entry/exit
- Pre-trade risk check queries total exposure across all services
- Simple schema: `(service, symbol, quantity, avg_price, margin_used, updated_at)`

### 3.2 Global Margin Budget
**File:** `cpapi/margin_check.py` (from 2.2)
**Problem:** Even with individual margin checks, two services could simultaneously pass margin checks and collectively exceed limits.
**Fix:**
- Query `shared_positions` for total margin in use across all services
- Enforce global margin cap: `total_margin_used + new_order_margin < account_equity * 0.8`
- Use PostgreSQL advisory locks for atomic check-and-reserve

---

## Phase 4: Vitals Monitor Fix (Medium — enables diagnosis of future incidents)

### 4.1 Fix Process Matching
**File:** `scripts/monitor_vitals.py` — `get_process_stats()`
**Problem:** Matches on `proc.info["name"]` which returns `"python3"` for all Python processes. Never matches trading process names.
**Fix:**
- Match on `proc.cmdline()` instead of `proc.info["name"]`
- Check if any element in cmdline contains the trading process identifier (e.g., `"l2_scalping"`, `"l2_vwap_reversion"`, `"start_paper_trading"`)
- Record per-process CPU/memory in the vitals DB, not just system-wide

### 4.2 CPU Spike Alert
**File:** `scripts/monitor_vitals.py`
**Problem:** Vitals are recorded but never acted on. A 2-hour 100% CPU spike went unnoticed.
**Fix:**
- If system CPU > 90% for 3 consecutive readings (30s), fire alert via `trading_notifications.py`
- If any single trading process > 80% CPU for 3 readings, fire process-specific alert

---

## Phase 5: Hardening (Medium — defense in depth)

### 5.1 Main Loop Rate Limiting for Exit Retries
**File:** `l2_scalping/src/main.py` — main loop
**Problem:** The 100Hz loop is appropriate for data processing but not for exit order retries.
**Fix:**
- Separate exit-check cadence from data-processing cadence
- Run `_check_position_exits()` at most once per second (not 100Hz)
- Keep the 100Hz loop for order updates and fill processing

### 5.2 EOD Emergency Flatten Hardening
**File:** `l2_scalping/src/main.py` — `_check_eod_flatten()`
**Problem:** If exit orders are stuck in `EXIT_FAILED` state, EOD flatten will also fail for the same margin reason.
**Fix:**
- EOD flatten should use `ib.reqGlobalCancel()` first to clear all pending orders
- Then place market exits with a 10s timeout
- If still stuck, log CRITICAL with full position details for manual intervention
- Consider: if margin is the issue, closing positions FREES margin — so a single market sell should succeed even if margin is tight

### 5.3 Startup Position Reconciliation
**File:** `l2_scalping/src/main.py` — `_sync_ibkr_positions()`
**Problem:** If the system restarts after a crash, orphaned positions from the previous session may not be properly tracked.
**Fix:**
- On startup, query IBKR for all positions
- Cross-reference with `shared_positions` table
- Any position in IBKR but not in shared_positions → log WARNING and add to tracking
- Any position in shared_positions but not in IBKR → mark as closed

---

## Execution Order

| Priority | Task | Est. Time | Status |
|----------|------|-----------|--------|
| P0 | 1.1 Exit retry circuit breaker | 30 min | ✅ `l2_scalping/src/exit_guard.py` — 10 tests |
| P0 | 1.2 Order rejection detection | 45 min | ✅ `PlaceOrderResult` in `order_manager.py` — 5 tests |
| P0 | 1.3 Emergency alert on exit failure | 20 min | ✅ `cpapi/emergency_alerts.py` — 5 tests |
| P0 | 2.1 IBKR margin query before entry | 45 min | ✅ `cpapi/margin_check.py` — 8 tests |
| P0 | Integration into main.py | — | ✅ exit guard + margin checker + 1/sec rate limit |
| P1 | 4.1 Fix vitals process matching | 15 min | ✅ `scripts/monitor_vitals.py` — 2 tests |
| P1 | 5.1 Rate-limit exit check cadence | 15 min | ✅ in main.py main loop — 1 test |
| P1 | 2.2 Margin check for l2-vwap-reversion | 30 min | ✅ in `l2_vwap_reversion/src/main.py` — 4 tests |
| P2 | 3.1 Shared position ledger (PostgreSQL) | 1.5 hr | ✅ `cpapi/shared_positions.py` — 6 tests |
| P2 | 3.2 Global margin budget | 1 hr | ✅ in `cpapi/shared_positions.py` — included above |
| P2 | 4.2 CPU spike alert in vitals monitor | 20 min | ✅ `CPUSpikeDetector` in `monitor_vitals.py` — 5 tests |
| P2 | 5.2 EOD flatten hardening | 30 min | ✅ in `l2_scalping/src/main.py` — 2 tests |
| P2 | 5.3 Startup position reconciliation | 45 min | ✅ in `l2_scalping/src/main.py` — 3 tests |
| P3 | Wire shared ledger into l2-scalping | 30 min | ✅ entry/exit/shutdown + margin gate — 5 tests |
| P3 | Wire shared ledger into l2-vwap-reversion | 30 min | ✅ entry/exit/disconnect + global margin — 5 tests |
| P3 | Global margin gate logic + cross-service scenarios | 30 min | ✅ advisory lock, cap enforcement — 6 tests |

### Test suite: `tests/test_feb9_incident_fixes.py` — 75/75 passing

| Test class | Count | Covers |
|------------|-------|--------|
| TestExitGuard | 10 | Circuit breaker, backoff, per-symbol isolation, alert callback |
| TestMarginChecker | 8 | Healthy/breached margin, exact Feb 9 numbers, cache, errors |
| TestPlaceOrderResult | 5 | Margin keyword detection across IBKR message variants |
| TestEmergencyAlerts | 5 | Send, rate-limit, different symbols, failure resilience |
| TestVitalsProcessMatching | 2 | cmdline matching, proof old method was broken |
| TestFeb9IncidentReplay | 5 | Full incident timeline replay, cross-service, backoff timing |
| TestRiskManagerMarginGap | 1 | Proves existing risk manager has no margin check |
| TestExitCheckRateLimiting | 1 | 100Hz → 1Hz reduction verified |
| TestCrossServiceMargin | 1 | Second service blocked when margin tight |
| TestEODFlattenWithFailedExits | 1 | Guard reset allows EOD retry |
| TestVWAPReversionMarginCheck | 4 | Rejection counter, reset, source verification |
| TestSharedPositionLedger | 6 | Upsert, delete, total margin, global cap, clear |
| TestCPUSpikeDetector | 5 | Below threshold, consecutive spikes, reset, per-process, Feb 9 replay |
| TestEODFlattenHardening | 2 | Guard reset, retry after failure |
| TestStartupReconciliation | 3 | Orphan detection, stale cleanup, matching positions |
| TestSharedLedgerIntegrationL2Scalping | 5 | Init, entry write, exit remove, shutdown clear, margin gate |
| TestSharedLedgerIntegrationVWAP | 5 | Init, entry write, exit remove, disconnect clear, global margin |
| TestGlobalMarginGateLogic | 4 | Cap exceeded, under cap, DB failure graceful, advisory lock |
| TestCrossServiceScenario | 2 | l2-scalping fills → vwap blocked, exit frees margin |

### Files changed/created

| File | Action |
|------|--------|
| `cpapi/margin_check.py` | NEW — shared pre-trade margin checker |
| `cpapi/emergency_alerts.py` | NEW — rate-limited NTFY alerts |
| `cpapi/shared_positions.py` | NEW — cross-service position ledger + global margin budget |
| `l2_scalping/src/exit_guard.py` | NEW — exit retry circuit breaker |
| `l2_scalping/src/execution/order_manager.py` | MODIFIED — added `PlaceOrderResult`, `place_order_safe()` |
| `l2_scalping/src/main.py` | MODIFIED — exit guard, margin checker, 1/sec exit check, EOD hardening, startup reconciliation, shared ledger integration |
| `l2_vwap_reversion/src/main.py` | MODIFIED — margin checker + circuit breaker + shared ledger in `_execute_signal()` |
| `scripts/monitor_vitals.py` | MODIFIED — cmdline process matching + CPU spike detector |
| `cpapi/schema.sql` | MODIFIED — added `shared_positions` table |
| `tests/test_feb9_incident_fixes.py` | NEW — 59 tests |
| `docs/SPRINT_FEB9_INCIDENT_FIX.md` | NEW — this plan |

### P1 remaining: Margin check for l2-vwap-reversion
- Import `MarginChecker` into `l2_vwap_reversion/src/main.py`
- Call before every entry in `_execute_signal()`
- Add basic circuit breaker (reuse `ExitGuard` or simple counter)
- Add tests

---

## Verification Plan

After P0 fixes:
1. Start l2-scalping in paper mode
2. Manually trigger a margin rejection (reduce account margin in paper account settings)
3. Verify: exit retry stops after 3 attempts, alert fires, CPU stays normal
4. Verify: new entries are blocked when margin is insufficient
5. Check vitals DB shows per-process CPU after 4.1

After P2 fixes:
1. Start all 3 services simultaneously
2. Verify shared_positions table is populated
3. Verify global margin cap prevents over-allocation
4. Simulate CPU spike and verify alert fires
