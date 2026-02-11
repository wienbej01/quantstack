#!/usr/bin/env python3
"""Nightly validation of trade recording integrity."""

import subprocess
import sys
from datetime import datetime, timedelta

import psycopg2


def send_ntfy_alert(title: str, message: str, priority: str = "default"):
    """Send NTFY notification for validation failures."""
    try:
        subprocess.run(
            [
                "curl",
                "-H",
                f"Title: {title}",
                "-H",
                f"Priority: {priority}",
                "-H",
                "Tags: warning,database",
                "-d",
                message,
                "ntfy.sh/quantstack_alerts",
            ],
            capture_output=True,
            timeout=5,
        )
    except Exception as e:
        print(f"Failed to send NTFY alert: {e}")


def validate_fills_have_trades():
    """Check that all fills have corresponding trades."""
    conn = psycopg2.connect(database="trading", user="jacobw")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT 
            f.symbol,
            COUNT(*) as fill_count,
            COUNT(DISTINCT t.trade_id) as trade_count
        FROM fills f
        LEFT JOIN trades t ON (
            f.order_id = t.entry_order_id OR 
            f.order_id = t.exit_order_id
        )
        WHERE f.timestamp::date >= CURRENT_DATE - INTERVAL '7 days'
        GROUP BY f.symbol
        HAVING COUNT(*) > COUNT(DISTINCT t.trade_id) * 2
    """
    )

    issues = cursor.fetchall()
    cursor.close()
    conn.close()

    if issues:
        print("⚠️  ORPHANED FILLS DETECTED:")
        msg_lines = ["Orphaned fills detected:"]
        for symbol, fills, trades in issues:
            line = f"  {symbol}: {fills} fills but only {trades} trades"
            print(line)
            msg_lines.append(f"{symbol}: {fills} fills, {trades} trades")

        send_ntfy_alert("Trade Recording Issue", "\n".join(msg_lines), priority="high")
        return False

    print("✅ All fills have corresponding trades")
    return True


def validate_exit_prices():
    """Check for suspicious exit prices."""
    conn = psycopg2.connect(database="trading", user="jacobw")
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT trade_id, symbol, entry_price, exit_price, system
        FROM trades
        WHERE entry_time::date >= CURRENT_DATE - INTERVAL '7 days'
          AND status = 'CLOSED'
          AND entry_price = exit_price
          AND gross_pnl = 0
    """
    )

    issues = cursor.fetchall()
    cursor.close()
    conn.close()

    if issues:
        print("⚠️  ZERO-SLIPPAGE EXITS DETECTED:")
        msg_lines = ["Zero-slippage exits detected:"]
        for trade_id, symbol, entry, exit, system in issues:
            line = f"  {system} {symbol}: entry={entry} exit={exit}"
            print(line)
            msg_lines.append(f"{system} {symbol}: ${entry}")

        send_ntfy_alert("Exit Price Issue", "\n".join(msg_lines), priority="high")
        return False

    print("✅ No suspicious exit prices")
    return True


def validate_l2_recording():
    """Check L2 system specifically for fills without trades."""
    conn = psycopg2.connect(database="trading", user="jacobw")
    cursor = conn.cursor()

    # Count L2 fills today
    cursor.execute(
        """
        SELECT COUNT(*) FROM fills 
        WHERE timestamp::date = CURRENT_DATE
        AND symbol IN (
            SELECT DISTINCT symbol FROM trades 
            WHERE system = 'l2-scalping' 
            AND entry_time::date >= CURRENT_DATE - INTERVAL '7 days'
        )
    """
    )
    l2_fills = cursor.fetchone()[0]

    # Count L2 trades today
    cursor.execute(
        """
        SELECT COUNT(*) FROM trades 
        WHERE system = 'l2-scalping' 
        AND entry_time::date = CURRENT_DATE
    """
    )
    l2_trades = cursor.fetchone()[0]

    cursor.close()
    conn.close()

    if l2_fills > 0 and l2_trades == 0:
        msg = f"L2 recording issue: {l2_fills} fills but 0 trades"
        print(f"⚠️  {msg}")
        send_ntfy_alert("L2 Recording Failure", msg, priority="urgent")
        return False

    if l2_fills > 0:
        print(f"✅ L2 recording OK: {l2_fills} fills, {l2_trades} trades")
    else:
        print("ℹ️  No L2 activity today")
    return True


if __name__ == "__main__":
    all_ok = True
    all_ok &= validate_fills_have_trades()
    all_ok &= validate_exit_prices()
    all_ok &= validate_l2_recording()

    if not all_ok:
        sys.exit(1)

    print("\n✅ All validation checks passed")
