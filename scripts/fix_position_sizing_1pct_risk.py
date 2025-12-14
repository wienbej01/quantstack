#!/usr/bin/env python3

from pathlib import Path

import numpy as np
import pandas as pd


def calculate_position_size_1pct_risk(entry_price, current_equity, atr_estimate=0.02):
    """
    Calculate position size based on 1% equity risk per trade.

    Args:
        entry_price: Entry price for the trade
        current_equity: Current account equity
        atr_estimate: ATR as percentage of price (default 2%)

    Returns:
        shares: Number of shares to trade
        position_value: Dollar value of position
        risk_amount: Dollar amount at risk (1% of equity)
    """
    # Risk amount is 1% of current equity
    risk_amount = current_equity * 0.01

    # Use 2x ATR as estimated risk per share
    risk_per_share = entry_price * atr_estimate * 2.0

    # Calculate shares based on risk
    if risk_per_share > 0:
        shares = int(risk_amount / risk_per_share)
    else:
        shares = 100  # Minimum position

    # Safety limits
    shares = max(100, min(shares, 10000))  # Between 100-10,000 shares

    # Calculate actual position value
    position_value = shares * entry_price

    # Ensure position doesn't exceed 50% of equity
    max_position_value = current_equity * 0.5
    if position_value > max_position_value:
        shares = int(max_position_value / entry_price)
        position_value = shares * entry_price

    return shares, position_value, risk_amount


