#!/usr/bin/env python3
"""Build daily feature store from 1m bars for fast SIP selection."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def load_gold_universe(gold_path: str) -> list[str]:
    """Load all symbols from gold data."""
    base = Path(gold_path)
    return sorted([d.name for d in base.iterdir() if d.is_dir()])


def compute_daily_features_for_symbol(
    symbol: str, gold_path: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """Compute daily features for one symbol across date range."""
    symbol_path = Path(gold_path) / symbol
    if not symbol_path.exists():
        return pd.DataFrame()

    # Load all monthly files in range (plus 1 month prior for rolling calcs)
    start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    files = []
    for year_dir in symbol_path.iterdir():
        if not year_dir.is_dir():
            continue
        for month_file in year_dir.glob("*.parquet"):
            files.append(month_file)

    if not files:
        return pd.DataFrame()

    # Load all data at once
    try:
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
    except Exception:
        return pd.DataFrame()

    if len(df) == 0:
        return pd.DataFrame()

    # Ensure timestamp column
    if "ts" not in df.columns:
        return pd.DataFrame()

    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date

    # Filter to date range
    df = df[(df["date"] >= start_dt.date()) & (df["date"] <= end_dt.date())]

    if len(df) == 0:
        return pd.DataFrame()

    # Compute daily OHLCV
    daily = df.groupby("date").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    daily = daily.sort_index()

    # Prior close for gap calculation
    daily["prior_close"] = daily["close"].shift(1)

    # Gap %
    daily["gap_pct"] = (daily["open"] - daily["prior_close"]) / daily["prior_close"]

    # 20-day ADV
    daily["adv20"] = daily["volume"].rolling(window=20, min_periods=1).mean()

    # 14-day ATR
    daily["hl"] = daily["high"] - daily["low"]
    daily["hc"] = (daily["high"] - daily["prior_close"]).abs()
    daily["lc"] = (daily["low"] - daily["prior_close"]).abs()
    daily["true_range"] = daily[["hl", "hc", "lc"]].max(axis=1)
    daily["atr14"] = daily["true_range"].rolling(window=14, min_periods=1).mean()

    # Premarket volume (before 9:30)
    pm_df = df[df["ts"].dt.hour < 9].copy()
    pm_volume = pm_df.groupby("date")["volume"].sum()
    daily["pm_volume"] = pm_volume
    daily["pm_volume"] = daily["pm_volume"].fillna(0)

    # PM RVOL = pm_volume / adv20
    daily["pm_rvol"] = daily["pm_volume"] / daily["adv20"]

    # Add symbol
    daily["symbol"] = symbol

    # Reset index to make date a column
    daily = daily.reset_index()

    # Select final columns
    daily = daily[
        [
            "date",
            "symbol",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "prior_close",
            "gap_pct",
            "pm_volume",
            "pm_rvol",
            "adv20",
            "atr14",
        ]
    ]

    # Filter to actual date range (remove seed period)
    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    daily = daily[(daily["date"] >= start_date_obj) & (daily["date"] <= end_date_obj)]

    return daily


def main():
    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    start_date = "2024-05-01"
    end_date = "2024-05-31"
    output_dir = Path("run/daily_features")
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("=" * 80)
    LOGGER.info("Building Daily Feature Store")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Period: {start_date} to {end_date}")
    LOGGER.info(f"Gold path: {gold_path}")
    LOGGER.info(f"Output: {output_dir}")

    # Load universe
    symbols = load_gold_universe(gold_path)
    LOGGER.info(f"Universe: {len(symbols)} symbols")

    # Process each symbol
    all_features = []
    for i, symbol in enumerate(symbols, 1):
        if i % 50 == 0:
            LOGGER.info(f"Progress: {i}/{len(symbols)} symbols processed")

        features = compute_daily_features_for_symbol(symbol, gold_path, start_date, end_date)

        if len(features) > 0:
            all_features.append(features)

    # Combine and save
    if all_features:
        combined = pd.concat(all_features, ignore_index=True)

        # Save
        output_file = output_dir / "features.parquet"
        combined.to_parquet(output_file, index=False)

        LOGGER.info("=" * 80)
        LOGGER.info("Feature Store Built")
        LOGGER.info("=" * 80)
        LOGGER.info(f"Total rows: {len(combined):,}")
        LOGGER.info(f"Unique symbols: {combined['symbol'].nunique()}")
        LOGGER.info(f"Unique dates: {combined['date'].nunique()}")
        LOGGER.info(f"Date range: {combined['date'].min()} to {combined['date'].max()}")
        LOGGER.info(f"Saved to: {output_file}")

        # Sample
        LOGGER.info("")
        LOGGER.info("Sample (first 5 rows):")
        print(combined.head(5).to_string())

    else:
        LOGGER.error("No features generated!")


if __name__ == "__main__":
    main()
