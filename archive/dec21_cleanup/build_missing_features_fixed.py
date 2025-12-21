#!/usr/bin/env python3
"""Build missing Sep-Dec 2025 features - FIXED to load historical data like original."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def load_historical_bars(symbol, target_date, data_root="/home/jacobw/gcs-mount/gold/stocks/1m"):
    """Load 30 days of historical data for feature calculation (matches original logic)."""
    symbol_path = Path(data_root) / symbol
    if not symbol_path.exists():
        return None

    if isinstance(target_date, str):
        date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        date_obj = target_date

    # Load current and previous month (like original)
    year = date_obj.year
    month = date_obj.strftime("%Y-%m")
    prev_month = (date_obj.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    prev_year = (date_obj.replace(day=1) - timedelta(days=1)).year

    files_to_try = [
        symbol_path / str(year) / f"{month}.parquet",
        symbol_path / str(prev_year) / f"{prev_month}.parquet",
    ]

    dfs = []
    for file_path in files_to_try:
        if file_path.exists():
            try:
                df = pl.read_parquet(file_path)
                if "ts" in df.columns:
                    df = df.rename({"ts": "timestamp"})
                
                # Standardize ALL column types before concat
                df = df.with_columns([
                    pl.col("timestamp").cast(pl.Datetime("us")),
                    pl.col("open").cast(pl.Float64),
                    pl.col("high").cast(pl.Float64),
                    pl.col("low").cast(pl.Float64),
                    pl.col("close").cast(pl.Float64),
                    pl.col("volume").cast(pl.Float64),
                ])
                
                # Only keep essential columns to avoid schema conflicts
                df = df.select(["timestamp", "open", "high", "low", "close", "volume"])
                dfs.append(df)
            except Exception as e:
                logging.warning(f"Failed to load {file_path}: {e}")
                pass

    if not dfs:
        return None

    df = pl.concat(dfs)

    # Load 30 days of history for rolling calculations
    start_date = date_obj - timedelta(days=30)
    df = df.filter(
        (pl.col("timestamp").dt.date() >= start_date)
        & (pl.col("timestamp").dt.date() <= date_obj)
    )

    return df.sort("timestamp") if len(df) > 0 else None

def engineer_features(df, target_date):
    """Build features using 30 days of data, return only target date."""
    if len(df) < 50:
        return None
    
    # Basic features
    df = df.with_columns([
        ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("returns"),
        (pl.col("high") - pl.col("low")).alias("range"),
        (pl.col("volume") / pl.col("volume").rolling_mean(20, min_periods=1)).alias("volume_ratio"),
        pl.col("timestamp").dt.hour().alias("hour_et"),
        (pl.col("high") - pl.col("low")) / pl.col("close").alias("atr_pct"),
    ])
    
    # Multi-timeframe returns
    for window in [1, 2, 3, 5, 10, 15, 20, 30]:
        df = df.with_columns([
            pl.col("returns").rolling_sum(window, min_periods=1).alias(f"ret_{window}bar"),
            pl.col("volume_ratio").rolling_mean(window, min_periods=1).alias(f"vol_{window}bar"),
        ])
    
    # RSI approximation
    for window in [7, 14, 21]:
        df = df.with_columns([
            pl.col("returns").rolling_mean(window, min_periods=1).alias(f"rsi_{window}")
        ])
    
    # Technical indicators using rolling windows
    df = df.with_columns([
        # MACD approximations
        (pl.col("close").ewm_mean(span=12) - pl.col("close").ewm_mean(span=26)).alias("macd_12_26"),
        (pl.col("close").ewm_mean(span=5) - pl.col("close").ewm_mean(span=10)).alias("macd_5_10"),
        (pl.col("close").ewm_mean(span=8) - pl.col("close").ewm_mean(span=21)).alias("macd_8_21"),
    ])
    
    # MACD signals
    for name in ["macd_12_26", "macd_5_10", "macd_8_21"]:
        df = df.with_columns([
            pl.col(name).ewm_mean(span=9).alias(f"{name.replace('macd', 'macd_signal')}")
        ])
        df = df.with_columns([
            (pl.col(name) - pl.col(f"{name.replace('macd', 'macd_signal')}")).alias(f"{name.replace('macd', 'macd_hist')}")
        ])
    
    # Bollinger Bands
    for window in [10, 20]:
        df = df.with_columns([
            pl.col("close").rolling_mean(window, min_periods=1).alias(f"bb_mid_{window}"),
            pl.col("close").rolling_std(window, min_periods=1).alias(f"bb_std_{window}"),
        ])
        df = df.with_columns([
            (pl.col(f"bb_mid_{window}") + 2 * pl.col(f"bb_std_{window}")).alias(f"bb_upper_{window}"),
            (pl.col(f"bb_mid_{window}") - 2 * pl.col(f"bb_std_{window}")).alias(f"bb_lower_{window}"),
        ])
        df = df.with_columns([
            ((pl.col("close") - pl.col(f"bb_lower_{window}")) / 
             (pl.col(f"bb_upper_{window}") - pl.col(f"bb_lower_{window}"))).alias(f"bb_position_{window}"),
            ((pl.col(f"bb_upper_{window}") - pl.col(f"bb_lower_{window}")) / 
             pl.col(f"bb_mid_{window}")).alias(f"bb_width_{window}")
        ])
    
    # Forward return target
    df = df.with_columns([
        pl.col("returns").shift(-30).alias("return_30min")
    ])
    
    # Filter to target date only (after calculating features on full history)
    if isinstance(target_date, str):
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    else:
        target_date_obj = target_date
    
    df = df.filter(pl.col("timestamp").dt.date() == target_date_obj)
    
    # Select feature columns
    feature_cols = [
        "timestamp", "returns", "return_30min", "volume_ratio", "hour_et", "atr_pct"
    ] + [f"ret_{w}bar" for w in [1,2,3,5,10,15,20,30]] + [f"vol_{w}bar" for w in [1,2,3,5,10,15,20,30]] + [
        f"rsi_{w}" for w in [7,14,21]
    ] + [
        "macd_12_26", "macd_signal_12_26", "macd_hist_12_26",
        "macd_5_10", "macd_signal_5_10", "macd_hist_5_10", 
        "macd_8_21", "macd_signal_8_21", "macd_hist_8_21"
    ] + [f"bb_{t}_{w}" for t in ["upper", "lower", "position", "width"] for w in [10,20]]
    
    available_cols = [c for c in feature_cols if c in df.columns]
    return df.select(available_cols).drop_nulls()

def main():
    logging.info("=" * 80)
    logging.info("BUILDING MISSING FEATURES: Sep-Dec 2025 (FIXED - with historical data)")
    logging.info("=" * 80)
    
    # Load SIP for missing period
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    sip = sip.filter(pl.col("date") >= pl.date(2025, 9, 10))
    
    if len(sip) == 0:
        logging.error("No SIP data for Sep-Dec 2025")
        return
    
    logging.info(f"Processing {len(sip)} SIP selections")
    
    # Group by date for processing
    dates = sorted(sip["date"].unique().to_list())
    logging.info(f"Processing {len(dates)} dates from {dates[0]} to {dates[-1]}")
    
    all_features = []
    
    for i, date in enumerate(dates):
        if i % 10 == 0:
            logging.info(f"[{i+1}/{len(dates)}] Processing {date}")
        
        date_sip = sip.filter(pl.col("date") == date)
        symbols = date_sip["symbol"].unique().to_list()
        
        date_features = []
        for symbol in symbols:
            # Load 30 days of historical data for this symbol/date
            df = load_historical_bars(symbol, date)
            if df is None or len(df) < 50:
                continue
            
            # Engineer features using full history, return target date only
            features = engineer_features(df, date)
            if features is not None and len(features) > 0:
                features = features.with_columns(pl.lit(symbol).alias("symbol"))
                date_features.append(features)
        
        if date_features:
            date_df = pl.concat(date_features)
            all_features.append(date_df)
        
        # Progress update
        if (i + 1) % 50 == 0:
            logging.info(f"  Processed {i+1} dates, {len(all_features)} successful")
    
    if not all_features:
        logging.error("No features generated!")
        return
    
    # Combine all dates
    new_features = pl.concat(all_features)
    logging.info(f"Generated {len(new_features):,} feature rows")
    
    # Load existing and combine
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if existing_path.exists():
        existing = pl.read_parquet(existing_path)
        existing = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
        combined = pl.concat([existing, new_features])
        logging.info(f"Combined total: {len(combined):,}")
    else:
        combined = new_features
    
    # Save
    output_dir = Path("run/intraday_features_rolling")
    output_dir.mkdir(parents=True, exist_ok=True)
    combined.write_parquet(output_dir / "features.parquet")
    
    logging.info("🎉 SUCCESS: Features complete through Dec 2025")
    logging.info(f"Date range: {combined['timestamp'].dt.date().min()} to {combined['timestamp'].dt.date().max()}")

if __name__ == "__main__":
    main()
