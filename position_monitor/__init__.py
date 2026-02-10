"""
Position Monitor - Real-time IBKR position and P&L tracking.

Queries IBKR Gateway every 60 seconds and writes positions to /tmp/positions.json
for consumption by Conky display widget.
"""

from position_monitor.models import PnLData, Position
from position_monitor.monitor import PositionMonitor

__all__ = ["Position", "PnLData", "PositionMonitor"]
__version__ = "1.0.0"
