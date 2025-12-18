#!/usr/bin/env python3
"""Targeted migration - only process files for tickers we actually need."""

import pandas as pd
from pathlib import Path
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def load_needed_tickers():
    """Load tickers that actually need processing."""
    universe_dir = Path("/home/jacobw/quantstack/universe_data")
    
    # Load the complete universe
    universe_file = universe_dir / "complete_universe.csv"
    if not universe_file.exists():
        logger.error("Universe file not found")
        return set()
    
    df = pd.read_csv(universe_file)
    universe_tickers = set(df['ticker'].astype(str).str.upper())
    
    logger.info(f"Loaded {len(universe_tickers)} universe tickers")
    return universe_tickers

def check_existing_gold_coverage(ticker):
    """Check if ticker already has good gold coverage."""
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    ticker_path = gold_root / ticker
    
    if not ticker_path.exists():
        return False
    
    # Check for historical data (2021-2024)
    year_dirs = [d for d in ticker_path.iterdir() if d.is_dir() and d.name.isdigit()]
    years = [int(d.name) for d in year_dirs]
    
    # If has data from 2021-2024, consider it good
    historical_years = [y for y in years if 2021 <= y <= 2024]
    return len(historical_years) >= 2  # At least 2 years of historical data

def process_ticker_efficiently(ticker, bronze_root, gold_root):
    """Process only necessary files for a ticker."""
    ticker_bronze = bronze_root / ticker
    ticker_gold = gold_root / ticker
    
    if not ticker_bronze.exists():
        return {"skipped": 0, "processed": 0, "failed": 0}
    
    stats = {"skipped": 0, "processed": 0, "failed": 0}
    
    # Only process years we don't have in gold
    for year_dir in ticker_bronze.iterdir():
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
            
        year = year_dir.name
        gold_year_dir = ticker_gold / year
        
        # Skip if gold year already exists and has files
        if gold_year_dir.exists() and list(gold_year_dir.glob("*.parquet")):
            stats["skipped"] += len(list(year_dir.glob("*.parquet")))
            continue
        
        # Process this year
        gold_year_dir.mkdir(parents=True, exist_ok=True)
        
        for bronze_file in year_dir.glob("*.parquet"):
            try:
                # Quick column mapping and conversion
                df = pd.read_parquet(bronze_file)
                if df.empty:
                    continue
                
                # Minimal column mapping
                col_map = {'t': 'ts_ms', 'o': 'open', 'h': 'high', 'l': 'low', 'c': 'close', 'v': 'volume'}
                df = df.rename(columns=col_map)
                
                # Minimal gold conversion
                gold_df = pd.DataFrame({
                    'ts': pd.to_datetime(df['ts_ms'], unit='ms', utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None),
                    'open': df['open'].astype('float64'),
                    'high': df['high'].astype('float64'),
                    'low': df['low'].astype('float64'), 
                    'close': df['close'].astype('float64'),
                    'volume': df['volume'].astype('float64'),
                    'bar_index': range(len(df))
                })
                
                # Save with correct filename
                filename = bronze_file.name
                if '_' in filename:
                    gold_filename = filename.split('_', 1)[1]
                else:
                    gold_filename = filename
                
                gold_path = gold_year_dir / gold_filename
                gold_df.to_parquet(gold_path, index=False)
                stats["processed"] += 1
                
            except Exception as e:
                logger.error(f"Failed {bronze_file}: {e}")
                stats["failed"] += 1
    
    return stats

def main():
    """Main targeted migration."""
    logger.info("Starting targeted migration for universe tickers only...")
    
    # Load needed tickers
    universe_tickers = load_needed_tickers()
    if not universe_tickers:
        return
    
    bronze_root = Path("/home/jacobw/gcs-mount/bronze/stocks/1m")
    gold_root = Path("/home/jacobw/gcs-mount/gold/stocks/1m")
    
    # Filter to tickers that need processing
    tickers_to_process = []
    for ticker in universe_tickers:
        if not check_existing_gold_coverage(ticker):
            tickers_to_process.append(ticker)
    
    logger.info(f"Need to process {len(tickers_to_process)} tickers (out of {len(universe_tickers)} total)")
    
    total_stats = {"skipped": 0, "processed": 0, "failed": 0}
    start_time = time.time()
    
    for i, ticker in enumerate(tickers_to_process):
        logger.info(f"Processing {i+1}/{len(tickers_to_process)}: {ticker}")
        
        ticker_stats = process_ticker_efficiently(ticker, bronze_root, gold_root)
        for key in total_stats:
            total_stats[key] += ticker_stats[key]
        
        if i % 10 == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            logger.info(f"Progress: {i+1}/{len(tickers_to_process)} tickers - {rate:.2f} tickers/min")
    
    elapsed = time.time() - start_time
    logger.info(f"Migration complete in {elapsed/60:.1f} minutes")
    logger.info(f"Results: {total_stats}")

if __name__ == "__main__":
    main()
