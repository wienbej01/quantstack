#!/bin/bash
# L2 VWAP Mean Reversion - Startup Script
# Requires l2-scalping to be running for L2 data

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Activate virtual environment
source /home/jacobw/quantstack/.venv/bin/activate

# Set Python path (include l2_scalping for sip_integration)
export PYTHONPATH="$SCRIPT_DIR/src:/home/jacobw/quantstack:$PYTHONPATH"

# Run the system
exec python src/main.py --config config "$@"
