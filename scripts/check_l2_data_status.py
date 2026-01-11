#!/usr/bin/env python3
"""
Check L2 data collection status and volume.
"""

import glob
import os
import sqlite3
from pathlib import Path

import pandas as pd


def check_l2_data_status():
    """Check current L2 data collection status."""

    print("=== L2 DATA COLLECTION STATUS ===\n")

    # 1. Check journal database
    journal_path = "/home/jacobw/quantstack/data/l2_maximum/journal.db"
    if os.path.exists(journal_path):
        conn = sqlite3.connect(journal_path)

        # Get collection stats
        stats_query = """
        SELECT 
            symbol,
            COUNT(*) as records,
            MIN(timestamp) as first_record,
            MAX(timestamp) as last_record,
            COUNT(DISTINCT date(timestamp)) as days_collected
        FROM l2_snapshots 
        GROUP BY symbol 
        ORDER BY records DESC
        """

        # Check what's actually in the database
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
        tables = cursor.fetchall()
        print(f"Available tables: {[t[0] for t in tables]}")

        # Check daily_stats table
        try:
            daily_stats = pd.read_sql_query(
                "SELECT * FROM daily_stats ORDER BY date DESC", conn
            )
            print(f"\n--- DAILY COLLECTION STATS ---")
            for _, row in daily_stats.iterrows():
                print(
                    f"  {row['date']}: {row['symbols_collected']} symbols, {row['total_snapshots']:,} snapshots"
                )

            total_snapshots = daily_stats["total_snapshots"].sum()
            print(f"\nTotal snapshots collected: {total_snapshots:,}")

        except Exception as e:
            print(f"Error reading daily_stats: {e}")

        # Check sessions table for symbol details
        try:
            sessions = pd.read_sql_query(
                "SELECT * FROM sessions ORDER BY start_time DESC LIMIT 20", conn
            )
            print(f"\n--- RECENT SESSIONS ---")
            symbol_counts = sessions["symbol"].value_counts()
            print(f"Symbols in recent sessions:")
            for symbol, count in symbol_counts.head(10).items():
                print(f"  {symbol}: {count} sessions")

        except Exception as e:
            print(f"Error reading sessions: {e}")

        conn.close()
    else:
        print("❌ Journal database not found")

    # 2. Check processed features
    features_path = "/home/jacobw/quantstack/data/l2_maximum/features"
    if os.path.exists(features_path):
        print(f"\n--- PROCESSED FEATURES ---")

        # Count by date
        date_dirs = glob.glob(f"{features_path}/date=*")
        print(f"Collection dates: {len(date_dirs)}")

        total_files = 0
        total_size = 0

        for date_dir in sorted(date_dirs):
            date = os.path.basename(date_dir).replace("date=", "")
            symbol_dirs = glob.glob(f"{date_dir}/symbol=*")

            date_files = 0
            date_size = 0

            for symbol_dir in symbol_dirs:
                symbol = os.path.basename(symbol_dir).replace("symbol=", "")
                parquet_files = glob.glob(f"{symbol_dir}/*.parquet")

                for pf in parquet_files:
                    size = os.path.getsize(pf)
                    date_files += 1
                    date_size += size

            total_files += date_files
            total_size += date_size

            print(
                f"  {date}: {len(symbol_dirs)} symbols, {date_files} files, {date_size/1024/1024:.1f} MB"
            )

        print(f"\nTotal: {total_files} parquet files, {total_size/1024/1024:.1f} MB")

    # 3. Check raw data
    raw_path = "/home/jacobw/quantstack/data/l2_maximum/raw"
    if os.path.exists(raw_path):
        print(f"\n--- RAW DATA ---")

        raw_dirs = glob.glob(f"{raw_path}/date=*")
        print(f"Raw collection dates: {len(raw_dirs)}")

        for raw_dir in sorted(raw_dirs)[-3:]:  # Last 3 days
            date = os.path.basename(raw_dir).replace("date=", "")
            symbol_dirs = glob.glob(f"{raw_dir}/symbol=*")

            total_raw_files = 0
            for symbol_dir in symbol_dirs:
                csv_files = glob.glob(f"{symbol_dir}/*.csv")
                total_raw_files += len(csv_files)

            print(f"  {date}: {len(symbol_dirs)} symbols, {total_raw_files} raw files")

    # 4. Sample recent data quality
    print(f"\n--- DATA QUALITY CHECK ---")

    # Find most recent processed data
    recent_features = []
    for date_dir in sorted(date_dirs)[-2:]:  # Last 2 days
        for symbol_dir in glob.glob(f"{date_dir}/symbol=*"):
            parquet_files = glob.glob(f"{symbol_dir}/*.parquet")
            if parquet_files:
                recent_features.extend(parquet_files[:1])  # One file per symbol

    if recent_features:
        print(f"Checking {len(recent_features)} recent feature files...")

        total_records = 0
        sample_df = None

        for pf in recent_features[:3]:  # Check first 3 files
            try:
                df = pd.read_parquet(pf)
                total_records += len(df)
                if sample_df is None:
                    sample_df = df

                symbol = pf.split("symbol=")[1].split("/")[0]
                print(f"  {symbol}: {len(df)} records, {len(df.columns)} features")
            except Exception as e:
                print(f"  Error reading {pf}: {e}")

        if sample_df is not None:
            print(f"\nSample features: {list(sample_df.columns)[:10]}...")
            print(
                f"Time range: {sample_df['ts_utc'].min()} to {sample_df['ts_utc'].max()}"
            )

    return {
        "total_symbols": len(stats_df) if "stats_df" in locals() else 0,
        "total_records": stats_df["records"].sum() if "stats_df" in locals() else 0,
        "collection_days": len(date_dirs) if "date_dirs" in locals() else 0,
        "processed_files": total_files if "total_files" in locals() else 0,
        "data_size_mb": total_size / 1024 / 1024 if "total_size" in locals() else 0,
    }


if __name__ == "__main__":
    stats = check_l2_data_status()

    print(f"\n=== SUMMARY ===")
    print(f"Symbols collected: {stats['total_symbols']}")
    print(f"Total L2 records: {stats['total_records']:,}")
    print(f"Collection days: {stats['collection_days']}")
    print(f"Processed files: {stats['processed_files']}")
    print(f"Data size: {stats['data_size_mb']:.1f} MB")
