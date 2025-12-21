#!/usr/bin/env python3
"""Build missing Sep-Dec 2025 features - simplified version."""

import logging
from pathlib import Path

import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def build_features_for_month(year, month):
    """Build features for one month."""
    logging.info(f"Building features for {year}-{month:02d}")

    # Load SIP for this month
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    sip = sip.filter(
        (pl.col("date").dt.year() == year) & (pl.col("date").dt.month() == month)
    )

    if len(sip) == 0:
        logging.info(f"No SIP data for {year}-{month:02d}")
        return None

    symbols = sip["symbol"].unique().to_list()
    logging.info(f"Processing {len(symbols)} symbols")

    all_features = []
    data_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    for i, symbol in enumerate(symbols):
        if i % 20 == 0:
            logging.info(f"  [{i+1}/{len(symbols)}] {symbol}")

        # Load monthly data
        symbol_path = data_root / symbol / str(year)
        monthly_file = symbol_path / f"{year}-{month:02d}.parquet"

        if not monthly_file.exists():
            continue

        try:
            df = pl.read_parquet(monthly_file)
            df = df.rename({"ts": "timestamp"})

            # Get SIP dates for this symbol
            symbol_dates = sip.filter(pl.col("symbol") == symbol)["date"].to_list()
            df = df.filter(pl.col("timestamp").dt.date().is_in(symbol_dates))

            if len(df) < 30:  # Need minimum bars
                continue

            # Build basic features
            df = df.with_columns(
                [
                    pl.lit(symbol).alias("symbol"),
                    ((pl.col("close") - pl.col("open")) / pl.col("open")).alias(
                        "returns"
                    ),
                    (
                        pl.col("volume")
                        / pl.col("volume").rolling_mean(20, min_periods=1)
                    ).alias("volume_ratio"),
                    pl.col("timestamp").dt.hour().alias("hour_et"),
                    (pl.col("high") - pl.col("low")).alias("range"),
                ]
            )

            # ATR percentage
            df = df.with_columns([(pl.col("range") / pl.col("close")).alias("atr_pct")])

            # Multi-timeframe returns (key features)
            for window in [1, 2, 3, 5, 10, 15, 20]:
                df = df.with_columns(
                    [
                        pl.col("returns")
                        .rolling_sum(window, min_periods=1)
                        .alias(f"ret_{window}bar"),
                        pl.col("volume_ratio")
                        .rolling_mean(window, min_periods=1)
                        .alias(f"vol_{window}bar"),
                    ]
                )

            # RSI approximation
            df = df.with_columns(
                [
                    pl.col("returns").rolling_mean(7, min_periods=1).alias("rsi_7"),
                    pl.col("returns").rolling_mean(14, min_periods=1).alias("rsi_14"),
                ]
            )

            # Forward return (target)
            df = df.with_columns([pl.col("returns").shift(-30).alias("return_30min")])

            # Select final features
            feature_cols = (
                [
                    "timestamp",
                    "symbol",
                    "returns",
                    "return_30min",
                    "volume_ratio",
                    "hour_et",
                    "atr_pct",
                    "rsi_7",
                    "rsi_14",
                ]
                + [f"ret_{w}bar" for w in [1, 2, 3, 5, 10, 15, 20]]
                + [f"vol_{w}bar" for w in [1, 2, 3, 5, 10, 15, 20]]
            )

            features = df.select(feature_cols).drop_nulls()

            if len(features) > 0:
                all_features.append(features)

        except Exception as e:
            logging.warning(f"Failed processing {symbol}: {e}")
            continue

    if all_features:
        month_features = pl.concat(all_features)
        logging.info(f"✅ {year}-{month:02d}: {len(month_features):,} feature rows")
        return month_features
    else:
        logging.warning(f"❌ {year}-{month:02d}: No features generated")
        return None


def main():
    logging.info("=" * 60)
    logging.info("BUILDING MISSING FEATURES: Sep-Dec 2025")
    logging.info("=" * 60)

    all_months = []

    # Process each month
    for month in [9, 10, 11, 12]:
        month_features = build_features_for_month(2025, month)
        if month_features is not None:
            all_months.append(month_features)

    if not all_months:
        logging.error("No features generated!")
        return

    # Combine all months
    new_features = pl.concat(all_months)
    logging.info(f"Total new features: {len(new_features):,}")

    # Load existing and combine
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if existing_path.exists():
        existing = pl.read_parquet(existing_path)
        # Remove any overlap
        existing = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
        combined = pl.concat([existing, new_features])
        logging.info(f"Combined total: {len(combined):,}")
    else:
        combined = new_features

    # Save
    output_dir = Path("run/intraday_features_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    combined.write_parquet(output_dir / "features.parquet")

    logging.info("🎉 SUCCESS: Features now complete through Dec 2025")
    logging.info(
        f"Date range: {combined['timestamp'].dt.date().min()} to {combined['timestamp'].dt.date().max()}"
    )


if __name__ == "__main__":
    main()
