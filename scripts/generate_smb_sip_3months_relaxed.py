#!/usr/bin/env python3
"""Generate SMB SIP with RELAXED filters for larger universe."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    features_file = Path("run/daily_features_3months/features.parquet")
    output_dir = Path("run/sip_membership_smb_3months_relaxed")
    output_dir.mkdir(parents=True, exist_ok=True)

    # RELAXED SMB filters for larger universe
    min_gap_pct = 0.01  # 1% gap (was 2%)
    min_atr = 1.0  # $1 ATR (was $2)
    min_adv = 5_000_000  # 5M ADV (was 10M)
    top_k = 50  # Top 50 per day (was 20)

    LOGGER.info("=" * 80)
    LOGGER.info("SMB SIP Selection - RELAXED FILTERS")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Features: {features_file}")
    LOGGER.info(f"Filters: gap≥{min_gap_pct:.1%}, atr≥${min_atr:.2f}, adv≥{min_adv:,}")
    LOGGER.info(f"Top-k per day: {top_k}")

    # Load features
    df = pd.read_parquet(features_file)
    LOGGER.info(f"Loaded {len(df):,} rows, {df['date'].nunique()} dates, {df['symbol'].nunique()} symbols")

    # Apply filters
    filtered = df[
        (df["gap_pct"].abs() >= min_gap_pct)
        & (df["atr14"] >= min_atr)
        & (df["adv20"] >= min_adv)
    ].copy()

    LOGGER.info(f"After filters: {len(filtered):,} rows")

    # Score = |gap%| × ATR × (ADV/1M)
    filtered["score"] = filtered["gap_pct"].abs() * filtered["atr14"] * (filtered["adv20"] / 1_000_000)

    # Select top-k per day
    sip = (
        filtered.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date")
        .head(top_k)
    )

    LOGGER.info(f"Top-{top_k} per day: {len(sip):,} rows")

    # Save
    output_file = output_dir / "sip_membership.parquet"
    sip.to_parquet(output_file, index=False)

    LOGGER.info("=" * 80)
    LOGGER.info("SIP Membership Generated - RELAXED")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Total rows: {len(sip):,}")
    LOGGER.info(f"Unique symbols: {sip['symbol'].nunique()}")
    LOGGER.info(f"Date range: {sip['date'].min()} to {sip['date'].max()}")
    LOGGER.info(f"Avg stocks/day: {len(sip) / sip['date'].nunique():.1f}")
    LOGGER.info(f"Saved to: {output_file}")

    # Daily distribution
    daily_counts = sip.groupby("date").size()
    LOGGER.info("")
    LOGGER.info("Daily Distribution:")
    LOGGER.info(f"  Min: {daily_counts.min()}")
    LOGGER.info(f"  Max: {daily_counts.max()}")
    LOGGER.info(f"  Mean: {daily_counts.mean():.1f}")
    LOGGER.info(f"  Median: {daily_counts.median():.1f}")

    # Top symbols
    top_symbols = sip["symbol"].value_counts().head(20)
    LOGGER.info("")
    LOGGER.info("Top 20 Most Frequent Symbols:")
    for symbol, count in top_symbols.items():
        LOGGER.info(f"  {symbol}: {count} days")

    # Save summary
    summary_file = output_dir / "summary.txt"
    with open(summary_file, "w") as f:
        f.write("SMB SIP 3-Month Summary - RELAXED FILTERS\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Filters: gap≥{min_gap_pct:.1%}, atr≥${min_atr:.2f}, adv≥{min_adv:,}\n")
        f.write(f"Top-k: {top_k}\n\n")
        f.write(f"Period: {sip['date'].min()} to {sip['date'].max()}\n")
        f.write(f"Total rows: {len(sip):,}\n")
        f.write(f"Unique symbols: {sip['symbol'].nunique()}\n")
        f.write(f"Unique dates: {sip['date'].nunique()}\n")
        f.write(f"Avg stocks/day: {len(sip) / sip['date'].nunique():.1f}\n\n")
        f.write("Daily Distribution:\n")
        f.write(f"  Min: {daily_counts.min()}\n")
        f.write(f"  Max: {daily_counts.max()}\n")
        f.write(f"  Mean: {daily_counts.mean():.1f}\n")
        f.write(f"  Median: {daily_counts.median():.1f}\n\n")
        f.write("Top 20 Symbols:\n")
        for symbol, count in top_symbols.items():
            f.write(f"  {symbol}: {count} days\n")

    LOGGER.info(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
