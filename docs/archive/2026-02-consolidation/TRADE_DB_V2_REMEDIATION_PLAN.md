# Trade DB v2 Remediation Plan (No Password, Full Strategy Capture)

**Date**: 2026-02-04  
**Owner**: Quantstack  
**Goal**: Ensure all trading strategies (l2-scalping, l2-vwap-reversion, intraday-paper) are captured in Trade DB v2 with reliable linkage from executions → trades.

---

## 1) Fix Connectivity (No Password)

**Problem**: Trade DB v2 uses TCP to `localhost` with empty password, causing `fe_sendauth` failures.  
**Target**: Use peer auth via Unix socket; no password needed.

**Actions**
1. Update Trade DB v2 config to prefer Unix socket:
   - In `cpapi/trade_integration.py`, set default `host` to `"/var/run/postgresql"` (or empty), not `localhost`.
   - Ensure `POSTGRES_HOST` is not set in systemd (or is set to socket path).
2. Update systemd units to export DB vars consistently:
   - `l2-scalping.service`, `l2-vwap-reversion.service`, `intraday-paper.service` (env file).
3. Ensure `psycopg2` is available to the Python interpreter used by each service:
   - `l2-scalping` uses `/usr/bin/python3`. Either:
     - Switch to venv python, or
     - Install `psycopg2` system-wide.

**Verification**
- Run `python3 scripts/verify_trade_db_v2.py`.
- Confirm no `fe_sendauth` errors in logs.

---

## 2) Make Executions → Trades Link Robust

**Problem**: `link_order_to_trade()` updates only existing `executions` rows; fills that arrive later remain unlinked.

**Target**: Create a persistent mapping from `ibkr_order_id` → `trade_id` and use it during insert.

**Actions**
1. Add new table:
   ```sql
   CREATE TABLE IF NOT EXISTS trade_order_links (
     trade_id UUID NOT NULL,
     ibkr_order_id INTEGER NOT NULL,
     is_entry BOOLEAN NOT NULL DEFAULT TRUE,
     created_at TIMESTAMPTZ DEFAULT NOW(),
     PRIMARY KEY (trade_id, ibkr_order_id)
   );
   CREATE INDEX IF NOT EXISTS idx_trade_order_links_order ON trade_order_links(ibkr_order_id);
   ```
2. Update `TradeDatabase.link_order_to_trade()` to insert into `trade_order_links` and also backfill any existing `executions` rows.
3. Update `UnifiedFillProcessor._insert_execution()`:
   - Look up `trade_id` using `trade_order_links` by `ibkr_order_id`.
   - Populate `executions.trade_id` during insert if mapping exists.
4. Update `_update_trade_from_execution()` to use `executions.trade_id` directly when available.

**Verification**
- Place a test trade, confirm:
  - `executions.trade_id` is set on first fill.
  - `trades_v2` transitions `PENDING → OPEN → CLOSED`.

---

## 3) Link Exit Orders (Bracket Children)

**Problem**: Only parent order ID is linked; child exit orders are not, so exit fills never tie back to the trade.

**Target**: Link all order IDs (parent + children).

**Actions**
1. **l2-scalping**:
   - After bracket placement, link the parent ID and any child IDs returned by order manager.
   - Store child IDs and register them in `trade_order_links`.
2. **l2-vwap-reversion**:
   - Use `result.parent_id`, `result.stop_id`, `result.target_id` (or equivalent) and link all of them.

**Verification**
- Confirm exit fills update `exit_fills`, `exit_price`, `exit_qty`, and `status=CLOSED`.

---

## 4) System Attribution for Executions

**Problem**: `_get_system_for_order()` always returns `"unknown"`, making system-level queries misleading.

**Target**: Determine system from `orderRef` or from the mapping table.

**Actions**
1. When linking orders, store `system` alongside `trade_id` in `trade_order_links`.
2. Use this mapping in `_insert_execution()` to set `system`.
3. Normalize system names:
   - `l2-scalping`, `l2-vwap`, `intraday-paper` (match docs).

**Verification**
- `SELECT system, COUNT(*) FROM executions GROUP BY system;` shows expected distribution.

---

## 5) Integrate Intraday Paper into Trade DB v2

**Problem**: Intraday-paper writes to EventStore only; no Trade DB v2 entries.

**Target**: Use `TradeIntegration` in intraday-paper to open/link trades.

**Actions**
1. Add `TradeIntegration` to `/home/jacobw/intraday_stack/scripts/paper_trade.py`.
2. On order placement, call:
   - `trade_db.open_trade(...)`
   - `trade_db.link_order(trade_id, order_id, is_entry=True)`
3. Link exit order IDs (stop/target/market) to same trade.
4. Keep EventStore logging for existing reports; Trade DB v2 is the source of truth.

**Verification**
- Run one paper trade and verify `executions` + `trades_v2` rows.

---

## 6) Data Backfill / Migration (Optional)

If needed, backfill missing trades from:
- EventStore `fills` + `trades` tables
- WAL `fills_YYYYMMDD.jsonl`

Only run after linkage fixes are deployed.

---

## 7) Monitoring + Guardrails

**Add validation checks** (daily):
- Unlinked executions in last 24h
- Trades stuck in `PENDING` > 10 minutes
- Executions with `system='unknown'`

**Alert channel**: NTFY existing alert topic.

---

## Acceptance Criteria

1. All three strategies write to `executions` and `trades_v2`.
2. `executions.trade_id` populated for all fills.
3. `trades_v2` transitions to `CLOSED` for completed trades.
4. No `fe_sendauth` errors in logs.
5. `system` column reflects correct strategy.

