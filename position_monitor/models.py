"""
Data models for position monitoring.
"""

from dataclasses import dataclass
from typing import List


@dataclass
class Position:
    """Represents an open trading position."""

    symbol: str
    quantity: int
    avg_price: float
    current_price: float
    unrealized_pnl: float
    market_value: float

    @property
    def pnl_display(self) -> str:
        """Format P&L for display."""
        if self.unrealized_pnl >= 0:
            return f"+${self.unrealized_pnl:.2f}"
        return f"-${abs(self.unrealized_pnl):.2f}"

    @property
    def pnl_value(self) -> str:
        """Format P&L value without dollar sign (for JSON)."""
        if self.unrealized_pnl >= 0:
            return f"+{self.unrealized_pnl:.2f}"
        return f"{self.unrealized_pnl:.2f}"

    @property
    def color(self) -> str:
        """Get color code based on P&L."""
        if self.unrealized_pnl > 0:
            return "#00FF00"  # Green
        elif self.unrealized_pnl < 0:
            return "#FF3333"  # Red
        return "#FFFF00"  # Yellow


@dataclass
class PnLData:
    """Represents daily P&L summary."""

    daily_pnl: float
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0

    @property
    def daily_display(self) -> str:
        """Format daily P&L for display."""
        if self.daily_pnl >= 0:
            return f"+${self.daily_pnl:.2f}"
        return f"-${abs(self.daily_pnl):.2f}"

    @property
    def daily_value(self) -> str:
        """Format daily P&L value with dollar sign (for JSON)."""
        if self.daily_pnl >= 0:
            return f"+${self.daily_pnl:.2f}"
        return f"-${abs(self.daily_pnl):.2f}"

    @property
    def color(self) -> str:
        """Get color code based on P&L."""
        if self.daily_pnl > 0:
            return "#00FF00"  # Green
        elif self.daily_pnl < 0:
            return "#FF3333"  # Red
        return "#FFFF00"  # Yellow


@dataclass
class PositionsOutput:
    """Output format for /tmp/positions.json."""

    positions: List[dict]
    daily_pnl: str
    daily_color: str
    market_hours: bool

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "positions": self.positions,
            "daily_pnl": self.daily_pnl,
            "daily_color": self.daily_color,
            "market_hours": self.market_hours,
        }
