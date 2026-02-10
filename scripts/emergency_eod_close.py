#!/usr/bin/env python3
"""
Emergency EOD Position Closer - Backup System

Runs independently via systemd timer at 3:55 PM ET (10 min after primary flatten).
Forces database closure of any remaining open positions even if IBKR Gateway is down.

This is a LAST RESORT backup to ensure no overnight positions.
"""

import logging
import sys
from datetime import datetime, timezone
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

    # Step 1: Cancel all open orders via IBKR
    try:
        from ib_insync import IB, MarketOrder
        ib = IB()
        ib.connect('127.0.0.1', 7494, clientId=997)
        
        open_orders = ib.openOrders()
        if open_orders:
            logger.warning(f"⚠️  CANCELLING {len(open_orders)} OPEN ORDERS")
            for order in open_orders:
                ib.cancelOrder(order)
                logger.warning(f"  Cancelled: {order.orderRef} (ID={order.orderId})")
        else:
            logger.info("✓ No open orders")

        # Force close live positions if possible
        try:
            positions = ib.positions()
            live_positions = [p for p in positions if getattr(p, "position", 0) != 0]
            if live_positions:
                logger.error(f"⚠️  IBKR POSITIONS FOUND: {len(live_positions)}")
                for pos in live_positions:
                    qty = int(pos.position)
                    action = "SELL" if qty > 0 else "BUY"
                    order = MarketOrder(action, abs(qty))
                    ib.placeOrder(pos.contract, order)
                    logger.warning(f"  MKT CLOSE: {pos.contract.symbol} {action} {abs(qty)}")
            else:
                logger.info("✓ No IBKR positions")
        except Exception as e:
            logger.error(f"Failed to close live positions via IBKR: {e}")
        
        ib.disconnect()
    except Exception as e:
        logger.error(f"Failed to cancel orders via IBKR: {e}")

    # Step 2: Get open positions from database
    import psycopg2
    conn = psycopg2.connect(database='trading', user='jacobw')
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM trades WHERE status = 'OPEN'")
    columns = [desc[0] for desc in cursor.description]
    open_trades = [dict(zip(columns, row)) for row in cursor.fetchall()]

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
            f"  OPEN: {trade.get('trade_id')} | {trade.get('symbol')} | {trade.get('system', 'unknown')} | "
            f"entry@{trade.get('entry_price', 0.0):.4f} | age={trade.get('entry_time')}"
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
        hold_time = (datetime.now(timezone.utc) - entry_time).total_seconds()

        # Update trade to CLOSED
        cursor.execute(
            """
            UPDATE trades SET
                exit_time = %s,
                exit_price = %s,
                exit_qty = %s,
                exit_reason = 'EMERGENCY_EOD',
                gross_pnl = 0.0,
                net_pnl = 0.0,
                commission = 0.0,
                hold_time_seconds = %s,
                status = 'CLOSED'
            WHERE trade_id = %s
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
