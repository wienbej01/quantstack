#!/usr/bin/env python3
"""Quick test of pattern backtest."""

import sys
from pathlib import Path

# Setup paths
root = Path("/home/jacobw/quantstack")
sys.path.insert(0, str(root / "sip_pattern_discovery"))
sys.path.insert(0, str(root / "pattern_backtest"))

from src.pattern_parser import parse_patterns_csv

# Test pattern parser
patterns_csv = root / "sip_pattern_discovery/output/patterns_60m.csv"
patterns = parse_patterns_csv(patterns_csv, max_patterns=5)

print(f"Loaded {len(patterns)} patterns:")
for p in patterns:
    print(f"  {p}")
