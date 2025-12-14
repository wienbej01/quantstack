#!/usr/bin/env python3
"""Analyze news-driven system performance and features."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def analyze_news_system():
    """Comprehensive analysis of news-driven system."""

    # Load results
    features_path = Path("run/news_driven_features/features.parquet")
    labels_path = Path("run/news_driven_features/labels.parquet")

    if not features_path.exists() or not labels_path.exists():
        logging.error("News-driven results not found")
        return False

    features_df = pd.read_parquet(features_path)
    labels_df = pd.read_parquet(labels_path)

    logging.info("=" * 80)
    logging.info("NEWS-DRIVEN SYSTEM ANALYSIS")
    logging.info("=" * 80)

    # Basic statistics
    logging.info(
        f"Features dataset: {len(features_df):,} rows, {len(features_df.columns)} columns"
    )
    logging.info(f"Labels dataset: {len(labels_df):,} events")

    # Strategy performance analysis
    logging.info("\n=== STRATEGY PERFORMANCE ANALYSIS ===")

    strategies = ["gap_fade", "continuation", "momentum", "reversion"]

    for strategy in strategies:
        label_col = f"{strategy}_label"
        return_col = f"{strategy}_return"

        if label_col in labels_df.columns:
            # Basic metrics
            total_opportunities = (labels_df[return_col] != 0).sum()
            positive_labels = labels_df[label_col].sum()
            label_rate = (
                (positive_labels / total_opportunities * 100)
                if total_opportunities > 0
                else 0
            )

            # Performance when strategy triggers
            strategy_returns = labels_df[labels_df[label_col] == 1][return_col]
            if len(strategy_returns) > 0:
                avg_return = strategy_returns.mean() * 100
                win_rate = (strategy_returns > 0).mean() * 100
                return_std = strategy_returns.std() * 100
                sharpe = avg_return / return_std if return_std > 0 else 0
            else:
                avg_return = win_rate = return_std = sharpe = 0

            logging.info(f"\n{strategy.upper()}:")
            logging.info(f"  Opportunities: {total_opportunities:,}")
            logging.info(f"  Positive labels: {positive_labels:,} ({label_rate:.2f}%)")
            logging.info(f"  Avg return: {avg_return:.3f}%")
            logging.info(f"  Win rate: {win_rate:.1f}%")
            logging.info(f"  Sharpe: {sharpe:.3f}")

    # Optimal strategy analysis
    logging.info("\n=== OPTIMAL STRATEGY ANALYSIS ===")

    if "optimal_strategy" in labels_df.columns:
        strategy_dist = labels_df["optimal_strategy"].value_counts()
        optimal_returns = labels_df.groupby("optimal_strategy")["optimal_return"].agg(
            ["mean", "std", "count"]
        )

        for strategy in strategy_dist.index:
            count = strategy_dist[strategy]
            pct = count / len(labels_df) * 100
            avg_ret = optimal_returns.loc[strategy, "mean"] * 100
            ret_std = optimal_returns.loc[strategy, "std"] * 100
            sharpe = avg_ret / ret_std if ret_std > 0 else 0

            logging.info(
                f"{strategy.upper()}: {count:,} ({pct:.1f}%) - "
                f"Return: {avg_ret:.3f}%, Sharpe: {sharpe:.3f}"
            )

    # Time-of-day analysis
    logging.info("\n=== TIME-OF-DAY ANALYSIS ===")

    if "hour_et" in labels_df.columns:
        hourly_stats = (
            labels_df.groupby("hour_et")
            .agg({"optimal_return": ["mean", "std", "count"], "optimal_label": "mean"})
            .round(4)
        )

        for hour in sorted(labels_df["hour_et"].unique()):
            hour_data = labels_df[labels_df["hour_et"] == hour]
            avg_ret = hour_data["optimal_return"].mean() * 100
            label_rate = hour_data["optimal_label"].mean() * 100
            count = len(hour_data)

            logging.info(
                f"Hour {hour}: {count:,} events, {avg_ret:+.3f}% return, {label_rate:.1f}% labels"
            )

    # Feature importance proxy analysis
    logging.info("\n=== FEATURE ANALYSIS ===")

    # Check key news-driven features
    key_features = [
        "news_attention_score",
        "volatility_expansion_ratio",
        "volume_expansion_ratio",
        "gap_size",
        "is_large_gap",
        "is_high_volume",
        "momentum_sustainability",
    ]

    for feature in key_features:
        if feature in features_df.columns:
            stats = features_df[feature].describe()
            logging.info(f"{feature}: mean={stats['mean']:.4f}, std={stats['std']:.4f}")

    # News-driven edge analysis
    logging.info("\n=== NEWS-DRIVEN EDGE ANALYSIS ===")

    # Large gap analysis
    if "is_large_gap" in features_df.columns and "optimal_return" in labels_df.columns:
        # Merge for analysis
        merged_df = features_df.merge(
            labels_df, on=["symbol", "timestamp"], how="inner"
        )

        large_gap_trades = merged_df[merged_df["is_large_gap"] == 1]
        normal_trades = merged_df[merged_df["is_large_gap"] == 0]

        if len(large_gap_trades) > 0 and len(normal_trades) > 0:
            large_gap_return = large_gap_trades["optimal_return"].mean() * 100
            normal_return = normal_trades["optimal_return"].mean() * 100

            logging.info(
                f"Large gap trades: {len(large_gap_trades):,} ({large_gap_return:.3f}% avg return)"
            )
            logging.info(
                f"Normal trades: {len(normal_trades):,} ({normal_return:.3f}% avg return)"
            )
            logging.info(f"Gap edge: {large_gap_return - normal_return:.3f}%")

    # High volume analysis
    if "is_high_volume" in features_df.columns:
        high_vol_trades = merged_df[merged_df["is_high_volume"] == 1]
        normal_vol_trades = merged_df[merged_df["is_high_volume"] == 0]

        if len(high_vol_trades) > 0 and len(normal_vol_trades) > 0:
            high_vol_return = high_vol_trades["optimal_return"].mean() * 100
            normal_vol_return = normal_vol_trades["optimal_return"].mean() * 100

            logging.info(
                f"High volume trades: {len(high_vol_trades):,} ({high_vol_return:.3f}% avg return)"
            )
            logging.info(
                f"Normal volume trades: {len(normal_vol_trades):,} ({normal_vol_return:.3f}% avg return)"
            )
            logging.info(f"Volume edge: {high_vol_return - normal_vol_return:.3f}%")

    # Multi-horizon analysis
    logging.info("\n=== MULTI-HORIZON ANALYSIS ===")

    horizons = ["15min", "30min", "60min", "120min"]
    for horizon in horizons:
        col = f"return_{horizon}"
        if col in labels_df.columns:
            returns = labels_df[col]
            avg_ret = returns.mean() * 100
            win_rate = (returns > 0).mean() * 100

            logging.info(
                f"{horizon}: {avg_ret:+.3f}% avg return, {win_rate:.1f}% win rate"
            )

    # Overall system assessment
    logging.info("\n=== SYSTEM ASSESSMENT ===")

    # Calculate overall expected value
    if "optimal_return" in labels_df.columns:
        overall_ev = labels_df["optimal_return"].mean() * 100
        overall_std = labels_df["optimal_return"].std() * 100
        overall_sharpe = overall_ev / overall_std if overall_std > 0 else 0
        overall_win_rate = (labels_df["optimal_return"] > 0).mean() * 100

        logging.info(f"Overall Expected Value: {overall_ev:.3f}%")
        logging.info(f"Overall Sharpe Ratio: {overall_sharpe:.3f}")
        logging.info(f"Overall Win Rate: {overall_win_rate:.1f}%")

        # Profitability assessment
        if overall_ev > 0.05:  # >5 bps
            logging.info("✅ SYSTEM SHOWS POSITIVE EDGE")
        elif overall_ev > -0.05:  # Within 5 bps of breakeven
            logging.info("⚠️ SYSTEM NEAR BREAKEVEN - OPTIMIZATION POTENTIAL")
        else:
            logging.info("❌ SYSTEM SHOWS NEGATIVE EDGE")

    # Data quality assessment
    logging.info(f"\nData Quality:")
    logging.info(f"  Total events: {len(labels_df):,}")
    logging.info(f"  Sufficient for ML: {'✅' if len(labels_df) > 10000 else '❌'}")
    logging.info(f"  Feature richness: {len(features_df.columns)} features")

    # Recommendations
    logging.info("\n=== RECOMMENDATIONS ===")

    if overall_ev > 0:
        logging.info("🚀 PROCEED WITH MODEL TRAINING")
        logging.info("   - System shows positive expected value")
        logging.info("   - Focus on multi-strategy ensemble approach")
        logging.info("   - Implement dynamic position sizing")
    else:
        logging.info("🔧 OPTIMIZATION NEEDED")
        logging.info("   - Tighten strategy filters")
        logging.info("   - Focus on highest-performing time windows")
        logging.info("   - Add market regime detection")
        logging.info("   - Consider transaction cost optimization")

    return True


if __name__ == "__main__":
    success = analyze_news_system()
    exit(0 if success else 1)
