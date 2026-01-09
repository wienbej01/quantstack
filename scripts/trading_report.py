#!/usr/bin/env python3
"""
Trading Performance Report - Per Strategy Audit

Generates comprehensive trade reports from event store with:
- Per-strategy performance breakdown
- Trade-by-trade audit trail
- Daily/weekly/monthly summaries
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, List
import json

def get_trades(db_path: str, date: str = None) -> List[Dict]:
    """Get all trades, optionally filtered by date."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if date:
        query = """
        SELECT * FROM trades 
        WHERE DATE(entry_time) = ? 
        ORDER BY entry_time DESC
        """
        cursor.execute(query, (date,))
    else:
        query = "SELECT * FROM trades ORDER BY entry_time DESC"
        cursor.execute(query)
    
    trades = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return trades


def get_fills(db_path: str, trade_id: str) -> List[Dict]:
    """Get fills for a specific trade."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM fills WHERE trade_id = ? ORDER BY timestamp", (trade_id,))
    fills = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return fills


def calculate_strategy_stats(trades: List[Dict]) -> Dict[str, Dict]:
    """Calculate per-strategy statistics."""
    stats = {}
    
    for trade in trades:
        strategy = trade['strategy']
        system = trade.get('system', 'unknown')
        key = f"{system}:{strategy}"
        
        if key not in stats:
            stats[key] = {
                'system': system,
                'strategy': strategy,
                'total_trades': 0,
                'open_trades': 0,
                'closed_trades': 0,
                'wins': 0,
                'losses': 0,
                'gross_pnl': 0.0,
                'net_pnl': 0.0,
                'commission': 0.0,
                'long_trades': 0,
                'short_trades': 0,
            }
        
        s = stats[key]
        s['total_trades'] += 1
        
        if trade['status'] == 'OPEN':
            s['open_trades'] += 1
        else:
            s['closed_trades'] += 1
            s['gross_pnl'] += trade['gross_pnl'] or 0.0
            s['net_pnl'] += trade['net_pnl'] or 0.0
            s['commission'] += trade['commission'] or 0.0
            
            if (trade['net_pnl'] or 0.0) > 0:
                s['wins'] += 1
            elif (trade['net_pnl'] or 0.0) < 0:
                s['losses'] += 1
        
        if trade['direction'] == 'long':
            s['long_trades'] += 1
        else:
            s['short_trades'] += 1
    
    # Calculate win rate
    for key, s in stats.items():
        if s['closed_trades'] > 0:
            s['win_rate'] = s['wins'] / s['closed_trades'] * 100
        else:
            s['win_rate'] = 0.0
    
    return stats


def print_report(trades: List[Dict], db_path: str, date: str = None):
    """Print comprehensive trading report."""
    print("=" * 80)
    print("TRADING PERFORMANCE REPORT")
    if date:
        print(f"Date: {date}")
    else:
        print("All Time")
    print("=" * 80)
    print()
    
    # Overall summary
    total_trades = len(trades)
    open_trades = sum(1 for t in trades if t['status'] == 'OPEN')
    closed_trades = sum(1 for t in trades if t['status'] == 'CLOSED')
    total_pnl = sum(t['net_pnl'] or 0.0 for t in trades if t['status'] == 'CLOSED')
    
    print(f"Total Trades: {total_trades}")
    print(f"Open: {open_trades} | Closed: {closed_trades}")
    print(f"Total Net P&L: ${total_pnl:,.2f}")
    print()
    
    # Per-strategy breakdown
    stats = calculate_strategy_stats(trades)
    
    print("PER-SYSTEM PERFORMANCE")
    print("-" * 80)
    for key, s in stats.items():
        print(f"\n[{s['system'].upper()}] {s['strategy'].upper()}")
        print(f"  Trades: {s['total_trades']} (Open: {s['open_trades']}, Closed: {s['closed_trades']})")
        print(f"  Direction: Long {s['long_trades']} | Short {s['short_trades']}")
        print(f"  Win Rate: {s['win_rate']:.1f}% ({s['wins']}W / {s['losses']}L)")
        print(f"  Gross P&L: ${s['gross_pnl']:,.2f}")
        print(f"  Commission: ${s['commission']:,.2f}")
        print(f"  Net P&L: ${s['net_pnl']:,.2f}")
    
    print()
    print("=" * 80)
    print("TRADE-BY-TRADE AUDIT")
    print("=" * 80)
    
    # Trade details
    for trade in trades:
        status_icon = "🟢" if trade['status'] == 'OPEN' else "🔴"
        pnl_icon = "✅" if (trade['net_pnl'] or 0) > 0 else "❌" if (trade['net_pnl'] or 0) < 0 else "⚪"
        system = trade.get('system', 'unknown')
        
        print(f"\n{status_icon} [{system}] {trade['symbol']} | {trade['strategy']} | {trade['direction'].upper()}")
        print(f"   Trade ID: {trade['trade_id']}")
        print(f"   Entry: {trade['entry_time']} @ ${trade['entry_price']:.2f} x {trade['entry_qty']}")
        
        if trade['status'] == 'CLOSED':
            print(f"   Exit:  {trade['exit_time']} @ ${trade['exit_price']:.2f} x {trade['exit_qty']}")
            print(f"   Reason: {trade['exit_reason']}")
            print(f"   Hold: {trade['hold_time_seconds']:.0f}s")
            print(f"   {pnl_icon} Net P&L: ${trade['net_pnl']:,.2f} (Gross: ${trade['gross_pnl']:,.2f}, Comm: ${trade['commission']:,.2f})")
        else:
            print(f"   Status: OPEN")
    
    print()
    print("=" * 80)


def export_csv(trades: List[Dict], output_path: str):
    """Export trades to CSV."""
    import csv
    
    if not trades:
        print("No trades to export")
        return
    
    with open(output_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=trades[0].keys())
        writer.writeheader()
        writer.writerows(trades)
    
    print(f"Exported {len(trades)} trades to {output_path}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate trading performance report")
    parser.add_argument("--db", default="/home/jacobw/intraday_stack/data/journal/events.db", help="Event store database path")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--export", help="Export to CSV file")
    parser.add_argument("--strategy", help="Filter by strategy")
    
    args = parser.parse_args()
    
    trades = get_trades(args.db, args.date)
    
    if args.strategy:
        trades = [t for t in trades if t['strategy'] == args.strategy]
    
    print_report(trades, args.db, args.date)
    
    if args.export:
        export_csv(trades, args.export)
