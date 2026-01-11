#!/usr/bin/env python3
"""Generate detailed trade report from backtest results."""

import sys
from pathlib import Path

import pandas as pd

trades_file = Path("pattern_backtest/output/trades_manual_patterns_180m_overnight.csv")

if not trades_file.exists():
    print(f"ERROR: {trades_file} not found")
    sys.exit(1)

# Load trades
df = pd.read_csv(trades_file)
print(f"Loaded {len(df)} fills")

# Convert timestamps
df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ns")

# Separate buys and sells
buys = df[df["side"] == "BUY"].copy()
sells = df[df["side"] == "SELL"].copy()

print(f"Buys: {len(buys)}")
print(f"Sells: {len(sells)}")

# Match buys to sells by symbol
matched_trades = []

for symbol in buys["symbol"].unique():
    symbol_buys = buys[buys["symbol"] == symbol].sort_values("timestamp")
    symbol_sells = sells[sells["symbol"] == symbol].sort_values("timestamp")

    for _, buy in symbol_buys.iterrows():
        # Find next sell after this buy
        next_sells = symbol_sells[symbol_sells["timestamp"] > buy["timestamp"]]

        if len(next_sells) > 0:
            sell = next_sells.iloc[0]

            # Calculate P&L
            entry_cost = buy["quantity"] * buy["price"] + buy["commission"]
            exit_proceeds = sell["quantity"] * sell["price"] - sell["commission"]
            pnl = exit_proceeds - entry_cost

            # Duration
            duration_minutes = (
                sell["timestamp"] - buy["timestamp"]
            ).total_seconds() / 60

            matched_trades.append(
                {
                    "symbol": symbol,
                    "entry_time": buy["timestamp"],
                    "exit_time": sell["timestamp"],
                    "duration_minutes": duration_minutes,
                    "quantity": buy["quantity"],
                    "entry_price": buy["price"],
                    "exit_price": sell["price"],
                    "entry_commission": buy["commission"],
                    "exit_commission": sell["commission"],
                    "pnl": pnl,
                    "pnl_pct": (pnl / entry_cost) * 100,
                }
            )

# Create matched trades dataframe
trades_df = pd.DataFrame(matched_trades)

if trades_df.empty:
    print("ERROR: No matched trades found")
    sys.exit(1)

print(f"\nMatched {len(trades_df)} complete trades")

# Save detailed report
output_file = Path("pattern_backtest/output/trade_report_detailed.csv")
trades_df.to_csv(output_file, index=False)
print(f"Saved to: {output_file}")

# Summary statistics
print("\n" + "=" * 80)
print("TRADE SUMMARY")
print("=" * 80)

print(f"\nTotal trades: {len(trades_df)}")
print(f"Total P&L: ${trades_df['pnl'].sum():,.2f}")
print(f"Average P&L: ${trades_df['pnl'].mean():,.2f}")
print(f"Win rate: {(trades_df['pnl'] > 0).mean():.1%}")
print(f"Best trade: ${trades_df['pnl'].max():,.2f}")
print(f"Worst trade: ${trades_df['pnl'].min():,.2f}")

print("\nDuration stats (minutes):")
print(trades_df["duration_minutes"].describe())

print("\nTrades per symbol (top 20):")
print(trades_df["symbol"].value_counts().head(20))

print("\nSample trades:")
print(
    trades_df[
        [
            "symbol",
            "entry_time",
            "exit_time",
            "duration_minutes",
            "entry_price",
            "exit_price",
            "pnl",
        ]
    ]
    .head(20)
    .to_string()
)
