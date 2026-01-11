#!/usr/bin/env python3
"""
Emergency EOD Position Closer - Backup System

Runs independently via systemd timer at 3:55 PM ET (10 min after primary flatten).
Forces database closure of any remaining open positions even if IBKR Gateway is down.

This is a LAST RESORT backup to ensure no overnight positions.
"""

import logging
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

import pytz

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("/home/jacobw/quantstack/logs/emergency_eod.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def emergency_close_positions():
    """Emergency close all open positions - runs even if IBKR is down."""

    now_et = datetime.now(ET)
    logger.info(f"EMERGENCY EOD CHECK: {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # Only run on weekdays during market hours
    if now_et.weekday() >= 5:
        logger.info("Weekend - skipping")
        return

    # Only run after 3:50 PM ET
    if now_et.time().hour < 15 or (
        now_et.time().hour == 15 and now_et.time().minute < 50
    ):
        logger.info("Too early - skipping")
        return

    # Get open positions from database (direct SQL - no dependencies)
    db_path = "/home/jacobw/intraday_stack/data/journal/events.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
    open_trades = [dict(row) for row in cursor.fetchall()]

    if not open_trades:
        logger.info("✓ No open positions - all clear")
        conn.close()
        return

    # CRITICAL: Open positions found after primary flatten time
    logger.error(
        f"⚠️  EMERGENCY: {len(open_trades)} OPEN POSITIONS FOUND AFTER 3:50 PM ET"
    )

    for trade in open_trades:
        logger.error(
            f"  OPEN: {trade['trade_id']} | {trade['symbol']} | {trade['system']} | "
            f"entry@{trade['entry_price']:.4f} | age={trade['entry_time']}"
        )

    # Force close in database (we can't rely on IBKR at this point)
    for trade in open_trades:
        # Use entry price as exit (conservative - no P&L)
        exit_price = trade["entry_price"]
        exit_time = datetime.utcnow().isoformat()

        logger.warning(
            f"FORCE CLOSING: {trade['symbol']} (trade_id={trade['trade_id']})"
        )

        # Calculate hold time
        entry_time = datetime.fromisoformat(trade["entry_time"])
        hold_time = (datetime.utcnow() - entry_time).total_seconds()

        # Update trade to CLOSED
        cursor.execute(
            """
            UPDATE trades SET
                exit_time = ?,
                exit_price = ?,
                exit_qty = ?,
                exit_reason = 'EMERGENCY_EOD',
                gross_pnl = 0.0,
                net_pnl = 0.0,
                commission = 0.0,
                hold_time_seconds = ?,
                status = 'CLOSED'
            WHERE trade_id = ?
        """,
            (exit_time, exit_price, trade["entry_qty"], hold_time, trade["trade_id"]),
        )

        logger.warning(f"  ✓ Force closed {trade['symbol']} at {exit_price:.4f}")

    conn.commit()
    conn.close()

    logger.error(
        f"⚠️  EMERGENCY CLOSE COMPLETE: {len(open_trades)} positions force-closed"
    )

    # Send alert via ntfy
    try:
        import requests

        requests.post(
            "https://ntfy.sh/jacobw-trading-alerts",
            data=f"EMERGENCY EOD: Force closed {len(open_trades)} positions after IBKR failure".encode(
                "utf-8"
            ),
            headers={"Priority": "urgent", "Tags": "warning"},
        )
    except:
        pass


if __name__ == "__main__":
    try:
        emergency_close_positions()
    except Exception as e:
        logger.error(f"Emergency close failed: {e}", exc_info=True)
        sys.exit(1)
