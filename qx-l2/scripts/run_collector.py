#!/usr/bin/env python3
"""Main L2 collector entry point script."""

import sys
from pathlib import Path

# Add package to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from qx_l2.cli import main

if __name__ == "__main__":
    sys.exit(main())
