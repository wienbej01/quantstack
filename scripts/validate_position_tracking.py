#!/usr/bin/env python3
"""
Validation Script for L2 Scalping Position Tracking Fix

Tests the new position tracking components to ensure they work correctly.
"""

import sys
import time
from pathlib import Path

# Add l2_scalping src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "l2_scalping" / "src"))

from order_tracker import OrderTracker, TrackedOrder
from position_manager import ManagedPosition, PositionManager


def test_position_manager():
    """Test PositionManager functionality"""
    print("Testing PositionManager...")

    pm = PositionManager()

    # Test creating positions
    pos1 = pm.create_position(
        entry_order_id=1001,
        trade_id="test_trade_1",
        symbol="AAPL",
        direction="long",
        target_qty=100,
    )

    pos2 = pm.create_position(
        entry_order_id=1002,
        trade_id="test_trade_2",
        symbol="AAPL",
        direction="long",
        target_qty=50,
    )

    # Test position retrieval
    assert pm.get_position_by_order(1001) == pos1
    assert pm.get_position_by_order(1002) == pos2
    assert pm.get_position_by_order(9999) is None

    # Test symbol indexing
    aapl_positions = pm.get_positions_for_symbol("AAPL")
    assert len(aapl_positions) == 2
    assert pos1 in aapl_positions
    assert pos2 in aapl_positions

    # Test position checks
    assert pm.has_pending_entry("AAPL") == True
    assert pm.has_open_position("AAPL") == False
    assert pm.count_pending_entries("AAPL") == 2

    # Test fill updates
    updated_pos = pm.update_fill(1001, 50, 150.00)
    assert updated_pos.filled_qty == 50
    assert updated_pos.avg_fill_price == 150.00
    assert updated_pos.status == "PENDING"  # Not fully filled

    # Complete the fill
    pm.update_fill(1001, 50, 151.00)
    assert pos1.filled_qty == 100
    assert abs(pos1.avg_fill_price - 150.50) < 0.01  # Weighted average
    assert pos1.status == "OPEN"  # Fully filled

    # Test TP/SL update timing
    assert pm.can_update_tp_sl(1001) == True
    # Mark TP/SL as placed first
    pos1.tp_sl_placed = True
    pm.mark_tp_sl_updated(1001)
    # Sleep briefly to test buffer
    time.sleep(0.1)
    # Within buffer period, should still be False
    assert pm.can_update_tp_sl(1001) == False  # Within buffer

    # Test position closure
    closed_pos = pm.close_position(1001)
    assert closed_pos.status == "CLOSED"
    assert pm.get_position_by_order(1001) is None
    assert len(pm.get_positions_for_symbol("AAPL")) == 1

    print("✅ PositionManager tests passed")


def test_order_tracker():
    """Test OrderTracker functionality"""
    print("Testing OrderTracker...")

    ot = OrderTracker()

    # Test adding orders
    entry_order = ot.add_order(
        order_id=2001,
        trade_id="test_trade_1",
        symbol="MSFT",
        intent="ENTRY",
        side="BUY",
        quantity=100,
        order_type="MKT",
    )

    tp_order = ot.add_order(
        order_id=2002,
        trade_id="test_trade_1",
        symbol="MSFT",
        intent="TP",
        side="SELL",
        quantity=100,
        order_type="LMT",
        limit_price=155.00,
    )

    sl_order = ot.add_order(
        order_id=2003,
        trade_id="test_trade_1",
        symbol="MSFT",
        intent="SL",
        side="SELL",
        quantity=100,
        order_type="STP",
        stop_price=145.00,
    )

    # Test order retrieval
    assert ot.get_order(2001) == entry_order
    assert ot.get_order(9999) is None

    # Test trade-based queries
    trade_orders = ot.get_orders_for_trade("test_trade_1")
    assert len(trade_orders) == 3

    entry_orders = ot.get_orders_by_intent("test_trade_1", "ENTRY")
    assert len(entry_orders) == 1
    assert entry_orders[0] == entry_order

    # Test convenience methods
    assert ot.is_entry_order(2001) == True
    assert ot.is_exit_order(2002) == True
    assert ot.is_exit_order(2003) == True

    assert ot.get_entry_order_for_trade("test_trade_1") == entry_order
    assert ot.get_tp_order_for_trade("test_trade_1") == tp_order
    assert ot.get_sl_order_for_trade("test_trade_1") == sl_order

    # Test status updates
    updated_order = ot.update_status(2001, "FILLED")
    assert updated_order.status == "FILLED"

    # Test fill updates
    ot.update_fill(2001, 100, 150.50)
    assert entry_order.filled_qty == 100
    assert entry_order.avg_fill_price == 150.50
    assert entry_order.status == "FILLED"

    # Test order ID updates (for TP/SL replacement)
    success = ot.update_order_id(2002, 2004)
    assert success == True
    assert ot.get_order(2002) is None
    assert ot.get_order(2004) is not None
    assert ot.get_tp_order_for_trade("test_trade_1").order_id == 2004

    print("✅ OrderTracker tests passed")


