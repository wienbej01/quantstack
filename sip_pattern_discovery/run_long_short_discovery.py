#!/usr/bin/env python3
"""Run pattern discovery for BOTH long and short opportunities."""

import subprocess
import sys
from pathlib import Path

# Run discovery with both UP and DOWN patterns
cmd = [
    sys.executable,
    "discover.py",
    "--start-date",
    "2024-06-01",
    "--end-date",
    "2024-07-31",
    "--horizons",
    "180",
    "--min-lift",
    "3.0",  # Higher quality threshold
    "--min-support",
    "0.01",  # More frequent patterns (1% vs 0.5%)
    "--max-p-value",
    "0.001",  # More significant (0.1% vs 1%)
    "--max-patterns",
    "10",  # Top 10 per direction only
    "--output-dir",
    "output_high_quality",
]

print("Running pattern discovery for BOTH long and short opportunities...")
print(f"Command: {' '.join(cmd)}")
print("This will take ~45 minutes...")

result = subprocess.run(cmd, cwd=Path(__file__).parent)
sys.exit(result.returncode)
