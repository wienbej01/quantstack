"""Rolling intraday VWAP calculator."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VWAPState:
    """Per-symbol VWAP state."""

    cum_tp_vol: float = 0.0  # sum(typical_price * volume)
    cum_vol: float = 0.0     # sum(volume)
    vwap: float = 0.0


class VWAPCalculator:
    """Intraday VWAP calculator with daily reset."""

    def __init__(self):
        self._state: dict[str, VWAPState] = {}

    def reset(self, symbol: str | None = None) -> None:
        """Reset VWAP state. If symbol is None, reset all."""
        if symbol is None:
            self._state.clear()
        elif symbol in self._state:
            self._state[symbol] = VWAPState()

    def reset_all(self) -> None:
        """Reset all symbols (call at market open)."""
        self._state.clear()

    def update(self, symbol: str, high: float, low: float, close: float, volume: float) -> float:
        """Update VWAP with new bar data. Returns current VWAP."""
        if symbol not in self._state:
            self._state[symbol] = VWAPState()

        state = self._state[symbol]

        if volume <= 0:
            return state.vwap

        typical_price = (high + low + close) / 3.0
        state.cum_tp_vol += typical_price * volume
        state.cum_vol += volume
        state.vwap = state.cum_tp_vol / state.cum_vol if state.cum_vol > 0 else close

        return state.vwap

    def get_vwap(self, symbol: str) -> float | None:
        """Get current VWAP for symbol."""
        state = self._state.get(symbol)
        return state.vwap if state and state.cum_vol > 0 else None

    def get_deviation(self, symbol: str, price: float) -> float | None:
        """Get price deviation from VWAP (price / VWAP)."""
        vwap = self.get_vwap(symbol)
        if vwap is None or vwap == 0:
            return None
        return price / vwap
