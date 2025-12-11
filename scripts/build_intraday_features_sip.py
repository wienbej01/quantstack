#!/usr/bin/env python3
"""Build intraday feature store for SIP-selected symbols using gold data for history."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import polars as pl

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/build_intraday_features.log"),
        logging.StreamHandler(),
    ],
)


def load_sip_membership():
    """Load SIP membership to know which symbols to process per day."""
    sip_path = Path("run/sip_membership_full_gold_6months/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    logging.info(
        f"Loaded SIP: {len(sip)} selections, {sip['symbol'].n_unique()} symbols"
    )
    return sip


def load_intraday_bars(symbol, date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load 1m bars for symbol on date, plus 20 days history for indicators."""
    symbol_path = Path(data_root) / symbol

    if not symbol_path.exists():
        return None

    # Convert date to date object if string
    if isinstance(date, str):
        date_obj = datetime.strptime(date, "%Y-%m-%d").date()
    else:
        date_obj = date
    year = date_obj.year
    month = date_obj.strftime("%Y-%m")

    files_to_try = [
        symbol_path / str(year) / f"{month}.parquet",
        symbol_path / f"{month}.parquet",
        symbol_path / f"{date}.parquet",
    ]

    # Also load previous month for history
    prev_month = (date_obj.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    prev_year = (date_obj.replace(day=1) - timedelta(days=1)).year
    files_to_try.extend(
        [
            symbol_path / str(prev_year) / f"{prev_month}.parquet",
            symbol_path / f"{prev_month}.parquet",
        ]
    )

    dfs = []
    for file_path in files_to_try:
        if file_path.exists():
            try:
                df = pl.read_parquet(file_path)
                # Normalize timestamp column
                if "ts" in df.columns:
                    df = df.rename({"ts": "timestamp"})
                dfs.append(df)
            except Exception as e:
                logging.debug(f"Error reading {file_path}: {e}")

    if not dfs:
        return None

    # Combine and filter
    df = pl.concat(dfs)
    df = df.with_columns(pl.col("timestamp").cast(pl.Datetime))

    # Filter to date and 20 days prior
    start_date = date_obj - timedelta(days=30)
    end_date = date_obj

    df = df.filter(
        (pl.col("timestamp").dt.date() >= start_date)
        & (pl.col("timestamp").dt.date() <= end_date)
    )

    return df.sort("timestamp")


def engineer_intraday_features(df, target_date):
    """Engineer features from 1m bars."""
    # Convert target_date to date object if string
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date

    # Filter to market hours (9:30-16:00)
    df = df.filter(
        (pl.col("timestamp").dt.hour() >= 9) & (pl.col("timestamp").dt.hour() < 16)
        | (
            (pl.col("timestamp").dt.hour() == 9)
            & (pl.col("timestamp").dt.minute() >= 30)
        )
    )

    # Returns
    df = df.with_columns(
        [
            pl.col("close").pct_change().alias("returns"),
            pl.col("close").pct_change(5).alias("returns_5"),
            pl.col("close").pct_change(10).alias("returns_10"),
            pl.col("close").pct_change(20).alias("returns_20"),
        ]
    )

    # Price structure
    df = df.with_columns(
        [
            ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("range_pct"),
            ((pl.col("close") - pl.col("open")).abs() / pl.col("close")).alias(
                "body_pct"
            ),
        ]
    )

    # Volume
    df = df.with_columns(
        [
            pl.col("volume").rolling_mean(5).alias("volume_ma5"),
            pl.col("volume").rolling_mean(20).alias("volume_ma20"),
        ]
    )
    df = df.with_columns(
        [
            (pl.col("volume") / (pl.col("volume_ma5") + 1)).alias("volume_ratio"),
            (pl.col("volume") / (pl.col("volume_ma20") + 1)).alias("volume_ratio_20"),
        ]
    )

    # Volatility
    df = df.with_columns(
        [
            pl.col("returns").rolling_std(5).alias("volatility_5"),
            pl.col("returns").rolling_std(20).alias("volatility_20"),
        ]
    )

    # Time features
    df = df.with_columns(
        [
            (
                (pl.col("timestamp").dt.hour() - 9) * 60
                + (pl.col("timestamp").dt.minute() - 30)
            ).alias("time_since_open"),
            (
                (16 - pl.col("timestamp").dt.hour()) * 60
                - pl.col("timestamp").dt.minute()
            ).alias("time_to_close"),
        ]
    )

    # Price position
    df = df.with_columns(
        [
            pl.col("high").rolling_max(5).alias("high_5"),
            pl.col("low").rolling_min(5).alias("low_5"),
        ]
    )
    df = df.with_columns(
        [
            (
                (pl.col("close") - pl.col("low_5"))
                / (pl.col("high_5") - pl.col("low_5") + 1e-8)
            ).alias("price_position"),
        ]
    )

    # Filter to target date only
    df = df.filter(pl.col("timestamp").dt.date() == target_date_obj)

    return df


def create_labels(df, forward_bars=5, profit_threshold=0.015):
    """Create LONG/SHORT labels."""
    df = df.with_columns(
        [
            pl.col("close").shift(-forward_bars).alias("future_close"),
        ]
    )
    df = df.with_columns(
        [
            ((pl.col("future_close") - pl.col("close")) / pl.col("close")).alias(
                "forward_return"
            ),
        ]
    )

    df = df.with_columns(
        [
            pl.when(pl.col("forward_return") > profit_threshold)
            .then(1)
            .otherwise(0)
            .alias("label_long"),
            pl.when(pl.col("forward_return") < -profit_threshold)
            .then(1)
            .otherwise(0)
            .alias("label_short"),
        ]
    )

    return df


def main():
    logging.info("=" * 80)
    logging.info("BUILDING INTRADAY FEATURE STORE FOR SIP SYMBOLS")
    logging.info("=" * 80)

    # Load SIP membership
    sip = load_sip_membership()

    # Group by date
    sip_by_date = sip.group_by("date").agg(pl.col("symbol"))
    dates = sorted(sip_by_date["date"].to_list())

    logging.info(f"Processing {len(dates)} dates")

    all_features = []
    total_bars = 0

    for i, date in enumerate(dates, 1):
        symbols = sip_by_date.filter(pl.col("date") == date)["symbol"][0]
        logging.info(f"[{i}/{len(dates)}] {date}: {len(symbols)} symbols")

        date_bars = 0
        for symbol in symbols:
            # Load intraday bars with history
            df = load_intraday_bars(symbol, date)
            if df is None or len(df) == 0:
                continue

            # Engineer features
            try:
                df = engineer_intraday_features(df, date)
                if len(df) == 0:
                    continue

                # Create labels
                df = create_labels(df)

                # Add metadata
                df = df.with_columns(
                    [
                        pl.lit(symbol).alias("symbol"),
                        pl.lit(date).alias("date"),
                    ]
                )

                all_features.append(df)
                date_bars += len(df)
            except Exception as e:
                logging.debug(f"Error processing {symbol} on {date}: {e}")

        total_bars += date_bars
        if date_bars > 0:
            logging.info(f"  Processed {date_bars} bars")

        # Save intermediate results every 10 dates
        if i % 10 == 0 and all_features:
            combined = pl.concat(all_features)
            output_dir = Path("run/intraday_features_sip_6months")
            output_dir.mkdir(parents=True, exist_ok=True)
            combined.write_parquet(output_dir / "features_temp.parquet")
            logging.info(f"  Saved intermediate: {len(combined):,} bars")

    # Final save
    if not all_features:
        logging.error("No features generated!")
        return

    combined = pl.concat(all_features)
    output_dir = Path("run/intraday_features_sip_6months")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / "features.parquet"
    combined.write_parquet(output_file)

    logging.info("")
    logging.info("=" * 80)
    logging.info("INTRADAY FEATURE STORE COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Total bars: {len(combined):,}")
    logging.info(f"Unique symbols: {combined['symbol'].n_unique()}")
    logging.info(f"Unique dates: {combined['date'].n_unique()}")
    logging.info(
        f"Avg bars/symbol/day: {len(combined) / (combined['symbol'].n_unique() * combined['date'].n_unique()):.1f}"
    )
    logging.info(f"Saved to: {output_file}")


if __name__ == "__main__":
    main()
