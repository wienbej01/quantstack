#!/usr/bin/env python3
"""Momentum/breakout labeling - trade WITH the move, not against it."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_momentum_labels(df, hold_minutes=30):
    """Create labels for momentum/breakout strategy."""

    results = []

    # Group by symbol and date
    grouped = df.groupby(["symbol", "date"])
    total_groups = len(grouped)

    for i, ((symbol, date), group_df) in enumerate(grouped):
        if i % 100 == 0:
            logging.info(f"Processing: {i:,}/{total_groups:,} symbol-days")

        group_df = group_df.sort_values("timestamp").reset_index(drop=True)

        for idx, row in group_df.iterrows():
            # Momentum/breakout entry conditions
            entry_time = pd.to_datetime(row["timestamp"])

            # Check for momentum setup
            momentum_score = calculate_momentum_score(row)
            if momentum_score < 0.3:  # Minimum momentum threshold
                continue

            # Determine direction based on momentum
            direction = 1 if momentum_score > 0 else -1  # 1=long, -1=short

            # Find exit point
            exit_time = entry_time + pd.Timedelta(minutes=hold_minutes)

            # Get future bars
            future_bars = group_df[pd.to_datetime(group_df["timestamp"]) >= exit_time]

            if len(future_bars) == 0:
                # Use last available bar
                last_bars = group_df[pd.to_datetime(group_df["timestamp"]) > entry_time]
                if len(last_bars) > 0:
                    exit_return = last_bars.iloc[-1]["forward_return"]
                else:
                    exit_return = 0.0
            else:
                exit_return = future_bars.iloc[0]["forward_return"]

            # Apply directional return (momentum trade)
            directional_return = exit_return * direction

            # Position sizing and costs
            entry_price = 100.0
            atr_pct = row["atr_pct"]

            # Risk management
            risk_amount = 100.0  # 1% of $10k
            stop_distance = (
                max(0.005, min(0.20, atr_pct)) * 1.0
            )  # Tighter stops for momentum
            shares = max(
                100, min(1000, int(risk_amount / (entry_price * stop_distance)))
            )

            # Transaction costs
            position_value = shares * entry_price
            fee = 0.70
            spread = position_value * 0.0003  # Tighter spread for momentum (3 bps)
            total_costs = fee + spread

            # Net P&L
            gross_pnl = directional_return * position_value
            net_pnl = gross_pnl - total_costs
            net_return = net_pnl / position_value

            # Labels
            label_profitable = 1 if net_return > 0.002 else 0
            label_momentum_long = 1 if (direction == 1 and net_return > 0.002) else 0
            label_momentum_short = 1 if (direction == -1 and net_return > 0.002) else 0

            results.append(
                {
                    "symbol": symbol,
                    "timestamp": row["timestamp"],
                    "date": date,
                    "hour_et": row["hour_et"],
                    "direction": direction,
                    "momentum_score": momentum_score,
                    "entry_price": entry_price,
                    "exit_return": exit_return,
                    "directional_return": directional_return,
                    "net_return": net_return,
                    "shares": shares,
                    "position_value": position_value,
                    "total_costs": total_costs,
                    # Labels
                    "label_profitable": label_profitable,
                    "label_momentum_long": label_momentum_long,
                    "label_momentum_short": label_momentum_short,
                    "label_return_target": net_return,
                    # Features
                    "atr_pct": row["atr_pct"],
                    "volume_ratio_20": row["volume_ratio_20"],
                    "returns": row["returns"],
                    "volatility_20": row["volatility_20"],
                }
            )

    return pd.DataFrame(results)


def calculate_momentum_score(row):
    """Calculate momentum score for entry decision."""

    # Momentum indicators
    recent_return = abs(row.get("returns", 0))
    volume_surge = row.get("volume_ratio_20", 1.0)
    volatility = row.get("atr_pct", 0.01)

    # ICT momentum signals
    displacement_up = row.get("displacement_up", 0)
    displacement_down = row.get("displacement_down", 0)
    order_block_bull = row.get("order_block_bull", 0)
    order_block_bear = row.get("order_block_bear", 0)

    # Combine signals
    momentum_score = (
        recent_return * 2.0  # Recent price movement
        + (volume_surge - 1.0) * 0.5  # Volume above average
        + volatility * 10.0  # Volatility expansion
        + displacement_up * 0.3  # ICT displacement up
        + displacement_down * 0.3  # ICT displacement down
        + order_block_bull * 0.2  # Bullish order block
        + order_block_bear * 0.2  # Bearish order block
    )

    # Direction (positive = bullish momentum, negative = bearish momentum)
    direction_score = (
        recent_return * (1 if row.get("returns", 0) > 0 else -1)
        + (displacement_up - displacement_down) * 0.5
        + (order_block_bull - order_block_bear) * 0.3
    )

    return direction_score if abs(momentum_score) > 0.3 else 0


def filter_breakout_setups(df):
    """Filter for high-quality breakout setups."""

    # Breakout conditions
    breakout_filter = (
        (df["hour_et"] >= 9.5)
        & (df["hour_et"] <= 14.0)  # Active hours
        & (df["atr_pct"] > 0.008)  # Higher volatility threshold
        & (df["volume_ratio_20"] > 1.5)  # Strong volume surge
        & (abs(df["returns"]) > 0.005)  # Minimum price movement
        & (
            (df.get("displacement_up", 0) > 0)  # ICT displacement
            | (df.get("displacement_down", 0) > 0)
            | (df.get("order_block_bull", 0) > 0)  # Order blocks
            | (df.get("order_block_bear", 0) > 0)
        )
    )

    return df[breakout_filter].copy()


def main():
    """Create momentum/breakout labels."""
    logging.info("=" * 80)
    logging.info("MOMENTUM/BREAKOUT LABELING")
    logging.info("=" * 80)

    # Load base features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Filter for breakout setups
    breakout_events = filter_breakout_setups(pdf)
    logging.info(f"Filtered to {len(breakout_events):,} breakout setups")

    # Create momentum labels
    logging.info("Creating momentum/breakout labels...")
    labels_df = create_momentum_labels(breakout_events, hold_minutes=30)

    # Analysis
    logging.info("\n=== MOMENTUM/BREAKOUT RESULTS ===")
    logging.info(f"Total labeled events: {len(labels_df):,}")

    profitable_rate = labels_df["label_profitable"].mean() * 100
    long_rate = labels_df["label_momentum_long"].mean() * 100
    short_rate = labels_df["label_momentum_short"].mean() * 100
    avg_return = labels_df["net_return"].mean() * 100
    return_std = labels_df["net_return"].std() * 100

    logging.info(f"Profitable rate: {profitable_rate:.1f}%")
    logging.info(f"Long momentum rate: {long_rate:.1f}%")
    logging.info(f"Short momentum rate: {short_rate:.1f}%")
    logging.info(f"Average net return: {avg_return:.3f}%")
    logging.info(f"Return volatility: {return_std:.3f}%")
    logging.info(f"Sharpe ratio: {avg_return/return_std:.3f}")

    # Direction analysis
    logging.info("\n=== DIRECTIONAL ANALYSIS ===")
    long_trades = labels_df[labels_df["direction"] == 1]
    short_trades = labels_df[labels_df["direction"] == -1]

    if len(long_trades) > 0:
        long_ev = long_trades["net_return"].mean() * 100
        long_win_rate = (long_trades["net_return"] > 0).mean() * 100
        logging.info(
            f"Long momentum: {len(long_trades):,} trades, {long_ev:.3f}% EV, {long_win_rate:.1f}% win rate"
        )

    if len(short_trades) > 0:
        short_ev = short_trades["net_return"].mean() * 100
        short_win_rate = (short_trades["net_return"] > 0).mean() * 100
        logging.info(
            f"Short momentum: {len(short_trades):,} trades, {short_ev:.3f}% EV, {short_win_rate:.1f}% win rate"
        )

    # Time-of-day analysis
    logging.info("\n=== TIME-OF-DAY PERFORMANCE ===")
    hourly_stats = (
        labels_df.groupby("hour_et")
        .agg({"net_return": ["mean", "count"], "label_profitable": "mean"})
        .round(4)
    )

    for hour in sorted(labels_df["hour_et"].unique()):
        hour_data = labels_df[labels_df["hour_et"] == hour]
        avg_ret = hour_data["net_return"].mean() * 100
        prof_rate = hour_data["label_profitable"].mean() * 100
        count = len(hour_data)

        logging.info(
            f"Hour {hour}: {count:,} events, {avg_ret:.3f}% avg return, {prof_rate:.1f}% profitable"
        )

    # Save results
    output_dir = Path("run/momentum_breakout_labels")
    output_dir.mkdir(exist_ok=True)

    labels_df.to_parquet(output_dir / "labels.parquet")

    logging.info(f"✅ Saved momentum/breakout labels to {output_dir}")

    # Recommendation
    if avg_return > 0:
        logging.info("✅ POSITIVE EXPECTED VALUE - Momentum strategy shows edge!")
    else:
        logging.info("⚠️ NEGATIVE EXPECTED VALUE - Need further optimization")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
