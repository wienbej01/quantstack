#!/usr/bin/env python3
"""Fast version of improved features for testing - limited date range."""

import logging
from datetime import datetime, time
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Test with recent data only
START_DATE = datetime(2025, 6, 1).date()
END_DATE = datetime(2025, 9, 30).date()

def calculate_improved_features(df_pd):
    """Calculate improved features - all relative."""
    
    # ATR calculation
    df_pd["tr"] = np.maximum(
        df_pd["high"] - df_pd["low"],
        np.maximum(
            abs(df_pd["high"] - df_pd["prev_close"]),
            abs(df_pd["low"] - df_pd["prev_close"])
        )
    )
    df_pd["atr"] = df_pd["tr"].rolling(14, min_periods=1).mean()
    
    # Relative features (no raw prices)
    df_pd["gap_pct"] = (df_pd["open"] - df_pd["prev_close"]) / df_pd["prev_close"]
    df_pd["price_vs_open"] = (df_pd["close"] - df_pd["open"]) / df_pd["open"]
    df_pd["range_pct"] = (df_pd["high"] - df_pd["low"]) / df_pd["close"]
    df_pd["atr_pct"] = df_pd["atr"] / df_pd["close"]
    
    # Time features
    df_pd["hour"] = df_pd["timestamp"].dt.hour
    df_pd["is_morning"] = (df_pd["hour"] < 12).astype(int)
    df_pd["minutes_from_open"] = (df_pd["timestamp"] - df_pd["timestamp"].iloc[0]).dt.total_seconds() / 60
    
    # Momentum
    df_pd["return_5m"] = df_pd["close"].pct_change(5)
    df_pd["return_10m"] = df_pd["close"].pct_change(10)
    
    # Volume (relative)
    df_pd["volume_vs_avg"] = df_pd["volume"] / df_pd["volume"].mean()
    
    return df_pd


def calculate_atr_labels(df_pd):
    """ATR-normalized labels."""
    df_pd["forward_return"] = df_pd["close"].pct_change(-5)
    df_pd["atr_threshold"] = df_pd["atr"] / df_pd["close"] * 1.5
    
    df_pd["label_long"] = (df_pd["forward_return"] > df_pd["atr_threshold"]).astype(int)
    df_pd["label_short"] = (df_pd["forward_return"] < -df_pd["atr_threshold"]).astype(int)
    
    # Entry/exit with delay
    df_pd["entry_timestamp"] = df_pd["timestamp"].shift(-1)
    df_pd["exit_timestamp"] = df_pd["timestamp"].shift(-6)
    df_pd["entry_close"] = df_pd["close"].shift(-1)
    df_pd["exit_close"] = df_pd["close"].shift(-6)
    
    return df_pd


def main():
    logging.info("FAST IMPROVED FEATURES - Testing")
    
    # Use existing features as base and modify
    existing_path = Path("run/intraday_features_rolling/features.parquet")
    if not existing_path.exists():
        logging.error("Need existing features first")
        return
    
    output_dir = Path("run/intraday_features_improved")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Load existing features for recent period
    logging.info("Loading existing features...")
    df = pl.read_parquet(existing_path)
    
    # Filter to test period - use last 3 months of available data
    max_date = df["date"].max()
    min_date = max_date - pl.duration(days=90)  # Last 3 months
    
    df = df.filter(pl.col("date") >= min_date)
    
    logging.info(f"Filtered to {len(df):,} rows ({min_date} to {max_date})")
    
    if len(df) == 0:
        logging.error("No data in test period")
        return
    
    # Convert to pandas for processing
    df_pd = df.to_pandas()
    
    # Process by symbol-date
    all_improved = []
    processed = 0
    
    for (symbol, date), group in df_pd.groupby(["symbol", "date"]):
        if len(group) < 50:
            continue
        
        try:
            group = group.sort_values("timestamp").copy()
            
            # Get previous close (simplified - use first bar's close)
            group["prev_close"] = group["close"].iloc[0]
            
            # Apply improvements
            group = calculate_improved_features(group)
            group = calculate_atr_labels(group)
            
            # Filter valid rows
            group = group.dropna(subset=["entry_timestamp", "exit_timestamp"])
            
            # Convert date to date object for comparison
            target_date = pd.to_datetime(date).date() if not isinstance(date, type(pd.to_datetime("2025-01-01").date())) else date
            
            group = group[
                (pd.to_datetime(group["entry_timestamp"]).dt.date == target_date) &
                (pd.to_datetime(group["exit_timestamp"]).dt.date == target_date)
            ]
            
            if len(group) > 0:
                all_improved.append(group)
                processed += 1
                
                if processed % 50 == 0:
                    logging.info(f"Processed {processed} symbol-dates")
                
        except Exception as e:
            logging.warning(f"Error processing {symbol} {date}: {e}")
    
    if not all_improved:
        logging.error("No improved features generated")
        return
    
    # Combine
    combined_df = pd.concat(all_improved, ignore_index=True)
    
    # Save
    output_path = output_dir / "features.parquet"
    combined_df.to_parquet(output_path, index=False)
    
    logging.info("=" * 60)
    logging.info("IMPROVED FEATURES COMPLETE")
    logging.info("=" * 60)
    logging.info(f"Rows: {len(combined_df):,}")
    logging.info(f"Symbols: {combined_df['symbol'].nunique()}")
    logging.info(f"Date range: {combined_df['date'].min()} to {combined_df['date'].max()}")
    
    # Label rates
    long_rate = combined_df["label_long"].mean() * 100
    short_rate = combined_df["label_short"].mean() * 100
    logging.info(f"Label rates: Long {long_rate:.2f}%, Short {short_rate:.2f}%")
    
    # Check for raw price features
    feature_cols = [c for c in combined_df.columns if c not in [
        "timestamp", "date", "symbol", "session_id", "bar_index",
        "entry_timestamp", "exit_timestamp", "entry_close", "exit_close",
        "forward_return", "label_long", "label_short", "atr_threshold",
        "open", "high", "low", "close", "volume", "atr", "tr", "prev_close"
    ]]
    
    price_features = [c for c in feature_cols if any(x in c.lower() for x in ["vwap_session", "first_open", "prev_session_close"])]
    if price_features:
        logging.warning(f"Raw price features: {price_features}")
    else:
        logging.info("✓ No raw price features")
    
    logging.info(f"Features: {len(feature_cols)}")
    logging.info(f"Output: {output_path}")


if __name__ == "__main__":
    main()
