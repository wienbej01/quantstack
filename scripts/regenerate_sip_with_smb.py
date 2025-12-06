#!/usr/bin/env python3
"""Regenerate SIP membership using SMB Capital catalyst-driven filters."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

from extensions.intraday_ml.smb_scanner_monthly import (
    save_daily_sip,
    smb_premarket_scan,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
LOGGER = logging.getLogger(__name__)


def get_trading_dates(start_date: str, end_date: str) -> list[str]:
    """Generate list of trading dates (Mon-Fri) between start and end."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")

    dates = []
    current = start
    while current <= end:
        if current.weekday() < 5:  # Mon-Fri
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return dates


def main():
    # Configuration
    start_date = "2023-10-02"  # Match existing SIP data
    end_date = "2024-05-31"
    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    output_path = "/home/jacobw/quantstack/run/sip_membership_smb"

    # SMB filter parameters
    min_gap_pct = 0.03  # 3% gap
    min_pm_rvol = 0.10  # 10% of ADV in premarket
    min_atr = 0.70  # $0.70 ATR
    min_adv = 1_000_000  # 1M ADV
    top_k = 20  # Top 20 stocks/day

    LOGGER.info("=" * 80)
    LOGGER.info("SMB-Style SIP Regeneration")
    LOGGER.info("=" * 80)
    LOGGER.info("Date range: %s to %s", start_date, end_date)
    LOGGER.info("Output: %s", output_path)
    LOGGER.info("")
    LOGGER.info("SMB Filters:")
    LOGGER.info("  - Gap: ≥%.1f%%", min_gap_pct * 100)
    LOGGER.info("  - Premarket RVOL: ≥%.0f%% of ADV", min_pm_rvol * 100)
    LOGGER.info("  - ATR: ≥$%.2f", min_atr)
    LOGGER.info("  - ADV: ≥%s shares", f"{min_adv:,}")
    LOGGER.info("  - Top K: %d stocks/day", top_k)
    LOGGER.info("=" * 80)

    # Get trading dates
    trading_dates = get_trading_dates(start_date, end_date)
    LOGGER.info("Processing %d trading dates...", len(trading_dates))

    # Process each date
    results = []
    for i, date in enumerate(trading_dates, 1):
        LOGGER.info("")
        LOGGER.info("[%d/%d] Processing %s", i, len(trading_dates), date)
        LOGGER.info("-" * 80)

        try:
            # Run SMB scan
            df = smb_premarket_scan(
                date=date,
                gold_path=gold_path,
                min_gap_pct=min_gap_pct,
                min_pm_rvol=min_pm_rvol,
                min_atr=min_atr,
                min_adv=min_adv,
                top_k=top_k,
            )

            if len(df) > 0:
                # Save daily SIP
                save_daily_sip(df, date, output_path)

                results.append(
                    {
                        "date": date,
                        "stocks_in_play": len(df),
                        "avg_gap": df["gap_pct"].abs().mean(),
                        "avg_pm_rvol": df["pm_rvol"].mean(),
                        "avg_atr": df["atr"].mean(),
                        "top_symbol": df.iloc[0]["symbol"],
                        "top_score": df.iloc[0]["score"],
                    }
                )
            else:
                LOGGER.warning("No stocks in play found for %s", date)
                results.append(
                    {
                        "date": date,
                        "stocks_in_play": 0,
                        "avg_gap": 0,
                        "avg_pm_rvol": 0,
                        "avg_atr": 0,
                        "top_symbol": None,
                        "top_score": 0,
                    }
                )

        except Exception as e:
            LOGGER.error("Error processing %s: %s", date, e)
            results.append(
                {
                    "date": date,
                    "stocks_in_play": 0,
                    "avg_gap": 0,
                    "avg_pm_rvol": 0,
                    "avg_atr": 0,
                    "top_symbol": None,
                    "top_score": 0,
                }
            )

    # Summary statistics
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("SMB SIP Regeneration Complete!")
    LOGGER.info("=" * 80)

    results_df = pd.DataFrame(results)

    total_days = len(results_df)
    days_with_stocks = (results_df["stocks_in_play"] > 0).sum()
    total_stocks = results_df["stocks_in_play"].sum()
    avg_stocks_per_day = results_df["stocks_in_play"].mean()
    unique_symbols = results_df[results_df["top_symbol"].notna()][
        "top_symbol"
    ].nunique()

    LOGGER.info("Total trading days: %d", total_days)
    LOGGER.info(
        "Days with stocks in play: %d (%.1f%%)",
        days_with_stocks,
        100 * days_with_stocks / total_days,
    )
    LOGGER.info("Total stock-days: %d", total_stocks)
    LOGGER.info("Avg stocks/day: %.1f", avg_stocks_per_day)
    LOGGER.info("Unique symbols: %d", unique_symbols)
    LOGGER.info("")
    LOGGER.info("Average metrics:")
    LOGGER.info("  - Gap: %.2f%%", results_df["avg_gap"].mean() * 100)
    LOGGER.info("  - PM RVOL: %.2f", results_df["avg_pm_rvol"].mean())
    LOGGER.info("  - ATR: $%.2f", results_df["avg_atr"].mean())
    LOGGER.info("")
    LOGGER.info("Output saved to: %s", output_path)
    LOGGER.info("=" * 80)

    # Save summary
    summary_path = Path(output_path) / "summary.parquet"
    results_df.to_parquet(summary_path, index=False)
    LOGGER.info("Summary saved to: %s", summary_path)


if __name__ == "__main__":
    main()
