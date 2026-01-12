"""Multi-strategy pattern-based trading policy for qx-backtest."""

import sys
from pathlib import Path
from typing import Any

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "quantstack"))

# Import only what we need to avoid dependency issues
from qx_backtest.policies.base import Policy

from .pattern_parser import PatternRule, parse_strategies_yaml
from .rule_evaluator import RuleEvaluator


class PatternMultiPolicy(Policy):
    """Multi-strategy trading policy based on discovered patterns."""

    def __init__(
        self,
        strategies_yaml: Path,
        position_size: int = 100,
        horizon_minutes: int = 180,
    ):
        """Initialize multi-strategy pattern policy.

        Args:
            strategies_yaml: Path to strategies YAML file
            position_size: Fixed position size in shares
            horizon_minutes: Exit horizon in minutes
        """
        super().__init__(name="PatternMultiPolicy")

        self.position_size = position_size
        self.horizon_minutes = horizon_minutes

        # Load strategies
        self.strategies: list[PatternRule] = parse_strategies_yaml(strategies_yaml)

        # Create evaluators for each strategy
        self.evaluators: dict[str, RuleEvaluator] = {}
        for strategy in self.strategies:
            self.evaluators[strategy.method_id] = RuleEvaluator(strategy.rule_string)

        # Track entry bars for time-based exits per strategy
        self.entry_bars: dict[str, dict[str, int]] = (
            {}
        )  # strategy_id -> symbol -> entry bar count
        self.bar_count: dict[str, int] = {}  # symbol -> current bar count

        # Initialize entry tracking for each strategy
        for strategy in self.strategies:
            self.entry_bars[strategy.method_id] = {}

        print(f"Loaded {len(self.strategies)} strategies:")
        for strategy in self.strategies:
            print(f"  - {strategy.method_id}: {strategy.rule_string}")

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

        # Check for exits (time-based) for each strategy
        for strategy in self.strategies:
            strategy_id = strategy.method_id
            position = self.get_position(symbol, strategy_id)

            if position is not None and symbol in self.entry_bars[strategy_id]:
                bars_held = (
                    self.bar_count[symbol] - self.entry_bars[strategy_id][symbol]
                )

                if bars_held >= self.horizon_minutes:
                    # Exit at market
                    exit_side = "SELL" if position.quantity > 0 else "BUY"

                    if hasattr(self.engine, "order_factory"):
                        order = self.engine.order_factory.create_market_order(
                            symbol=symbol,
                            side=exit_side,
                            quantity=abs(position.quantity),
                            strategy_id=strategy_id,
                        )
                    else:
                        # Fallback
                        order = {
                            "symbol": symbol,
                            "side": exit_side,
                            "quantity": abs(position.quantity),
                            "strategy_id": strategy_id,
                            "order_type": "MARKET",
                        }

                    self.submit_order(order)
                    del self.entry_bars[strategy_id][symbol]

        # Check for entries (no position) for each strategy
        for strategy in self.strategies:
            strategy_id = strategy.method_id
            position = self.get_position(symbol, strategy_id)

            if position is None:
                # Evaluate strategy pattern
                evaluator = self.evaluators[strategy_id]
                if evaluator.evaluate(bar):
                    # Signal triggered - enter at next bar open
                    side = "BUY" if strategy.direction == "LONG" else "SELL"

                    # Create order using engine's order factory
                    if hasattr(self.engine, "order_factory"):
                        order = self.engine.order_factory.create_market_order(
                            symbol=symbol,
                            side=side,
                            quantity=self.position_size,
                            strategy_id=strategy_id,
                        )
                    else:
                        # Fallback - create simple order dict
                        order = {
                            "symbol": symbol,
                            "side": side,
                            "quantity": self.position_size,
                            "strategy_id": strategy_id,
                            "order_type": "MARKET",
                        }

                    self.submit_order(order)
                    self.entry_bars[strategy_id][symbol] = self.bar_count[symbol]

    def get_position(self, symbol: str, strategy_id: str = None):
        """Get position for symbol and strategy.

        Args:
            symbol: Symbol to check
            strategy_id: Strategy identifier (if None, checks overall position)

        Returns:
            Position object or None
        """
        if self.engine is None:
            return None

        # For multi-strategy, we need to track positions per strategy
        # This is a simplified version - in practice you'd need more sophisticated tracking
        if strategy_id:
            # Check if we have any position for this symbol under this strategy
            # This would need to be implemented based on your order tracking system
            return self.engine.portfolio.positions.get(f"{symbol}_{strategy_id}")
        else:
            return self.engine.portfolio.positions.get(symbol)

    def on_end(self) -> None:
        """Close all positions at end of backtest."""
        if self.engine is None:
            return

        # Close positions for each strategy
        for strategy in self.strategies:
            strategy_id = strategy.method_id
            for symbol, position in self.engine.portfolio.positions.items():
                if position.quantity != 0 and symbol.endswith(f"_{strategy_id}"):
                    actual_symbol = symbol.replace(f"_{strategy_id}", "")
                    exit_side = "SELL" if position.quantity > 0 else "BUY"

                    if hasattr(self.engine, "order_factory"):
                        order = self.engine.order_factory.create_market_order(
                            symbol=actual_symbol,
                            side=exit_side,
                            quantity=abs(position.quantity),
                            strategy_id=strategy_id,
                        )
                    else:
                        order = {
                            "symbol": actual_symbol,
                            "side": exit_side,
                            "quantity": abs(position.quantity),
                            "strategy_id": strategy_id,
                            "order_type": "MARKET",
                        }

                    self.submit_order(order)
