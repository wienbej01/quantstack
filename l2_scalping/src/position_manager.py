"""Position Manager for L2 Scalping System.

Manages positions by entry order ID, not by symbol. Each entry order creates
a separate managed position with its own trade_id and TP/SL management.
Multiple concurrent entries for the same symbol are tracked independently.
"""

import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ManagedPosition:
    """Represents a managed position tied to a specific entry order."""

    trade_id: str
    symbol: str
    direction: str  # "long" or "short"
    target_qty: int
    filled_qty: int = 0
    avg_fill_price: float = 0.0
    entry_order_id: int = 0
    tp_order_id: int = 0
    sl_order_id: int = 0
    tp_price: float = 0.0
    sl_price: float = 0.0
    status: str = "PENDING"  # PENDING, OPEN, CLOSING, CLOSED
    tp_sl_placed: bool = False
    last_tp_sl_update: float = 0.0  # timestamp of last TP/SL modification
    entry_fills: list = field(default_factory=list)
    exit_fills: list = field(default_factory=list)


class PositionManager:
    """Manages positions by ENTRY ORDER, not by symbol.

    Each entry order gets its own trade_id and independent TP/SL management.
    Multiple concurrent entries for same symbol are tracked separately.
    """

    TP_SL_UPDATE_BUFFER_SECONDS = 2.0  # Min time between TP/SL adjustments

    def __init__(self):
        # Key: entry_order_id -> ManagedPosition
        self.positions: dict[int, ManagedPosition] = {}
        # Index: symbol -> list of entry_order_ids (for lookup)
        self.symbol_index: dict[str, list[int]] = defaultdict(list)

    def create_position(
        self,
        entry_order_id: int,
        trade_id: str,
        symbol: str,
        direction: str,
        target_qty: int,
    ) -> ManagedPosition:
        """Create new position tied to specific entry order."""
        pos = ManagedPosition(
            trade_id=trade_id,
            symbol=symbol,
            direction=direction,
            target_qty=target_qty,
            entry_order_id=entry_order_id,
        )
        self.positions[entry_order_id] = pos
        self.symbol_index[symbol].append(entry_order_id)
        return pos

    def get_position_by_order(self, order_id: int) -> Optional[ManagedPosition]:
        """Get position by entry order ID."""
        return self.positions.get(order_id)

    def get_positions_for_symbol(self, symbol: str) -> list[ManagedPosition]:
        """Get all positions (including pending) for a symbol."""
        return [
            self.positions[oid]
            for oid in self.symbol_index.get(symbol, [])
            if oid in self.positions
        ]

    def has_open_position(self, symbol: str) -> bool:
        """Check if any OPEN position exists for symbol."""
        return any(p.status == "OPEN" for p in self.get_positions_for_symbol(symbol))

    def has_pending_entry(self, symbol: str) -> bool:
        """Check if any PENDING entry exists for symbol."""
        return any(p.status == "PENDING" for p in self.get_positions_for_symbol(symbol))

    def count_pending_entries(self, symbol: str) -> int:
        """Count pending entry orders for symbol."""
        return sum(
            1 for p in self.get_positions_for_symbol(symbol) if p.status == "PENDING"
        )

    def update_fill(
        self, entry_order_id: int, fill_qty: int, fill_price: float
    ) -> Optional[ManagedPosition]:
        """Update position with new fill data."""
        pos = self.positions.get(entry_order_id)
        if not pos:
            return None

        # Calculate new weighted average
        old_qty = pos.filled_qty
        new_qty = old_qty + fill_qty

        if old_qty == 0:
            pos.avg_fill_price = fill_price
        else:
            pos.avg_fill_price = (
                pos.avg_fill_price * old_qty + fill_price * fill_qty
            ) / new_qty

        pos.filled_qty = new_qty

        # Update status if fully filled
        if pos.filled_qty >= pos.target_qty:
            pos.status = "OPEN"

        return pos

    def can_update_tp_sl(self, entry_order_id: int) -> bool:
        """Check if TP/SL can be updated (respects time buffer)."""
        pos = self.positions.get(entry_order_id)
        if not pos or not pos.tp_sl_placed:
            return True

        return (time.time() - pos.last_tp_sl_update) >= self.TP_SL_UPDATE_BUFFER_SECONDS

    def mark_tp_sl_updated(self, entry_order_id: int) -> None:
        """Mark TP/SL as updated with current timestamp."""
        pos = self.positions.get(entry_order_id)
        if pos:
            pos.last_tp_sl_update = time.time()

    def close_position(self, entry_order_id: int) -> Optional[ManagedPosition]:
        """Mark position as closed and remove from tracking."""
        pos = self.positions.get(entry_order_id)
        if not pos:
            return None

        pos.status = "CLOSED"

        # Remove from symbol index
        if pos.symbol in self.symbol_index:
            try:
                self.symbol_index[pos.symbol].remove(entry_order_id)
                if not self.symbol_index[pos.symbol]:
                    del self.symbol_index[pos.symbol]
            except ValueError:
                pass

        # Remove from positions
        del self.positions[entry_order_id]

        return pos

    def get_net_position(self, symbol: str) -> int:
        """Get net position quantity for symbol (sum of all open positions)."""
        net = 0
        for pos in self.get_positions_for_symbol(symbol):
            if pos.status in ("OPEN", "CLOSING"):
                multiplier = 1 if pos.direction == "long" else -1
                net += pos.filled_qty * multiplier
        return net

    def __len__(self) -> int:
        """Return number of active positions."""
        return len(self.positions)

    def __repr__(self) -> str:
        """String representation for debugging."""
        return f"PositionManager({len(self.positions)} positions)"
