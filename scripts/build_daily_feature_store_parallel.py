#!/usr/bin/env python3
"""Build daily feature store with parallel processing."""

import logging
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def compute_daily_features_for_symbol(args):
    """Compute daily features for one symbol."""
    symbol, gold_path, start_date, end_date = args
    
    symbol_path = Path(gold_path) / symbol
    if not symbol_path.exists():
        return None

    start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")

    files = []
    for year_dir in symbol_path.iterdir():
        if not year_dir.is_dir():
            continue
        for month_file in year_dir.glob("*.parquet"):
            files.append(month_file)

    if not files:
        return None

    try:
        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)
    except Exception:
        return None

    if len(df) == 0 or "ts" not in df.columns:
        return None

    df["ts"] = pd.to_datetime(df["ts"])
    df["date"] = df["ts"].dt.date
    df = df[(df["date"] >= start_dt.date()) & (df["date"] <= end_dt.date())]

    if len(df) == 0:
        return None

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

    daily["symbol"] = symbol
    daily = daily.reset_index()

    daily = daily[
        ["date", "symbol", "open", "high", "low", "close", "volume", 
         "prior_close", "gap_pct", "adv20", "atr14"]
    ]

    start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
    daily = daily[(daily["date"] >= start_date_obj) & (daily["date"] <= end_date_obj)]

    return daily if len(daily) > 0 else None


def main():
    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    start_date = "2024-05-01"
    end_date = "2024-05-31"
    output_dir = Path("run/daily_features")
    output_dir.mkdir(parents=True, exist_ok=True)

    LOGGER.info("=" * 80)
    LOGGER.info("Building Daily Feature Store - PARALLEL")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Period: {start_date} to {end_date}")

    # Load universe
    base = Path(gold_path)
    symbols = sorted([d.name for d in base.iterdir() if d.is_dir()])
    LOGGER.info(f"Universe: {len(symbols)} symbols")

    # Prepare args
    args_list = [(s, gold_path, start_date, end_date) for s in symbols]

    # Parallel processing
    n_workers = min(cpu_count(), 16)
    LOGGER.info(f"Using {n_workers} workers")

    all_features = []
    with Pool(n_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(compute_daily_features_for_symbol, args_list), 1):
            if i % 100 == 0:
                LOGGER.info(f"Progress: {i}/{len(symbols)} symbols processed")
            if result is not None:
                all_features.append(result)

    # Combine and save
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
    else:
        LOGGER.error("No features generated!")


if __name__ == "__main__":
    main()
