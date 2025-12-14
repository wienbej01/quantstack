#!/usr/bin/env python3
"""
Correct Position Sizing: 1% Equity Risk Per Trade

Position size = (Equity * 0.01) / Risk_Per_Share

Where Risk_Per_Share is:
1. If stop loss known: abs(entry_price - stop_loss)
2. If no stop: estimate from 2x ATR or recent max adverse move
"""

from pathlib import Path

import numpy as np
import pandas as pd


def calculate_shares(equity, entry_price, risk_per_share, risk_pct=0.01):
    """
    Calculate shares based on fixed percentage risk.

    shares = (equity * risk_pct) / risk_per_share
    """
    if risk_per_share <= 0 or entry_price <= 0:
        return 0

    dollar_risk = equity * risk_pct
    shares = int(dollar_risk / risk_per_share)

    # Minimum 1 share, maximum based on position value < 25% equity
    max_shares = int((equity * 0.25) / entry_price)
    shares = max(1, min(shares, max_shares, 10000))

    return shares


def estimate_risk_per_share(entry_price, atr_pct=None, max_adverse_pct=None):
    """
    Estimate risk per share when no explicit stop loss.

    Priority:
    1. Use 2x ATR if available
    2. Use historical max adverse move if available
    3. Fallback: 4% of entry price (conservative)
    """
    if atr_pct and atr_pct > 0:
        # 2x ATR is typical stop distance
        return entry_price * atr_pct * 2.0

    if max_adverse_pct and max_adverse_pct > 0:
        # Use historical worst-case
        return entry_price * max_adverse_pct

    # Conservative fallback: 4% stop
    return entry_price * 0.04


