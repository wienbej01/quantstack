# Trade Reconciliation System

**Version**: 1.0  
**Date**: 2026-02-03  
**Script**: `/home/jacobw/quantstack/scripts/reconcile_trades.py`

## Overview

Trade-by-trade reconciliation validates data integrity across three authoritative sources:

| Source | Location | Purpose |
|--------|----------|---------|
| **TradeDB** | PostgreSQL `trading` | Trade records (entry/exit prices, qty, PnL) |
| **Audit Log** | `~/quantstack/logs/audit/` | Event trail (TRADE_OPEN, TRADE_CLOSE) |
| **IBKR API Log** | `~/IBKRlogs/YYYYMMDD/` | Broker execution data (fills, VWAP) |

## Usage

```bash
# Auto-detect IBKR log location
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02

# Explicit IBKR log path
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02 \
    --ibkr-log /home/jacobw/IBKRlogs/20260202/api-exported-logs.txt

# Custom IBKR log directory
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02 \
    --ibkr-dir /custom/path

# Don't save JSON report
python3 ~/quantstack/scripts/reconcile_trades.py --date 2026-02-02 --no-save
```

## Validation Checks

### Per-Trade Checks

| Check | Description | Tolerance | Severity |
|-------|-------------|-----------|----------|
| `has_entry_order_id` | Entry order ID present in TradeDB | Required | FAIL |
| `has_ibkr_entry_fills` | IBKR fills found for entry order | Required | FAIL |
| `entry_qty_match` | DB qty = IBKR fill qty | Exact | FAIL |
| `entry_price_match` | DB price = IBKR VWAP | $0.01 | FAIL |
| `entry_slippage_match` | Recorded vs actual slippage | $0.02 | WARN |
| `has_exit_order_id` | Exit order ID present (if closed) | Required | WARN |
| `has_ibkr_exit_fills` | IBKR fills found for exit order | Required | WARN |
| `exit_qty_match` | DB qty = IBKR fill qty | Exact | FAIL |
| `exit_price_match` | DB price = IBKR VWAP | $0.01 | FAIL |
| `pnl_match` | DB PnL = calculated PnL | $1.00 | FAIL |
| `has_audit_open` | TRADE_OPEN event in audit log | Present | WARN |
| `has_audit_close` | TRADE_CLOSE event in audit log | Present | WARN |

### Data Integrity Checks

| Check | Description |
|-------|-------------|
| Orphan IBKR Orders | Fills in IBKR log with no matching TradeDB trade |
| Missing IBKR Fills | TradeDB trades with no IBKR fills |
| Audit Open Coverage | % of trades with TRADE_OPEN events |
| Audit Close Coverage | % of closed trades with TRADE_CLOSE events |
| Price Accuracy | % of trades where DB price matches IBKR VWAP |
| PnL Accuracy | % of trades where PnL calculation verified |

## Output

### Console Output
```
================================================================================
TRADE-BY-TRADE RECONCILIATION REPORT - 2026-02-02
Generated: 2026-02-02 20:20:40 ET
================================================================================

Data Sources:
  TradeDB:    16 trades
  Audit Log:  0 opens, 0 closes
  IBKR Log:   679 unique orders with fills

================================================================================
RECONCILIATION SUMMARY
================================================================================
  PASS: 12  |  WARN: 4  |  FAIL: 0  |  Total: 16

...
```

### JSON Report
Saved to: `~/quantstack/logs/reconciliation/reconciliation_YYYY-MM-DD.json`

```json
{
  "date": "2026-02-02",
  "generated_at": "2026-02-02T20:20:40-05:00",
  "sources": {
    "trade_db": 16,
    "audit_opens": 0,
    "audit_closes": 0,
    "ibkr_orders": 679,
    "ibkr_log_path": "/home/jacobw/IBKRlogs/20260202/api-exported-logs.txt"
  },
  "summary": {
    "total": 16,
    "passed": 12,
    "warned": 4,
    "failed": 0,
    "audit_open_coverage_pct": 0.0,
    "audit_close_coverage_pct": 0.0,
    "orphan_ibkr_orders": 0
  },
  "results": [...]
}
```

## Status Codes

| Status | Meaning | Action |
|--------|---------|--------|
| **PASS** | All checks passed | None |
| **WARN** | Minor issues (missing audit events) | Review recommended |
| **FAIL** | Critical issues (price/qty mismatch) | Investigation required |

## IBKR Log Export

IBKR API logs must be exported daily from Gateway:

1. Open IBKR Gateway
2. File > Export API Logs
3. Save to `/home/jacobw/IBKRlogs/YYYYMMDD/api-exported-logs.txt`

The script auto-detects logs in this location based on date.

## Recommended Schedule

Run reconciliation after market close each day:

```bash
# Manual
python3 ~/quantstack/scripts/reconcile_trades.py --date $(date +%F)

# Or add to daily-trade-report timer
```

## Common Issues

### ENTRY_PRICE_MISMATCH
**Cause**: TradeDB recording signal price instead of actual fill price  
**Fix**: Update trade recording to use IBKR fill VWAP

### NO_AUDIT_OPEN_EVENT / NO_AUDIT_CLOSE_EVENT
**Cause**: Audit logging not integrated into trading service  
**Fix**: Add `_audit.trade_open()` / `_audit.trade_close()` calls

### NO_IBKR_ENTRY_FILLS
**Cause**: Order ID mismatch or IBKR log not exported  
**Fix**: Verify order IDs match, export IBKR logs

### Orphan IBKR Orders
**Cause**: Orders placed but not recorded in TradeDB  
**Fix**: Investigate order flow, check for crashes during trade recording

## File Locations

| File | Purpose |
|------|---------|
| `~/quantstack/scripts/reconcile_trades.py` | Reconciliation script |
| `~/quantstack/logs/reconciliation/` | JSON reports |
| `~/quantstack/logs/audit/` | Audit logs (JSONL + human-readable) |
| `~/IBKRlogs/YYYYMMDD/` | IBKR API exported logs |
| PostgreSQL `trading` | Trade database |

## Related Documentation

- [System Guide](SYSTEM_GUIDE.md) - Complete system overview
- [Audit Logging](AUDIT_LOGGING.md) - Audit log format and integration
- [Trade Database](TRADE_DATABASE.md) - TradeDB schema
- [EOD Report](EOD_REPORT.md) - End-of-day performance report
