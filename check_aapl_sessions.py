#!/usr/bin/env python3
"""
Check AAPL trading sessions and time ranges available in GOLD data
"""


import pandas as pd
import pytz


def check_aapl_sessions():
    """Check AAPL trading sessions and available time ranges."""

    # Load January 2024 data
    parquet_path = "/home/jacobw/gcs-mount/gold/stocks/1m/AAPL/2024/2024-01.parquet"

    print(f"📂 Loading data from: {parquet_path}")

    try:
        # Load parquet file
        df = pd.read_parquet(parquet_path)
        print(f"✅ Loaded {len(df)} total records for January 2024")

        # Convert timestamp to ET for display
        et_tz = pytz.timezone("US/Eastern")
        df["ts_et"] = pd.to_datetime(df["ts"], unit="ns", utc=True).dt.tz_convert(
            "US/Eastern"
        )

        # Check unique session IDs and their time ranges
        print("\n📊 Session Analysis:")
        print(f"   Unique sessions: {df['session_id'].nunique()}")

        # Group by session and get time ranges
        session_ranges = (
            df.groupby("session_id")
            .agg({"ts_et": ["min", "max"], "ts": ["min", "max"]})
            .round()
        )

        print("\n🕐 Session Time Ranges (first 10 sessions):")
        for i, (session_id, row) in enumerate(session_ranges.head(10).iterrows()):
            et_min = row[("ts_et", "min")]
            et_max = row[("ts_et", "max")]
            print(f"   Session {session_id}: {et_min} to {et_max}")

        # Check what time the first bar of 2024-01-09 appears
        jan_9_data = df[
            df["ts_et"].dt.date == pd.to_datetime("2024-01-09").date()
        ].copy()

        if len(jan_9_data) > 0:
            print("\n📅 January 9, 2024 Analysis:")
            print(f"   First bar: {jan_9_data['ts_et'].min()}")
            print(f"   Last bar: {jan_9_data['ts_et'].max()}")
            print(f"   Total bars: {len(jan_9_data)}")

            # Check for pre-market data (before 09:30 ET)
            pre_market = jan_9_data[
                jan_9_data["ts_et"].dt.time < pd.to_datetime("09:30:00").time()
            ]
            if len(pre_market) > 0:
                print(f"   Pre-market bars: {len(pre_market)}")
                print(
                    f"   Pre-market range: {pre_market['ts_et'].min()} to {pre_market['ts_et'].max()}"
                )
            else:
                print("   Pre-market bars: 0 (no pre-market data)")

            # Check for post-market data (after 16:00 ET)
            post_market = jan_9_data[
                jan_9_data["ts_et"].dt.time > pd.to_datetime("16:00:00").time()
            ]
            if len(post_market) > 0:
                print(f"   Post-market bars: {len(post_market)}")
                print(
                    f"   Post-market range: {post_market['ts_et'].min()} to {post_market['ts_et'].max()}"
                )
            else:
                print("   Post-market bars: 0 (no post-market data)")
        else:
            print("\n❌ No data found for January 9, 2024")

        # Check overall time range in the dataset
        print("\n📊 Overall Dataset Time Range:")
        print(f"   Earliest: {df['ts_et'].min()}")
        print(f"   Latest: {df['ts_et'].max()}")

        # Check trading hours by looking at unique times
        df["time_only"] = df["ts_et"].dt.time
        unique_times = sorted(df["time_only"].unique())

        print("\n🕐 Trading Hours Available:")
        print(f"   Earliest time: {unique_times[0]}")
        print(f"   Latest time: {unique_times[-1]}")

        # Show sample of times around market open
        open_times = [
            t
            for t in unique_times
            if pd.to_datetime("09:00:00").time()
            <= t
            <= pd.to_datetime("10:00:00").time()
        ]
        print(f"   Times around market open: {open_times[:10]}")

    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    check_aapl_sessions()
