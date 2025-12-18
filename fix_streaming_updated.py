#!/usr/bin/env python3
"""Updated streaming bronze-to-gold fix with proper column handling."""

import logging
import os
import time
import pandas as pd
import numpy as np

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
logger = logging.getLogger(__name__)

def convert_bronze_columns(df):
    """Convert bronze columns to expected format."""
    # Standard column mapping
    column_map = {
        't': 'ts_ms', 
        'timestamp': 'ts_ms',
        'time': 'ts_ms',
        'o': 'open', 
        'h': 'high', 
        'l': 'low', 
        'c': 'close', 
        'v': 'volume', 
        'vw': 'vwap', 
        'n': 'trades'
    }
    
    # Apply column mapping
    df = df.rename(columns=column_map)
    
    # Ensure required columns exist
    if 'ticker' not in df.columns: 
        df['ticker'] = 'UNKNOWN'
    if 'vendor' not in df.columns: 
        df['vendor'] = 'polygon_v2'
    if 'ingested_at_ms' not in df.columns: 
        df['ingested_at_ms'] = int(pd.Timestamp.now().timestamp() * 1000)
    if 'page' not in df.columns: 
        df['page'] = 1
    
    return df

def convert_to_gold(bronze_df):
    """Convert bronze DataFrame to gold format."""
    if bronze_df.empty: 
        return pd.DataFrame()
    
    bronze_df = bronze_df.sort_values('ts_ms').reset_index(drop=True)
    gold_df = pd.DataFrame()
    
    # Convert timestamp to ET timezone
    gold_df['ts'] = pd.to_datetime(bronze_df['ts_ms'], unit='ms', utc=True).dt.tz_convert('US/Eastern').dt.tz_localize(None)
    
    # OHLCV data
    gold_df['open'] = bronze_df['open'].astype('float64')
    gold_df['high'] = bronze_df['high'].astype('float64')
    gold_df['low'] = bronze_df['low'].astype('float64')
    gold_df['close'] = bronze_df['close'].astype('float64')
    gold_df['volume'] = bronze_df['volume'].astype('float64')
    
    # Session calculations
    gold_df['session_date'] = gold_df['ts'].dt.date
    session_groups = gold_df.groupby('session_date')
    session_ids = {date: i+1 for i, (date, _) in enumerate(session_groups)}
    gold_df['session_id'] = gold_df['session_date'].map(session_ids).astype('uint32')
    
    # Bar calculations
    gold_df['bar_index'] = range(len(gold_df))
    gold_df['bar_index'] = gold_df['bar_index'].astype('int32')
    gold_df['ret_1m'] = gold_df['close'].pct_change().fillna(0.0)
    gold_df['log_ret_1m'] = np.log(gold_df['close'] / gold_df['close'].shift(1)).fillna(0.0)
    
    # Session-based calculations
    gold_df['first_open'] = session_groups['open'].transform('first')
    gold_df['ret_from_open'] = (gold_df['close'] - gold_df['first_open']) / gold_df['first_open']
    gold_df['cum_volume'] = session_groups['volume'].cumsum()
    
    # VWAP calculations
    if 'vwap' in bronze_df.columns:
        dollar_vol = bronze_df['volume'] * bronze_df['vwap']
        gold_df['cum_dollar_vol'] = dollar_vol.groupby(gold_df['session_id']).cumsum()
        gold_df['vwap_session'] = (gold_df['cum_dollar_vol'] / gold_df['cum_volume']).fillna(0)
    else:
        # Calculate VWAP from OHLC if not available
        typical_price = (gold_df['high'] + gold_df['low'] + gold_df['close']) / 3
        dollar_vol = gold_df['volume'] * typical_price
        gold_df['cum_dollar_vol'] = dollar_vol.groupby(gold_df['session_id']).cumsum()
        gold_df['vwap_session'] = (gold_df['cum_dollar_vol'] / gold_df['cum_volume']).fillna(0)
    
    # Bar position in session
    gold_df['bars_in_session'] = session_groups.cumcount() + 1
    total_bars = session_groups.transform('count')['open']
    gold_df['is_first_bar'] = (gold_df['bars_in_session'] == 1)
    gold_df['is_last_bar'] = (gold_df['bars_in_session'] == total_bars)
    
    # Previous session close
    session_closes = session_groups['close'].last()
    prev_closes = session_closes.shift(1)
    gold_df['prev_session_close'] = gold_df['session_date'].map(prev_closes).astype('float64')
    
    return gold_df.drop('session_date', axis=1)

def main():
    """Main migration function."""
    bronze_root = "/home/jacobw/gcs-mount/bronze/stocks/1m"
    gold_root = "/home/jacobw/gcs-mount/gold/stocks/1m"
    
    logger.info("Starting updated streaming migration...")
    migrated = skipped = failed = 0
    start_time = time.time()
    
    try:
        tickers = [d for d in os.listdir(bronze_root) if os.path.isdir(os.path.join(bronze_root, d)) and d.isupper()]
        logger.info(f"Found {len(tickers)} tickers")
    except Exception as e:
        logger.error(f"Failed to list tickers: {e}")
        return
    
    for i, ticker in enumerate(tickers):
        if i % 100 == 0:
            logger.info(f"Processing ticker {i+1}/{len(tickers)}: {ticker}")
        
        ticker_path = os.path.join(bronze_root, ticker)
        
        try:
            years = [d for d in os.listdir(ticker_path) if os.path.isdir(os.path.join(ticker_path, d))]
        except:
            continue
            
        for year in years:
            year_path = os.path.join(ticker_path, year)
            try:
                files = [f for f in os.listdir(year_path) if f.endswith('.parquet')]
            except:
                continue
                
            for file in files:
                bronze_path = os.path.join(year_path, file)
                
                # Build gold path
                if '_' in file:
                    date_part = file.split('_')[1]
                    gold_filename = date_part
                else:
                    gold_filename = file
                
                gold_path = os.path.join(gold_root, ticker, year, gold_filename)
                
                if os.path.exists(gold_path):
                    skipped += 1
                    continue
                
                try:
                    bronze_df = pd.read_parquet(bronze_path)
                    if bronze_df.empty: 
                        continue
                    
                    bronze_df = convert_bronze_columns(bronze_df)
                    gold_df = convert_to_gold(bronze_df)
                    if gold_df.empty: 
                        continue
                    
                    os.makedirs(os.path.dirname(gold_path), exist_ok=True)
                    tmp_path = gold_path + ".tmp"
                    gold_df.to_parquet(tmp_path, index=False)
                    os.replace(tmp_path, gold_path)
                    
                    migrated += 1
                    
                except Exception as e:
                    logger.error(f"Failed {bronze_path}: {e}")
                    failed += 1
    
    elapsed = time.time() - start_time
    logger.info(f"Complete: {migrated} migrated, {skipped} skipped, {failed} failed in {elapsed/60:.1f}min")

if __name__ == "__main__":
    main()
