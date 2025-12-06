#!/usr/bin/env python3
"""Generate SMB SIP without premarket volume (gap + ATR + ADV only)."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    features_file = Path("run/daily_features/features.parquet")
    output_dir = Path("run/sip_membership_smb_1month")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Modified SMB filters (no PM RVOL since we don't have premarket data)
    min_gap_pct = 0.02  # 2% gap
    min_atr = 2.0  # $2 ATR
    min_adv = 10_000_000  # 10M ADV
    top_k = 20

    LOGGER.info("=" * 80)
    LOGGER.info("SMB SIP Selection - Modified (No PM Data)")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Features: {features_file}")
    LOGGER.info(f"Filters: gap≥{min_gap_pct:.1%}, atr≥${min_atr:.2f}, adv≥{min_adv:,}")
    LOGGER.info(f"Top-k per day: {top_k}")

    df = pd.read_parquet(features_file)
    LOGGER.info(f"Loaded {len(df):,} rows, {df['date'].nunique()} dates, {df['symbol'].nunique()} symbols")

    # Apply filters (gap + ATR + ADV only)
    filtered = df[
        (df["gap_pct"].abs() >= min_gap_pct)
        & (df["atr14"] >= min_atr)
        & (df["adv20"] >= min_adv)
    ].copy()

    LOGGER.info(f"After filters: {len(filtered):,} rows")

    # Score = gap_pct * atr14 * (adv20 / 1M)
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

    # Top symbols
    top_symbols = sip["symbol"].value_counts()
    LOGGER.info("")
    LOGGER.info("Symbol Frequency:")
    for symbol, count in top_symbols.items():
        LOGGER.info(f"  {symbol}: {count} days ({count/sip['date'].nunique()*100:.1f}%)")

    LOGGER.info("")
    LOGGER.info("Sample SIP (first 15 rows):")
    print(sip[["date", "symbol", "gap_pct", "atr14", "adv20", "score"]].head(15).to_string())


if __name__ == "__main__":
    main()
