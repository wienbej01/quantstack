#!/usr/bin/env python3
"""Run pattern discovery with t-statistic ranking."""

import subprocess
import sys
from pathlib import Path

cmd = [
    sys.executable,
    "discover.py",
    "--start-date",
    "2024-06-01",
    "--end-date",
    "2024-07-31",
    "--horizons",
    "30,60,90,180",
    "--min-t-stat",
    "3.0",  # 99% confidence
    "--min-expectancy",
    "0.01",  # 0.01% per trade (realistic)
    "--min-trades",
    "50",  # Statistical validity
    "--max-patterns",
    "5",  # Top 5 per direction per horizon
    "--output-dir",
    "output_tstat",
]

print("Running pattern discovery with t-statistic ranking...")
print(f"Command: {' '.join(cmd)}")

result = subprocess.run(cmd, cwd=Path(__file__).parent)
sys.exit(result.returncode)
