#!/usr/bin/env python3
"""Export L2 data for ML training."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from qx_l2 import L2Storage, load_config


def main():
    parser = argparse.ArgumentParser(description="Export L2 training dataset")
    parser.add_argument("--output", required=True, help="Output parquet file path")
    parser.add_argument("--start-date", help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (YYYY-MM-DD)")
    parser.add_argument("--symbols", nargs="+", help="Filter by symbols")
    parser.add_argument(
        "--features-only", action="store_true", help="Export features only (not raw)"
    )
    parser.add_argument("--config", default="configs/default.yaml", help="Config file")

    args = parser.parse_args()

    # Load config and create storage
    config = load_config(args.config)
    storage = L2Storage(config)

    # Export
    print(f"Exporting L2 data to {args.output}...")
    result = storage.export_training_dataset(
        output_path=args.output,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=args.symbols,
        features_only=args.features_only,
    )

    if "error" in result:
        print(f"Error: {result['error']}")
        return 1

    print("\nExport complete:")
    print(f"  Output: {result['output_path']}")
    print(f"  Records: {result['records']:,}")
    print(f"  Symbols: {result['symbols']}")
    print(f"  Date range: {result['date_range']}")
    print(f"  Size: {result['size_mb']:.2f} MB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
