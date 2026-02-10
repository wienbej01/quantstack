#!/usr/bin/env python3
"""
L2 Order Size Distribution Analysis

Characterizes order sizes in L2 market data to understand:
1. Distribution of bid/ask sizes (is 100 dominant?)
2. Symbol-by-symbol variations
3. "Large order" thresholds using percentiles
4. Time-of-day patterns in large orders
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
L2_RAW_DIR = Path("/home/jacobw/quantstack/data/l2/l2_maximum/raw")
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output/size_analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def load_l2_raw_data() -> pd.DataFrame:
    """Load all raw L2 data from parquet files."""
    logger.info("Loading raw L2 data...")
    import sys
    import time

    all_data = []
    file_count = 0
    start_time = time.time()

    for date_dir in sorted(L2_RAW_DIR.glob("date=*")):
        date_str = date_dir.name.replace("date=", "")
        logger.info(f"  Processing {date_str}...")
        sys.stdout.flush()

        for symbol_dir in date_dir.glob("symbol=*"):
            symbol = symbol_dir.name.replace("symbol=", "")

            for pq_file in symbol_dir.glob("*.parquet"):
                try:
                    df = pd.read_parquet(pq_file)
                    df["symbol"] = symbol
                    df["date"] = date_str
                    all_data.append(df)
                    file_count += 1

                    # Heartbeat every 100 files
                    if file_count % 100 == 0:
                        elapsed = time.time() - start_time
                        logger.info(f"    Loaded {file_count} files in {elapsed:.0f}s...")
                        sys.stdout.flush()
                except Exception as e:
                    logger.warning(f"    Error loading {pq_file}: {e}")

    if not all_data:
        logger.error("No L2 data found!")
        return pd.DataFrame()

    df = pd.concat(all_data, ignore_index=True)
    logger.info(f"Loaded {len(df):,} L2 snapshots across {df['symbol'].nunique()} symbols")
    return df


def extract_all_sizes(df: pd.DataFrame) -> dict[str, list[float]]:
    """Extract all bid and ask sizes from the dataframe."""
    logger.info("Extracting all order sizes...")

    bid_sizes = []
    ask_sizes = []

    for level in range(1, 6):  # 5 levels
        bid_col = f"bid_sz_{level}"
        ask_col = f"ask_sz_{level}"

        if bid_col in df.columns:
            bid_sizes.extend(df[bid_col].dropna().tolist())
        if ask_col in df.columns:
            ask_sizes.extend(df[ask_col].dropna().tolist())

    logger.info(f"  {len(bid_sizes):,} bid sizes, {len(ask_sizes):,} ask sizes")

    return {"bid": bid_sizes, "ask": ask_sizes}


def compute_size_stats(sizes: list[float], name: str) -> dict[str, Any]:
    """Compute statistics for a size distribution."""
    sizes = np.array(sizes)
    sizes = sizes[sizes > 0]  # Filter out zeros

    if len(sizes) == 0:
        return {}

    unique_sizes = sorted(set(sizes))
    percentiles = [50, 75, 90, 95, 97.5, 99]

    stats_dict = {
        "name": name,
        "count": len(sizes),
        "mean": float(np.mean(sizes)),
        "std": float(np.std(sizes)),
        "min": float(np.min(sizes)),
        "max": float(np.max(sizes)),
        "unique_count": len(unique_sizes),
        "unique_sizes": unique_sizes[:20],  # First 20 unique sizes
    }

    for p in percentiles:
        stats_dict[f"p{p}"] = float(np.percentile(sizes, p))

    # Mode (most common size)
    values, counts = np.unique(sizes, return_counts=True)
    mode_idx = np.argmax(counts)
    stats_dict["mode"] = float(values[mode_idx])
    stats_dict["mode_count"] = int(counts[mode_idx])
    stats_dict["mode_pct"] = float(counts[mode_idx] / len(sizes) * 100)

    return stats_dict


def analyze_symbol_sizes(
    df: pd.DataFrame, symbol: str
) -> dict[str, dict[str, Any]]:
    """Analyze size distribution for a specific symbol."""
    symbol_df = df[df["symbol"] == symbol]

    bid_sizes = []
    ask_sizes = []

    for level in range(1, 6):
        bid_col = f"bid_sz_{level}"
        ask_col = f"ask_sz_{level}"

        if bid_col in symbol_df.columns:
            bid_sizes.extend(symbol_df[bid_col].dropna().tolist())
        if ask_col in symbol_df.columns:
            ask_sizes.extend(symbol_df[ask_col].dropna().tolist())

    return {
        "bid": compute_size_stats(bid_sizes, f"{symbol}_bid"),
        "ask": compute_size_stats(ask_sizes, f"{symbol}_ask"),
    }


def compute_aggregate_statistics(
    df: pd.DataFrame, sizes: dict[str, list[float]]
) -> pd.DataFrame:
    """Compute aggregate and per-symbol size statistics."""
    results = []

    # Overall statistics
    logger.info("\n=== OVERALL SIZE DISTRIBUTION ===")
    bid_stats = compute_size_stats(sizes["bid"], "overall_bid")
    ask_stats = compute_size_stats(sizes["ask"], "overall_ask")

    results.append(bid_stats)
    results.append(ask_stats)

    logger.info(f"\nBid Sizes:")
    logger.info(f"  Unique values: {bid_stats['unique_count']}")
    logger.info(f"  Mode: {bid_stats['mode']:.0f} ({bid_stats['mode_pct']:.1f}%)")
    logger.info(f"  Mean: {bid_stats['mean']:.1f}")
    logger.info(f"  50th/75th/90th/95th: {bid_stats['p50']:.0f} / {bid_stats['p75']:.0f} / {bid_stats['p90']:.0f} / {bid_stats['p95']:.0f}")

    logger.info(f"\nAsk Sizes:")
    logger.info(f"  Unique values: {ask_stats['unique_count']}")
    logger.info(f"  Mode: {ask_stats['mode']:.0f} ({ask_stats['mode_pct']:.1f}%)")
    logger.info(f"  Mean: {ask_stats['mean']:.1f}")
    logger.info(f"  50th/75th/90th/95th: {ask_stats['p50']:.0f} / {ask_stats['p75']:.0f} / {ask_stats['p90']:.0f} / {ask_stats['p95']:.0f}")

    # Per-symbol statistics
    logger.info("\n=== PER-SYMBOL STATISTICS ===")
    for symbol in sorted(df["symbol"].unique()):
        symbol_stats = analyze_symbol_sizes(df, symbol)
        results.append(symbol_stats["bid"])
        results.append(symbol_stats["ask"])

        logger.info(f"\n{symbol}:")
        logger.info(
            f"  Bid: mode={symbol_stats['bid']['mode']:.0f} ({symbol_stats['bid']['mode_pct']:.1f}%), "
            f"p95={symbol_stats['bid']['p95']:.0f}"
        )
        logger.info(
            f"  Ask: mode={symbol_stats['ask']['mode']:.0f} ({symbol_stats['ask']['mode_pct']:.1f}%), "
            f"p95={symbol_stats['ask']['p95']:.0f}"
        )

    return pd.DataFrame(results)


def identify_large_order_thresholds(
    df: pd.DataFrame, percentiles: list[float] = [90, 95, 97.5, 99]
) -> pd.DataFrame:
    """Identify 'large order' thresholds per symbol using percentiles."""
    logger.info("\n=== LARGE ORDER THRESHOLDS (PER-SYMBOL) ===")

    thresholds = []

    for symbol in sorted(df["symbol"].unique()):
        symbol_df = df[df["symbol"] == symbol]

        # Collect all sizes for this symbol
        all_sizes = []
        for level in range(1, 6):
            for col in [f"bid_sz_{level}", f"ask_sz_{level}"]:
                if col in symbol_df.columns:
                    all_sizes.extend(symbol_df[col].dropna().tolist())

        all_sizes = np.array(all_sizes)
        all_sizes = all_sizes[all_sizes > 0]

        threshold_row = {"symbol": symbol, "count": len(all_sizes)}

        for p in percentiles:
            threshold_row[f"p{p}"] = float(np.percentile(all_sizes, p))

        thresholds.append(threshold_row)

        logger.info(
            f"{symbol:6s}: p90={threshold_row['p90']:.0f}, "
            f"p95={threshold_row['p95']:.0f}, "
            f"p99={threshold_row['p99']:.0f}"
        )

    return pd.DataFrame(thresholds)


def analyze_time_of_day_patterns(df: pd.DataFrame) -> pd.DataFrame:
    """Analyze size patterns by time of day."""
    logger.info("\n=== TIME-OF-DAY PATTERNS ===")

    # Convert ts_utc to datetime and extract hour
    df = df.copy()
    df["hour"] = pd.to_datetime(df["ts_utc"]).dt.hour

    # Define "large order" as >95th percentile overall
    all_sizes = []
    for level in range(1, 6):
        for col in [f"bid_sz_{level}", f"ask_sz_{level}"]:
            if col in df.columns:
                all_sizes.extend(df[col].dropna().tolist())

    all_sizes = np.array(all_sizes)
    all_sizes = all_sizes[all_sizes > 0]
    large_threshold = float(np.percentile(all_sizes, 95))

    logger.info(f"Using large order threshold: >{large_threshold:.0f} shares (95th percentile)")

    # Count large orders by hour
    hour_stats = []

    for hour in range(9, 17):  # Market hours 9-16
        hour_df = df[df["hour"] == hour]

        total_levels = 0
        large_count = 0

        for level in range(1, 6):
            for col in [f"bid_sz_{level}", f"ask_sz_{level}"]:
                if col in hour_df.columns:
                    sizes = hour_df[col].dropna()
                    total_levels += len(sizes)
                    large_count += (sizes > large_threshold).sum()

        if total_levels > 0:
            hour_stats.append({
                "hour": hour,
                "total_levels": total_levels,
                "large_count": large_count,
                "large_pct": large_count / total_levels * 100,
            })

    hour_df_result = pd.DataFrame(hour_stats)

    logger.info("\nHour | Large Order %")
    logger.info("-" * 30)
    for _, row in hour_df_result.iterrows():
        logger.info(f"{row['hour']:2d}   | {row['large_pct']:5.2f}%")

    return hour_df_result


def main():
    """Main entry point for size distribution analysis."""

    logger.info("=" * 70)
    logger.info("L2 ORDER SIZE DISTRIBUTION ANALYSIS")
    logger.info("=" * 70)

    # Load data
    logger.info("\n[1/4] Loading raw L2 data...")
    df = load_l2_raw_data()

    if df.empty:
        logger.error("No data loaded!")
        return

    # Extract sizes
    logger.info("\n[2/4] Extracting order sizes...")
    sizes = extract_all_sizes(df)

    # Compute statistics
    logger.info("\n[3/4] Computing statistics...")
    stats_df = compute_aggregate_statistics(df, sizes)

    # Save statistics
    stats_file = OUTPUT_DIR / "size_distribution.csv"
    stats_df.to_csv(stats_file, index=False)
    logger.info(f"\nSaved statistics to {stats_file}")

    # Identify large order thresholds
    thresholds_df = identify_large_order_thresholds(df)

    thresholds_file = OUTPUT_DIR / "large_order_thresholds.csv"
    thresholds_df.to_csv(thresholds_file, index=False)
    logger.info(f"\nSaved thresholds to {thresholds_file}")

    # Time of day patterns
    logger.info("\n[4/4] Analyzing time-of-day patterns...")
    hour_df = analyze_time_of_day_patterns(df)

    hour_file = OUTPUT_DIR / "time_of_day_patterns.csv"
    hour_df.to_csv(hour_file, index=False)
    logger.info(f"\nSaved time-of-day patterns to {hour_file}")

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)

    bid_mode = stats_df[stats_df["name"] == "overall_bid"]["mode"].values[0]
    bid_mode_pct = stats_df[stats_df["name"] == "overall_bid"]["mode_pct"].values[0]
    bid_p95 = stats_df[stats_df["name"] == "overall_bid"]["p95"].values[0]

    logger.info(f"\nRound Lot (100 shares) dominance:")
    logger.info(f"  Mode: {bid_mode:.0f} shares ({bid_mode_pct:.1f}% of all orders)")
    logger.info(f"  95th percentile: {bid_p95:.0f} shares")

    logger.info(f"\nInterpretation:")
    if bid_mode == 100 and bid_mode_pct > 50:
        logger.info(
            f"  ✓ 100-share round lots dominate ({bid_mode_pct:.1f}%) - "
            "typical market maker quoting"
        )
    logger.info(f"  'Institutional' threshold: >{bid_p95:.0f} shares (95th percentile)")

    logger.info(f"\nOutputs:")
    logger.info(f"  - {stats_file}")
    logger.info(f"  - {thresholds_file}")
    logger.info(f"  - {hour_file}")


if __name__ == "__main__":
    main()
