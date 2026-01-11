#!/usr/bin/env python3
"""Quick test to find gold data structure."""

from pathlib import Path

gold_dir = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

# Check structure
print("Gold dir exists:", gold_dir.exists())
print("\nTop level:")
for item in sorted(gold_dir.iterdir())[:10]:
    print(f"  {item.name}")

# Check for CCL
ccl_paths = [
    gold_dir / "CCL",
    gold_dir / "1m" / "CCL",
]

for p in ccl_paths:
    if p.exists():
        print(f"\nFound CCL at: {p}")
        print(f"Contents: {list(p.iterdir())[:5]}")
        parquets = list(p.glob("**/*.parquet"))
        print(f"Parquet files (recursive): {len(parquets)}")
        if parquets:
            print(f"Sample: {parquets[0]}")
        break
else:
    print("\nCCL not found in expected locations")