def fix_backtest_results():
    """Fix the existing backtest results with proper position sizing."""

    # Load the trades data
    trades_file = Path("run/enhanced_results/trades.csv.backup")
    if not trades_file.exists():
        print("❌ Trades file not found")
        return

    print("📊 Loading trades data...")
    df = pd.read_csv(trades_file)
    print(f"Loaded {len(df):,} trades")
    print(f"Columns: {list(df.columns)}")

    # Initialize equity tracking
    current_equity = 10000.0  # Starting capital
    transaction_cost_rate = 0.00057  # 0.057% per trade

    fixed_trades = []

    print("🔧 Recalculating position sizes with 1% risk...")

    for i, trade in df.iterrows():
        if i % 5000 == 0:
            print(
                f"  Processing trade {i:,}/{len(df):,} - Equity: ${current_equity:,.0f}"
            )

        entry_price = trade["entry_price"]
        exit_price = trade["exit_price"]

        # Calculate proper position size (1% risk)
        shares, position_value, risk_amount = calculate_position_size_1pct_risk(
            entry_price=entry_price,
            current_equity=current_equity,
            atr_estimate=0.02,  # 2% ATR estimate
        )

        # Calculate transaction costs
        entry_cost = position_value * transaction_cost_rate
        exit_cost = position_value * transaction_cost_rate
        total_costs = entry_cost + exit_cost

        # Calculate P&L
        price_change = exit_price - entry_price
        gross_pnl = shares * price_change
        net_pnl = gross_pnl - total_costs

        # Calculate returns
        gross_return = (exit_price / entry_price - 1) if entry_price > 0 else 0
        net_return = net_pnl / position_value if position_value > 0 else 0

        # Update equity
        current_equity += net_pnl

        # Prevent negative equity
        if current_equity < 1000:
            current_equity = 1000  # Stop trading if equity too low

        # Store fixed trade
        fixed_trade = {
            "signal_timestamp": trade["signal_timestamp"],
            "symbol": trade["symbol"],
            "side": trade["side"],
            "entry_price": entry_price,
            "exit_price": exit_price,
            "shares": shares,
            "position_value": position_value,
            "risk_amount": risk_amount,
            "gross_pnl": gross_pnl,
            "transaction_costs": total_costs,
            "net_pnl": net_pnl,
            "gross_return": gross_return,
            "net_return": net_return,
            "equity_after": current_equity,
            "hour_et": trade["hour_et"],
            "prob_long": trade["prob_long"],
            "prob_short": trade["prob_short"],
        }

        fixed_trades.append(fixed_trade)

    # Create fixed trades DataFrame
    fixed_df = pd.DataFrame(fixed_trades)

    # Calculate summary statistics
    total_trades = len(fixed_df)
    winning_trades = (fixed_df["net_pnl"] > 0).sum()
    win_rate = winning_trades / total_trades

    total_gross_pnl = fixed_df["gross_pnl"].sum()
    total_costs = fixed_df["transaction_costs"].sum()
    total_net_pnl = fixed_df["net_pnl"].sum()

    final_equity = current_equity
    total_return = (final_equity / 10000.0 - 1) * 100

    avg_win = fixed_df[fixed_df["net_pnl"] > 0]["net_pnl"].mean()
    avg_loss = fixed_df[fixed_df["net_pnl"] < 0]["net_pnl"].mean()
    profit_factor = abs(avg_win / avg_loss) if avg_loss < 0 else float("inf")

    # Calculate Sharpe ratio (annualized)
    daily_returns = fixed_df.groupby(fixed_df["signal_timestamp"].str[:10])[
        "net_pnl"
    ].sum()
    daily_returns_pct = daily_returns / 10000  # As percentage of starting capital
    sharpe_ratio = (
        (daily_returns_pct.mean() * 252) / (daily_returns_pct.std() * np.sqrt(252))
        if daily_returns_pct.std() > 0
        else 0
    )

    # Print results
    print("\n" + "=" * 80)
    print("FIXED POSITION SIZING RESULTS (1% RISK PER TRADE)")
    print("=" * 80)
    print(f"Starting Capital: ${10000:,.0f}")
    print(f"Final Equity: ${final_equity:,.0f}")
    print(f"Total Return: {total_return:.1f}%")
    print(f"Total Net P&L: ${total_net_pnl:,.0f}")
    print(f"Total Costs: ${total_costs:,.0f}")
    print()
    print(f"Total Trades: {total_trades:,}")
    print(f"Winning Trades: {winning_trades:,}")
    print(f"Win Rate: {win_rate:.1%}")
    print(f"Average Win: ${avg_win:.0f}")
    print(f"Average Loss: ${avg_loss:.0f}")
    print(f"Profit Factor: {profit_factor:.2f}")
    print(f"Sharpe Ratio: {sharpe_ratio:.2f}")
    print()
    print(f"Average Position Size: ${fixed_df['position_value'].mean():,.0f}")
    print(f"Average Risk per Trade: ${fixed_df['risk_amount'].mean():.0f}")
    print(f"Max Position Size: ${fixed_df['position_value'].max():,.0f}")
    print(
        f"Position Size Range: ${fixed_df['position_value'].min():,.0f} - ${fixed_df['position_value'].max():,.0f}"
    )

    # Save fixed results
    output_dir = Path("run/fixed_position_sizing")
    output_dir.mkdir(exist_ok=True)

    trades_file = output_dir / "trades_fixed.csv"
    fixed_df.to_csv(trades_file, index=False)

    # Create monthly summary
    fixed_df["month"] = pd.to_datetime(fixed_df["signal_timestamp"]).dt.to_period("M")
    monthly_summary = (
        fixed_df.groupby("month")
        .agg(
            {
                "net_pnl": ["count", "sum", "mean"],
                "net_return": "mean",
                "equity_after": "last",
            }
        )
        .round(4)
    )

    monthly_summary.columns = ["trades", "total_pnl", "avg_pnl", "avg_return", "equity"]
    monthly_summary["win_rate"] = (
        fixed_df.groupby("month").apply(lambda x: (x["net_pnl"] > 0).mean()).round(3)
    )

    monthly_file = output_dir / "monthly_summary.csv"
    monthly_summary.to_csv(monthly_file)

    print(f"\n📁 Results saved to: {output_dir}")
    print(f"   - {trades_file}")
    print(f"   - {monthly_file}")

    # Show monthly performance
    print("\n📈 MONTHLY PERFORMANCE:")
    print(monthly_summary.to_string())

    return fixed_df


if __name__ == "__main__":
    fixed_df = fix_backtest_results()