def run_backtest_correct():
    """Run backtest with correct position sizing."""

    trades_file = Path("run/enhanced_results/trades.csv.backup")
    if not trades_file.exists():
        print("❌ Trades file not found")
        return

    print("📊 Loading trades...")
    df = pd.read_csv(trades_file)
    print(f"Loaded {len(df):,} trades")

    # Calculate ATR estimate per symbol (rolling)
    df["date"] = pd.to_datetime(df["signal_timestamp"]).dt.date
    df["price_move_pct"] = abs(df["exit_price"] / df["entry_price"] - 1)

    # Group by symbol to get rolling ATR estimate
    symbol_atr = (
        df.groupby("symbol")["price_move_pct"]
        .expanding()
        .mean()
        .reset_index(level=0, drop=True)
    )
    df["atr_estimate"] = symbol_atr.clip(lower=0.01, upper=0.10)  # 1-10% range

    # Initialize
    equity = 10000.0
    risk_pct = 0.01  # 1% risk per trade
    cost_rate = 0.001  # 0.1% round trip (spread + commission)

    results = []

    print(f"🔧 Running backtest with {risk_pct:.0%} risk per trade...")
    print(f"   Starting equity: ${equity:,.0f}")

    for i, trade in df.iterrows():
        entry_price = trade["entry_price"]
        exit_price = trade["exit_price"]
        atr_est = trade["atr_estimate"]

        # Estimate risk per share (no explicit stop, use 2x ATR)
        risk_per_share = estimate_risk_per_share(entry_price, atr_pct=atr_est)

        # Calculate position size
        shares = calculate_shares(equity, entry_price, risk_per_share, risk_pct)

        if shares == 0:
            continue

        # Calculate P&L
        position_value = shares * entry_price
        price_change = exit_price - entry_price
        gross_pnl = shares * price_change
        costs = position_value * cost_rate
        net_pnl = gross_pnl - costs

        # Update equity
        equity += net_pnl

        # Prevent negative equity
        if equity < 100:
            print(f"⚠️ Account blown at trade {i}")
            break

        results.append(
            {
                "timestamp": trade["signal_timestamp"],
                "symbol": trade["symbol"],
                "side": trade["side"],
                "entry_price": entry_price,
                "exit_price": exit_price,
                "shares": shares,
                "position_value": position_value,
                "risk_per_share": risk_per_share,
                "dollar_risk": shares * risk_per_share,
                "gross_pnl": gross_pnl,
                "costs": costs,
                "net_pnl": net_pnl,
                "equity": equity,
            }
        )

    results_df = pd.DataFrame(results)

    # Summary stats
    total_trades = len(results_df)
    winners = (results_df["net_pnl"] > 0).sum()
    win_rate = winners / total_trades if total_trades > 0 else 0

    total_pnl = results_df["net_pnl"].sum()
    avg_win = results_df[results_df["net_pnl"] > 0]["net_pnl"].mean()
    avg_loss = results_df[results_df["net_pnl"] < 0]["net_pnl"].mean()

    # Risk metrics
    avg_position = results_df["position_value"].mean()
    avg_risk = results_df["dollar_risk"].mean()
    max_position = results_df["position_value"].max()

    # Drawdown
    results_df["peak"] = results_df["equity"].cummax()
    results_df["drawdown"] = (results_df["equity"] - results_df["peak"]) / results_df[
        "peak"
    ]
    max_dd = results_df["drawdown"].min()

    print("\n" + "=" * 70)
    print("CORRECT POSITION SIZING RESULTS (1% RISK PER TRADE)")
    print("=" * 70)
    print(f"Starting Capital:    ${10000:>12,.0f}")
    print(f"Final Equity:        ${equity:>12,.0f}")
    print(f"Total P&L:           ${total_pnl:>12,.0f}")
    print(f"Total Return:        {(equity/10000-1)*100:>12.1f}%")
    print()
    print(f"Total Trades:        {total_trades:>12,}")
    print(f"Win Rate:            {win_rate:>12.1%}")
    print(f"Avg Win:             ${avg_win:>12,.0f}")
    print(f"Avg Loss:            ${avg_loss:>12,.0f}")
    print(f"Profit Factor:       {abs(avg_win/avg_loss) if avg_loss else 0:>12.2f}")
    print()
    print(f"Avg Position Size:   ${avg_position:>12,.0f}")
    print(f"Avg Dollar Risk:     ${avg_risk:>12,.0f}")
    print(f"Max Position Size:   ${max_position:>12,.0f}")
    print(f"Max Drawdown:        {max_dd:>12.1%}")

    # Monthly summary
    results_df["month"] = pd.to_datetime(results_df["timestamp"]).dt.to_period("M")
    monthly = results_df.groupby("month").agg(
        {"net_pnl": ["count", "sum"], "equity": "last"}
    )
    monthly.columns = ["trades", "pnl", "equity"]
    monthly["return_pct"] = (
        monthly["pnl"] / monthly["equity"].shift(1).fillna(10000) * 100
    )
    monthly["win_rate"] = results_df.groupby("month").apply(
        lambda x: (x["net_pnl"] > 0).mean(), include_groups=False
    )

    print("\n📈 MONTHLY PERFORMANCE:")
    print("-" * 70)
    print(
        f"{'Month':<10} {'Trades':>8} {'P&L':>12} {'Return':>10} {'Equity':>12} {'Win%':>8}"
    )
    print("-" * 70)

    for month, row in monthly.iterrows():
        print(
            f"{str(month):<10} {row['trades']:>8,.0f} ${row['pnl']:>10,.0f} "
            f"{row['return_pct']:>9.1f}% ${row['equity']:>10,.0f} {row['win_rate']:>7.1%}"
        )

    # Save results
    output_dir = Path("run/correct_position_sizing")
    output_dir.mkdir(exist_ok=True)
    results_df.to_csv(output_dir / "trades.csv", index=False)
    monthly.to_csv(output_dir / "monthly.csv")

    print(f"\n📁 Saved to: {output_dir}")

    return results_df


if __name__ == "__main__":
    run_backtest_correct()
