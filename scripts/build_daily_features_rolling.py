#!/usr/bin/env python3
"""Build daily feature store for rolling training: 2024-11 to 2025-12."""

import logging
from datetime import datetime
from pathlib import Path

import polars as pl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/build_daily_features_rolling.log"),
        logging.StreamHandler(),
    ],
)

# Check if GCS mount is available, otherwise use gcsfs
MOUNT_PATH = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
USE_MOUNT = MOUNT_PATH.exists()

if not USE_MOUNT:
    import gcsfs

    fs = gcsfs.GCSFileSystem()
    GCS_BUCKET = "jwss_data_store"
    GCS_PATH = f"{GCS_BUCKET}/gold/stocks/1m"
    logging.info("Using gcsfs (mount not available)")
else:
    logging.info("Using GCS mount")


def load_gold_universe():
    """Load all symbols from GCS."""
    if USE_MOUNT:
        symbols = [d.name for d in MOUNT_PATH.iterdir() if d.is_dir()]
        return sorted(symbols)
    else:
        symbols = []
        for path in fs.ls(GCS_PATH):
            symbol = path.split("/")[-1]
            if symbol and symbol != "1m":
                symbols.append(symbol)
        return sorted(symbols)


def load_daily_bars(symbol, start_date, end_date):
    """Load and aggregate to daily bars."""
    if USE_MOUNT:
        return load_daily_bars_mount(symbol, start_date, end_date)
    else:
        return load_daily_bars_gcs(symbol, start_date, end_date)


KEEP_COLS = [
    "date",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "prior_close",
    "gap_pct",
    "atr14",
    "adv20",
]

SCHEMA_CASTS = {
    "date": pl.Date,
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Float64,
    "prior_close": pl.Float64,
    "gap_pct": pl.Float64,
    "tr": pl.Float64,
    "atr14": pl.Float64,
    "adv20": pl.Float64,
}


def _read_parquet_minimal(source) -> pl.DataFrame:
    """Read only the columns needed for daily aggregation."""
    columns = ["ts", "timestamp", "open", "high", "low", "close", "volume"]
    try:
        return pl.read_parquet(source, columns=columns)
    except Exception:
        df = pl.read_parquet(source)
        keep = [col for col in columns if col in df.columns]
        return df.select(keep)


