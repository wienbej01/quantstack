#!/usr/bin/env python3
"""Diagnose why fixed-time approach performs worse than random."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def diagnose_methodology_errors():
    """Check for systematic errors in the fixed-time approach."""

    # Load results
    ft_path = Path("run/fixed_time_labels/labels.parquet")
    if not ft_path.exists():
        logging.error("Fixed-time results not found")
        return False

    ft_df = pd.read_parquet(ft_path)

    logging.info("=" * 80)
    logging.info("FIXED-TIME METHODOLOGY DIAGNOSIS")
    logging.info("=" * 80)

    # Basic sanity checks
    logging.info("=== BASIC SANITY CHECKS ===")
    logging.info(f"Total events: {len(ft_df):,}")
    logging.info(f"Unique symbols: {ft_df['symbol'].nunique()}")
    logging.info(f"Date range: {ft_df['date'].min()} to {ft_df['date'].max()}")

    # Check for data leakage
    logging.info("\n=== DATA LEAKAGE CHECK ===")

    # Check if exit_return is always the same as forward_return
    if "exit_return" in ft_df.columns:
        same_return = (ft_df["exit_return"] == ft_df.get("forward_return", 0)).sum()
        logging.info(
            f"Exit return = forward return: {same_return:,}/{len(ft_df):,} ({same_return/len(ft_df)*100:.1f}%)"
        )

        if same_return / len(ft_df) > 0.9:
            logging.warning(
                "⚠️ POTENTIAL ISSUE: Exit return too similar to forward return"
            )

    # Check return distribution
    logging.info("\n=== RETURN DISTRIBUTION ANALYSIS ===")

    returns = ft_df["net_return"]
    gross_returns = ft_df.get("exit_return", ft_df["net_return"])

    logging.info(f"Net return stats:")
    logging.info(f"  Mean: {returns.mean()*100:.4f}%")
    logging.info(f"  Median: {returns.median()*100:.4f}%")
    logging.info(f"  Std: {returns.std()*100:.4f}%")
    logging.info(f"  Min: {returns.min()*100:.4f}%")
    logging.info(f"  Max: {returns.max()*100:.4f}%")

    # Check if returns are normally distributed around zero
    positive_returns = (returns > 0).sum()
    negative_returns = (returns < 0).sum()
    zero_returns = (returns == 0).sum()

    logging.info(f"\nReturn distribution:")
    logging.info(
        f"  Positive: {positive_returns:,} ({positive_returns/len(ft_df)*100:.1f}%)"
    )
    logging.info(
        f"  Negative: {negative_returns:,} ({negative_returns/len(ft_df)*100:.1f}%)"
    )
    logging.info(f"  Zero: {zero_returns:,} ({zero_returns/len(ft_df)*100:.1f}%)")

    # Random expectation check
    random_expectation = (
        0.5 * returns[returns > 0].mean() + 0.5 * returns[returns < 0].mean()
    )
    logging.info(f"Random expectation (50/50): {random_expectation*100:.4f}%")

    # Check transaction costs
    logging.info("\n=== TRANSACTION COST ANALYSIS ===")

    if "total_costs" in ft_df.columns and "position_value" in ft_df.columns:
        cost_pct = ft_df["total_costs"] / ft_df["position_value"] * 100
        logging.info(f"Transaction costs:")
        logging.info(f"  Mean: {cost_pct.mean():.4f}%")
        logging.info(f"  Median: {cost_pct.median():.4f}%")
        logging.info(f"  Range: {cost_pct.min():.4f}% to {cost_pct.max():.4f}%")

        # Check if costs are too high
        if cost_pct.mean() > 0.1:  # >0.1% is high for intraday
            logging.warning(f"⚠️ HIGH TRANSACTION COSTS: {cost_pct.mean():.4f}% average")

    # Check position sizing logic
    logging.info("\n=== POSITION SIZING ANALYSIS ===")

    if "shares" in ft_df.columns:
        shares = ft_df["shares"]
        position_values = ft_df.get("position_value", shares * 100)

        logging.info(f"Position sizing:")
        logging.info(f"  Shares range: {shares.min():,} to {shares.max():,}")
        logging.info(
            f"  Position values: ${position_values.min():,.0f} to ${position_values.max():,.0f}"
        )
        logging.info(f"  Average position: ${position_values.mean():,.0f}")

        # Check for unrealistic position sizes
        large_positions = (position_values > 5000).sum()  # >50% of $10k account
        if large_positions > 0:
            logging.warning(f"⚠️ LARGE POSITIONS: {large_positions:,} positions >$5k")

    # Check forward return logic
    logging.info("\n=== FORWARD RETURN LOGIC CHECK ===")

    # Load original features to compare
    orig_path = Path("run/intraday_features_fixed/features.parquet")
    if orig_path.exists():
        import polars as pl

        orig_df = pl.read_parquet(orig_path).to_pandas()

        # Sample comparison
        sample_symbols = ft_df["symbol"].unique()[:5]

        for symbol in sample_symbols:
            ft_symbol = ft_df[ft_df["symbol"] == symbol].head(3)
            orig_symbol = orig_df[orig_df["symbol"] == symbol].head(10)

            if len(ft_symbol) > 0 and len(orig_symbol) > 0:
                logging.info(f"\nSample {symbol}:")
                for _, row in ft_symbol.iterrows():
                    timestamp = row["timestamp"]
                    exit_ret = row.get("exit_return", 0)

                    # Find matching original row
                    orig_match = orig_symbol[orig_symbol["timestamp"] == timestamp]
                    if len(orig_match) > 0:
                        orig_forward = orig_match.iloc[0]["forward_return"]
                        logging.info(
                            f"  {timestamp}: Exit={exit_ret:.4f}, Orig={orig_forward:.4f}"
                        )
                    else:
                        logging.info(
                            f"  {timestamp}: Exit={exit_ret:.4f}, Orig=NOT_FOUND"
                        )
                break

    # Check for systematic bias
    logging.info("\n=== SYSTEMATIC BIAS CHECK ===")

    # Check by hour
    hourly_returns = ft_df.groupby("hour_et")["net_return"].agg(["mean", "count"])
    logging.info("Hourly performance:")
    for hour, stats in hourly_returns.iterrows():
        mean_ret = stats["mean"] * 100
        count = stats["count"]
        logging.info(f"  Hour {hour}: {mean_ret:+.4f}% ({count:,} trades)")

    # Check by symbol (top 10 by count)
    symbol_returns = (
        ft_df.groupby("symbol")["net_return"]
        .agg(["mean", "count"])
        .sort_values("count", ascending=False)
    )
    logging.info("\nTop symbols by count:")
    for symbol, stats in symbol_returns.head(10).iterrows():
        mean_ret = stats["mean"] * 100
        count = stats["count"]
        logging.info(f"  {symbol}: {mean_ret:+.4f}% ({count:,} trades)")

    # Check for time-based patterns
    logging.info("\n=== TIME-BASED PATTERN CHECK ===")

    ft_df["date_dt"] = pd.to_datetime(ft_df["date"])
    ft_df["year"] = ft_df["date_dt"].dt.year
    ft_df["month"] = ft_df["date_dt"].dt.month

    # Yearly performance
    yearly_returns = ft_df.groupby("year")["net_return"].agg(["mean", "count"])
    logging.info("Yearly performance:")
    for year, stats in yearly_returns.iterrows():
        mean_ret = stats["mean"] * 100
        count = stats["count"]
        logging.info(f"  {year}: {mean_ret:+.4f}% ({count:,} trades)")

    # Check for obvious errors
    logging.info("\n=== ERROR DETECTION ===")

    errors_found = []

    # Error 1: All returns are the same
    if returns.std() < 1e-6:
        errors_found.append("All returns are identical")

    # Error 2: Returns are too large
    if abs(returns.mean()) > 0.1:  # >10% average return is unrealistic
        errors_found.append(f"Unrealistic average return: {returns.mean()*100:.2f}%")

    # Error 3: No variation in position sizes
    if "shares" in ft_df.columns and ft_df["shares"].std() < 1:
        errors_found.append("No variation in position sizes")

    # Error 4: Transaction costs too high
    if "total_costs" in ft_df.columns:
        avg_cost_pct = (ft_df["total_costs"] / ft_df["position_value"]).mean()
        if avg_cost_pct > 0.002:  # >0.2% is high
            errors_found.append(f"High transaction costs: {avg_cost_pct*100:.3f}%")

    # Error 5: Negative bias in all hours
    all_hours_negative = all(hourly_returns["mean"] < 0)
    if all_hours_negative:
        errors_found.append("All hours show negative returns (systematic bias)")

    if errors_found:
        logging.error("\n🚨 ERRORS DETECTED:")
        for i, error in enumerate(errors_found, 1):
            logging.error(f"  {i}. {error}")
    else:
        logging.info("\n✅ No obvious errors detected")

    # Recommendations
    logging.info("\n=== RECOMMENDATIONS ===")

    if len(errors_found) > 0:
        logging.info("CRITICAL ISSUES FOUND - Fix before proceeding:")
        if "High transaction costs" in str(errors_found):
            logging.info("  - Reduce transaction cost assumptions")
        if "systematic bias" in str(errors_found):
            logging.info("  - Check forward return calculation logic")
        if "Unrealistic" in str(errors_found):
            logging.info("  - Validate return calculation methodology")
    else:
        logging.info("METHODOLOGY APPEARS SOUND - Consider:")
        logging.info("  - Market conditions may be genuinely difficult")
        logging.info("  - Entry filters may need tightening")
        logging.info("  - Different holding periods may work better")
        logging.info("  - Market regime filtering may be needed")

    return True


if __name__ == "__main__":
    success = diagnose_methodology_errors()
    exit(0 if success else 1)
