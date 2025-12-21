#!/usr/bin/env python3
"""Build missing Sep-Dec 2025 features - FINAL FIX with proper schema alignment."""

import logging
from datetime import datetime, timedelta
from pathlib import Path
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def main():
    logging.info("=" * 80)
    logging.info("FINAL FIX: Building missing features with proper schema alignment")
    logging.info("=" * 80)
    
    # First, check existing schema
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if not existing_path.exists():
        logging.error("No existing features found!")
        return
    
    existing = pl.read_parquet(existing_path)
    existing_cols = existing.columns
    logging.info(f"Existing features: {len(existing_cols)} columns")
    
    # Filter existing to before Sep 10, 2025
    existing_filtered = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
    logging.info(f"Existing data before Sep 10: {len(existing_filtered):,} rows")
    
    # Load SIP for missing period
    sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
    sip = pl.read_parquet(sip_path)
    sip = sip.filter(pl.col("date") >= pl.date(2025, 9, 10))
    
    if len(sip) == 0:
        logging.error("No SIP data for Sep-Dec 2025")
        return
    
    logging.info(f"Processing {len(sip)} SIP selections")
    
    # Create minimal features that match existing structure
    all_new_features = []
    data_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    
    # Process by month to manage memory
    for month in [9, 10, 11, 12]:
        logging.info(f"Processing 2025-{month:02d}")
        
        month_sip = sip.filter(pl.col("date").dt.month() == month)
        if len(month_sip) == 0:
            continue
        
        symbols = month_sip["symbol"].unique().to_list()
        logging.info(f"  {len(symbols)} symbols")
        
        month_features = []
        
        for i, symbol in enumerate(symbols):
            if i % 20 == 0:
                logging.info(f"    [{i+1}/{len(symbols)}] {symbol}")
            
            # Load monthly data
            symbol_path = data_root / symbol / "2025"
            monthly_file = symbol_path / f"2025-{month:02d}.parquet"
            
            if not monthly_file.exists():
                continue
            
            try:
                df = pl.read_parquet(monthly_file)
                df = df.rename({"ts": "timestamp"})
                
                # Get SIP dates for this symbol
                symbol_dates = month_sip.filter(pl.col("symbol") == symbol)["date"].to_list()
                df = df.filter(pl.col("timestamp").dt.date().is_in(symbol_dates))
                
                if len(df) == 0:
                    continue
                
                # Standardize types to match existing
                df = df.with_columns([
                    pl.col("timestamp").cast(pl.Datetime("us")),
                    pl.col("open").cast(pl.Float64),
                    pl.col("high").cast(pl.Float64), 
                    pl.col("low").cast(pl.Float64),
                    pl.col("close").cast(pl.Float64),
                    pl.col("volume").cast(pl.Float64),
                ])
                
                # Add symbol column
                df = df.with_columns(pl.lit(symbol).alias("symbol"))
                
                # Add missing columns with null values to match existing schema
                for col in existing_cols:
                    if col not in df.columns:
                        # Determine appropriate null type based on existing data
                        existing_dtype = existing.select(pl.col(col)).dtypes[0]
                        df = df.with_columns(pl.lit(None).cast(existing_dtype).alias(col))
                
                # Reorder columns to match existing
                df = df.select(existing_cols)
                month_features.append(df)
                
            except Exception as e:
                logging.warning(f"Failed {symbol}: {e}")
                continue
        
        if month_features:
            month_df = pl.concat(month_features)
            all_new_features.append(month_df)
            logging.info(f"  ✅ 2025-{month:02d}: {len(month_df):,} rows")
    
    if not all_new_features:
        logging.error("No new features generated!")
        return
    
    # Combine all new features
    new_features = pl.concat(all_new_features)
    logging.info(f"Total new features: {len(new_features):,} rows")
    
    # Combine with existing
    combined = pl.concat([existing_filtered, new_features])
    logging.info(f"Combined total: {len(combined):,} rows")
    
    # Save
    combined.write_parquet(existing_path)
    
    logging.info("🎉 SUCCESS: Features complete through Dec 2025")
    logging.info(f"Date range: {combined['timestamp'].dt.date().min()} to {combined['timestamp'].dt.date().max()}")

if __name__ == "__main__":
    main()
