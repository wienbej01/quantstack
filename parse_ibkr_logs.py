#!/usr/bin/env python3
"""
Parse IBKR API and Portal logs to find why orders didn't fill.
"""
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def parse_api_log(log_file):
    """Parse IBKR API log file"""
    orders = []
    rejections = []

    with open(log_file, "r", errors="ignore") as f:
        for line in f:
            # Look for order submissions
            if "placeOrder" in line or "Order" in line:
                orders.append(line.strip())

            # Look for rejections/errors
            if "reject" in line.lower() or "error" in line.lower():
                rejections.append(line.strip())

    return orders, rejections


def parse_portal_log(log_file):
    """Parse IBKR Portal log file"""
    events = []

    with open(log_file, "r", errors="ignore") as f:
        for line in f:
            if any(kw in line.lower() for kw in ["order", "reject", "cancel", "fill"]):
                events.append(line.strip())

    return events


def analyze_logs(log_dir):
    """Analyze all IBKR logs in directory"""
    log_dir = Path(log_dir)

    print("=" * 80)
    print("IBKR LOG ANALYSIS - Jan 23, 2026")
    print("=" * 80)

    # Find log files
    api_logs = list(log_dir.glob("*api*.log*")) + list(log_dir.glob("*API*.log*"))
    portal_logs = list(log_dir.glob("*portal*.log*")) + list(
        log_dir.glob("*Portal*.log*")
    )
    all_logs = list(log_dir.glob("*.log*"))

    print(f"\nFound {len(all_logs)} log files:")
    print(f"  API logs: {len(api_logs)}")
    print(f"  Portal logs: {len(portal_logs)}")
    print(f"  Other logs: {len(all_logs) - len(api_logs) - len(portal_logs)}")

    if not all_logs:
        print("\n❌ No log files found")
        print(f"Place IBKR logs in: {log_dir}")
        return

    # Parse all logs
    all_orders = []
    all_rejections = []
    all_events = []

    for log_file in all_logs:
        print(f"\nParsing: {log_file.name}")

        try:
            with open(log_file, "r", errors="ignore") as f:
                content = f.read()

                # Count key events
                order_count = content.lower().count("order")
                reject_count = content.lower().count("reject")
                cancel_count = content.lower().count("cancel")
                fill_count = content.lower().count("fill")
                error_count = content.lower().count("error")

                print(f"  Orders mentioned: {order_count}")
                print(f"  Rejections: {reject_count}")
                print(f"  Cancellations: {cancel_count}")
                print(f"  Fills: {fill_count}")
                print(f"  Errors: {error_count}")

                # Extract relevant lines
                for line in content.split("\n"):
                    line_lower = line.lower()

                    if "placeorder" in line_lower or "submit" in line_lower:
                        all_orders.append(line.strip())

                    if "reject" in line_lower or "error" in line_lower:
                        all_rejections.append(line.strip())

                    if any(kw in line_lower for kw in ["ioc", "immediate", "cancel"]):
                        all_events.append(line.strip())

        except Exception as e:
            print(f"  ⚠ Error reading file: {e}")

    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)

    print(f"\nTotal order submissions found: {len(all_orders)}")
    print(f"Total rejections/errors found: {len(all_rejections)}")
    print(f"Total IOC-related events: {len(all_events)}")

    if all_orders:
        print("\n--- Sample Order Submissions ---")
        for order in all_orders[:10]:
            print(f"  {order[:150]}")

    if all_rejections:
        print("\n--- Sample Rejections/Errors ---")
        for rej in all_rejections[:20]:
            print(f"  {rej[:150]}")

    if all_events:
        print("\n--- Sample IOC Events ---")
        for event in all_events[:10]:
            print(f"  {event[:150]}")

    # Key findings
    print("\n" + "=" * 80)
    print("KEY FINDINGS")
    print("=" * 80)

    if len(all_orders) == 0:
        print("\n❌ NO ORDERS FOUND IN IBKR LOGS")
        print("Orders were never sent to IBKR!")
        print("\nThis means the problem is in YOUR code, not IBKR:")
        print("  - Orders not being generated")
        print("  - Orders rejected before sending")
        print("  - Connection issue preventing order submission")

    elif len(all_orders) > 0 and len(all_rejections) > 0:
        print(f"\n⚠️  {len(all_orders)} orders sent, {len(all_rejections)} rejections")
        print("Orders reached IBKR but were rejected")
        print("Check rejection reasons above")

    elif len(all_orders) > 0 and len(all_rejections) == 0:
        print(f"\n✓ {len(all_orders)} orders sent, no explicit rejections")
        print("Orders may have been cancelled due to IOC expiry")
        print("This supports the 'buffer too small' hypothesis")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        log_dir = sys.argv[1]
    else:
        log_dir = "/home/jacobw/quantstack/ibkr_logs_jan23"

    print(f"Looking for IBKR logs in: {log_dir}")
    analyze_logs(log_dir)
