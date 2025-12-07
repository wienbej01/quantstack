#!/usr/bin/env python3
"""Generate SIP membership for rolling period."""

import logging
from pathlib import Path

import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("GENERATING SIP MEMBERSHIP: 2023-07 to 2025-09")
    logging.info("=" * 80)
    
    features_path = Path("run/daily_features_rolling/features.parquet")
    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)
    logging.info(f"Loaded {len(df):,} rows, {df['symbol'].n_unique()} symbols, {df['date'].n_unique()} dates")
    
    # SIP filters
    min_gap_pct = 0.02
    min_atr = 0.70
    min_adv = 1_000_000
    top_k = 50
    
    logging.info(f"Filters: gap≥{min_gap_pct:.1%}, ATR≥${min_atr:.2f}, ADV≥{min_adv:,}, top-k={top_k}")
    
    df = df.with_columns([pl.col("gap_pct").abs().alias("abs_gap_pct")])
    
    filtered = df.filter(
        (pl.col("abs_gap_pct") >= min_gap_pct) &
        (pl.col("atr14") >= min_atr) &
        (pl.col("adv20") >= min_adv)
    )
    
    logging.info(f"After filters: {len(filtered):,} rows")
    
    filtered = filtered.with_columns([
        (pl.col("abs_gap_pct") * pl.col("atr14") * (pl.col("adv20") / 1_000_000)).alias("score")
    ])
    
    sip = (
        filtered
        .sort(["date", "score"], descending=[False, True])
        .group_by("date")
        .head(top_k)
    )
    
    logging.info(f"Selected {len(sip):,} symbol-date pairs")
    logging.info(f"Unique symbols: {sip['symbol'].n_unique()}")
    logging.info(f"Unique dates: {sip['date'].n_unique()}")
    
    output_dir = Path("run/sip_membership_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "sip_membership.parquet"
    sip.write_parquet(output_file)
    
    logging.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
