#!/usr/bin/env python3
"""Analyze L2 data quality and statistics."""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from qx_l2 import L2Journal, L2Storage, load_config


def main():
    parser = argparse.ArgumentParser(description="Analyze L2 data")
    parser.add_argument("--date", help="Analyze specific date (YYYY-MM-DD)")
    parser.add_argument("--config", default="configs/default.yaml", help="Config file")

    args = parser.parse_args()

    config = load_config(args.config)
    storage = L2Storage(config)
    journal = L2Journal(config)

    print("=" * 60)
    print("L2 DATA ANALYSIS REPORT")
    print("=" * 60)

    # Storage stats
    stats = storage.get_stats()
    print("\nStorage Statistics:")
    print(f"  Raw files: {stats['raw_files']}")
    print(f"  Feature files: {stats['feature_files']}")
    print(f"  Total size: {stats['total_size_mb']:.2f} MB")
    print(f"  Est. records: {stats['est_records']:,}")
    print(f"  Symbols: {stats['symbols']}")

    # Daily summary
    if args.date:
        summary = journal.get_daily_summary(args.date)
        print(f"\nDaily Summary ({args.date}):")
        print(f"  Sessions: {summary['sessions']}")
        print(f"  Records: {summary['records']:,}")
        print(f"  Depth rate: {summary['depth_rate']:.1%}")
        print(f"  Avg spread: {summary['avg_spread']:.4f}")
        print(f"  Errors: {summary['errors']}")

    # ML readiness
    target_records = 50000
    current_records = stats["est_records"]
    progress = current_records / target_records * 100

    print("\nML Training Readiness:")
    print(f"  Current: {current_records:,} records")
    print(f"  Target: {target_records:,} records")
    print(f"  Progress: {progress:.1f}%")

    if progress >= 100:
        print("  Status: ✅ Ready for ML training")
    elif progress >= 50:
        print("  Status: 🟡 Partially ready")
    else:
        print("  Status: 🔴 More data needed")

    return 0


if __name__ == "__main__":
    sys.exit(main())
