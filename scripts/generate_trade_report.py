#!/usr/bin/env python3
"""Generate comprehensive trade report."""

from pathlib import Path

import pandas as pd


def generate_report():
    trades_file = Path("run/rolling_results/trades.csv")
    if not trades_file.exists():
        print(f"ERROR: {trades_file} not found")
        return

    trades = pd.read_csv(trades_file)

    print("=" * 80)
    print("COMPREHENSIVE TRADE REPORT")
    print("=" * 80)

    # Overall metrics
    print(f"\n{'OVERALL METRICS':-^80}")
    print(f"Total Trades: {len(trades):,}")
    print(f"Win Rate: {(trades['net_pnl'] > 0).mean():.2%}")
    print(f"Total Net P&L: ${trades['net_pnl'].sum():,.2f}")
    print(f"Total Gross P&L: ${trades['gross_pnl'].sum():,.2f}")
    print(f"Total Fees: ${trades['fee'].sum():,.2f}")
    print(f"Total Spread: ${trades['spread'].sum():,.2f}")
    print(f"Avg Net P&L: ${trades['net_pnl'].mean():.2f}")
    print(f"Avg R-Multiple: {trades['r_multiple'].mean():.2f}R")
    print(f"Median R-Multiple: {trades['r_multiple'].median():.2f}R")

    # By direction
    print(f"\n{'BY DIRECTION':-^80}")
    for side in ["LONG", "SHORT"]:
        side_trades = trades[trades["side"] == side]
        if len(side_trades) == 0:
            continue
        print(f"\n{side}:")
        print(f"  Trades: {len(side_trades):,} ({len(side_trades)/len(trades):.1%})")
        print(f"  Win Rate: {(side_trades['net_pnl'] > 0).mean():.2%}")
        print(f"  Avg Net P&L: ${side_trades['net_pnl'].mean():.2f}")
        print(f"  Avg R-Multiple: {side_trades['r_multiple'].mean():.2f}R")
        print(f"  Total P&L: ${side_trades['net_pnl'].sum():,.2f}")

    # By exit reason
    print(f"\n{'BY EXIT REASON':-^80}")
    for reason in trades["exit_reason"].unique():
        reason_trades = trades[trades["exit_reason"] == reason]
        print(f"\n{reason.upper()}:")
        print(f"  Count: {len(reason_trades):,} ({len(reason_trades)/len(trades):.1%})")
        print(f"  Win Rate: {(reason_trades['net_pnl'] > 0).mean():.2%}")
        print(f"  Avg R: {reason_trades['r_multiple'].mean():.2f}R")
        print(f"  Avg P&L: ${reason_trades['net_pnl'].mean():.2f}")

    # Cost analysis
    print(f"\n{'COST ANALYSIS':-^80}")
    print(f"Total Fees: ${trades['fee'].sum():,.2f}")
    print(f"Total Spread: ${trades['spread'].sum():,.2f}")
    print(f"Total Costs: ${(trades['fee'] + trades['spread']).sum():,.2f}")
    print(f"Avg Cost per Trade: ${(trades['fee'] + trades['spread']).mean():.2f}")
    print(
        f"Cost as % of Gross P&L: {(trades['fee'] + trades['spread']).sum() / trades['gross_pnl'].sum():.2%}"
    )

    # Position sizing
    print(f"\n{'POSITION SIZING':-^80}")
    print(f"Avg Shares: {trades['shares'].mean():.0f}")
    print(f"Median Shares: {trades['shares'].median():.0f}")
    print(f"Min Shares: {trades['shares'].min():.0f}")
    print(f"Max Shares: {trades['shares'].max():.0f}")
    print(f"Avg Entry Price: ${trades['entry_price'].mean():.2f}")
    print(f"Avg Stop Distance: ${trades['stop_distance'].mean():.4f}")
    print(f"Avg ATR: ${trades['atr'].mean():.4f}")

    # Duration analysis
    trades["entry_ts"] = pd.to_datetime(trades["entry_timestamp"])
    trades["exit_ts"] = pd.to_datetime(trades["exit_timestamp"])
    trades["duration_min"] = (
        trades["exit_ts"] - trades["entry_ts"]
    ).dt.total_seconds() / 60

    print(f"\n{'DURATION ANALYSIS':-^80}")
    print(f"Avg Duration: {trades['duration_min'].mean():.1f} minutes")
    print(f"Median Duration: {trades['duration_min'].median():.1f} minutes")
    print(f"Min Duration: {trades['duration_min'].min():.1f} minutes")
    print(f"Max Duration: {trades['duration_min'].max():.1f} minutes")

    # Top performers
    print(f"\n{'TOP 10 TRADES':-^80}")
    top_trades = trades.nlargest(10, "net_pnl")[
        [
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "net_pnl",
            "r_multiple",
            "exit_reason",
        ]
    ]
    print(top_trades.to_string(index=False))

    # Worst performers
    print(f"\n{'BOTTOM 10 TRADES':-^80}")
    bottom_trades = trades.nsmallest(10, "net_pnl")[
        [
            "symbol",
            "side",
            "entry_price",
            "exit_price",
            "net_pnl",
            "r_multiple",
            "exit_reason",
        ]
    ]
    print(bottom_trades.to_string(index=False))

    # Monthly breakdown
    if "oos_month" in trades.columns:
        print(f"\n{'MONTHLY BREAKDOWN':-^80}")
        monthly = (
            trades.groupby("oos_month")
            .agg({"net_pnl": ["count", "sum", "mean"], "r_multiple": "mean"})
            .round(2)
        )
        monthly.columns = ["Trades", "Total P&L", "Avg P&L", "Avg R"]
        monthly["Win Rate"] = (
            trades.groupby("oos_month")
            .apply(lambda x: (x["net_pnl"] > 0).mean())
            .round(3)
        )
        print(monthly.to_string())

    print("\n" + "=" * 80)
    print("REPORT COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    generate_report()
