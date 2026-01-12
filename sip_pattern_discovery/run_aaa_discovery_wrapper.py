#!/usr/bin/env python3
"""
Run AAA pattern discovery with all filters enabled.
Replaces run_long_short_discovery.py with AAA system.
"""

import subprocess
import sys
from pathlib import Path

def main():
    """Run AAA discovery pipeline."""
    
    script_path = Path(__file__).parent / "discover_aaa.py"
    
    # Default parameters for AAA discovery
    cmd = [
        "python3",
        str(script_path),
        "--start-date", "2024-01-01",
        "--end-date", "2024-12-31",
        "--horizons", "30,60,90,180",
        "--config", "config/aaa_config.yaml",
        "--output-dir", "output_aaa",
        "--use-aaa-scoring",  # Enable AAA scoring
    ]
    
    print("=" * 80)
    print("RUNNING AAA PATTERN DISCOVERY")
    print("=" * 80)
    print("Command:", " ".join(cmd))
    print("=" * 80)
    print()
    
    # Run the discovery
    result = subprocess.run(cmd, cwd=Path(__file__).parent)
    
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
