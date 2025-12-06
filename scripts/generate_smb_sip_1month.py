#!/usr/bin/env python3
"""Generate SMB-filtered SIP membership for 1 month (validation test)."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from extensions.intraday_ml.smb_scanner_monthly import smb_premarket_scan

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def get_trading_days(start: str, end: str) -> list[str]:
    """Generate list of trading days (Mon-Fri)."""
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    dates = []
    current = start_dt
    while current <= end_dt:
        if current.weekday() < 5:
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def main():
    # Test period: May 2024 (1 month)
    start_date = "2024-05-01"
    end_date = "2024-05-31"
    output_dir = Path("run/sip_membership_smb_1month")
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("=" * 80)
    LOGGER.info("SMB SIP Generation - 1 Month Validation")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Period: {start_date} to {end_date}")
    LOGGER.info(f"Output: {output_dir}")

    # Get trading days
    trading_days = get_trading_days(start_date, end_date)
    LOGGER.info(f"Trading days: {len(trading_days)}")

    # Scan each day
    all_results = []
    for i, date in enumerate(trading_days, 1):
        LOGGER.info(f"[{i}/{len(trading_days)}] Scanning {date}...")

        try:
            df = smb_premarket_scan(
                date=date,
                min_gap_pct=0.03,
                min_pm_rvol=0.10,
                min_atr=0.70,
                top_k=20,
            )

            if df is not None and len(df) > 0:
                df["date"] = date
                all_results.append(df)
                LOGGER.info(f"  Found {len(df)} stocks in play")
            else:
                LOGGER.warning(f"  No stocks found for {date}")

        except Exception as e:
            LOGGER.error(f"  Error scanning {date}: {e}")
            continue

    # Combine and save
    if all_results:
        combined = pd.concat(all_results, ignore_index=True)

        # Save as parquet (partitioned by date for efficiency)
        output_file = output_dir / "sip_membership.parquet"
        combined.to_parquet(output_file, index=False)

        LOGGER.info("=" * 80)
        LOGGER.info("Results Summary")
        LOGGER.info("=" * 80)
        LOGGER.info(f"Total rows: {len(combined)}")
        LOGGER.info(f"Unique symbols: {combined['symbol'].nunique()}")
        LOGGER.info(f"Date range: {combined['date'].min()} to {combined['date'].max()}")
        LOGGER.info(f"Avg stocks/day: {len(combined) / combined['date'].nunique():.1f}")
        LOGGER.info(f"Saved to: {output_file}")

        # Validation analysis
        LOGGER.info("")
        LOGGER.info("Daily Distribution:")
        daily_counts = combined.groupby("date").size()
        LOGGER.info(f"  Min: {daily_counts.min()} stocks/day")
        LOGGER.info(f"  Max: {daily_counts.max()} stocks/day")
        LOGGER.info(f"  Mean: {daily_counts.mean():.1f} stocks/day")
        LOGGER.info(f"  Median: {daily_counts.median():.1f} stocks/day")

        LOGGER.info("")
        LOGGER.info("Top 10 Most Frequent Symbols:")
        top_symbols = combined["symbol"].value_counts().head(10)
        for symbol, count in top_symbols.items():
            LOGGER.info(f"  {symbol}: {count} days ({count/len(trading_days)*100:.1f}%)")

        # Save summary
        summary_file = output_dir / "validation_summary.txt"
        with open(summary_file, "w") as f:
            f.write("SMB SIP 1-Month Validation Summary\n")
            f.write("=" * 80 + "\n\n")
            f.write(f"Period: {start_date} to {end_date}\n")
            f.write(f"Trading days: {len(trading_days)}\n")
            f.write(f"Total rows: {len(combined)}\n")
            f.write(f"Unique symbols: {combined['symbol'].nunique()}\n")
            f.write(f"Avg stocks/day: {len(combined) / combined['date'].nunique():.1f}\n\n")
            f.write("Daily Distribution:\n")
            f.write(f"  Min: {daily_counts.min()}\n")
            f.write(f"  Max: {daily_counts.max()}\n")
            f.write(f"  Mean: {daily_counts.mean():.1f}\n")
            f.write(f"  Median: {daily_counts.median():.1f}\n\n")
            f.write("Top 10 Symbols:\n")
            for symbol, count in top_symbols.items():
                f.write(f"  {symbol}: {count} days\n")

        LOGGER.info(f"Summary saved to: {summary_file}")

    else:
        LOGGER.error("No results generated!")


if __name__ == "__main__":
    main()
