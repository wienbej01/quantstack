#!/usr/bin/env python3
"""Fixed-time exit labeling for better predictability."""

import logging
from pathlib import Path

import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_fixed_time_labels(df, hold_minutes=60):
    """Create labels based on fixed holding period returns."""

    results = []

    # Group by symbol and date for efficient processing
    grouped = df.groupby(["symbol", "date"])
    total_groups = len(grouped)

    for i, ((symbol, date), group_df) in enumerate(grouped):
        if i % 100 == 0:
            logging.info(f"Processing: {i:,}/{total_groups:,} symbol-days")

        group_df = group_df.sort_values("timestamp").reset_index(drop=True)

        for idx, row in group_df.iterrows():
            # Find exit point (fixed time ahead)
            entry_time = pd.to_datetime(row["timestamp"])
            exit_time = entry_time + pd.Timedelta(minutes=hold_minutes)

            # Find the bar closest to exit time
            future_bars = group_df[pd.to_datetime(group_df["timestamp"]) >= exit_time]

            if len(future_bars) == 0:
                # No future data - use end of session
                session_end = entry_time.replace(hour=16, minute=0)
                if entry_time < session_end:
                    # Use last available bar
                    last_bars = group_df[
                        pd.to_datetime(group_df["timestamp"]) > entry_time
                    ]
                    if len(last_bars) > 0:
                        exit_return = last_bars.iloc[-1]["forward_return"]
                    else:
                        exit_return = 0.0
                else:
                    exit_return = 0.0
            else:
                # Use the first bar at or after exit time
                exit_return = future_bars.iloc[0]["forward_return"]

            # Calculate net return with costs
            entry_price = 100.0  # Normalized
            atr_pct = row["atr_pct"]

            # Position sizing
            risk_amount = 100.0  # 1% of $10k
            stop_distance = max(0.005, min(0.20, atr_pct)) * 1.5
            shares = max(
                100, min(1000, int(risk_amount / (entry_price * stop_distance)))
            )

            # Transaction costs
            position_value = shares * entry_price
            fee = 0.70  # $0.35 * 2 sides
            spread = position_value * 0.0005  # 5 bps
            total_costs = fee + spread

            # Net return
            gross_pnl = exit_return * position_value
            net_pnl = gross_pnl - total_costs
            net_return = net_pnl / position_value

            # Simple binary labels based on profitability
            label_profitable = 1 if net_return > 0.002 else 0  # >0.2% net

            # Directional labels
            label_long = 1 if net_return > 0.002 else 0
            label_short = 1 if net_return < -0.002 else 0

            # Regression target (for EV prediction)
            label_return = net_return

            results.append(
                {
                    "symbol": symbol,
                    "timestamp": row["timestamp"],
                    "date": date,
                    "hour_et": row["hour_et"],
                    "entry_price": entry_price,
                    "exit_return": exit_return,
                    "net_return": net_return,
                    "shares": shares,
                    "position_value": position_value,
                    "total_costs": total_costs,
                    "hold_minutes": hold_minutes,
                    # Labels
                    "label_profitable": label_profitable,
                    "label_long_fixed": label_long,
                    "label_short_fixed": label_short,
                    "label_return_target": label_return,
                    # Features (copy key ones)
                    "atr_pct": row["atr_pct"],
                    "volume_ratio_20": row["volume_ratio_20"],
                    "returns": row["returns"],
                    "volatility_20": row["volatility_20"],
                }
            )

    return pd.DataFrame(results)


def optimize_holding_period(df, test_periods=[30, 60, 90, 120, 180]):
    """Test different holding periods to find optimal."""

    logging.info("Testing different holding periods...")

    results = {}

    for period in test_periods:
        logging.info(f"Testing {period} minute hold...")

        # Sample subset for speed (every 10th row)
        sample_df = df.iloc[::10].copy()

        labels_df = create_fixed_time_labels(sample_df, hold_minutes=period)

        # Calculate metrics
        profitable_rate = labels_df["label_profitable"].mean() * 100
        avg_return = labels_df["net_return"].mean() * 100
        return_std = labels_df["net_return"].std() * 100
        sharpe = avg_return / return_std if return_std > 0 else 0

        results[period] = {
            "profitable_rate": profitable_rate,
            "avg_return": avg_return,
            "return_std": return_std,
            "sharpe": sharpe,
            "sample_size": len(labels_df),
        }

        logging.info(
            f"  {period}min: {profitable_rate:.1f}% profitable, {avg_return:.3f}% avg return, Sharpe: {sharpe:.3f}"
        )

    # Find best period
    best_period = max(results.keys(), key=lambda x: results[x]["sharpe"])
    logging.info(
        f"\nBest holding period: {best_period} minutes (Sharpe: {results[best_period]['sharpe']:.3f})"
    )

    return best_period, results


def main():
    """Create fixed-time exit labels."""
    logging.info("=" * 80)
    logging.info("FIXED-TIME EXIT LABELING")
    logging.info("=" * 80)

    # Load base features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Filter for trading events (same as triple-barrier)
    trading_events = pdf[
        (pdf["hour_et"] >= 9.5)
        & (pdf["hour_et"] <= 15.0)
        & (pdf["atr_pct"] > 0.005)
        & (pdf["volume_ratio_20"] > 1.2)
    ].copy()

    logging.info(f"Filtered to {len(trading_events):,} trading events")

    # Optimize holding period
    best_period, period_results = optimize_holding_period(trading_events)

    # Create labels with optimal period
    logging.info(f"\nCreating labels with {best_period}-minute fixed exit...")
    labels_df = create_fixed_time_labels(trading_events, hold_minutes=best_period)

    # Analysis
    logging.info("\n=== FIXED-TIME LABELING RESULTS ===")
    logging.info(f"Total labeled events: {len(labels_df):,}")
    logging.info(f"Holding period: {best_period} minutes")

    profitable_rate = labels_df["label_profitable"].mean() * 100
    long_rate = labels_df["label_long_fixed"].mean() * 100
    short_rate = labels_df["label_short_fixed"].mean() * 100
    avg_return = labels_df["net_return"].mean() * 100
    return_std = labels_df["net_return"].std() * 100

    logging.info(f"Profitable rate: {profitable_rate:.1f}%")
    logging.info(f"Long label rate: {long_rate:.1f}%")
    logging.info(f"Short label rate: {short_rate:.1f}%")
    logging.info(f"Average net return: {avg_return:.3f}%")
    logging.info(f"Return volatility: {return_std:.3f}%")
    logging.info(f"Sharpe ratio: {avg_return/return_std:.3f}")

    # Time-of-day analysis
    logging.info("\n=== TIME-OF-DAY PERFORMANCE ===")
    hourly_stats = (
        labels_df.groupby("hour_et")
        .agg({"net_return": ["mean", "std", "count"], "label_profitable": "mean"})
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
    output_dir = Path("run/fixed_time_labels")
    output_dir.mkdir(exist_ok=True)

    labels_df.to_parquet(output_dir / "labels.parquet")

    # Save optimization results
    import json

    with open(output_dir / "period_optimization.json", "w") as f:
        json.dump(period_results, f, indent=2)

    logging.info(f"✅ Saved fixed-time labels to {output_dir}")

    # Recommendation
    if avg_return > 0:
        logging.info("✅ POSITIVE EXPECTED VALUE - Ready for model training")
    else:
        logging.info("⚠️ NEGATIVE EXPECTED VALUE - Consider further filtering")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
