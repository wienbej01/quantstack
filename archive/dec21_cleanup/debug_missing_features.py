#!/usr/bin/env python3
"""Build missing Sep-Dec 2025 features - FULL DEBUG VERSION."""

import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
import polars as pl

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

def main():
    logging.info("=" * 80)
    logging.info("DEBUG: Building missing features with FULL LOGGING")
    logging.info("=" * 80)
    
    try:
        # Step 1: Load existing features
        logging.info("STEP 1: Loading existing features...")
        existing_path = Path("run/intraday_features_rolling/features.parquet")
        if not existing_path.exists():
            logging.error(f"File not found: {existing_path}")
            return
        
        existing = pl.read_parquet(existing_path)
        logging.info(f"  Loaded {len(existing):,} rows, {len(existing.columns)} columns")
        logging.info(f"  Columns: {existing.columns}")
        logging.info(f"  Schema: {existing.schema}")
        
        # Step 2: Filter existing to before Sep 10
        logging.info("STEP 2: Filtering existing data...")
        existing_filtered = existing.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
        logging.info(f"  Filtered to {len(existing_filtered):,} rows")
        
        # Step 3: Load SIP
        logging.info("STEP 3: Loading SIP data...")
        sip_path = Path("run/sip_membership_rolling/sip_membership.parquet")
        sip = pl.read_parquet(sip_path)
        sip = sip.filter(pl.col("date") >= pl.date(2025, 9, 10))
        logging.info(f"  SIP selections: {len(sip)}")
        logging.info(f"  Date range: {sip['date'].min()} to {sip['date'].max()}")
        
        if len(sip) == 0:
            logging.error("No SIP data!")
            return
        
        # Step 4: Test loading ONE symbol
        logging.info("STEP 4: Testing single symbol load...")
        test_symbol = sip["symbol"].unique().to_list()[0]
        test_date = sip["date"].unique().to_list()[0]
        logging.info(f"  Test symbol: {test_symbol}, date: {test_date}")
        
        data_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
        test_month = test_date.month
        test_file = data_root / test_symbol / "2025" / f"2025-{test_month:02d}.parquet"
        logging.info(f"  Test file: {test_file}")
        logging.info(f"  File exists: {test_file.exists()}")
        
        if test_file.exists():
            test_df = pl.read_parquet(test_file)
            logging.info(f"  Test file columns: {test_df.columns}")
            logging.info(f"  Test file schema: {test_df.schema}")
            logging.info(f"  Test file rows: {len(test_df)}")
        
        # Step 5: Process ONE symbol completely
        logging.info("STEP 5: Processing single symbol with full feature engineering...")
        
        df = pl.read_parquet(test_file)
        logging.debug(f"  Raw data loaded: {len(df)} rows")
        
        # Rename ts to timestamp
        if "ts" in df.columns:
            df = df.rename({"ts": "timestamp"})
            logging.debug("  Renamed ts -> timestamp")
        
        # Check timestamp type
        logging.debug(f"  Timestamp dtype: {df['timestamp'].dtype}")
        
        # Cast timestamp
        df = df.with_columns(pl.col("timestamp").cast(pl.Datetime("us")))
        logging.debug(f"  After cast, timestamp dtype: {df['timestamp'].dtype}")
        
        # Filter to SIP date
        df = df.filter(pl.col("timestamp").dt.date() == test_date)
        logging.info(f"  After date filter: {len(df)} rows")
        
        if len(df) == 0:
            logging.warning("  No data for test date!")
            # Try to see what dates are available
            df_full = pl.read_parquet(test_file)
            if "ts" in df_full.columns:
                df_full = df_full.rename({"ts": "timestamp"})
            dates_available = df_full["timestamp"].dt.date().unique().to_list()
            logging.info(f"  Available dates in file: {dates_available[:10]}...")
            return
        
        # Add symbol
        df = df.with_columns(pl.lit(test_symbol).alias("symbol"))
        logging.debug(f"  Added symbol column")
        
        # Now align to existing schema
        logging.info("STEP 6: Aligning to existing schema...")
        existing_cols = existing.columns
        existing_schema = existing.schema
        
        for col in existing_cols:
            if col not in df.columns:
                dtype = existing_schema[col]
                logging.debug(f"  Adding missing column: {col} ({dtype})")
                df = df.with_columns(pl.lit(None).cast(dtype).alias(col))
        
        # Remove extra columns not in existing
        extra_cols = [c for c in df.columns if c not in existing_cols]
        if extra_cols:
            logging.debug(f"  Removing extra columns: {extra_cols}")
            df = df.select(existing_cols)
        
        logging.info(f"  Final columns: {len(df.columns)}")
        logging.info(f"  Final schema matches existing: {df.schema == existing.schema}")
        
        if df.schema != existing.schema:
            logging.error("Schema mismatch!")
            for col in existing_cols:
                if col in df.columns:
                    if df[col].dtype != existing[col].dtype:
                        logging.error(f"  {col}: {df[col].dtype} vs {existing[col].dtype}")
            return
        
        # Step 7: Test concat
        logging.info("STEP 7: Testing concat...")
        test_concat = pl.concat([existing_filtered.head(100), df.head(100)])
        logging.info(f"  Concat successful! {len(test_concat)} rows")
        
        logging.info("=" * 80)
        logging.info("DEBUG COMPLETE - All steps passed!")
        logging.info("=" * 80)
        
    except Exception as e:
        logging.error(f"EXCEPTION: {e}")
        logging.error(traceback.format_exc())

if __name__ == "__main__":
    main()
