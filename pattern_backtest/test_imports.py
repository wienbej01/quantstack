#!/usr/bin/env python3
"""Simple test to check imports."""

import sys
from pathlib import Path

# Add paths
script_dir = Path(__file__).parent.parent
sip_discovery_dir = script_dir.parent / "sip_pattern_discovery"

sys.path.insert(0, str(script_dir))
sys.path.insert(0, str(sip_discovery_dir))
sys.path.insert(0, str(sip_discovery_dir / "src"))

print("Testing imports...")

try:
    print("✅ data_loader imported")
except Exception as e:
    print(f"❌ data_loader failed: {e}")

try:
    print("✅ feature_pipeline imported")
except Exception as e:
    print(f"❌ feature_pipeline failed: {e}")

try:
    print("✅ pattern_parser imported")
except Exception as e:
    print(f"❌ pattern_parser failed: {e}")

try:
    print("✅ yaml imported")
except Exception as e:
    print(f"❌ yaml failed: {e}")

print("All basic imports successful!")
