#!/usr/bin/env python3
"""Monitor and distinguish activities from multiple trading systems."""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))

from qx_data.live.ibkr_data_tagged import (
    create_quantstack_manager,
    create_system2_manager,
)


def monitor_all_systems():
    """Monitor activities from all trading systems."""

    print("🔍 Multi-System Trading Monitor")
    print("=" * 50)

    # Connect to both systems
    quantstack = create_quantstack_manager()
    system2 = create_system2_manager()

    systems = [
        ("QUANTSTACK", quantstack),
        ("SYSTEM2", system2),
    ]

    for system_name, manager in systems:
        print(f"\n📊 {system_name} Status:")
        print("-" * 30)

        if manager.connect():
            print(f"✅ Connected (Client ID: {manager.client_id})")

            # Get system-specific trades
            trades = manager.get_system_trades()
            print(f"📈 Active Trades: {len(trades)}")

            # Show recent trades with tags
            for trade in trades[-5:]:  # Last 5 trades
                order_ref = trade.order.orderRef or "NO_TAG"
                print(
                    f"  • {trade.contract.symbol}: {trade.order.action} "
                    f"{trade.order.totalQuantity} (ref: {order_ref})"
                )

            # Get positions
            positions = manager.get_system_positions()
            active_positions = [p for p in positions if p.position != 0]
            print(f"💼 Active Positions: {len(active_positions)}")

            for pos in active_positions[:3]:  # Show top 3
                print(f"  • {pos.contract.symbol}: {pos.position} shares")

        else:
            print("❌ Connection failed")

    print(f"\n🕐 Last updated: {datetime.now().strftime('%H:%M:%S')}")


def analyze_order_refs():
    """Analyze order references to distinguish systems."""

    quantstack = create_quantstack_manager()
    if not quantstack.connect():
        print("❌ Cannot connect to analyze orders")
        return

    all_trades = quantstack.ib.trades()

    print("\n🏷️  Order Reference Analysis:")
    print("=" * 40)

    # Group by order reference patterns
    ref_patterns = {}

    for trade in all_trades:
        order_ref = trade.order.orderRef or "NO_TAG"

        # Extract system identifier
        if order_ref.startswith("QUANTSTACK"):
            system = "QUANTSTACK"
        elif order_ref.startswith("SYSTEM2"):
            system = "SYSTEM2"
        else:
            system = "UNKNOWN"

        if system not in ref_patterns:
            ref_patterns[system] = []
        ref_patterns[system].append(
            {
                "symbol": trade.contract.symbol,
                "action": trade.order.action,
                "quantity": trade.order.totalQuantity,
                "ref": order_ref,
                "time": trade.log[-1].time if trade.log else "N/A",
            }
        )

    # Display by system
    for system, trades in ref_patterns.items():
        print(f"\n{system} Trades ({len(trades)}):")
        for trade in trades[-3:]:  # Last 3 per system
            print(
                f"  {trade['time']}: {trade['action']} {trade['quantity']} "
                f"{trade['symbol']} [{trade['ref']}]"
            )


if __name__ == "__main__":
    try:
        monitor_all_systems()
        analyze_order_refs()
    except KeyboardInterrupt:
        print("\n👋 Monitoring stopped")
    except Exception as e:
        print(f"❌ Error: {e}")
