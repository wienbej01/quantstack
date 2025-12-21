#!/usr/bin/env python3
"""Build missing Sep-Dec 2025 features - PRODUCTION VERSION."""

import logging
from pathlib import Path
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def main():
    logging.info("=" * 80)
    logging.info("Building missing Sep-Dec 2025 features")
    logging.info("=" * 80)
    
    # Load existing features and get schema
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    existing = pl.read_parquet(existing_path)
    existing_cols = existing.columns
    existing_schema = existing.schema
    logging.info(f"Existing: {len(existing):,} rows, {len(existing_cols)} columns")
    
    # Filter existing to before Sep 10
    existing_filtered = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
    logging.info(f"Existing before Sep 10: {len(existing_filtered):,} rows")
    
    # Load SIP
    sip = pl.read_parquet("run/sip_membership_rolling/sip_membership.parquet")
    sip = sip.filter(pl.col("date") >= pl.date(2025, 9, 10))
    logging.info(f"SIP selections: {len(sip)}")
    
    data_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    all_features = []
    
    # Process by month
    for month in [9, 10, 11, 12]:
        logging.info(f"Processing 2025-{month:02d}...")
        month_sip = sip.filter(pl.col("date").dt.month() == month)
        if len(month_sip) == 0:
            continue
        
        symbols = month_sip["symbol"].unique().to_list()
        month_features = []
        
        for i, symbol in enumerate(symbols):
            if i % 20 == 0:
                logging.info(f"  [{i+1}/{len(symbols)}] {symbol}")
            
            monthly_file = data_root / symbol / "2025" / f"2025-{month:02d}.parquet"
            if not monthly_file.exists():
                continue
            
            try:
                df = pl.read_parquet(monthly_file)
                if "ts" in df.columns:
                    df = df.rename({"ts": "timestamp"})
                
                # Get SIP dates
                symbol_dates = month_sip.filter(pl.col("symbol") == symbol)["date"].to_list()
                df = df.filter(pl.col("timestamp").dt.date().is_in(symbol_dates))
                
                if len(df) == 0:
                    continue
                
                # Add symbol
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                
                # Cast ALL columns to match existing schema EXACTLY
                for col in existing_cols:
                    dtype = existing_schema[col]
                    if col in df.columns:
                        # Cast to exact type
                        df = df.with_columns(pl.col(col).cast(dtype))
                    else:
                        # Add missing column with correct type
                        df = df.with_columns(pl.lit(None).cast(dtype).alias(col))
                
                # Select in exact order
                df = df.select(existing_cols)
                month_features.append(df)
                
            except Exception as e:
                logging.warning(f"Failed {symbol}: {e}")
                continue
        
        if month_features:
            month_df = pl.concat(month_features)
            all_features.append(month_df)
            logging.info(f"  ✅ 2025-{month:02d}: {len(month_df):,} rows")
    
    if not all_features:
        logging.error("No features generated!")
        return
    
    # Combine
    new_features = pl.concat(all_features)
    logging.info(f"New features: {len(new_features):,} rows")
    
    combined = pl.concat([existing_filtered, new_features])
    logging.info(f"Combined: {len(combined):,} rows")
    
    # Save
    combined.write_parquet(existing_path)
    logging.info(f"🎉 SUCCESS! Date range: {combined['timestamp'].dt.date().min()} to {combined['timestamp'].dt.date().max()}")

if __name__ == "__main__":
    main()