def test_integration():
    """Test integration between components"""
    print("Testing component integration...")

    pm = PositionManager()
    ot = OrderTracker()

    # Simulate signal -> order -> fill -> TP/SL flow
    trade_id = "integration_test_1"

    # 1. Create position when order is placed
    position = pm.create_position(
        entry_order_id=3001,
        trade_id=trade_id,
        symbol="GOOGL",
        direction="long",
        target_qty=25,
    )

    # 2. Track the entry order
    entry_order = ot.add_order(
        order_id=3001,
        trade_id=trade_id,
        symbol="GOOGL",
        intent="ENTRY",
        side="BUY",
        quantity=25,
        order_type="MKT",
    )

    # 3. Simulate partial fill
    pm.update_fill(3001, 15, 2800.00)
    ot.update_fill(3001, 15, 2800.00)

    assert position.filled_qty == 15
    assert position.status == "PENDING"  # Not fully filled
    assert entry_order.filled_qty == 15
    assert entry_order.status == "PARTIALLY_FILLED"

    # 4. Complete the fill
    pm.update_fill(3001, 10, 2805.00)
    ot.update_fill(3001, 25, 2802.00)  # Total average price

    assert position.filled_qty == 25
    assert position.status == "OPEN"
    # Weighted average: (15 * 2800 + 10 * 2805) / 25 = 2802
    assert abs(position.avg_fill_price - 2802.00) < 0.01
    assert entry_order.status == "FILLED"

    # 5. Add TP/SL orders
    tp_order = ot.add_order(
        order_id=3002,
        trade_id=trade_id,
        symbol="GOOGL",
        intent="TP",
        side="SELL",
        quantity=25,
        order_type="LMT",
        limit_price=2806.00,
    )

    sl_order = ot.add_order(
        order_id=3003,
        trade_id=trade_id,
        symbol="GOOGL",
        intent="SL",
        side="SELL",
        quantity=25,
        order_type="STP",
        stop_price=2798.00,
    )

    position.tp_order_id = 3002
    position.sl_order_id = 3003
    position.tp_sl_placed = True

    # 6. Verify complete trade setup
    assert len(ot.get_orders_for_trade(trade_id)) == 3
    assert ot.get_entry_order_for_trade(trade_id) == entry_order
    assert ot.get_tp_order_for_trade(trade_id) == tp_order
    assert ot.get_sl_order_for_trade(trade_id) == sl_order

    print("✅ Integration tests passed")


def main():
    """Run all validation tests"""
    print("🚀 Starting L2 Scalping Position Tracking Validation")
    print("=" * 60)

    try:
        test_position_manager()
        test_order_tracker()
        test_integration()

        print("=" * 60)
        print("✅ All validation tests passed!")
        print("\nThe new position tracking system is ready for deployment.")
        print("\nNext steps:")
        print(
            "1. Run database schema update: python scripts/update_position_tracking_schema.py"
        )
        print("2. Test with paper trading mode")
        print("3. Deploy to live trading")

        return True

    except Exception as e:
        print(f"❌ Validation failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
