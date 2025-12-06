#!/usr/bin/env python3
"""Build daily feature store for 6 months with checkpointing."""

import logging
import time
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path
from threading import Thread

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def heartbeat_monitor(interval=60):
    """Log heartbeat every N seconds."""
    while True:
        time.sleep(interval)
        LOGGER.info(f"[HEARTBEAT] Process alive, time: {datetime.now().strftime('%H:%M:%S')}")


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
    start_date = "2024-01-01"  # 6 months: Jan-Jun
    end_date = "2024-06-30"
    output_dir = Path("run/daily_features_6months")
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)

    LOGGER.info("=" * 80)
    LOGGER.info("Building Daily Feature Store - 6 MONTHS")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Period: {start_date} to {end_date}")
    LOGGER.info(f"Output: {output_dir}")

    # Start heartbeat
    heartbeat = Thread(target=heartbeat_monitor, args=(60,), daemon=True)
    heartbeat.start()

    # Load universe
    base = Path(gold_path)
    symbols = sorted([d.name for d in base.iterdir() if d.is_dir()])
    LOGGER.info(f"Universe: {len(symbols)} symbols")

    # Check for existing checkpoint
    checkpoint_file = checkpoint_dir / "progress.txt"
    processed_symbols = set()
    if checkpoint_file.exists():
        with open(checkpoint_file) as f:
            processed_symbols = set(line.strip() for line in f)
        LOGGER.info(f"Resuming: {len(processed_symbols)} symbols already processed")

    remaining_symbols = [s for s in symbols if s not in processed_symbols]
    LOGGER.info(f"Processing: {len(remaining_symbols)} symbols")

    # Prepare args
    args_list = [(s, gold_path, start_date, end_date) for s in remaining_symbols]

    # Parallel processing
    n_workers = min(cpu_count(), 16)
    LOGGER.info(f"Using {n_workers} workers")

    all_features = []
    checkpoint_interval = 50
    
    with Pool(n_workers) as pool:
        for i, result in enumerate(pool.imap_unordered(compute_daily_features_for_symbol, args_list), 1):
            if result is not None:
                all_features.append(result)
            
            if i % 100 == 0:
                LOGGER.info(f"Progress: {i}/{len(remaining_symbols)} symbols processed")
            
            if i % checkpoint_interval == 0:
                LOGGER.info(f"[CHECKPOINT] Saving intermediate results...")
                if all_features:
                    checkpoint_data = pd.concat(all_features, ignore_index=True)
                    checkpoint_data.to_parquet(
                        checkpoint_dir / f"features_batch_{i}.parquet", 
                        index=False
                    )
                
                with open(checkpoint_file, "a") as f:
                    for j in range(max(0, i - checkpoint_interval), i):
                        if j < len(remaining_symbols):
                            f.write(f"{remaining_symbols[j]}\n")

    # Final save
    LOGGER.info("Combining all results...")
    
    checkpoint_files = list(checkpoint_dir.glob("features_batch_*.parquet"))
    if checkpoint_files:
        LOGGER.info(f"Loading {len(checkpoint_files)} checkpoint files...")
        checkpoint_dfs = [pd.read_parquet(f) for f in checkpoint_files]
        all_features.extend(checkpoint_dfs)
    
    if all_features:
        combined = pd.concat(all_features, ignore_index=True)
        output_file = output_dir / "features.parquet"
        combined.to_parquet(output_file, index=False)

        LOGGER.info("=" * 80)
        LOGGER.info("Feature Store Built - 6 MONTHS")
        LOGGER.info("=" * 80)
        LOGGER.info(f"Total rows: {len(combined):,}")
        LOGGER.info(f"Unique symbols: {combined['symbol'].nunique()}")
        LOGGER.info(f"Unique dates: {combined['date'].nunique()}")
        LOGGER.info(f"Saved to: {output_file}")
        
        # Clean up checkpoints
        for f in checkpoint_files:
            f.unlink()
        checkpoint_file.unlink()
    else:
        LOGGER.error("No features generated!")


if __name__ == "__main__":
    main()
