#!/usr/bin/env python3
"""
Analyze January 9th trading results for L2 scalping reliability.
"""

import sqlite3
from datetime import datetime

import pandas as pd


def analyze_jan9_results():
    """Analyze Jan 9 results for L2 scalping reliability."""

    db_path = "/home/jacobw/intraday_stack/data/journal/events.db"
    conn = sqlite3.connect(db_path)

    # Get all trades
    all_trades = pd.read_sql_query("SELECT * FROM trades", conn)

    # Filter for Jan 9 trades (entry or exit on Jan 9)
    all_trades["entry_date"] = pd.to_datetime(all_trades["entry_time"]).dt.date
    all_trades["exit_date"] = pd.to_datetime(all_trades["exit_time"]).dt.date

    jan9_date = pd.to_datetime("2026-01-09").date()
    jan9_trades = all_trades[
        (all_trades["entry_date"] == jan9_date) | (all_trades["exit_date"] == jan9_date)
    ]

    print("=== JANUARY 9TH TRADING ANALYSIS ===\n")
    print(f"Total trades in database: {len(all_trades)}")
    print(f"Jan 9 related trades: {len(jan9_trades)}")

    if len(jan9_trades) == 0:
        print("No trades found for January 9th")
        return

    # System breakdown
    print(f"\n--- BY SYSTEM ---")
    system_summary = (
        jan9_trades.groupby("system")
        .agg({"net_pnl": ["count", "sum", "mean"], "symbol": "nunique"})
        .round(2)
    )
    print(system_summary)

    # Check for corruption indicators
    print(f"\n--- CORRUPTION ANALYSIS ---")

    # 1. Zero P&L trades (the known bug)
    zero_pnl = jan9_trades[jan9_trades["net_pnl"] == 0.0]
    print(
        f"Zero P&L trades: {len(zero_pnl)}/{len(jan9_trades)} ({len(zero_pnl)/len(jan9_trades)*100:.1f}%)"
    )

    # 2. Identical entry/exit prices (position sync bug)
    same_price = jan9_trades[jan9_trades["entry_price"] == jan9_trades["exit_price"]]
    print(
        f"Same entry/exit price: {len(same_price)}/{len(jan9_trades)} ({len(same_price)/len(jan9_trades)*100:.1f}%)"
    )

    # 3. Manual closes (overnight positions)
    manual_closes = jan9_trades[jan9_trades["exit_reason"] == "MANUAL_CLOSE"]
    print(
        f"Manual closes: {len(manual_closes)}/{len(jan9_trades)} ({len(manual_closes)/len(jan9_trades)*100:.1f}%)"
    )

    # 4. System attribution issues
    unknown_system = jan9_trades[jan9_trades["system"] == "unknown"]
    print(
        f"Unknown system: {len(unknown_system)}/{len(jan9_trades)} ({len(unknown_system)/len(jan9_trades)*100:.1f}%)"
    )

    # L2 scalping specific analysis
    l2_trades = jan9_trades[jan9_trades["system"] == "l2-scalping"]

    print(f"\n--- L2 SCALPING RELIABILITY ---")
    print(f"L2 scalping trades: {len(l2_trades)}")

    if len(l2_trades) > 0:
        # Performance metrics
        l2_pnl = l2_trades["net_pnl"]
        wins = (l2_pnl > 0).sum()
        losses = (l2_pnl < 0).sum()
        win_rate = wins / len(l2_pnl) * 100 if len(l2_pnl) > 0 else 0

        print(f"Win rate: {win_rate:.1f}% ({wins}W/{losses}L)")
        print(f"Total P&L: ${l2_pnl.sum():.2f}")
        print(f"Avg P&L: ${l2_pnl.mean():.2f}")

        if wins > 0:
            print(f"Avg win: ${l2_pnl[l2_pnl > 0].mean():.2f}")
        if losses > 0:
            print(f"Avg loss: ${l2_pnl[l2_pnl < 0].mean():.2f}")

        # Check for corruption in L2 trades
        l2_zero_pnl = l2_trades[l2_trades["net_pnl"] == 0.0]
        l2_same_price = l2_trades[l2_trades["entry_price"] == l2_trades["exit_price"]]
        l2_manual = l2_trades[l2_trades["exit_reason"] == "MANUAL_CLOSE"]

        print(f"\nL2 Corruption indicators:")
        print(f"  Zero P&L: {len(l2_zero_pnl)}/{len(l2_trades)}")
        print(f"  Same price: {len(l2_same_price)}/{len(l2_trades)}")
        print(f"  Manual close: {len(l2_manual)}/{len(l2_trades)}")

        # Show sample L2 trades
        print(f"\nSample L2 trades:")
        for _, trade in l2_trades.head(3).iterrows():
            print(
                f"  {trade['symbol']}: ${trade['entry_price']:.2f} -> ${trade['exit_price']:.2f} = ${trade['net_pnl']:.2f} ({trade['exit_reason']})"
            )

    # Check fills data for price validation
    fills_df = pd.read_sql_query(
        "SELECT * FROM fills WHERE date(timestamp) = '2026-01-09'", conn
    )

    print(f"\n--- PRICE DATA VALIDATION ---")
    print(f"Jan 9 fills: {len(fills_df)}")

    if len(fills_df) > 0:
        # Check for suspicious price patterns
        price_duplicates = fills_df.groupby(["symbol", "price"]).size()
        suspicious = price_duplicates[price_duplicates > 5]

        print(f"Suspicious price duplicates: {len(suspicious)}")
        if len(suspicious) > 0:
            print("Top suspicious prices:")
            for (symbol, price), count in suspicious.head(3).items():
                print(f"  {symbol} @ ${price}: {count} times")

        # Price range
        print(
            f"Price range: ${fills_df['price'].min():.2f} - ${fills_df['price'].max():.2f}"
        )

    # Timeline analysis
    print(f"\n--- TIMELINE ANALYSIS ---")

    # Convert to ET for analysis
    jan9_trades["entry_hour"] = pd.to_datetime(jan9_trades["entry_time"]).dt.hour
    jan9_trades["exit_hour"] = pd.to_datetime(jan9_trades["exit_time"]).dt.hour

    # Check for after-hours activity
    after_hours_entries = jan9_trades[
        (jan9_trades["entry_hour"] < 9) | (jan9_trades["entry_hour"] >= 16)
    ]
    after_hours_exits = jan9_trades[
        (jan9_trades["exit_hour"] < 9) | (jan9_trades["exit_hour"] >= 16)
    ]

    print(f"After-hours entries: {len(after_hours_entries)}")
    print(f"After-hours exits: {len(after_hours_exits)}")

    # Show trading window
    if len(jan9_trades) > 0:
        first_entry = jan9_trades["entry_time"].min()
        last_exit = jan9_trades["exit_time"].max()
        print(f"Trading window: {first_entry} to {last_exit}")

    conn.close()

    # Reliability assessment
    print(f"\n=== RELIABILITY ASSESSMENT ===")

    corruption_score = 0
    total_trades = len(jan9_trades)

    if total_trades == 0:
        print("❌ NO DATA - Cannot assess reliability")
        return

    # Score corruption indicators
    zero_pnl_pct = len(zero_pnl) / total_trades
    same_price_pct = len(same_price) / total_trades
    manual_close_pct = len(manual_closes) / total_trades
    unknown_system_pct = len(unknown_system) / total_trades

    if zero_pnl_pct > 0.5:
        corruption_score += 3
        print(f"❌ HIGH CORRUPTION: {zero_pnl_pct*100:.1f}% zero P&L trades")
    elif zero_pnl_pct > 0.2:
        corruption_score += 2
        print(f"⚠️  MEDIUM CORRUPTION: {zero_pnl_pct*100:.1f}% zero P&L trades")
    elif zero_pnl_pct > 0:
        corruption_score += 1
        print(f"⚠️  MINOR CORRUPTION: {zero_pnl_pct*100:.1f}% zero P&L trades")

    if same_price_pct > 0.8:
        corruption_score += 3
        print(f"❌ POSITION SYNC BUG: {same_price_pct*100:.1f}% same entry/exit prices")
    elif same_price_pct > 0.5:
        corruption_score += 2
        print(
            f"⚠️  POSITION SYNC ISSUES: {same_price_pct*100:.1f}% same entry/exit prices"
        )

    if manual_close_pct > 0.8:
        corruption_score += 2
        print(f"⚠️  OVERNIGHT POSITIONS: {manual_close_pct*100:.1f}% manual closes")

    if unknown_system_pct > 0.5:
        corruption_score += 1
        print(f"⚠️  ATTRIBUTION ISSUES: {unknown_system_pct*100:.1f}% unknown system")

    # Final assessment
    if corruption_score == 0:
        print("✅ L2 SCALPING RESULTS ARE RELIABLE")
    elif corruption_score <= 2:
        print("⚠️  L2 SCALPING RESULTS HAVE MINOR ISSUES")
    elif corruption_score <= 4:
        print("❌ L2 SCALPING RESULTS ARE MODERATELY CORRUPTED")
    else:
        print("❌ L2 SCALPING RESULTS ARE SEVERELY CORRUPTED")

    print(f"Corruption score: {corruption_score}/10")

    # Specific L2 assessment
    if len(l2_trades) > 0:
        l2_corruption = 0
        if len(l2_zero_pnl) > 0:
            l2_corruption += 2
        if len(l2_same_price) > 0:
            l2_corruption += 2
        if len(l2_manual) > len(l2_trades) * 0.5:
            l2_corruption += 1

        print(f"\nL2 Scalping specific assessment:")
        if l2_corruption == 0:
            print("✅ L2 scalping data appears clean and reliable")
        elif l2_corruption <= 2:
            print("⚠️  L2 scalping has minor data issues")
        else:
            print("❌ L2 scalping data is corrupted")


if __name__ == "__main__":
    analyze_jan9_results()
