#!/usr/bin/env python3
"""
Complete Trading Report - Full trade-by-trade analysis

Generates comprehensive report with all trade details:
ticker, strategy, direction, entry/exit times/prices, P&L, fees
"""

import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd


def generate_full_trading_report(
    db_path: str = "/home/jacobw/intraday_stack/data/journal/events.db",
    date: str = None,
) -> pd.DataFrame:
    """Generate complete trading report with all trade details."""

    conn = sqlite3.connect(db_path)

    # Build query
    where_clause = ""
    params = []
    if date:
        where_clause = "WHERE DATE(entry_time) = ?"
        params = [date]

    query = f"""
    SELECT 
        trade_id,
        symbol as ticker,
        strategy,
        system,
        direction,
        entry_time,
        entry_price,
        entry_qty,
        exit_time,
        exit_price,
        exit_qty,
        exit_reason,
        gross_pnl,
        commission as fees,
        net_pnl,
        hold_time_seconds,
        status,
        entry_slippage,
        exit_slippage
    FROM trades 
    {where_clause}
    ORDER BY entry_time DESC
    """

    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if df.empty:
        return df

    # Format columns
    df["entry_time"] = pd.to_datetime(df["entry_time"]).dt.strftime("%Y-%m-%d %H:%M:%S")
    df["exit_time"] = pd.to_datetime(df["exit_time"], errors="coerce").dt.strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # Format prices and P&L
    for col in [
        "entry_price",
        "exit_price",
        "gross_pnl",
        "fees",
        "net_pnl",
        "entry_slippage",
        "exit_slippage",
    ]:
        df[col] = df[col].round(4)

    # Add derived columns
    df["hold_time_min"] = (df["hold_time_seconds"] / 60).round(1)
    df["return_pct"] = (
        (df["exit_price"] - df["entry_price"]) / df["entry_price"] * 100
    ).round(2)
    df["return_pct"] = df.apply(
        lambda x: -x["return_pct"] if x["direction"] == "short" else x["return_pct"],
        axis=1,
    )

    # Reorder columns for better readability
    columns = [
        "trade_id",
        "ticker",
        "strategy",
        "system",
        "direction",
        "status",
        "entry_time",
        "entry_price",
        "entry_qty",
        "exit_time",
        "exit_price",
        "exit_qty",
        "exit_reason",
        "hold_time_min",
        "return_pct",
        "gross_pnl",
        "fees",
        "net_pnl",
        "entry_slippage",
        "exit_slippage",
    ]

    return df[columns]


def print_trading_summary(df: pd.DataFrame):
    """Print summary statistics."""
    if df.empty:
        print("No trades found.")
        return

    closed_trades = df[df["status"] == "CLOSED"]

    print("=" * 100)
    print("TRADING SUMMARY")
    print("=" * 100)
    print(f"Total Trades: {len(df)}")
    print(f"Open: {len(df[df['status'] == 'OPEN'])}")
    print(f"Closed: {len(closed_trades)}")

    if not closed_trades.empty:
        total_pnl = closed_trades["net_pnl"].sum()
        total_fees = closed_trades["fees"].sum()
        winners = len(closed_trades[closed_trades["net_pnl"] > 0])
        losers = len(closed_trades[closed_trades["net_pnl"] < 0])
        win_rate = winners / len(closed_trades) * 100 if len(closed_trades) > 0 else 0

        print(f"Total Net P&L: ${total_pnl:,.2f}")
        print(f"Total Fees: ${total_fees:,.2f}")
        print(f"Win Rate: {win_rate:.1f}% ({winners}W/{losers}L)")
        print(f"Avg P&L per Trade: ${total_pnl/len(closed_trades):,.2f}")
        print(f"Avg Hold Time: {closed_trades['hold_time_min'].mean():.1f} minutes")

        # By system
        print("\nBY SYSTEM:")
        system_summary = (
            closed_trades.groupby("system")
            .agg({"net_pnl": ["count", "sum", "mean"], "fees": "sum"})
            .round(2)
        )
        system_summary.columns = ["Trades", "Total_PnL", "Avg_PnL", "Total_Fees"]
        print(system_summary)

        # By strategy
        print("\nBY STRATEGY:")
        strategy_summary = (
            closed_trades.groupby("strategy")
            .agg({"net_pnl": ["count", "sum", "mean"], "fees": "sum"})
            .round(2)
        )
        strategy_summary.columns = ["Trades", "Total_PnL", "Avg_PnL", "Total_Fees"]
        print(strategy_summary)

    print("=" * 100)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Generate complete trading report")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--export", help="Export to CSV file")
    parser.add_argument(
        "--db",
        default="/home/jacobw/intraday_stack/data/journal/events.db",
        help="Database path",
    )

    args = parser.parse_args()

    # Generate report
    df = generate_full_trading_report(args.db, args.date)

    # Print summary
    print_trading_summary(df)

    if not df.empty:
        print("\nFULL TRADE DETAILS:")
        print("=" * 100)

        # Configure pandas display
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", None)
        pd.set_option("display.max_colwidth", 20)

        print(df.to_string(index=False))

        # Export if requested
        if args.export:
            df.to_csv(args.export, index=False)
            print(f"\nExported to: {args.export}")


if __name__ == "__main__":
    main()
