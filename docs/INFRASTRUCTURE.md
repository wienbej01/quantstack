# Infrastructure Reference

> Consolidated from: IBKR_IB_INSYNC_CONNECTION_PROTOCOL, TRADE_DATABASE, AUDIT_LOGGING, AUDIT_QUICK_REF
>
> Last updated: 2026-02-10

---

## 1. IBKR Connection Protocol

All services connect to IBKR Gateway via `qx_broker.ibkr` (ib_insync-based).

### Gateway
- Host: `127.0.0.1:7494` (paper trading)
- Must be running and authenticated before services start
- Check: `ss -ltn | grep :7494`

### Client ID Ranges

| Service | Range | Notes |
|---------|-------|-------|
| l2-collector | 1–99 | Data collection |
| intraday-paper | 100–199 | Paper trading |
| l2-scalping | 200–299 | Live scalping (data + orders) |
| l2-vwap-reversion | 300–399 | VWAP strategy (data + orders) |
| monitoring/health | 900–999 | Health checks, preflight |

Rules: never reuse IDs concurrently. On reconnect, increment within range.

### Session Lifecycle
1. Gateway readiness check (`ibkr-gateway-ready.service`)
2. Create `IBKRSession` with single event loop thread
3. All IBKR calls via `session.call(...)` — never from worker threads
4. Set `IB.RequestTimeout` and `IB.RaiseRequestErrors=True`

### Key Modules (`qx_broker/ibkr/`)
- `connection.py` — event loop + session lifecycle
- `market_data.py` — L1 market data
- `market_depth.py` — L2 depth
- `orders.py` — order placement and tracking
- `account.py` — positions, account summary, PnL
- `health.py` — data freshness + connectivity checks

---

## 2. Trade Database (PostgreSQL)

Database: `trading`, user: `jacobw`

### Schema (`cpapi/schema.sql`)

**executions** — Source of truth. Immutable fill log, deduplicated by `exec_id`.

| Column | Type | Key fields |
|--------|------|------------|
| exec_id | VARCHAR(50) PK | IBKR execution ID |
| ibkr_time | TIMESTAMPTZ | IBKR execution timestamp |
| symbol | VARCHAR(10) | Ticker |
| system | VARCHAR(20) | l2-scalping, l2-vwap, etc. |
| side | VARCHAR(4) | BUY / SELL |
| quantity | INTEGER | Shares filled |
| price | DECIMAL(12,4) | Fill price |
| trade_id | UUID | Link to trades_v2 |
| source | VARCHAR(20) | CALLBACK, POLL, RECONCILE |

**trades_v2** — Denormalized trade records (entry/exit prices, PnL, metadata).

**positions** — Current position state per service/symbol.

**shared_positions** — Cross-service position ledger (Feb 9 fix). Used for global margin budget.

**trade_order_links** — Maps IBKR order IDs to trade IDs.

### Triple-Layer Fill Capture
1. **Callback** — immediate fill notification from ib_insync
2. **Polling** — periodic `reqExecutions()` sweep
3. **Reconciliation** — end-of-day cross-reference with IBKR API logs

### WAL Durability
Fills written to `logs/wal/fills_YYYYMMDD.jsonl` before DB insert. Survives DB outages.

### Key Queries
```sql
-- Today's fills
SELECT * FROM executions WHERE ibkr_time::date = CURRENT_DATE ORDER BY ibkr_time;

-- Orphaned fills (no trade link)
SELECT * FROM executions WHERE trade_id IS NULL AND ibkr_time::date = CURRENT_DATE;

-- Today's trades
SELECT * FROM trades_v2 WHERE entry_time::date = CURRENT_DATE ORDER BY entry_time;

-- Cross-service positions
SELECT * FROM shared_positions;
```

---

## 3. Audit Logging

### Log Files
Location: `logs/audit/`
- `audit_YYYY-MM-DD.jsonl` — structured JSON Lines
- `audit_YYYY-MM-DD.log` — human-readable timeline

### Core Library (`cpapi/audit_logger.py`)
```python
from cpapi.audit_logger import get_audit_logger
_audit = get_audit_logger("l2-scalping")
_audit.trade_open(symbol, side, qty, price, trade_id)
_audit.trade_close(symbol, side, qty, price, pnl, trade_id)
```

### Service Wrapper (`scripts/audit_wrapper.sh`)
Wraps systemd service commands. Tracks START/READY/STOP lifecycle, captures resource metrics, records exit codes.

### Query Tools
```bash
python3 scripts/query_audit.py                          # Today
python3 scripts/query_audit.py --date 2026-02-09        # Specific date
python3 scripts/query_audit.py --service l2-scalping    # Filter by service
python3 scripts/analyze_failures.py                     # Failure statistics
```

---

## 4. Emergency Alerts (`cpapi/emergency_alerts.py`)

Rate-limited NTFY alerts for critical failures. Added as part of Feb 9 incident fix.

| Alert | Trigger | Topic |
|-------|---------|-------|
| Exit failed | 3 exit attempts exhausted | `jacobw-trading-status` |
| Margin breach | Entry blocked by margin check | `jacobw-trading-status` |
| CPU spike | >90% CPU for 30s | `jacobw-trading-status` |

---

## 5. Shared Position Ledger (`cpapi/shared_positions.py`)

Cross-service position awareness via PostgreSQL `shared_positions` table. Added as part of Feb 9 incident fix.

- Each service writes positions on entry/exit
- Global margin cap: 80% of account equity across all services
- PostgreSQL advisory lock for atomic check-and-reserve
- Startup reconciliation cross-references IBKR positions

---

## 6. Margin Check (`cpapi/margin_check.py`)

Pre-trade margin verification using IBKR `whatIfOrder`. Added as part of Feb 9 incident fix.

- Queries IBKR for margin impact before every entry
- Requires 50% headroom over margin impact
- 30-second cache to avoid hammering IBKR
- Used by both l2-scalping and l2-vwap-reversion
