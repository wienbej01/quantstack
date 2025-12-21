#!/usr/bin/env python3
"""Build intraday features for Sep-Dec 2025 ONLY - incremental approach."""

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def load_sip():
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    # Filter for Sep-Dec 2025 only
    sip = sip.filter(pl.col("date") >= pl.date(2025, 9, 10))
    logging.info(f"Loaded SIP for Sep-Dec 2025: {len(sip)} selections")
    return sip

def load_monthly_bars(symbol, year, month, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load from monthly parquet files (new format)."""
    symbol_path = Path(data_root) / symbol / str(year)
    monthly_file = symbol_path / f"{year}-{month:02d}.parquet"
    
    if not monthly_file.exists():
        return None
    
    try:
        df = pl.read_parquet(monthly_file)
        # Rename ts to timestamp and ensure consistent datetime type
        if "ts" in df.columns:
            df = df.rename({"ts": "timestamp"})
        if "timestamp" in df.columns:
            df = df.with_columns(pl.col("timestamp").cast(pl.Datetime("ns")))
        return df
    except Exception as e:
        logging.warning(f"Failed to load {monthly_file}: {e}")
        return None

def build_features(df):
    """Build 30 ICT features."""
    if len(df) < 50:
        return None
    
    # Sort by timestamp
    df = df.sort("timestamp")
    
    # Basic features
    df = df.with_columns([
        ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("returns"),
        (pl.col("high") - pl.col("low")).alias("range"),
        (pl.col("volume") / pl.col("volume").rolling_mean(20)).alias("volume_ratio"),
        pl.col("timestamp").dt.hour().alias("hour_et"),
    ])
    
    # Multi-timeframe returns
    for window in [1, 2, 3, 5, 10, 15, 20, 30]:
        df = df.with_columns([
            pl.col("returns").rolling_sum(window).alias(f"ret_{window}bar"),
            pl.col("volume_ratio").rolling_mean(window).alias(f"vol_{window}bar"),
        ])
    
    # Technical indicators
    df = df.with_columns([
        # RSI
        pl.col("returns").rolling_mean(7).alias("rsi_7"),
        pl.col("returns").rolling_mean(14).alias("rsi_14"),
        pl.col("returns").rolling_mean(21).alias("rsi_21"),
        
        # ATR percentage
        (pl.col("range") / pl.col("close")).alias("atr_pct"),
    ])
    
    # Forward return (target)
    df = df.with_columns([
        pl.col("returns").shift(-30).alias("return_30min")
    ])
    
    # Select features
    feature_cols = [
        "timestamp", "symbol", "returns", "return_30min", "volume_ratio", "hour_et", "atr_pct"
    ] + [f"ret_{w}bar" for w in [1,2,3,5,10,15,20,30]] + [f"vol_{w}bar" for w in [1,2,3,5,10,15,20,30]] + [
        "rsi_7", "rsi_14", "rsi_21"
    ]
    
    available_cols = [c for c in feature_cols if c in df.columns]
    return df.select(available_cols).drop_nulls()

def main():
    logging.info("=" * 80)
    logging.info("BUILDING INTRADAY FEATURES: Sep-Dec 2025 ONLY")
    logging.info("=" * 80)
    
    # Load SIP for missing period
    sip = load_sip()
    if len(sip) == 0:
        logging.error("No SIP data for Sep-Dec 2025")
        return
    
    # Group by month for incremental processing
    sip = sip.with_columns([
        pl.col("date").dt.year().alias("year"),
        pl.col("date").dt.month().alias("month")
    ])
    
    all_features = []
    
    # Process each month separately
    for year_month in [(2025, 9), (2025, 10), (2025, 11), (2025, 12)]:
        year, month = year_month
        logging.info(f"\n--- Processing {year}-{month:02d} ---")
        
        month_sip = sip.filter((pl.col("year") == year) & (pl.col("month") == month))
        if len(month_sip) == 0:
            logging.info(f"No SIP data for {year}-{month:02d}")
            continue
        
        symbols = month_sip["symbol"].unique().to_list()
        logging.info(f"Processing {len(symbols)} symbols for {year}-{month:02d}")
        
        month_features = []
        for i, symbol in enumerate(symbols):
            if i % 10 == 0:
                logging.info(f"  [{i+1}/{len(symbols)}] {symbol}")
            
            # Load monthly data
            df = load_monthly_bars(symbol, year, month)
            if df is None:
                continue
            
            # Filter to SIP dates only
            symbol_dates = month_sip.filter(pl.col("symbol") == symbol)["date"].to_list()
            df = df.filter(pl.col("timestamp").dt.date().is_in(symbol_dates))
            
            if len(df) == 0:
                continue
            
            # Build features
            features = build_features(df)
            if features is not None and len(features) > 0:
                features = features.with_columns(pl.lit(symbol).alias("symbol"))
                month_features.append(features)
        
        if month_features:
            month_df = pl.concat(month_features)
            all_features.append(month_df)
            logging.info(f"✅ {year}-{month:02d}: {len(month_df):,} feature rows from {len(month_features)} symbols")
        else:
            logging.warning(f"❌ {year}-{month:02d}: No features generated")
    
    if not all_features:
        logging.error("No features generated for any month!")
        return
    
    # Combine all months
    final_features = pl.concat(all_features)
    logging.info(f"\n✅ Total features generated: {len(final_features):,} rows")
    
    # Load existing features and append
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if existing_path.exists():
        existing = pl.read_parquet(existing_path)
        # Remove any overlapping dates
        existing = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
        combined = pl.concat([existing, final_features])
        logging.info(f"Combined with existing: {len(combined):,} total rows")
    else:
        combined = final_features
    
    # Save
    output_dir = Path("run/intraday_features_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    combined.write_parquet(output_dir / "features.parquet")
    
    logging.info(f"\n🎉 COMPLETE: Intraday features now cover through Dec 2025")
    logging.info(f"Date range: {combined['timestamp'].dt.date().min()} to {combined['timestamp'].dt.date().max()}")

if __name__ == "__main__":
    main()
