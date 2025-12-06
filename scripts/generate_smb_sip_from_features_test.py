#!/usr/bin/env python3
"""Generate SMB SIP from test features (10 symbols)."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    features_file = Path("run/daily_features_test/features.parquet")
    output_dir = Path("run/sip_membership_smb_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    min_gap_pct = 0.01  # Lower for test
    min_pm_rvol = 0.01  # Lower for test
    min_atr = 0.50  # Lower for test
    min_adv = 10_000  # Lower for test
    top_k = 5

    LOGGER.info("SMB SIP Selection - TEST")
    LOGGER.info(f"Features: {features_file}")

    df = pd.read_parquet(features_file)
    LOGGER.info(f"Loaded {len(df):,} rows")

    filtered = df[
        (df["gap_pct"].abs() >= min_gap_pct)
        & (df["pm_rvol"] >= min_pm_rvol)
        & (df["atr14"] >= min_atr)
        & (df["adv20"] >= min_adv)
    ].copy()

    LOGGER.info(f"After filters: {len(filtered):,} rows")

    filtered["score"] = filtered["gap_pct"].abs() * filtered["pm_rvol"] * filtered["atr14"]

    sip = (
        filtered.sort_values(["date", "score"], ascending=[True, False])
        .groupby("date")
        .head(top_k)
    )

    LOGGER.info(f"Top-{top_k} per day: {len(sip):,} rows")

    output_file = output_dir / "sip_membership.parquet"
    sip.to_parquet(output_file, index=False)

    LOGGER.info(f"Saved to: {output_file}")
    LOGGER.info("")
    LOGGER.info("Sample SIP (first 20 rows):")
    print(sip[["date", "symbol", "gap_pct", "pm_rvol", "atr14", "score"]].head(20).to_string())


if __name__ == "__main__":
    main()
