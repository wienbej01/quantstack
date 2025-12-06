#!/usr/bin/env python3
"""Generate SMB SIP membership from precomputed daily features (fast)."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    features_file = Path("run/daily_features/features.parquet")
    output_dir = Path("run/sip_membership_smb_1month")
    output_dir.mkdir(parents=True, exist_ok=True)

    # SMB filter thresholds
    min_gap_pct = 0.03
    min_pm_rvol = 0.10
    min_atr = 0.70
    min_adv = 1_000_000
    top_k = 20

    LOGGER.info("=" * 80)
    LOGGER.info("SMB SIP Selection from Feature Store")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Features: {features_file}")
    LOGGER.info(
        f"Filters: gap≥{min_gap_pct:.1%}, pm_rvol≥{min_pm_rvol:.2f}, atr≥${min_atr:.2f}, adv≥{min_adv:,}"
    )
    LOGGER.info(f"Top-k per day: {top_k}")

    # Load features
    df = pd.read_parquet(features_file)
    LOGGER.info(
        f"Loaded {len(df):,} rows, {df['date'].nunique()} dates, {df['symbol'].nunique()} symbols"
    )

    # Apply SMB filters
    filtered = df[
        (df["gap_pct"].abs() >= min_gap_pct)
        & (df["pm_rvol"] >= min_pm_rvol)
        & (df["atr14"] >= min_atr)
        & (df["adv20"] >= min_adv)
    ].copy()

    LOGGER.info(f"After filters: {len(filtered):,} rows")

    # Score = gap_pct * pm_rvol * atr14
    filtered["score"] = filtered["gap_pct"].abs() * filtered["pm_rvol"] * filtered["atr14"]

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
    LOGGER.info("SIP Membership Generated")
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
    top_symbols = sip["symbol"].value_counts().head(10)
    LOGGER.info("")
    LOGGER.info("Top 10 Most Frequent Symbols:")
    for symbol, count in top_symbols.items():
        LOGGER.info(f"  {symbol}: {count} days")

    # Save summary
    summary_file = output_dir / "validation_summary.txt"
    with open(summary_file, "w") as f:
        f.write("SMB SIP 1-Month Validation Summary\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total rows: {len(sip):,}\n")
        f.write(f"Unique symbols: {sip['symbol'].nunique()}\n")
        f.write(f"Unique dates: {sip['date'].nunique()}\n")
        f.write(f"Avg stocks/day: {len(sip) / sip['date'].nunique():.1f}\n\n")
        f.write("Daily Distribution:\n")
        f.write(f"  Min: {daily_counts.min()}\n")
        f.write(f"  Max: {daily_counts.max()}\n")
        f.write(f"  Mean: {daily_counts.mean():.1f}\n")
        f.write(f"  Median: {daily_counts.median():.1f}\n\n")
        f.write("Top 10 Symbols:\n")
        for symbol, count in top_symbols.items():
            f.write(f"  {symbol}: {count} days\n")

    LOGGER.info(f"Summary saved to: {summary_file}")


if __name__ == "__main__":
    main()
