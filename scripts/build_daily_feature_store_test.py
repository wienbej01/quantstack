#!/usr/bin/env python3
"""Build daily feature store - TEST VERSION (10 symbols only)."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def compute_daily_features_for_symbol(
    symbol: str, gold_path: str, start_date: str, end_date: str
) -> pd.DataFrame:
    """Compute daily features for one symbol across date range."""
    symbol_path = Path(gold_path) / symbol
    if not symbol_path.exists():
        LOGGER.warning(f"{symbol}: Path does not exist")
        return pd.DataFrame()

    start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    files = []
    for year_dir in symbol_path.iterdir():
        if not year_dir.is_dir():
            continue
        for month_file in year_dir.glob("*.parquet"):
            files.append(month_file)

    if not files:
        LOGGER.warning(f"{symbol}: No parquet files found")
        return pd.DataFrame()

    try:
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
    except Exception as e:
        LOGGER.warning(f"{symbol}: Failed to load - {e}")
        return pd.DataFrame()

    if len(df) == 0 or "ts" not in df.columns:
        return pd.DataFrame()

    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    df = df[(df["date"] >= start_dt.date()) & (df["date"] <= end_dt.date())]

    if len(df) == 0:
        return pd.DataFrame()

    daily = df.groupby("date").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    daily = daily.sort_index()
    daily["prior_close"] = daily["close"].shift(1)
    daily["gap_pct"] = (daily["open"] - daily["prior_close"]) / daily["prior_close"]
    daily["adv20"] = daily["volume"].rolling(window=20, min_periods=1).mean()

    daily["hl"] = daily["high"] - daily["low"]
    daily["hc"] = (daily["high"] - daily["prior_close"]).abs()
    daily["lc"] = (daily["low"] - daily["prior_close"]).abs()
    daily["true_range"] = daily[["hl", "hc", "lc"]].max(axis=1)
    daily["atr14"] = daily["true_range"].rolling(window=14, min_periods=1).mean()

    pm_df = df[df["ts"].dt.hour < 9].copy()
    pm_volume = pm_df.groupby("date")["volume"].sum()
    daily["pm_volume"] = pm_volume
    daily["pm_volume"] = daily["pm_volume"].fillna(0)
    daily["pm_rvol"] = daily["pm_volume"] / daily["adv20"]

    daily["symbol"] = symbol
    daily = daily.reset_index()

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

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    daily = daily[(daily["date"] >= start_date_obj) & (daily["date"] <= end_date_obj)]

    return daily


def main():
    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    start_date = "2024-05-01"
    end_date = "2024-05-31"
    output_dir = Path("run/daily_features_test")
    output_dir.mkdir(parents=True, exist_ok=True)

    # TEST: Only 10 symbols
    test_symbols = ["AAPL", "TSLA", "NVDA", "AMD", "MSFT", "GOOGL", "AMZN", "META", "NFLX", "SPY"]

    LOGGER.info("=" * 80)
    LOGGER.info("Building Daily Feature Store - TEST (10 symbols)")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Period: {start_date} to {end_date}")
    LOGGER.info(f"Symbols: {test_symbols}")

    all_features = []
    for i, symbol in enumerate(test_symbols, 1):
        LOGGER.info(f"[{i}/{len(test_symbols)}] Processing {symbol}...")
        features = compute_daily_features_for_symbol(symbol, gold_path, start_date, end_date)

        if len(features) > 0:
            LOGGER.info(f"  {symbol}: {len(features)} rows")
            all_features.append(features)
        else:
            LOGGER.warning(f"  {symbol}: No data")

    if all_features:
        combined = pd.concat(all_features, ignore_index=True)
        output_file = output_dir / "features.parquet"
        combined.to_parquet(output_file, index=False)

        LOGGER.info("=" * 80)
        LOGGER.info("Feature Store Built")
        LOGGER.info("=" * 80)
        LOGGER.info(f"Total rows: {len(combined):,}")
        LOGGER.info(f"Unique symbols: {combined['symbol'].nunique()}")
        LOGGER.info(f"Unique dates: {combined['date'].nunique()}")
        LOGGER.info(f"Saved to: {output_file}")
        LOGGER.info("")
        LOGGER.info("Sample:")
        print(combined.head(10).to_string())
    else:
        LOGGER.error("No features generated!")


if __name__ == "__main__":
    main()
