#!/usr/bin/env python3
"""Analyze overnight gap performance for power hour entries."""

from pathlib import Path

import pandas as pd


def analyze_overnight_gaps(trades_csv: Path):
    """Analyze overnight gap contribution to P&L.

    Args:
        trades_csv: Path to trades CSV file
    """
    trades = pd.read_csv(trades_csv)

    if trades.empty:
        print("No trades found")
        return

    print("=" * 80)
    print("OVERNIGHT GAP ANALYSIS")
    print("=" * 80)

    # Convert timestamps
    trades["entry_time"] = pd.to_datetime(trades["entry_time"])
    trades["exit_time"] = pd.to_datetime(trades["exit_time"])

    # Identify overnight holds
    trades["entry_date"] = trades["entry_time"].dt.date
    trades["exit_date"] = trades["exit_time"].dt.date
    trades["is_overnight"] = trades["entry_date"] != trades["exit_date"]

    overnight_trades = trades[trades["is_overnight"]]
    intraday_trades = trades[~trades["is_overnight"]]

    print(f"\nTotal trades: {len(trades)}")
    print(
        f"Overnight holds: {len(overnight_trades)} ({len(overnight_trades)/len(trades)*100:.1f}%)"
    )
    print(
        f"Intraday exits: {len(intraday_trades)} ({len(intraday_trades)/len(trades)*100:.1f}%)"
    )

    if len(overnight_trades) > 0:
        print("\n## OVERNIGHT HOLD PERFORMANCE")
        print(f"Total P&L: ${overnight_trades['pnl'].sum():,.2f}")
        print(f"Avg P&L: ${overnight_trades['pnl'].mean():,.2f}")
        print(f"Win rate: {(overnight_trades['pnl'] > 0).mean():.1%}")
        print(f"Best trade: ${overnight_trades['pnl'].max():,.2f}")
        print(f"Worst trade: ${overnight_trades['pnl'].min():,.2f}")

    if len(intraday_trades) > 0:
        print("\n## INTRADAY EXIT PERFORMANCE")
        print(f"Total P&L: ${intraday_trades['pnl'].sum():,.2f}")
        print(f"Avg P&L: ${intraday_trades['pnl'].mean():,.2f}")
        print(f"Win rate: {(intraday_trades['pnl'] > 0).mean():.1%}")

    # Entry hour distribution
    print("\n## ENTRY HOUR DISTRIBUTION")
    trades["entry_hour"] = trades["entry_time"].dt.hour
    hour_dist = trades.groupby("entry_hour").size()
    for hour, count in hour_dist.items():
        print(f"  {hour:02d}:00 - {count} trades ({count/len(trades)*100:.1f}%)")

    # Power hour entries
    power_hour_trades = trades[trades["entry_hour"] == 15]
    if len(power_hour_trades) > 0:
        print("\n## POWER HOUR ENTRIES (3 PM)")
        print(f"Total: {len(power_hour_trades)} trades")
        print(
            f"Overnight: {power_hour_trades['is_overnight'].sum()} ({power_hour_trades['is_overnight'].mean():.1%})"
        )
        print(f"P&L: ${power_hour_trades['pnl'].sum():,.2f}")
        print(f"Win rate: {(power_hour_trades['pnl'] > 0).mean():.1%}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python analyze_overnight_gaps.py <trades_csv>")
        sys.exit(1)

    analyze_overnight_gaps(Path(sys.argv[1]))
