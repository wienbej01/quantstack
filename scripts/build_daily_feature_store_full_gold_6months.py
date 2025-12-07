#!/usr/bin/env python3
"""Build daily feature store for FULL GOLD UNIVERSE (600 symbols) for 6 months."""

import logging
import time
from datetime import datetime, timedelta
from multiprocessing import Pool, cpu_count
from pathlib import Path
from threading import Thread

import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def heartbeat_monitor(interval=60):
    """Log heartbeat every N seconds."""
    while True:
        time.sleep(interval)
        LOGGER.info(
            f"[HEARTBEAT] Process alive, time: {datetime.now().strftime('%H:%M:%S')}"
        )


def compute_daily_features_for_symbol(args):
    """Compute daily features for one symbol."""
    symbol, gold_path, start_date, end_date = args

    try:
        symbol_path = Path(gold_path) / symbol
        if not symbol_path.exists():
            return None

        start_dt = datetime.strptime(start_date, "%Y-%m-%d") - timedelta(days=30)
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        files = []

        # Handle both file structures:
        # 1. symbol/YYYY/YYYY-MM.parquet (standard structure)
        # 2. symbol/YYYY-MM.parquet (flat structure)
        # 3. symbol/*.parquet (direct files)

        for item in symbol_path.iterdir():
            if item.is_dir():
                # Year directory - look for month files inside
                for month_file in item.glob("*.parquet"):
                    files.append(month_file)
            elif item.suffix == ".parquet":
                # Direct parquet file
                files.append(item)

        if not files:
            return None

        dfs = [pd.read_parquet(f) for f in files]
        df = pd.concat(dfs, ignore_index=True)

        if len(df) == 0:
            return None

        # Handle both 'ts' and 'timestamp' column names
        if "timestamp" in df.columns:
            df["ts"] = pd.to_datetime(df["timestamp"])
        elif "ts" in df.columns:
            df["ts"] = pd.to_datetime(df["ts"])
        else:
            return None

        df["date"] = df["ts"].dt.date
        df = df[(df["date"] >= start_dt.date()) & (df["date"] <= end_dt.date())]

        if len(df) == 0:
            return None

        daily = df.groupby("date").agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
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
                "adv20",
                "atr14",
            ]
        ]

        start_date_obj = datetime.strptime(start_date, "%Y-%m-%d").date()
        end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date()
        daily = daily[
            (daily["date"] >= start_date_obj) & (daily["date"] <= end_date_obj)
        ]

        return daily if len(daily) > 0 else None

    except Exception:
        return None


def main():
    # Load full gold universe
    with open("configs/extensions/intraday_ml/universe_gold_full.yaml") as f:
        config = yaml.safe_load(f)
    symbols = [
        s for s in config["symbols"] if isinstance(s, str)
    ]  # Filter out non-strings

    gold_path = "/home/jacobw/gcs-mount/gold/stocks/1m"
    start_date = "2024-01-02"
    end_date = "2024-06-28"
    output_dir = Path("run/daily_features_full_gold_6months")
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"
    checkpoint_dir.mkdir(exist_ok=True)

    LOGGER.info("=" * 80)
    LOGGER.info("Building Daily Feature Store - FULL GOLD UNIVERSE (6 MONTHS)")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Gold path: {gold_path}")
    LOGGER.info(f"Date range: {start_date} to {end_date}")
    LOGGER.info(f"Symbols: {len(symbols)}")
    LOGGER.info(f"Output: {output_dir}")
    LOGGER.info(f"Workers: {cpu_count()}")
    LOGGER.info("")

    # Start heartbeat
    heartbeat_thread = Thread(target=heartbeat_monitor, args=(60,), daemon=True)
    heartbeat_thread.start()

    # Check for existing checkpoint
    checkpoint_file = checkpoint_dir / "progress.txt"
    processed_symbols = set()
    if checkpoint_file.exists():
        with open(checkpoint_file) as f:
            processed_symbols = set(line.strip() for line in f)
        LOGGER.info(
            f"Resuming from checkpoint: {len(processed_symbols)} symbols already processed"
        )

    # Filter to unprocessed symbols
    symbols_to_process = [s for s in symbols if s not in processed_symbols]
    LOGGER.info(f"Symbols to process: {len(symbols_to_process)}")

    # Prepare args
    args = [(symbol, gold_path, start_date, end_date) for symbol in symbols_to_process]

    # Process in batches with checkpointing
    batch_size = 50
    all_results = []

    for i in range(0, len(args), batch_size):
        batch = args[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(args) + batch_size - 1) // batch_size

        LOGGER.info(
            f"Processing batch {batch_num}/{total_batches} ({len(batch)} symbols)..."
        )

        with Pool(cpu_count()) as pool:
            results = pool.map(compute_daily_features_for_symbol, batch)

        # Filter out None results
        valid_results = [r for r in results if r is not None]
        all_results.extend(valid_results)

        LOGGER.info(
            f"  Batch {batch_num}: {len(valid_results)}/{len(batch)} symbols had data"
        )

        # Save checkpoint
        batch_symbols = [arg[0] for arg in batch]
        with open(checkpoint_file, "a") as f:
            for symbol in batch_symbols:
                f.write(f"{symbol}\n")

        # Save intermediate results
        if all_results:
            intermediate_df = pd.concat(all_results, ignore_index=True)
            intermediate_file = checkpoint_dir / f"batch_{batch_num}.parquet"
            intermediate_df.to_parquet(intermediate_file, index=False)
            LOGGER.info(f"  Saved intermediate results: {len(intermediate_df):,} rows")

    # Combine all results
    if not all_results:
        LOGGER.error("No data collected!")
        return

    final_df = pd.concat(all_results, ignore_index=True)
    final_df = final_df.sort_values(["date", "symbol"])

    # Save final output
    output_file = output_dir / "features.parquet"
    final_df.to_parquet(output_file, index=False)

    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Feature Store Build Complete")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Total rows: {len(final_df):,}")
    LOGGER.info(f"Unique symbols: {final_df['symbol'].nunique()}")
    LOGGER.info(f"Unique dates: {final_df['date'].nunique()}")
    LOGGER.info(f"Date range: {final_df['date'].min()} to {final_df['date'].max()}")
    LOGGER.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
