#!/usr/bin/env python3
"""Build daily feature store for 2024-2025 (21 months)."""

import logging
from datetime import datetime
from pathlib import Path

import polars as pl
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/build_daily_features_2024_2025.log"),
        logging.StreamHandler()
    ]
)


def load_gold_universe():
    """Load gold universe symbols."""
    with open("configs/extensions/intraday_ml/universe_gold_full.yaml") as f:
        config = yaml.safe_load(f)
    return config.get("symbols", [])


def load_daily_bars(symbol, start_date, end_date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load and aggregate to daily bars."""
    symbol_path = Path(data_root) / symbol
    
    if not symbol_path.exists():
        return None
    
    # Load all 2024 and 2025 files
    files = []
    for year_dir in ["2024", "2025"]:
        year_path = symbol_path / year_dir
        if year_path.exists():
            files.extend(sorted(year_path.glob("*.parquet")))
    
    if not files:
        # Try flat structure
        files = sorted(symbol_path.glob("2024-*.parquet")) + sorted(symbol_path.glob("2025-*.parquet"))
    
    if not files:
        return None
    
    dfs = []
    for file_path in files:
        try:
            df = pl.read_parquet(file_path)
            if "ts" in df.columns:
                df = df.rename({"ts": "timestamp"})
            dfs.append(df)
        except Exception as e:
            logging.debug(f"Error reading {file_path}: {e}")
    
    if not dfs:
        return None
    
    df = pl.concat(dfs)
    df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))
    
    # Filter date range
    df = df.filter(
        (pl.col("timestamp").dt.date() >= start_date) &
        (pl.col("timestamp").dt.date() <= end_date)
    )
    
    if len(df) == 0:
        return None
    
    # Aggregate to daily
    daily = df.group_by(pl.col("timestamp").dt.date().alias("date")).agg([
        pl.col("open").first().alias("open"),
        pl.col("high").max().alias("high"),
        pl.col("low").min().alias("low"),
        pl.col("close").last().alias("close"),
        pl.col("volume").sum().alias("volume"),
    ])
    
    daily = daily.sort("date")
    
    # Calculate features
    daily = daily.with_columns([
        pl.col("close").shift(1).alias("prior_close"),
    ])
    
    daily = daily.with_columns([
        ((pl.col("open") - pl.col("prior_close")) / pl.col("prior_close")).alias("gap_pct"),
    ])
    
    # ATR (14-day)
    daily = daily.with_columns([
        (pl.col("high") - pl.col("low")).alias("tr"),
    ])
    daily = daily.with_columns([
        pl.col("tr").rolling_mean(14).alias("atr14"),
    ])
    
    # ADV (20-day)
    daily = daily.with_columns([
        pl.col("volume").rolling_mean(20).alias("adv20"),
    ])
    
    return daily


def main():
    logging.info("=" * 80)
    logging.info("BUILDING DAILY FEATURE STORE: 2024-2025")
    logging.info("=" * 80)
    
    # Load universe
    symbols = load_gold_universe()
    logging.info(f"Universe: {len(symbols)} symbols")
    
    # Date range
    start_date = datetime(2024, 1, 1).date()
    end_date = datetime(2025, 9, 30).date()
    logging.info(f"Date range: {start_date} to {end_date}")
    
    # Process in batches
    batch_size = 50
    all_features = []
    
    for i in range(0, len(symbols), batch_size):
        batch = symbols[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size
        
        logging.info(f"Processing batch {batch_num}/{total_batches} ({len(batch)} symbols)...")
        
        batch_data = []
        for symbol in batch:
            df = load_daily_bars(symbol, start_date, end_date)
            if df is not None and len(df) > 0:
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                batch_data.append(df)
        
        if batch_data:
            batch_df = pl.concat(batch_data)
            all_features.append(batch_df)
            logging.info(f"  Batch {batch_num}: {len(batch_data)}/{len(batch)} symbols had data")
        
        # Save intermediate
        if batch_num % 5 == 0 and all_features:
            combined = pl.concat(all_features)
            output_dir = Path("run/daily_features_2024_2025")
            output_dir.mkdir(parents=True, exist_ok=True)
            combined.write_parquet(output_dir / "features_temp.parquet")
            logging.info(f"  Saved intermediate: {len(combined):,} rows")
    
    # Final save
    if not all_features:
        logging.error("No features generated!")
        return
    
    combined = pl.concat(all_features)
    output_dir = Path("run/daily_features_2024_2025")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "features.parquet"
    combined.write_parquet(output_file)
    
    logging.info("")
    logging.info("=" * 80)
    logging.info("DAILY FEATURE STORE COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total rows: {len(combined):,}")
    logging.info(f"Unique symbols: {combined['symbol'].n_unique()}")
    logging.info(f"Unique dates: {combined['date'].n_unique()}")
    logging.info(f"Date range: {combined['date'].min()} to {combined['date'].max()}")
    logging.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
