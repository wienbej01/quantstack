#!/usr/bin/env python3
"""
Extract AAPL data from GOLD parquet file for 2024-01-09 09:00-10:00 ET
"""

from datetime import datetime

import pandas as pd
import pytz


def extract_aapl_data():
    """Extract AAPL data for specified date and time range."""

    # Load January 2024 data
    parquet_path = "/home/jacobw/gcs-mount/gold/stocks/1m/AAPL/2024/2024-01.parquet"

    print(f"📂 Loading data from: {parquet_path}")

    try:
        # Load parquet file
        df = pd.read_parquet(parquet_path)
        print(f"✅ Loaded {len(df)} total records for January 2024")

        # Check column structure
        print(f"📊 Columns: {list(df.columns)}")
        print(f"📅 Date range: {df['ts'].min()} to {df['ts'].max()}")

        # Convert timestamp to ET for display
        et_tz = pytz.timezone("US/Eastern")

        # Define target date and time range in ET
        target_date = "2024-01-09"
        # GOLD data only has regular session (09:30-15:59 ET), so use earliest available
        start_time_et = "09:30:00"
        end_time_et = (
            "09:45:00"  # Show first 15 minutes as closest to requested 09:15-09:25
        )

        # Create datetime strings in ET and convert to UTC
        start_et_str = f"{target_date} {start_time_et}"
        end_et_str = f"{target_date} {end_time_et}"

        # Parse as ET and convert to UTC
        start_et = et_tz.localize(datetime.strptime(start_et_str, "%Y-%m-%d %H:%M:%S"))
        end_et = et_tz.localize(datetime.strptime(end_et_str, "%Y-%m-%d %H:%M:%S"))

        # Convert to UTC for filtering
        start_utc = start_et.astimezone(pytz.UTC)
        end_utc = end_et.astimezone(pytz.UTC)

        print("\n🎯 Extracting data for:")
        print(f"   Date: {target_date}")
        print("   Requested: 09:15-09:25 ET")
        print(
            f"   Available: {start_time_et} - {end_time_et} (closest possible in GOLD dataset)"
        )
        print(f"   Time Range (UTC): {start_utc} - {end_utc}")
        print(
            "\n📝 IMPORTANT: GOLD dataset only contains regular trading hours (09:30-15:59 ET)"
        )
        print(
            "   No pre-market (04:00-09:30 ET) or after-hours (16:00-20:00 ET) data available"
        )

        # Convert df['ts'] to datetime for comparison
        df["ts_datetime"] = pd.to_datetime(df["ts"], unit="ns", utc=True)

        # Filter data for the specified time range
        mask = (df["ts_datetime"] >= start_utc) & (df["ts_datetime"] < end_utc)
        filtered_data = df[mask].copy()

        print(f"\n📈 Found {len(filtered_data)} records in specified time range")

        if len(filtered_data) == 0:
            print("❌ No data found in the specified range")
            return None

        # Convert UTC timestamps back to ET for display
        filtered_data["ts_et"] = pd.to_datetime(
            filtered_data["ts"], unit="ns", utc=True
        ).dt.tz_convert("US/Eastern")

        # Format for display
        display_df = filtered_data[
            ["ts_et", "open", "high", "low", "close", "volume"]
        ].copy()
        display_df["ts_et"] = display_df["ts_et"].dt.strftime("%Y-%m-%d %H:%M:%S %Z")
        display_df = display_df.rename(
            columns={
                "ts_et": "Timestamp (ET)",
                "open": "Open",
                "high": "High",
                "low": "Low",
                "close": "Close",
                "volume": "Volume",
            }
        )

        # Display as formatted table
        print(f"\n📊 AAPL Data for {target_date} {start_time_et} - {end_time_et} ET:")
        print("=" * 100)

        # Format numbers for better readability
        pd.set_option("display.float_format", "{:.2f}".format)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 120)
        pd.set_option("display.colheader_justify", "center")

        print(display_df.to_string(index=False))
        print("=" * 100)

        # Summary statistics
        print("\n📈 Summary Statistics:")
        print(
            f"   Price Range: ${display_df['Low'].min():.2f} - ${display_df['High'].max():.2f}"
        )
        print(f"   Open Price: ${display_df.iloc[0]['Open']:.2f}")
        print(f"   Close Price: ${display_df.iloc[-1]['Close']:.2f}")
        print(
            f"   Net Change: ${display_df.iloc[-1]['Close'] - display_df.iloc[0]['Open']:.2f}"
        )
        print(f"   Total Volume: {display_df['Volume'].sum():,}")
        print(f"   Avg Volume: {display_df['Volume'].mean():,.0f}")

        # Save to CSV
        output_file = "aapl_2024-01-09_0930-0945_et.csv"
        display_df.to_csv(output_file, index=False)
        print(f"\n💾 Data saved to: {output_file}")

        return display_df

    except Exception as e:
        print(f"❌ Error: {e}")
        return None


if __name__ == "__main__":
    result = extract_aapl_data()
