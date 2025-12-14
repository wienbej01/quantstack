#!/usr/bin/env python3
"""Build enhanced features for news-driven trading system."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def add_news_driven_features(df):
    """Add comprehensive features for news-driven trading."""

    logging.info("Adding news-driven features...")

    # Sort by symbol and timestamp for rolling calculations
    df = df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    # 1. Pre-market context features
    df["premarket_gap_pct"] = df["returns"]  # Proxy for gap (first bar return)
    df["premarket_volume_ratio"] = df["volume_ratio_20"]
    df["overnight_range_pct"] = df["atr_pct"]  # Proxy for overnight range

    # 2. News impact quantification
    df["time_since_open"] = (df["hour_et"] - 9.5) * 60  # Minutes since open
    df["news_attention_score"] = df["volume_ratio_20"] * abs(df["returns"]) * 100
    df["volatility_expansion_ratio"] = (
        df["atr_pct"] / df.groupby("symbol")["atr_pct"].rolling(20).mean().values
    )
    df["volume_expansion_ratio"] = df["volume_ratio_20"]

    # 3. Microstructure features
    df["price_velocity"] = abs(df["returns"]) / (
        df["time_since_open"] + 1
    )  # Price change per minute
    df["momentum_acceleration"] = df["returns"] - df.groupby("symbol")["returns"].shift(
        1
    )
    df["volume_at_price_momentum"] = df["volume_ratio_20"] * np.sign(df["returns"])

    # 4. Session dynamics
    df["session_progress"] = df["time_since_open"] / 390  # 0-1 through 6.5 hour session
    df["time_to_close"] = 390 - df["time_since_open"]
    df["lunch_hour_proximity"] = abs(df["hour_et"] - 12.5)  # Distance from lunch
    df["power_hour_proximity"] = abs(df["hour_et"] - 15.5)  # Distance from power hour

    # 5. Volatility regime features
    df["volatility_persistence"] = (
        df.groupby("symbol")["atr_pct"].rolling(5).std().values
    )
    df["volume_persistence"] = (
        df.groupby("symbol")["volume_ratio_20"].rolling(5).std().values
    )

    # 6. Support/Resistance proxies
    df["session_high_position"] = df.groupby(["symbol", "date"])["returns"].cummax()
    df["session_low_position"] = df.groupby(["symbol", "date"])["returns"].cummin()
    df["opening_range_position"] = df["returns"] - df.groupby(["symbol", "date"])[
        "returns"
    ].transform("first")

    # 7. Strategy identification features
    df["gap_size"] = abs(df.groupby(["symbol", "date"])["returns"].transform("first"))
    df["gap_direction"] = np.sign(
        df.groupby(["symbol", "date"])["returns"].transform("first")
    )
    df["is_large_gap"] = (df["gap_size"] > 0.02).astype(int)  # >2% gap
    df["is_high_volume"] = (df["volume_ratio_20"] > 2.0).astype(int)  # >2x volume

    # 8. Momentum quality features
    df["momentum_breadth"] = (
        np.sign(df["returns"]) + np.sign(df["returns_5"]) + np.sign(df["returns_10"])
    ) / 3  # Alignment across timeframes

    df["momentum_sustainability"] = (
        df["returns"] * df["volume_ratio_20"]
    )  # Volume-weighted momentum

    # 9. Exhaustion signals
    df["price_extension"] = abs(df["returns"]) / df["atr_pct"]  # How many ATRs moved
    df["volume_exhaustion"] = (
        df["volume_ratio_20"]
        / df.groupby("symbol")["volume_ratio_20"].rolling(5).max().values
    )

    # 10. News timing features
    df["optimal_news_window"] = (
        ((df["hour_et"] >= 9.5) & (df["hour_et"] <= 10.5))  # Market open
        | ((df["hour_et"] >= 15.0) & (df["hour_et"] <= 16.0))  # Power hour
    ).astype(int)

    return df


def create_strategy_labels(df):
    """Create labels for different trading strategies."""

    logging.info("Creating strategy-specific labels...")

    results = []

    # Group by symbol and date
    for (symbol, date), group in df.groupby(["symbol", "date"]):
        group = group.sort_values("timestamp").reset_index(drop=True)

        for idx, row in group.iterrows():
            # Skip if not enough future data
            if idx >= len(group) - 10:
                continue

            # Get future returns at different horizons
            future_15min = get_future_return(group, idx, 15)
            future_30min = get_future_return(group, idx, 30)
            future_60min = get_future_return(group, idx, 60)
            future_120min = get_future_return(group, idx, 120)

            # Strategy 1: Opening Gap Fade (9:30-10:30)
            if row["hour_et"] <= 10.5 and row["is_large_gap"] and row["is_high_volume"]:
                gap_fade_return = -row["gap_direction"] * future_30min  # Fade the gap
                gap_fade_label = 1 if gap_fade_return > 0.005 else 0
            else:
                gap_fade_return = 0
                gap_fade_label = 0

            # Strategy 2: Breakout Continuation (10:00-14:00)
            if (
                10.0 <= row["hour_et"] <= 14.0
                and row["momentum_breadth"] > 0.5
                and row["volume_expansion_ratio"] > 1.5
            ):
                continuation_return = np.sign(row["returns"]) * future_60min
                continuation_label = 1 if continuation_return > 0.008 else 0
            else:
                continuation_return = 0
                continuation_label = 0

            # Strategy 3: News Momentum (9:30-15:30)
            if (
                row["news_attention_score"] > 5.0
                and row["momentum_sustainability"] > 0.01
            ):
                momentum_return = np.sign(row["momentum_sustainability"]) * future_30min
                momentum_label = 1 if momentum_return > 0.006 else 0
            else:
                momentum_return = 0
                momentum_label = 0

            # Strategy 4: Volatility Mean Reversion (11:00-15:00)
            if (
                11.0 <= row["hour_et"] <= 15.0
                and row["price_extension"] > 2.0
                and row["volume_exhaustion"] < 0.5
            ):
                reversion_return = -np.sign(row["returns"]) * future_60min
                reversion_label = 1 if reversion_return > 0.005 else 0
            else:
                reversion_return = 0
                reversion_label = 0

            # Determine optimal strategy
            strategy_returns = {
                "gap_fade": gap_fade_return,
                "continuation": continuation_return,
                "momentum": momentum_return,
                "reversion": reversion_return,
            }

            optimal_strategy = max(
                strategy_returns.keys(), key=lambda k: strategy_returns[k]
            )
            optimal_return = strategy_returns[optimal_strategy]

            results.append(
                {
                    "symbol": symbol,
                    "timestamp": row["timestamp"],
                    "date": date,
                    "hour_et": row["hour_et"],
                    # Strategy returns
                    "gap_fade_return": gap_fade_return,
                    "continuation_return": continuation_return,
                    "momentum_return": momentum_return,
                    "reversion_return": reversion_return,
                    # Strategy labels
                    "gap_fade_label": gap_fade_label,
                    "continuation_label": continuation_label,
                    "momentum_label": momentum_label,
                    "reversion_label": reversion_label,
                    # Optimal strategy
                    "optimal_strategy": optimal_strategy,
                    "optimal_return": optimal_return,
                    "optimal_label": 1 if optimal_return > 0.005 else 0,
                    # Multi-horizon returns
                    "return_15min": future_15min,
                    "return_30min": future_30min,
                    "return_60min": future_60min,
                    "return_120min": future_120min,
                }
            )

    return pd.DataFrame(results)


def get_future_return(group, current_idx, minutes_ahead):
    """Get return at specified minutes in the future."""

    current_time = pd.to_datetime(group.iloc[current_idx]["timestamp"])
    target_time = current_time + pd.Timedelta(minutes=minutes_ahead)

    # Find closest future bar
    future_bars = group[pd.to_datetime(group["timestamp"]) >= target_time]

    if len(future_bars) == 0:
        # Use last available bar
        if current_idx < len(group) - 1:
            return group.iloc[-1]["forward_return"]
        else:
            return 0.0

    return future_bars.iloc[0]["forward_return"]


def main():
    """Build news-driven features and labels."""
    logging.info("=" * 80)
    logging.info("NEWS-DRIVEN ML SYSTEM - FEATURE ENGINEERING")
    logging.info("=" * 80)

    # Load base features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Add news-driven features
    enhanced_df = add_news_driven_features(pdf)
    logging.info(
        f"Added news-driven features: {len(enhanced_df.columns)} total columns"
    )

    # Create strategy labels
    labels_df = create_strategy_labels(enhanced_df)
    logging.info(f"Created strategy labels: {len(labels_df):,} events")

    # Merge features with labels
    final_df = enhanced_df.merge(
        labels_df, on=["symbol", "timestamp", "date", "hour_et"], how="inner"
    )

    # Analysis
    logging.info("\n=== NEWS-DRIVEN SYSTEM ANALYSIS ===")
    logging.info(f"Total events: {len(final_df):,}")

    # Strategy performance
    strategies = ["gap_fade", "continuation", "momentum", "reversion"]
    for strategy in strategies:
        label_col = f"{strategy}_label"
        return_col = f"{strategy}_return"

        if label_col in final_df.columns:
            label_rate = final_df[label_col].mean() * 100
            avg_return = final_df[final_df[label_col] == 1][return_col].mean() * 100

            logging.info(
                f"{strategy.title()}: {label_rate:.1f}% label rate, {avg_return:.3f}% avg return"
            )

    # Optimal strategy distribution
    if "optimal_strategy" in final_df.columns:
        strategy_dist = final_df["optimal_strategy"].value_counts()
        logging.info(f"\nOptimal strategy distribution:")
        for strategy, count in strategy_dist.items():
            pct = count / len(final_df) * 100
            logging.info(f"  {strategy}: {count:,} ({pct:.1f}%)")

    # Save results
    output_dir = Path("run/news_driven_features")
    output_dir.mkdir(exist_ok=True)

    # Save enhanced features
    final_pl = pl.from_pandas(final_df)
    final_pl.write_parquet(output_dir / "features.parquet")

    # Save labels separately
    labels_pl = pl.from_pandas(labels_df)
    labels_pl.write_parquet(output_dir / "labels.parquet")

    logging.info(f"✅ Saved news-driven system to {output_dir}")
    logging.info(f"   Features: {len(final_df.columns)} columns")
    logging.info(f"   Events: {len(final_df):,} rows")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
