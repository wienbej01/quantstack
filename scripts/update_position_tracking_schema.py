#!/usr/bin/env python3
"""
Database Schema Update Script for L2 Scalping Position Tracking Fix

Updates the PostgreSQL schema to support enhanced trade tracking with:
- Order intent and trade_id linkage
- Fill to trade_id linkage  
- Trade TP/SL price and order ID tracking
"""

import logging
import sys
from pathlib import Path

# Add intraday_stack to path for event store access
_intraday_path = str(
    Path(__file__).parent.parent.parent.parent / "intraday_stack" / "src"
)
if _intraday_path not in sys.path:
    sys.path.append(_intraday_path)

try:
    from journal.event_store import EventStore

    SHARED_EVENT_STORE = True
except ImportError:
    SHARED_EVENT_STORE = False
    print("Could not import shared event store")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def update_database_schema():
    """Update database schema for enhanced position tracking"""

    if not SHARED_EVENT_STORE:
        logger.error("Shared event store not available")
        return False

    try:
        # Initialize event store
        event_store = EventStore()

        if not hasattr(event_store, "conn") or not event_store.conn:
            logger.error("No database connection available")
            return False

        conn = event_store.conn
        cursor = conn.cursor()

        logger.info("Starting database schema update...")

        # Orders table enhancements
        orders_updates = [
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS intent TEXT",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS parent_order_id INTEGER",
            "ALTER TABLE orders ADD COLUMN IF NOT EXISTS trade_id TEXT",
        ]

        # Fills table enhancements
        fills_updates = [
            "ALTER TABLE fills ADD COLUMN IF NOT EXISTS trade_id TEXT",
            "ALTER TABLE fills ADD COLUMN IF NOT EXISTS is_partial BOOLEAN DEFAULT FALSE",
        ]

        # Trades table enhancements
        trades_updates = [
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_price REAL",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS sl_price REAL",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS tp_order_id INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS sl_order_id INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS entry_order_id INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS exit_order_id INTEGER",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS partial_fills INTEGER DEFAULT 0",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS avg_entry_price REAL",
            "ALTER TABLE trades ADD COLUMN IF NOT EXISTS avg_exit_price REAL",
        ]

        # Execute all updates
        all_updates = orders_updates + fills_updates + trades_updates

        for sql in all_updates:
            try:
                logger.info(f"Executing: {sql}")
                cursor.execute(sql)
            except Exception as e:
                logger.warning(f"Failed to execute {sql}: {e}")

        # Create indexes for performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_orders_trade_id ON orders(trade_id)",
            "CREATE INDEX IF NOT EXISTS idx_orders_intent ON orders(intent)",
            "CREATE INDEX IF NOT EXISTS idx_fills_trade_id ON fills(trade_id)",
            "CREATE INDEX IF NOT EXISTS idx_trades_entry_order_id ON trades(entry_order_id)",
            "CREATE INDEX IF NOT EXISTS idx_trades_tp_order_id ON trades(tp_order_id)",
            "CREATE INDEX IF NOT EXISTS idx_trades_sl_order_id ON trades(sl_order_id)",
        ]

        for sql in indexes:
            try:
                logger.info(f"Creating index: {sql}")
                cursor.execute(sql)
            except Exception as e:
                logger.warning(f"Failed to create index: {e}")

        # Commit changes
        conn.commit()
        logger.info("Database schema update completed successfully")
        return True

    except Exception as e:
        logger.error(f"Failed to update database schema: {e}")
        if "conn" in locals():
            conn.rollback()
        return False


if __name__ == "__main__":
    success = update_database_schema()
    if success:
        print("✅ Database schema updated successfully")
        sys.exit(0)
    else:
        print("❌ Database schema update failed")
        sys.exit(1)