def _normalize_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Align schema across parquet shards to avoid concat mismatches."""
    casts = {}
    if "timestamp" in df.columns:
        casts["timestamp"] = pl.Datetime("ns")
    for col in ("open", "high", "low", "close"):
        if col in df.columns:
            casts[col] = pl.Float64
    if "volume" in df.columns:
        casts["volume"] = pl.Int64
    if not casts:
        return df
    return df.with_columns([pl.col(name).cast(dtype) for name, dtype in casts.items()])


def load_daily_bars_mount(symbol, start_date, end_date):
    """Load from mount."""
    symbol_path = MOUNT_PATH / symbol
    if not symbol_path.exists():
        return None

    files = []
    for year in ["2023", "2024", "2025"]:
        year_path = symbol_path / year
        if year_path.exists():
            files.extend(sorted(year_path.glob("*.parquet")))

    if not files:
        return None

    dfs = []
    for file_path in files:
        try:
            df = _read_parquet_minimal(file_path)
            if "ts" in df.columns:
                df = df.rename({"ts": "timestamp"})
            df = _normalize_schema(df)
            dfs.append(df)
        except Exception as e:
            logging.debug(f"Error reading {file_path}: {e}")

    if not dfs:
        return None

    return aggregate_to_daily(pl.concat(dfs), start_date, end_date)


def load_daily_bars_gcs(symbol, start_date, end_date):
    """Load from GCS via gcsfs."""
    files = []
    for year in ["2023", "2024", "2025"]:
        year_path = f"{GCS_PATH}/{symbol}/{year}"
        try:
            year_files = fs.glob(f"{year_path}/*.parquet")
            files.extend(sorted(year_files))
        except FileNotFoundError:
            continue

    if not files:
        return None

    dfs = []
    for file_path in files:
        try:
            with fs.open(file_path, "rb") as f:
                df = _read_parquet_minimal(f)
            if "ts" in df.columns:
                df = df.rename({"ts": "timestamp"})
            df = _normalize_schema(df)
            dfs.append(df)
        except Exception as e:
            logging.debug(f"Error reading {file_path}: {e}")

    if not dfs:
        return None

    return aggregate_to_daily(pl.concat(dfs), start_date, end_date)


def aggregate_to_daily(df, start_date, end_date):
    """Aggregate intraday bars to daily and calculate features."""
    df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))

    # Filter date range
    df = df.filter(
        (pl.col("timestamp").dt.date() >= start_date)
        & (pl.col("timestamp").dt.date() <= end_date)
    )

    if len(df) == 0:
        return None

    # Aggregate to daily
    daily = df.group_by(pl.col("timestamp").dt.date().alias("date")).agg(
        [
            pl.col("open").first().alias("open"),
            pl.col("high").max().alias("high"),
            pl.col("low").min().alias("low"),
            pl.col("close").last().alias("close"),
            pl.col("volume").sum().alias("volume"),
        ]
    )

    daily = daily.sort("date")

    # Calculate features
    daily = daily.with_columns(
        [
            pl.col("close").shift(1).alias("prior_close"),
        ]
    )

    daily = daily.with_columns(
        [
            ((pl.col("open") - pl.col("prior_close")) / pl.col("prior_close")).alias(
                "gap_pct"
            ),
        ]
    )

    # ATR (14-day)
    daily = daily.with_columns(
        [
            (pl.col("high") - pl.col("low")).alias("tr"),
        ]
    )
    daily = daily.with_columns(
        [
            pl.col("tr").rolling_mean(14).alias("atr14"),
        ]
    )

    # ADV (20-day)
    daily = daily.with_columns(
        [
            pl.col("volume").rolling_mean(20).alias("adv20"),
        ]
    )
    # Enforce consistent schema across all batches
    for col, dtype in SCHEMA_CASTS.items():
        if col not in daily.columns:
            daily = daily.with_columns(pl.lit(None).cast(dtype).alias(col))
        else:
            daily = daily.with_columns(pl.col(col).cast(dtype))

    daily = daily.select(KEEP_COLS)

    return daily


def main():
    logging.info("=" * 80)
    logging.info("BUILDING DAILY FEATURE STORE: 2024-11 to 2025-12")
    logging.info("=" * 80)

    # Load universe
    symbols = load_gold_universe()
    logging.info(f"Universe: {len(symbols)} symbols")

    # Date range: 2024-11-01 to 2025-12-15 (train/val/oos window)
    start_date = datetime(2024, 11, 1).date()
    end_date = datetime(2025, 12, 15).date()
    logging.info(f"Date range: {start_date} to {end_date}")

    # Check for checkpoint
    output_dir = Path("run/daily_features_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_file = output_dir / "features_temp.parquet"

    all_features = []
    processed_symbols = set()
    start_batch = 0

    if checkpoint_file.exists():
        logging.info(f"Found checkpoint: {checkpoint_file}")
        checkpoint_df = pl.read_parquet(checkpoint_file)
        # Align checkpoint schema to KEEP_COLS
        for col in KEEP_COLS:
            if col not in checkpoint_df.columns:
                checkpoint_df = checkpoint_df.with_columns(
                    pl.lit(None).cast(SCHEMA_CASTS[col]).alias(col)
                )
            else:
                checkpoint_df = checkpoint_df.with_columns(
                    pl.col(col).cast(SCHEMA_CASTS[col])
                )
        checkpoint_df = checkpoint_df.select(KEEP_COLS)
        all_features.append(checkpoint_df)
        processed_symbols = set(checkpoint_df["symbol"].unique().to_list())
        start_batch = len(processed_symbols) // 50
        logging.info(
            f"Resuming from batch {start_batch + 1}, {len(processed_symbols)} symbols already processed"
        )

    # Process in batches
    batch_size = 50

    for i in range(0, len(symbols), batch_size):
        batch = symbols[i : i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(symbols) + batch_size - 1) // batch_size

        # Skip already processed batches
        if batch_num <= start_batch:
            continue

        logging.info(
            f"Processing batch {batch_num}/{total_batches} ({len(batch)} symbols)..."
        )

        batch_data = []
        for symbol in batch:
            if symbol in processed_symbols:
                continue
            df = load_daily_bars(symbol, start_date, end_date)
            if df is not None and len(df) > 0:
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                batch_data.append(df)

        if batch_data:
            batch_df = pl.concat(batch_data)
            # Enforce schema and column order
            for col in KEEP_COLS:
                if col not in batch_df.columns:
                    batch_df = batch_df.with_columns(
                        pl.lit(None).cast(SCHEMA_CASTS[col]).alias(col)
                    )
                else:
                    batch_df = batch_df.with_columns(
                        pl.col(col).cast(SCHEMA_CASTS[col])
                    )
            batch_df = batch_df.select(KEEP_COLS)
            all_features.append(batch_df)
            logging.info(
                f"  Batch {batch_num}: {len(batch_data)}/{len(batch)} symbols had data"
            )

        # Save intermediate
        if batch_num % 5 == 0 and all_features:
            combined = pl.concat(all_features)
            output_dir = Path("run/daily_features_rolling")
            output_dir.mkdir(parents=True, exist_ok=True)
            combined.write_parquet(output_dir / "features_temp.parquet")
            logging.info(f"  Saved intermediate: {len(combined):,} rows")

    # Final save
    if not all_features:
        logging.error("No features generated!")
        return

    # Final alignment before concat to guarantee identical width/order
    aligned = []
    for df in all_features:
        tmp = df
        for col in KEEP_COLS:
            if col not in tmp.columns:
                tmp = tmp.with_columns(pl.lit(None).cast(SCHEMA_CASTS[col]).alias(col))
            else:
                tmp = tmp.with_columns(pl.col(col).cast(SCHEMA_CASTS[col]))
        tmp = tmp.select(KEEP_COLS)
        aligned.append(tmp)

    combined = pl.concat(aligned)
    output_dir = Path("run/daily_features_rolling")
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
