#!/usr/bin/env python3
"""Update gold data from September 2025 to December 15, 2025."""

import os
import sys
from datetime import date, datetime
from pathlib import Path

# Add R2K ingest to path
r2k_path = Path.home() / "data_download" / "r2k_ingest"
sys.path.insert(0, str(r2k_path.parent))

from r2k_ingest.bronze_to_gold import convert_bronze_to_gold
from r2k_ingest.bronze_writer import backfill_bronze
from r2k_ingest.polygon_client import PolygonClient


def create_update_config():
    """Create config for data update."""
    config = {
        "lookback_years": 1,
        "start_date": "2025-09-01",
        "end_date": "2025-12-15",
        "paths": {
            "bronze_root": "/home/jacobw/quantstack/data/bronze_update",
            "silver_root": "/home/jacobw/quantstack/data/silver_update",
            "gold_root": "/home/jacobw/gcs-mount/gold/stocks/1m",
            "checkpoints_dir": "/home/jacobw/quantstack/data/checkpoints",
            "prefilter_dir": "/home/jacobw/quantstack/data/prefilter",
        },
        "polygon": {
            "api_key": os.getenv("POLYGON_API_KEY"),
            "rate_limit_per_minute": 300,
        },
        "price_band": {"min_price": 5.0, "max_price": 50.0},
        "prefilter_frac_min": 0.8,
    }

    # Save config
    config_path = "/home/jacobw/quantstack/data_update_config.yaml"
    import yaml

    with open(config_path, "w") as f:
        yaml.dump(config, f)

    return config_path


def get_nyse_symbols_for_update():
    """Get NYSE symbols from gold data directory."""
    gold_path = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

    if not gold_path.exists():
        raise RuntimeError(
            "Gold data mount not available at /home/jacobw/gcs-mount/gold/stocks/1m"
        )

    symbols = [p.name for p in gold_path.iterdir() if p.is_dir()]
    print(f"Found {len(symbols)} symbols in gold data for update")
    return symbols


def check_latest_gold_date(symbol: str) -> str:
    """Check latest available date for a symbol in gold data."""
    try:
        symbol_path = Path(f"/home/jacobw/gcs-mount/gold/stocks/1m/{symbol}")

        if not symbol_path.exists():
            return "2025-08-31"  # Before our update range

        # Find latest year directory
        year_dirs = [
            d for d in symbol_path.iterdir() if d.is_dir() and d.name.isdigit()
        ]
        if not year_dirs:
            return "2025-08-31"

        latest_year = max(year_dirs, key=lambda x: int(x.name))

        # Find latest month file
        month_files = list(latest_year.glob("*.parquet"))
        if not month_files:
            return "2025-08-31"

        latest_file = max(month_files, key=lambda x: x.stem)
        latest_month = latest_file.stem  # e.g., "2025-09"

        return latest_month + "-30"  # End of month

    except Exception as e:
        print(f"Error checking {symbol}: {e}")
        return "2025-08-31"


def main():
    """Main data update process."""
    print("🔄 Starting Gold Data Update Process...")

    # Check API key
    if not os.getenv("POLYGON_API_KEY"):
        print("❌ POLYGON_API_KEY not set")
        return

    # Create update config
    config_path = create_update_config()
    print(f"✅ Config created: {config_path}")

    # Get NYSE symbols
    nyse_symbols = get_nyse_symbols_for_update()

    # Check latest data dates
    print("🔍 Checking latest gold data dates...")
    sample_symbols = nyse_symbols[:5]  # Check sample

    for symbol in sample_symbols:
        latest_date = check_latest_gold_date(symbol)
        print(f"   {symbol}: latest data {latest_date}")

    # Create directories
    os.makedirs("/home/jacobw/quantstack/data/bronze_update", exist_ok=True)
    os.makedirs("/home/jacobw/quantstack/data/silver_update", exist_ok=True)
    os.makedirs("/home/jacobw/quantstack/data/checkpoints", exist_ok=True)

    print("\n📋 Update Plan:")
    print(f"   Symbols: {len(nyse_symbols)} NYSE tickers")
    print(f"   Date Range: 2025-09-01 to 2025-12-15")
    print(f"   Bronze → Silver → Gold pipeline")
    print(f"   Uniform timezone: ET")
    print(f"   Fix folder structures")

    # Step 1: Download bronze data
    print("\n1️⃣ Starting bronze data download...")
    try:
        backfill_bronze(config_path)
        print("✅ Bronze download complete")
    except Exception as e:
        print(f"❌ Bronze download failed: {e}")
        return

    # Step 2: Convert to gold
    print("\n2️⃣ Converting bronze to gold...")
    try:
        convert_bronze_to_gold(config_path)
        print("✅ Bronze to gold conversion complete")
    except Exception as e:
        print(f"❌ Bronze to gold failed: {e}")
        return

    print("\n🎉 Gold data update complete!")
    print("   Updated data available for live trading system")


if __name__ == "__main__":
    main()
