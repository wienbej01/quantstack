# Forensic Audit Report — Trading Outage (2026-01-21 ET)

## Scope & Evidence Reviewed
- System docs: `/home/jacobw/quantstack/docs/SYSTEM_GUIDE.md`, `/home/jacobw/quantstack/docs/L2_SCALPING_SYSTEM_DESIGN.md`
- Systemd units: `/etc/systemd/system/l2-scalping.service`, `/etc/systemd/system/intraday-paper.service`
- Strategy configs and runtime logs for 2026-01-21 (ET)

## Timeline (ET, 2026-01-21)
- intraday-paper started **09:28**, safe‑start until **09:35**, then crashed with Postgres error and exited; restarted **09:57** and exited again **10:29**. Source: `/home/jacobw/intraday_stack/logs/paper_20260121.log`
- l2-scalping hit IBKR client‑ID/depth errors at **09:26–09:27**, then repeated `KeyError` in pattern execution and later DB duplicate‑key errors; daily report shows 0 trades. Sources: `/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log`, `/home/jacobw/quantstack/l2_scalping/logs/daily_report_2026-01-21.txt`

## Root Causes (Blocking)

### 1) EventStore SQL corruption (orders/fills/risk)
**Impact**: Any order/fill/risk event logging will hard‑fail, aborting DB transactions and breaking runtime paths that rely on logging.

**Evidence**: `/home/jacobw/intraday_stack/src/journal/event_store.py:429-504`
- SQL strings contain literal Python lines (`ph = ...`) and `fINSERT` tokens inside the SQL string.

### 2) Decision ID collisions + transaction poisoning
**Impact**: Duplicate `event_id` collisions trigger `UniqueViolation`, which poisons the transaction; subsequent inserts fail with `InFailedSqlTransaction`. This blocks l2‑scalping during `_on_market_data` and prevents trades.

**Evidence**:
- ID truncation: `/home/jacobw/intraday_stack/src/journal/event_store.py:351`
- Error sequence: `/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log` around **10:07:19 ET**

### 3) Intraday‑paper Postgres insert fails on numpy types
**Impact**: `log_decision()` fails with `InvalidSchemaName: schema "np" does not exist`, crashing intraday‑paper and aborting reporting with `InFailedSqlTransaction`.

**Evidence**:
- Crash trace: `/home/jacobw/intraday_stack/logs/paper_20260121.log`

### 4) L2 scalping config key mismatch
**Impact**: `KeyError: 'max_hold_seconds'` during pattern execution; repeated exceptions reduce/no trading.

**Evidence**:
- Error: `/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log`
- Config structure: `/home/jacobw/quantstack/l2_scalping/config/strategy.yaml:4-20`

### 5) L2 scalping account_id placeholder
**Impact**: `account.account_id` is `DU123456`. This likely causes order rejections once trades are attempted (docs show `DUN575068`).

**Evidence**:
- Config: `/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml:20-22`
- Docs: `/home/jacobw/quantstack/docs/SYSTEM_GUIDE.md`

## Contributing Risks (High Impact)
- intraday‑paper `Restart=no`, so any crash halts trading for the day. Source: `/etc/systemd/system/intraday-paper.service`
- IBKR errors **326/309** at open indicate client‑ID conflicts and depth subscription exhaustion, blocking L2 data at the open. Source: `/home/jacobw/quantstack/l2_scalping/logs/scalping_system.log`

## Additional Defects (Non‑blocking but critical)
- Postgres path in `get_summary_for_date()` uses SQLite `?` placeholders; `get_trade_stats()` builds invalid SQL when `date_str` is `None`. These will break reporting/monitoring.
  - `/home/jacobw/intraday_stack/src/journal/event_store.py:542-570`, `:720+`

## Access Gap
- Could not read `/etc/systemd/system/intraday-paper.env` (permission denied). If you want a full env audit, I can request elevated read access.

---

**Status**: Audit complete. Awaiting approval to begin remediation.
