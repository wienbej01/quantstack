#!/usr/bin/env python3
"""
L2 Order Size Distribution Analysis - Efficient Streaming Version

Processes data incrementally without loading all 482k files into RAM.
"""

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
L2_RAW_DIR = Path("/home/jacobw/quantstack/data/l2/l2_maximum/raw")
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output/size_analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def process_file_incremental(
    pq_file: Path, symbol: str, date: str
) -> tuple[list[float], list[float]]:
    """Process a single parquet file and return bid/ask sizes."""
    try:
        df = pd.read_parquet(pq_file)
    except Exception:
        return [], []

    bid_sizes = []
    ask_sizes = []

    for level in range(1, 6):
        bid_col = f"bid_sz_{level}"
        ask_col = f"ask_sz_{level}"

        if bid_col in df.columns:
            bid_sizes.extend(df[bid_col].dropna().tolist())
        if ask_col in df.columns:
            ask_sizes.extend(df[ask_col].dropna().tolist())

    return bid_sizes, ask_sizes


def compute_stats_from_sizes(sizes: list[float], name: str) -> dict[str, Any]:
    """Compute statistics from a list of sizes."""
    sizes = np.array(sizes)
    sizes = sizes[sizes > 0]

    if len(sizes) == 0:
        return {}

    values, counts = np.unique(sizes, return_counts=True)
    mode_idx = np.argmax(counts)

    return {
        "name": name,
        "count": len(sizes),
        "mean": float(np.mean(sizes)),
        "median": float(np.median(sizes)),
        "std": float(np.std(sizes)),
        "min": float(np.min(sizes)),
        "max": float(np.max(sizes)),
        "mode": float(values[mode_idx]),
        "mode_count": int(counts[mode_idx]),
        "mode_pct": float(counts[mode_idx] / len(sizes) * 100),
        "p50": float(np.percentile(sizes, 50)),
        "p75": float(np.percentile(sizes, 75)),
        "p90": float(np.percentile(sizes, 90)),
        "p95": float(np.percentile(sizes, 95)),
        "p99": float(np.percentile(sizes, 99)),
    }


def main():
    """Main entry point - streaming processing."""

    logger.info("=" * 70)
    logger.info("L2 ORDER SIZE DISTRIBUTION (STREAMING VERSION)")
    logger.info("=" * 70)

    # Collect all sizes incrementally
    all_bid_sizes = []
    all_ask_sizes = []
    symbol_sizes = {}
    file_count = 0
    start_time = __import__("time").time()

    logger.info("\n[1/3] Processing files incrementally...")

    for date_dir in sorted(L2_RAW_DIR.glob("date=*")):
        date_str = date_dir.name.replace("date=", "")
        logger.info(f"  Processing {date_str}...")

        for symbol_dir in date_dir.glob("symbol=*"):
            symbol = symbol_dir.name.replace("symbol=", "")

            if symbol not in symbol_sizes:
                symbol_sizes[symbol] = {"bid": [], "ask": []}

            for pq_file in symbol_dir.glob("*.parquet"):
                bid_sz, ask_sz = process_file_incremental(pq_file, symbol, date_str)

                all_bid_sizes.extend(bid_sz)
                all_ask_sizes.extend(ask_sz)
                symbol_sizes[symbol]["bid"].extend(bid_sz)
                symbol_sizes[symbol]["ask"].extend(ask_sz)

                file_count += 1

                if file_count % 50000 == 0:
                    elapsed = __import__("time").time() - start_time
                    logger.info(f"    Processed {file_count:,} files in {elapsed:.0f}s")

    elapsed = __import__("time").time() - start_time
    logger.info(f"\n  Processed {file_count:,} files in {elapsed:.0f}s")

    # Compute statistics
    logger.info("\n[2/3] Computing statistics...")

    results = []

    # Overall stats
    logger.info("  Overall statistics...")
    results.append(compute_stats_from_sizes(all_bid_sizes, "overall_bid"))
    results.append(compute_stats_from_sizes(all_ask_sizes, "overall_ask"))

    # Per-symbol stats
    logger.info("  Per-symbol statistics...")
    for symbol in sorted(symbol_sizes.keys()):
        results.append(compute_stats_from_sizes(symbol_sizes[symbol]["bid"], f"{symbol}_bid"))
        results.append(compute_stats_from_sizes(symbol_sizes[symbol]["ask"], f"{symbol}_ask"))

    stats_df = pd.DataFrame(results)

    # Save results
    logger.info("\n[3/3] Saving results...")

    stats_file = OUTPUT_DIR / "size_distribution.csv"
    stats_df.to_csv(stats_file, index=False)
    logger.info(f"  Saved to {stats_file}")

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)

    overall_bid = stats_df[stats_df["name"] == "overall_bid"].iloc[0]
    overall_ask = stats_df[stats_df["name"] == "overall_ask"].iloc[0]

    logger.info(f"\nBid Sizes (n={overall_bid['count']:,}):")
    logger.info(f"  Mode: {overall_bid['mode']:.0f} ({overall_bid['mode_pct']:.1f}%)")
    logger.info(f"  Mean: {overall_bid['mean']:.1f}")
    logger.info(f"  95th percentile: {overall_bid['p95']:.0f}")
    logger.info(f"  Max: {overall_bid['max']:.0f}")

    logger.info(f"\nAsk Sizes (n={overall_ask['count']:,}):")
    logger.info(f"  Mode: {overall_ask['mode']:.0f} ({overall_ask['mode_pct']:.1f}%)")
    logger.info(f"  Mean: {overall_ask['mean']:.1f}")
    logger.info(f"  95th percentile: {overall_ask['p95']:.0f}")
    logger.info(f"  Max: {overall_ask['max']:.0f}")

    logger.info(f"\n100 shares = round lot (standard market maker quoting)")
    logger.info(f"'Large order' threshold: ~{overall_bid['p95']:.0f} shares (95th percentile)")

    logger.info(f"\nDone! Results saved to {stats_file}")


if __name__ == "__main__":
    main()
