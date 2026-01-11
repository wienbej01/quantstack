"""Pattern-based trading policy for qx-backtest."""

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "quantstack"))

from qx_backtest.order import OrderFactory
from qx_backtest.policies.base import Policy

from .pattern_parser import PatternRule, parse_patterns_csv
from .rule_evaluator import RuleEvaluator


class PatternPolicy(Policy):
    """Trading policy based on discovered patterns."""

    def __init__(
        self,
        patterns_csv: Path,
        position_size: int = 100,
        min_lift: float = 2.0,
        max_patterns: int = 20,
        horizon_minutes: int = 60,
        method_id: str = "pattern_discovery",
    ):
        """Initialize pattern policy.

        Args:
            patterns_csv: Path to patterns CSV file
            position_size: Fixed position size in shares
            min_lift: Minimum lift threshold
            max_patterns: Maximum patterns to trade
            horizon_minutes: Exit horizon in minutes
            method_id: Identifier for this method
        """
        super().__init__(name=f"PatternPolicy_{method_id}")

        self.position_size = position_size
        self.horizon_minutes = horizon_minutes
        self.method_id = method_id

        # Load patterns
        self.patterns: list[PatternRule] = parse_patterns_csv(
            patterns_csv,
            min_lift=min_lift,
            max_patterns=max_patterns,
            method_id=method_id,
        )

        # Create evaluators
        self.evaluators = [RuleEvaluator(p.rule_string) for p in self.patterns]

        # Track entry bars for time-based exits
        self.entry_bars: dict[str, int] = {}  # symbol -> entry bar count
        self.bar_count: dict[str, int] = {}  # symbol -> current bar count

        print(f"Loaded {len(self.patterns)} patterns for method '{method_id}'")

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
            # Evaluate all patterns
            for pattern, evaluator in zip(self.patterns, self.evaluators):
                if evaluator.evaluate(bar):
                    # Signal triggered - enter at next bar open
                    # Note: In backtest, this will be filled at current bar close
                    # or next bar open depending on filler implementation
                    order = OrderFactory.market_order(
                        symbol=symbol,
                        quantity=self.position_size,
                        side="BUY",
                        strategy_id=f"{self.strategy_id}_{self.method_id}",
                    )
                    self.submit_order(order)
                    self.entry_bars[symbol] = self.bar_count[symbol]
                    break  # Only one entry per bar

    def on_end(self) -> None:
        """Close all positions at end of backtest."""
        # Get all open positions
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
