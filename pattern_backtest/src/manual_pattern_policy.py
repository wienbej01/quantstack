"""Manual pattern policy for backtesting hand-coded rules."""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "quantstack"))

from qx_backtest.order import OrderFactory
from qx_backtest.policies.base import Policy

from .manual_patterns import MANUAL_PATTERNS, evaluate_all_manual_patterns


class ManualPatternPolicy(Policy):
    """Trading policy based on manually coded patterns.

    NOTE: 180-minute horizon from power hour entries spans overnight.
    Entry at 3:30 PM + 180 bars = ~12:00 PM next trading day.
    This is an overnight hold strategy, not intraday.
    """

    def __init__(
        self,
        position_size: int = 100,
        horizon_minutes: int = 180,
        method_id: str = "manual_patterns_180m_overnight",
    ):
        """Initialize manual pattern policy.

        Args:
            position_size: Fixed position size in shares
            horizon_minutes: Exit horizon in minutes (180 = next day noon for power hour entries)
            method_id: Identifier for this method
        """
        super().__init__(name=f"ManualPatternPolicy_{method_id}")

        self.position_size = position_size
        self.horizon_minutes = horizon_minutes
        self.method_id = method_id

        # Track entry bars for time-based exits
        self.entry_bars: dict[str, int] = {}
        self.bar_count: dict[str, int] = {}

        print(f"Loaded {len(MANUAL_PATTERNS)} manual patterns for method '{method_id}'")
        print("NOTE: 180m horizon from power hour = overnight hold to next day ~noon")
        for pattern_id, data in MANUAL_PATTERNS.items():
            print(f"  - {pattern_id}: {data['description']} (lift={data['lift']:.2f}x)")

    def process_bar(self, bar: dict[str, Any]) -> None:
        """Process a single bar.

        Args:
            bar: Bar data with features
        """
        symbol = bar["symbol"]

        # Update bar count
        if symbol not in self.bar_count:
            self.bar_count[symbol] = 0
        self.bar_count[symbol] += 1

        # Check for exits (time-based)
        position = self.get_position(symbol)
        if position is not None and symbol in self.entry_bars:
            bars_held = self.bar_count[symbol] - self.entry_bars[symbol]

            if bars_held >= self.horizon_minutes:
                # Exit at market
                order = OrderFactory.market_order(
                    symbol=symbol,
                    quantity=abs(position.quantity),
                    side="SELL" if position.quantity > 0 else "BUY",
                    strategy_id=f"{self.strategy_id}_{self.method_id}",
                )
                self.submit_order(order)
                del self.entry_bars[symbol]
                return

        # Check for entries (no position)
        if position is None:
            # Evaluate all manual patterns
            matches = evaluate_all_manual_patterns(bar)

            if matches:
                # Signal triggered - enter at next bar open
                order = OrderFactory.market_order(
                    symbol=symbol,
                    quantity=self.position_size,
                    side="BUY",
                    strategy_id=f"{self.strategy_id}_{self.method_id}",
                )
                self.submit_order(order)
                self.entry_bars[symbol] = self.bar_count[symbol]

    def on_end(self) -> None:
        """Close all positions at end of backtest."""
        if self.engine is None:
            return

        for symbol, position in self.engine.portfolio.positions.items():
            if position.quantity != 0:
                order = OrderFactory.market_order(
                    symbol=symbol,
                    quantity=abs(position.quantity),
                    side="SELL" if position.quantity > 0 else "BUY",
                    strategy_id=f"{self.strategy_id}_{self.method_id}",
                )
                self.submit_order(order)
