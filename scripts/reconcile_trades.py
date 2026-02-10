#!/usr/bin/env python3
"""
Trade-by-Trade Reconciliation Report

Reconciles TradeDB, Audit Log, and IBKR API logs at the individual trade level.
Validates: order matching, price accuracy, quantity, PnL calculations, slippage.

Usage:
    python3 reconcile_trades.py --date 2026-02-02 --ibkr-log /path/to/api-exported-logs.txt
    python3 reconcile_trades.py --date 2026-02-02 --ibkr-dir /home/jacobw/IBKRlogs
    python3 reconcile_trades.py --date 2026-02-02  # auto-detect IBKR log location
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import psycopg2
import pytz

ET = pytz.timezone("America/New_York")
AUDIT_DIR = Path.home() / "quantstack" / "logs" / "audit"
IBKR_LOG_DIR = Path.home() / "IBKRlogs"
REPORT_DIR = Path.home() / "quantstack" / "logs" / "reconciliation"

# Tolerances
PRICE_TOLERANCE = 0.01  # $0.01 for price matching
PNL_TOLERANCE = 1.00    # $1.00 for PnL matching
SLIPPAGE_TOLERANCE = 0.02  # $0.02 for slippage


def get_db_trades(date_str: str) -> list[dict]:
    """Get all trade fields from TradeDB."""
    try:
        conn = psycopg2.connect(dbname="trading", host="localhost")
        cur = conn.cursor()
        cur.execute("""
            SELECT trade_id, symbol, direction, system, strategy,
                   entry_time, exit_time, entry_order_id, exit_order_id,
                   entry_price, exit_price, entry_qty, exit_qty,
                   signal_entry_price, gross_pnl, net_pnl, commission,
                   entry_slippage, exit_slippage, hold_time_seconds, exit_reason
            FROM trades
            WHERE entry_time LIKE %s
            ORDER BY entry_time
        """, (f"{date_str}%",))
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
        cur.close()
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except psycopg2.Error as e:
        print(f"ERROR: Database connection failed: {e}", file=sys.stderr)
        return []


def get_audit_events(date_str: str) -> dict:
    """Get trade events from audit log indexed by trade_id."""
    jsonl_path = AUDIT_DIR / f"audit_{date_str}.jsonl"
    events = {"opens": {}, "closes": {}}
    
    if not jsonl_path.exists():
        return events
    
    with open(jsonl_path) as f:
        for line in f:
            try:
                e = json.loads(line.strip())
                ctx = e.get("context", {})
                tid = ctx.get("trade_id")
                if not tid:
                    continue
                if e.get("event_type") == "TRADE_OPEN":
                    events["opens"][tid] = e
                elif e.get("event_type") == "TRADE_CLOSE":
                    events["closes"][tid] = e
            except json.JSONDecodeError:
                continue
    return events


def parse_ibkr_fills(ibkr_log_path: str) -> dict:
    """Parse IBKR fills indexed by order_id."""
    fills_by_order = defaultdict(list)
    if not ibkr_log_path or not Path(ibkr_log_path).exists():
        return fills_by_order
    
    pattern = re.compile(r'\[11;2;([^\]]+)\]')
    seen_exec_ids = set()
    
    with open(ibkr_log_path) as f:
        for line in f:
            match = pattern.search(line)
            if not match:
                continue
            fields = match.group(1).split(';')
            if len(fields) < 24:
                continue
            
            exec_id = fields[12]
            if exec_id in seen_exec_ids:
                continue  # Skip duplicate reports
            seen_exec_ids.add(exec_id)
            
            try:
                fill = {
                    "order_id": int(fields[0]),
                    "symbol": fields[2],
                    "exec_id": exec_id,
                    "time": fields[13],
                    "exchange": fields[15],
                    "side": fields[16],
                    "qty": int(fields[17]),
                    "price": float(fields[18]),
                    "perm_id": fields[19],
                    "cum_qty": int(fields[21]),
                    "avg_price": float(fields[22]),
                    "order_ref": fields[23] if len(fields) > 23 else "",
                }
                fills_by_order[fill["order_id"]].append(fill)
            except (ValueError, IndexError):
                continue
    
    return fills_by_order


def compute_ibkr_vwap(fills: list) -> tuple:
    """Compute VWAP and total qty from fills."""
    if not fills:
        return None, 0
    total_value = sum(f["qty"] * f["price"] for f in fills)
    total_qty = sum(f["qty"] for f in fills)
    return total_value / total_qty if total_qty else None, total_qty


def reconcile_trade(trade: dict, ibkr_fills: dict, audit: dict) -> dict:
    """Reconcile a single trade against IBKR and audit log."""
    tid = trade["trade_id"]
    result = {
        "trade_id": tid,
        "trade_id_short": tid[:8],
        "symbol": trade["symbol"],
        "direction": trade["direction"],
        "system": trade["system"],
        "strategy": trade["strategy"],
        "entry_time": trade["entry_time"],
        "exit_time": trade["exit_time"],
        "issues": [],
        "warnings": [],
        "checks": {},
    }
    
    # --- IBKR Entry Reconciliation ---
    entry_order_id = trade.get("entry_order_id")
    entry_fills = ibkr_fills.get(entry_order_id, []) if entry_order_id else []
    
    result["checks"]["has_entry_order_id"] = bool(entry_order_id)
    result["checks"]["has_ibkr_entry_fills"] = bool(entry_fills)
    
    if not entry_order_id:
        result["issues"].append("MISSING_ENTRY_ORDER_ID: No entry_order_id in TradeDB")
    elif not entry_fills:
        result["issues"].append(f"NO_IBKR_ENTRY_FILLS: order_id={entry_order_id} not found in IBKR log")
    else:
        ibkr_vwap, ibkr_qty = compute_ibkr_vwap(entry_fills)
        db_entry_price = float(trade["entry_price"]) if trade["entry_price"] else None
        db_entry_qty = trade["entry_qty"]
        signal_price = float(trade["signal_entry_price"]) if trade["signal_entry_price"] else None
        
        result["entry_db_price"] = db_entry_price
        result["entry_ibkr_vwap"] = ibkr_vwap
        result["entry_ibkr_qty"] = ibkr_qty
        result["entry_db_qty"] = db_entry_qty
        result["entry_signal_price"] = signal_price
        result["entry_fill_count"] = len(entry_fills)
        result["entry_exchanges"] = list(set(f["exchange"] for f in entry_fills))
        
        # Quantity check
        result["checks"]["entry_qty_match"] = (ibkr_qty == db_entry_qty)
        if ibkr_qty != db_entry_qty:
            result["issues"].append(f"ENTRY_QTY_MISMATCH: DB={db_entry_qty} IBKR={ibkr_qty}")
        
        # Price check
        if db_entry_price and ibkr_vwap:
            price_diff = abs(db_entry_price - ibkr_vwap)
            result["entry_price_diff"] = price_diff
            result["checks"]["entry_price_match"] = (price_diff <= PRICE_TOLERANCE)
            if price_diff > PRICE_TOLERANCE:
                result["issues"].append(
                    f"ENTRY_PRICE_MISMATCH: DB={db_entry_price:.4f} IBKR_VWAP={ibkr_vwap:.4f} diff={price_diff:.4f}"
                )
        
        # Slippage verification
        if signal_price and ibkr_vwap:
            if trade["direction"] == "long":
                actual_slip = ibkr_vwap - signal_price
            else:
                actual_slip = signal_price - ibkr_vwap
            
            db_slip = float(trade["entry_slippage"]) if trade["entry_slippage"] else 0
            slip_diff = abs(actual_slip - db_slip)
            
            result["entry_actual_slippage"] = actual_slip
            result["entry_db_slippage"] = db_slip
            result["checks"]["entry_slippage_match"] = (slip_diff <= SLIPPAGE_TOLERANCE)
            
            if slip_diff > SLIPPAGE_TOLERANCE:
                result["warnings"].append(
                    f"ENTRY_SLIPPAGE_DIFF: recorded={db_slip:.4f} actual={actual_slip:.4f}"
                )
    
    # --- IBKR Exit Reconciliation ---
    exit_order_id = trade.get("exit_order_id")
    result["checks"]["has_exit_order_id"] = bool(exit_order_id)
    
    if trade["exit_time"]:
        exit_fills = ibkr_fills.get(exit_order_id, []) if exit_order_id else []
        result["checks"]["has_ibkr_exit_fills"] = bool(exit_fills)
        
        if exit_order_id and not exit_fills:
            result["warnings"].append(f"NO_IBKR_EXIT_FILLS: order_id={exit_order_id}")
        elif exit_fills:
            ibkr_exit_vwap, ibkr_exit_qty = compute_ibkr_vwap(exit_fills)
            db_exit_price = float(trade["exit_price"]) if trade["exit_price"] else None
            db_exit_qty = trade["exit_qty"]
            
            result["exit_db_price"] = db_exit_price
            result["exit_ibkr_vwap"] = ibkr_exit_vwap
            result["exit_ibkr_qty"] = ibkr_exit_qty
            result["exit_db_qty"] = db_exit_qty
            result["exit_fill_count"] = len(exit_fills)
            
            # Quantity check
            result["checks"]["exit_qty_match"] = (ibkr_exit_qty == db_exit_qty)
            if ibkr_exit_qty != db_exit_qty:
                result["issues"].append(f"EXIT_QTY_MISMATCH: DB={db_exit_qty} IBKR={ibkr_exit_qty}")
            
            # Price check
            if db_exit_price and ibkr_exit_vwap:
                price_diff = abs(db_exit_price - ibkr_exit_vwap)
                result["exit_price_diff"] = price_diff
                result["checks"]["exit_price_match"] = (price_diff <= PRICE_TOLERANCE)
                if price_diff > PRICE_TOLERANCE:
                    result["issues"].append(
                        f"EXIT_PRICE_MISMATCH: DB={db_exit_price:.4f} IBKR_VWAP={ibkr_exit_vwap:.4f}"
                    )
    
    # --- PnL Verification ---
    if trade["exit_time"] and trade["entry_price"] and trade["exit_price"]:
        entry_p = float(trade["entry_price"])
        exit_p = float(trade["exit_price"])
        qty = trade["exit_qty"] or trade["entry_qty"]
        
        if trade["direction"] == "long":
            expected_pnl = (exit_p - entry_p) * qty
        else:
            expected_pnl = (entry_p - exit_p) * qty
        
        db_pnl = float(trade["gross_pnl"]) if trade["gross_pnl"] else 0
        pnl_diff = abs(expected_pnl - db_pnl)
        
        result["pnl_db"] = db_pnl
        result["pnl_calculated"] = expected_pnl
        result["pnl_diff"] = pnl_diff
        result["checks"]["pnl_match"] = (pnl_diff <= PNL_TOLERANCE)
        
        if pnl_diff > PNL_TOLERANCE:
            result["issues"].append(
                f"PNL_MISMATCH: DB={db_pnl:.2f} calculated={expected_pnl:.2f} diff={pnl_diff:.2f}"
            )
        
        # Verify PnL using IBKR prices if available
        if result.get("entry_ibkr_vwap") and result.get("exit_ibkr_vwap"):
            if trade["direction"] == "long":
                ibkr_pnl = (result["exit_ibkr_vwap"] - result["entry_ibkr_vwap"]) * qty
            else:
                ibkr_pnl = (result["entry_ibkr_vwap"] - result["exit_ibkr_vwap"]) * qty
            result["pnl_ibkr"] = ibkr_pnl
    
    # --- Audit Log Reconciliation ---
    audit_open = audit["opens"].get(tid)
    audit_close = audit["closes"].get(tid)
    
    result["checks"]["has_audit_open"] = bool(audit_open)
    result["checks"]["has_audit_close"] = bool(audit_close) or not trade["exit_time"]
    
    if not audit_open:
        result["warnings"].append("NO_AUDIT_OPEN_EVENT")
    else:
        audit_ctx = audit_open.get("context", {})
        result["audit_open_symbol"] = audit_ctx.get("symbol")
        result["audit_open_qty"] = audit_ctx.get("qty")
        result["audit_open_price"] = audit_ctx.get("price")
        
        if audit_ctx.get("symbol") != trade["symbol"]:
            result["issues"].append(
                f"AUDIT_SYMBOL_MISMATCH: DB={trade['symbol']} audit={audit_ctx.get('symbol')}"
            )
    
    if trade["exit_time"] and not audit_close:
        result["warnings"].append("NO_AUDIT_CLOSE_EVENT")
    elif audit_close:
        audit_ctx = audit_close.get("context", {})
        result["audit_close_price"] = audit_ctx.get("price")
        result["audit_close_pnl"] = audit_ctx.get("pnl")
    
    # --- Final Status ---
    result["status"] = "PASS" if not result["issues"] else "FAIL"
    if result["status"] == "PASS" and result["warnings"]:
        result["status"] = "WARN"
    
    return result


def find_ibkr_log(date_str: str, ibkr_log: str = None, ibkr_dir: str = None) -> str | None:
    """Find IBKR log file for a given date."""
    if ibkr_log and Path(ibkr_log).exists():
        return ibkr_log
    
    # Try standard location: /home/jacobw/IBKRlogs/YYYYMMDD/api-exported-logs.txt
    base_dir = Path(ibkr_dir) if ibkr_dir else IBKR_LOG_DIR
    date_folder = date_str.replace("-", "")
    standard_path = base_dir / date_folder / "api-exported-logs.txt"
    
    if standard_path.exists():
        return str(standard_path)
    
    return None


def save_report(report: dict, date_str: str):
    """Save reconciliation report to JSON file."""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"reconciliation_{date_str}.json"
    
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    
    return report_path


def run_reconciliation(date_str: str, ibkr_log: str = None, ibkr_dir: str = None, save: bool = True):
    """Run full trade-by-trade reconciliation."""
    timestamp = datetime.now(ET)
    
    print(f"\n{'='*80}")
    print(f"TRADE-BY-TRADE RECONCILIATION REPORT - {date_str}")
    print(f"Generated: {timestamp.strftime('%Y-%m-%d %H:%M:%S ET')}")
    print(f"{'='*80}\n")
    
    # Find IBKR log
    ibkr_log_path = find_ibkr_log(date_str, ibkr_log, ibkr_dir)
    
    # Load data
    db_trades = get_db_trades(date_str)
    audit = get_audit_events(date_str)
    ibkr_fills = parse_ibkr_fills(ibkr_log_path) if ibkr_log_path else {}
    
    print(f"Data Sources:")
    print(f"  TradeDB:    {len(db_trades)} trades")
    print(f"  Audit Log:  {len(audit['opens'])} opens, {len(audit['closes'])} closes")
    print(f"  IBKR Log:   {len(ibkr_fills)} unique orders with fills")
    if ibkr_log_path:
        print(f"              ({ibkr_log_path})")
    else:
        print(f"              (not found)")
    print()
    
    if not db_trades:
        print("No trades found for this date.")
        return {"date": date_str, "total": 0, "results": []}
    
    # Reconcile each trade
    results = []
    for trade in db_trades:
        result = reconcile_trade(trade, ibkr_fills, audit)
        results.append(result)
    
    # Summary counts
    passed = sum(1 for r in results if r["status"] == "PASS")
    warned = sum(1 for r in results if r["status"] == "WARN")
    failed = sum(1 for r in results if r["status"] == "FAIL")
    
    print(f"{'='*80}")
    print(f"RECONCILIATION SUMMARY")
    print(f"{'='*80}")
    print(f"  PASS: {passed}  |  WARN: {warned}  |  FAIL: {failed}  |  Total: {len(results)}")
    print()
    
    # Detail by status
    if failed > 0:
        print(f"{'='*80}")
        print("FAILED TRADES (require investigation)")
        print(f"{'='*80}")
        for r in results:
            if r["status"] == "FAIL":
                print(f"\n[{r['trade_id_short']}] {r['symbol']} {r['direction']} ({r['system']})")
                print(f"    Entry: {r.get('entry_time', 'N/A')}")
                for issue in r["issues"]:
                    print(f"    ❌ {issue}")
                for warn in r["warnings"]:
                    print(f"    ⚠️  {warn}")
    
    if warned > 0:
        print(f"\n{'='*80}")
        print("WARNINGS (review recommended)")
        print(f"{'='*80}")
        for r in results:
            if r["status"] == "WARN":
                print(f"\n[{r['trade_id_short']}] {r['symbol']} {r['direction']} ({r['system']})")
                for warn in r["warnings"]:
                    print(f"    ⚠️  {warn}")
    
    if passed > 0:
        print(f"\n{'='*80}")
        print("PASSED TRADES")
        print(f"{'='*80}")
        for r in results:
            if r["status"] == "PASS":
                pnl_str = f"PnL=${r.get('pnl_db', 0):.2f}" if r.get('pnl_db') is not None else ""
                print(f"  ✓ [{r['trade_id_short']}] {r['symbol']} {r['direction']} {pnl_str}")
    
    # Data integrity checks
    print(f"\n{'='*80}")
    print("DATA INTEGRITY CHECKS")
    print(f"{'='*80}")
    
    # Check for orphan IBKR orders
    db_order_ids = set()
    for t in db_trades:
        if t.get("entry_order_id"):
            db_order_ids.add(t["entry_order_id"])
        if t.get("exit_order_id"):
            db_order_ids.add(t["exit_order_id"])
    
    orphan_orders = set(ibkr_fills.keys()) - db_order_ids
    trading_orphans = []
    for oid in orphan_orders:
        fills = ibkr_fills[oid]
        if fills and any("SCALP" in f.get("order_ref", "") or "reversal" in f.get("order_ref", "") 
                        or "ENTRY" in f.get("order_ref", "") for f in fills):
            trading_orphans.append({
                "order_id": oid,
                "symbol": fills[0]["symbol"],
                "side": fills[0]["side"],
                "fill_count": len(fills),
                "total_qty": sum(f["qty"] for f in fills),
                "order_ref": fills[0].get("order_ref", ""),
            })
    
    if trading_orphans:
        print(f"  ⚠️  ORPHAN IBKR ORDERS (fills with no DB trade): {len(trading_orphans)}")
        for o in trading_orphans[:10]:
            print(f"      order_id={o['order_id']} {o['symbol']} {o['side']} qty={o['total_qty']}")
    else:
        print(f"  ✓ No orphan IBKR orders detected")
    
    # Check for DB trades with no IBKR fills
    no_fills = [r for r in results if not r["checks"].get("has_ibkr_entry_fills")]
    if no_fills:
        print(f"  ⚠️  DB TRADES WITH NO IBKR FILLS: {len(no_fills)}")
        for r in no_fills[:5]:
            print(f"      [{r['trade_id_short']}] {r['symbol']}")
    else:
        print(f"  ✓ All DB trades have IBKR fills")
    
    # Audit coverage
    audit_open_count = sum(1 for r in results if r["checks"].get("has_audit_open"))
    audit_close_count = sum(1 for r in results if r["checks"].get("has_audit_close"))
    closed_trades = sum(1 for r in results if r.get("exit_time"))
    
    audit_open_pct = audit_open_count / len(results) * 100 if results else 0
    audit_close_pct = audit_close_count / closed_trades * 100 if closed_trades else 100
    
    print(f"  {'✓' if audit_open_pct == 100 else '⚠️'} Audit OPEN coverage: {audit_open_pct:.1f}% ({audit_open_count}/{len(results)})")
    print(f"  {'✓' if audit_close_pct == 100 else '⚠️'} Audit CLOSE coverage: {audit_close_pct:.1f}% ({audit_close_count}/{closed_trades})")
    
    # Price accuracy summary
    price_matches = sum(1 for r in results if r["checks"].get("entry_price_match"))
    price_checked = sum(1 for r in results if "entry_price_match" in r["checks"])
    if price_checked:
        print(f"  {'✓' if price_matches == price_checked else '⚠️'} Entry price accuracy: {price_matches}/{price_checked} trades match IBKR VWAP")
    
    # PnL accuracy summary
    pnl_matches = sum(1 for r in results if r["checks"].get("pnl_match"))
    pnl_checked = sum(1 for r in results if "pnl_match" in r["checks"])
    if pnl_checked:
        print(f"  {'✓' if pnl_matches == pnl_checked else '⚠️'} PnL accuracy: {pnl_matches}/{pnl_checked} trades verified")
    
    print(f"\n{'='*80}")
    print(f"RECONCILIATION COMPLETE")
    print(f"{'='*80}\n")
    
    # Build report
    report = {
        "date": date_str,
        "generated_at": timestamp.isoformat(),
        "sources": {
            "trade_db": len(db_trades),
            "audit_opens": len(audit["opens"]),
            "audit_closes": len(audit["closes"]),
            "ibkr_orders": len(ibkr_fills),
            "ibkr_log_path": ibkr_log_path,
        },
        "summary": {
            "total": len(results),
            "passed": passed,
            "warned": warned,
            "failed": failed,
            "audit_open_coverage_pct": audit_open_pct,
            "audit_close_coverage_pct": audit_close_pct,
            "orphan_ibkr_orders": len(trading_orphans),
        },
        "orphan_orders": trading_orphans,
        "results": results,
    }
    
    # Save report
    if save:
        report_path = save_report(report, date_str)
        print(f"Report saved to: {report_path}\n")
    
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trade-by-Trade Reconciliation")
    parser.add_argument("--date", default=datetime.now(ET).strftime("%Y-%m-%d"),
                        help="Date to reconcile (YYYY-MM-DD)")
    parser.add_argument("--ibkr-log", help="Path to IBKR API exported log file")
    parser.add_argument("--ibkr-dir", help="Base directory for IBKR logs (default: ~/IBKRlogs)")
    parser.add_argument("--no-save", action="store_true", help="Don't save report to file")
    args = parser.parse_args()
    
    run_reconciliation(args.date, args.ibkr_log, args.ibkr_dir, save=not args.no_save)
