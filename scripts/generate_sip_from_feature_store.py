#!/usr/bin/env python3
"""Generate SIP membership from existing feature store."""

import logging
from pathlib import Path

import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("GENERATING SIP MEMBERSHIP FROM FEATURE STORE")
    logging.info("=" * 80)

    # Load feature store
    feature_path = Path("run/daily_features_full_gold_6months/features.parquet")
    logging.info(f"Loading features from: {feature_path}")
    
    df = pl.read_parquet(feature_path)
    logging.info(f"Loaded {len(df):,} rows, {df['symbol'].n_unique()} symbols, {df['date'].n_unique()} dates")

    # SMB SIP parameters
    min_gap_pct = 0.02  # 2% gap
    min_atr = 0.70  # $0.70 ATR (adjusted for gold universe)
    min_adv = 1_000_000  # 1M ADV (adjusted for gold universe)
    top_k = 50  # Top 50 per day

    logging.info(f"SIP Filters: gap≥{min_gap_pct:.1%}, ATR≥${min_atr:.2f}, ADV≥{min_adv:,}")
    logging.info(f"Top-k per day: {top_k}")
    logging.info("")

    # Calculate gap % (open vs prev_close)
    df = df.with_columns([
        (pl.col("gap_pct").abs()).alias("abs_gap_pct")
    ])

    # Apply filters
    filtered = df.filter(
        (pl.col("abs_gap_pct") >= min_gap_pct) &
        (pl.col("atr14") >= min_atr) &
        (pl.col("adv20") >= min_adv)
    )

    logging.info(f"After filters: {len(filtered):,} rows ({len(filtered)/len(df)*100:.1f}%)")

    # Score = |gap| * ATR * (ADV / 1M)
    filtered = filtered.with_columns([
        (pl.col("abs_gap_pct") * pl.col("atr14") * (pl.col("adv20") / 1_000_000)).alias("score")
    ])

    # Select top-k per day
    sip = (
        filtered
        .sort(["date", "score"], descending=[False, True])
        .group_by("date")
        .head(top_k)
    )

    logging.info(f"Selected {len(sip):,} symbol-date pairs")
    logging.info(f"Unique symbols: {sip['symbol'].n_unique()}")
    logging.info(f"Unique dates: {sip['date'].n_unique()}")
    logging.info(f"Avg symbols/day: {len(sip) / sip['date'].n_unique():.1f}")

    # Save
    output_dir = Path("run/sip_membership_full_gold_6months")
    output_dir.mkdir(parents=True, exist_ok=True)

    output_file = output_dir / "sip_membership.parquet"
    sip.write_parquet(output_file)

    logging.info("")
    logging.info("=" * 80)
    logging.info("SIP MEMBERSHIP GENERATED")
    logging.info("=" * 80)
    logging.info(f"Saved to: {output_file}")

    # Daily distribution
    daily_counts = sip.group_by("date").agg(pl.count().alias("count"))
    logging.info("")
    logging.info("Daily Distribution:")
    logging.info(f"  Min: {daily_counts['count'].min()}")
    logging.info(f"  Max: {daily_counts['count'].max()}")
    logging.info(f"  Mean: {daily_counts['count'].mean():.1f}")
    logging.info(f"  Std: {daily_counts['count'].std():.1f}")

    # Top symbols
    top_symbols = sip.group_by("symbol").agg(pl.count().alias("count")).sort("count", descending=True).head(20)
    logging.info("")
    logging.info("Top 20 Most Frequent Symbols:")
    for row in top_symbols.iter_rows(named=True):
        pct = row["count"] / sip["date"].n_unique() * 100
        logging.info(f"  {row['symbol']}: {row['count']} days ({pct:.1f}%)")


if __name__ == "__main__":
    main()
