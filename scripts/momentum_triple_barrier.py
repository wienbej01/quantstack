#!/usr/bin/env python3
"""Momentum strategy with triple-barrier exits."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_momentum_triple_barrier_labels(
    df, pt_mult=1.5, sl_mult=1.0, horizon_minutes=60
):
    """Create momentum labels with triple-barrier exits."""

    results = []

    # Group by symbol and date
    grouped = df.groupby(["symbol", "date"])
    total_groups = len(grouped)

    for i, ((symbol, date), group_df) in enumerate(grouped):
        if i % 50 == 0:
            logging.info(f"Processing: {i:,}/{total_groups:,} symbol-days")

        group_df = group_df.sort_values("timestamp").reset_index(drop=True)

        for idx, row in group_df.iterrows():
            # Calculate momentum score
            momentum_score = calculate_momentum_score(row)
            if abs(momentum_score) < 0.3:
                continue

            # Determine direction
            direction = 1 if momentum_score > 0 else -1

            # Entry setup
            entry_time = pd.to_datetime(row["timestamp"])
            entry_price = 100.0
            atr_pct = max(0.005, min(0.20, row["atr_pct"]))

            # Calculate barriers (momentum-friendly)
            pt_distance = pt_mult * atr_pct  # Smaller profit target
            sl_distance = sl_mult * atr_pct  # Tighter stop

            # Barrier prices (direction-aware)
            if direction == 1:  # Long momentum
                pt_price = entry_price * (1 + pt_distance)
                sl_price = entry_price * (1 - sl_distance)
            else:  # Short momentum
                pt_price = entry_price * (1 - pt_distance)
                sl_price = entry_price * (1 + sl_distance)

            # Time barrier
            session_end = entry_time.replace(hour=16, minute=0, second=0)
            exit_time = min(
                entry_time + pd.Timedelta(minutes=horizon_minutes), session_end
            )

            # Get future data
            future_data = group_df[
                (pd.to_datetime(group_df["timestamp"]) > entry_time)
                & (pd.to_datetime(group_df["timestamp"]) <= exit_time)
            ].sort_values("timestamp")

            # Check barriers
            outcome, final_price, actual_exit_time = check_momentum_barriers(
                future_data, entry_price, pt_price, sl_price, exit_time, direction
            )

            # Calculate returns
            if direction == 1:
                gross_return = (final_price - entry_price) / entry_price
            else:
                gross_return = (entry_price - final_price) / entry_price

            # Position sizing and costs
            risk_amount = 100.0
            stop_distance = sl_distance
            shares = max(
                100, min(1000, int(risk_amount / (entry_price * stop_distance)))
            )

            position_value = shares * entry_price
            fee = 0.70
            spread = position_value * 0.0003  # 3 bps for momentum
            total_costs = fee + spread

            # Net P&L
            gross_pnl = gross_return * position_value
            net_pnl = gross_pnl - total_costs
            net_return = net_pnl / position_value

            # Labels
            label_profitable = 1 if net_return > 0.002 else 0
            label_momentum = 1 if outcome == "pt" else 0

            results.append(
                {
                    "symbol": symbol,
                    "timestamp": row["timestamp"],
                    "date": date,
                    "hour_et": row["hour_et"],
                    "direction": direction,
                    "momentum_score": momentum_score,
                    "entry_price": entry_price,
                    "final_price": final_price,
                    "pt_price": pt_price,
                    "sl_price": sl_price,
                    "outcome": outcome,
                    "gross_return": gross_return,
                    "net_return": net_return,
                    "shares": shares,
                    "position_value": position_value,
                    "total_costs": total_costs,
                    # Labels
                    "label_profitable": label_profitable,
                    "label_momentum": label_momentum,
                    "label_return_target": net_return,
                    # Features
                    "atr_pct": row["atr_pct"],
                    "volume_ratio_20": row["volume_ratio_20"],
                    "returns": row["returns"],
                }
            )

    return pd.DataFrame(results)


def calculate_momentum_score(row):
    """Calculate momentum score (same as before)."""
    recent_return = row.get("returns", 0)  # Keep direction
    volume_surge = row.get("volume_ratio_20", 1.0)
    volatility = row.get("atr_pct", 0.01)

    # ICT signals
    displacement_up = row.get("displacement_up", 0)
    displacement_down = row.get("displacement_down", 0)
    order_block_bull = row.get("order_block_bull", 0)
    order_block_bear = row.get("order_block_bear", 0)

    # Momentum magnitude
    momentum_magnitude = (
        abs(recent_return) * 2.0
        + (volume_surge - 1.0) * 0.5
        + volatility * 10.0
        + (displacement_up + displacement_down) * 0.3
        + (order_block_bull + order_block_bear) * 0.2
    )

    # Direction
    direction_signal = (
        recent_return  # Recent price direction
        + (displacement_up - displacement_down) * 0.5
        + (order_block_bull - order_block_bear) * 0.3
    )

    return direction_signal if momentum_magnitude > 0.3 else 0


def check_momentum_barriers(
    future_data, entry_price, pt_price, sl_price, exit_time, direction
):
    """Check barriers for momentum trade."""

    if len(future_data) == 0:
        return "time", entry_price, exit_time

    for _, bar in future_data.iterrows():
        # Simulate price movement within bar
        bar_return = bar.get("forward_return", 0)
        bar_high = entry_price * (1 + max(0, bar_return))
        bar_low = entry_price * (1 + min(0, bar_return))

        if direction == 1:  # Long momentum
            # Check stop first (conservative)
            if bar_low <= sl_price:
                return "sl", sl_price, pd.to_datetime(bar["timestamp"])
            elif bar_high >= pt_price:
                return "pt", pt_price, pd.to_datetime(bar["timestamp"])
        else:  # Short momentum
            # Check stop first
            if bar_high >= sl_price:
                return "sl", sl_price, pd.to_datetime(bar["timestamp"])
            elif bar_low <= pt_price:
                return "pt", pt_price, pd.to_datetime(bar["timestamp"])

    # Time exit
    last_price = entry_price * (1 + future_data.iloc[-1].get("forward_return", 0))
    return "time", last_price, exit_time


def filter_momentum_setups(df):
    """Filter for momentum setups (same as before but more selective)."""

    momentum_filter = (
        (df["hour_et"] >= 9.5)
        & (df["hour_et"] <= 14.0)
        & (df["atr_pct"] > 0.010)  # Higher volatility
        & (df["volume_ratio_20"] > 2.0)  # Stronger volume surge
        & (abs(df["returns"]) > 0.008)  # Bigger price moves
        & (
            (df.get("displacement_up", 0) > 0)
            | (df.get("displacement_down", 0) > 0)
            | (df.get("order_block_bull", 0) > 0)
            | (df.get("order_block_bear", 0) > 0)
        )
    )

    return df[momentum_filter].copy()


def main():
    """Create momentum triple-barrier labels."""
    logging.info("=" * 80)
    logging.info("MOMENTUM TRIPLE-BARRIER LABELING")
    logging.info("=" * 80)

    # Load base features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Filter for momentum setups (more selective)
    momentum_events = filter_momentum_setups(pdf)
    logging.info(f"Filtered to {len(momentum_events):,} momentum setups")

    # Create labels
    logging.info("Creating momentum triple-barrier labels...")
    labels_df = create_momentum_triple_barrier_labels(momentum_events)

    # Analysis
    logging.info("\n=== MOMENTUM TRIPLE-BARRIER RESULTS ===")
    logging.info(f"Total labeled events: {len(labels_df):,}")

    if len(labels_df) > 0:
        profitable_rate = labels_df["label_profitable"].mean() * 100
        momentum_rate = labels_df["label_momentum"].mean() * 100
        avg_return = labels_df["net_return"].mean() * 100
        return_std = labels_df["net_return"].std() * 100

        logging.info(f"Profitable rate: {profitable_rate:.1f}%")
        logging.info(f"Momentum success rate: {momentum_rate:.1f}%")
        logging.info(f"Average net return: {avg_return:.3f}%")
        logging.info(f"Return volatility: {return_std:.3f}%")
        logging.info(f"Sharpe ratio: {avg_return/return_std:.3f}")

        # Outcome analysis
        logging.info("\n=== OUTCOME ANALYSIS ===")
        outcome_dist = labels_df["outcome"].value_counts()
        for outcome, count in outcome_dist.items():
            pct = count / len(labels_df) * 100
            avg_ret = (
                labels_df[labels_df["outcome"] == outcome]["net_return"].mean() * 100
            )
            logging.info(
                f"  {outcome}: {count:,} ({pct:.1f}%), avg return: {avg_ret:.3f}%"
            )

        # Direction analysis
        logging.info("\n=== DIRECTIONAL ANALYSIS ===")
        long_trades = labels_df[labels_df["direction"] == 1]
        short_trades = labels_df[labels_df["direction"] == -1]

        if len(long_trades) > 0:
            long_ev = long_trades["net_return"].mean() * 100
            long_pt_rate = (long_trades["outcome"] == "pt").mean() * 100
            logging.info(
                f"Long momentum: {len(long_trades):,} trades, {long_ev:.3f}% EV, {long_pt_rate:.1f}% PT rate"
            )

        if len(short_trades) > 0:
            short_ev = short_trades["net_return"].mean() * 100
            short_pt_rate = (short_trades["outcome"] == "pt").mean() * 100
            logging.info(
                f"Short momentum: {len(short_trades):,} trades, {short_ev:.3f}% EV, {short_pt_rate:.1f}% PT rate"
            )

        # Save results
        output_dir = Path("run/momentum_triple_barrier_labels")
        output_dir.mkdir(exist_ok=True)

        labels_df.to_parquet(output_dir / "labels.parquet")

        logging.info(f"✅ Saved momentum triple-barrier labels to {output_dir}")

        if avg_return > 0:
            logging.info(
                "✅ POSITIVE EXPECTED VALUE - Momentum triple-barrier shows edge!"
            )
        else:
            logging.info("⚠️ NEGATIVE EXPECTED VALUE - Need further optimization")
    else:
        logging.warning("No momentum setups found with current filters")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
