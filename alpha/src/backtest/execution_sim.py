"""L2-based execution simulation for realistic fills.

Models market impact and slippage using order book depth:
- Walk the book to compute fill price
- Model latency (50-100ms retail)
- Calculate slippage from available depth

This provides more realistic fill prices than simple percentage slippage.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class FillResult:
    """Result of simulating a fill."""
    fill_price: float
    slippage_bps: float  # Slippage in basis points
    walked_levels: int  # How many levels were consumed
    fill_time_ms: int  # Time to fill (latency)
    partially_filled: bool  # True if order couldn't be fully filled


class L2ExecutionSimulator:
    """Simulate order execution using L2 order book data.

    Models:
    1. Latency: Signal to execution delay (50-100ms for retail)
    2. Book walking: Consuming multiple levels impacts price
    3. Market impact: Large orders move price against them
    """

    def __init__(
        self,
        latency_ms: int = 75,
        slippage_model: str = "book_walk",
        max_levels: int = 10,
    ):
        """Initialize execution simulator.

        Args:
            latency_ms: Simulated signal-to-fill latency in milliseconds
            slippage_model: Model for slippage ("book_walk" or "fixed_bps")
            max_levels: Maximum book levels to consider
        """
        self.latency_ms = latency_ms
        self.slippage_model = slippage_model
        self.max_levels = max_levels

        logger.info(
            f"L2ExecutionSimulator initialized: "
            f"latency={latency_ms}ms, model={slippage_model}"
        )

    def simulate_fill(
        self,
        order_side: str,
        quantity: int,
        book_snapshot: pd.Series,
        reference_price: float,
    ) -> FillResult:
        """Simulate order execution against L2 book.

        For BUY orders: Walk through ASK levels upward
        For SELL orders: Walk through BID levels downward

        Args:
            order_side: "BUY" or "SELL"
            quantity: Number of shares to execute
            book_snapshot: L2 book snapshot with bid_px_N, ask_px_N, bid_sz_N, ask_sz_N
            reference_price: Mid price or last trade for comparison

        Returns:
            FillResult with fill price and slippage
        """
        if self.slippage_model == "fixed_bps":
            return self._simulate_fixed_bps(order_side, reference_price)

        return self._walk_book(order_side, quantity, book_snapshot, reference_price)

    def _simulate_fixed_bps(
        self,
        order_side: str,
        reference_price: float,
        fixed_bps: int = 5,
    ) -> FillResult:
        """Simple fixed slippage model.

        Used as fallback when L2 data not available or for simplicity.
        """
        slippage_decimals = fixed_bps / 10000

        if order_side == "BUY":
            fill_price = reference_price * (1 + slippage_decimals)
        else:
            fill_price = reference_price * (1 - slippage_decimals)

        return FillResult(
            fill_price=fill_price,
            slippage_bps=fixed_bps,
            walked_levels=1,
            fill_time_ms=self.latency_ms,
            partially_filled=False,
        )

    def _walk_book(
        self,
        order_side: str,
        quantity: int,
        book_snapshot: pd.Series,
        reference_price: float,
    ) -> FillResult:
        """Walk the order book to calculate realistic fill price.

        Algorithm:
        1. Start at best bid/ask
        2. Consume available quantity at each level
        3. Move to next level if more needed
        4. Calculate VWAP of filled levels

        Args:
            order_side: "BUY" or "SELL"
            quantity: Shares to execute
            book_snapshot: L2 book with bid/ask levels
            reference_price: Reference for slippage calculation

        Returns:
            FillResult with walked fill price
        """
        total_cost = 0.0
        total_filled = 0
        levels_walked = 0

        remaining = quantity

        for level in range(1, self.max_levels + 1):
            if remaining <= 0:
                break

            if order_side == "BUY":
                # Walk ask levels upward
                price = book_snapshot.get(f"ask_px_{level}")
                size = book_snapshot.get(f"ask_sz_{level}")
            else:
                # Walk bid levels downward
                price = book_snapshot.get(f"bid_px_{level}")
                size = book_snapshot.get(f"bid_sz_{level}")

            # Skip if no data
            if pd.isna(price) or pd.isna(size) or size == 0:
                continue

            # Fill at this level
            fill_qty = min(remaining, size)
            total_cost += price * fill_qty
            total_filled += fill_qty
            remaining -= fill_qty
            levels_walked += 1

        # Check if fully filled
        partially_filled = remaining > 0

        if total_filled == 0:
            # No liquidity - use reference price with penalty
            fill_price = reference_price * 1.001  # 0.1% penalty
            return FillResult(
                fill_price=fill_price,
                slippage_bps=10,  # 10 bps penalty
                walked_levels=0,
                fill_time_ms=self.latency_ms,
                partially_filled=True,
            )

        # VWAP fill price
        fill_price = total_cost / total_filled

        # Calculate slippage vs reference
        slippage = abs(fill_price - reference_price) / reference_price
        slippage_bps = int(slippage * 10000)

        return FillResult(
            fill_price=fill_price,
            slippage_bps=slippage_bps,
            walked_levels=levels_walked,
            fill_time_ms=self.latency_ms,
            partially_filled=partially_filled,
        )

    def estimate_market_impact(
        self,
        quantity: int,
        book_snapshot: pd.Series,
        side: str = "both",
    ) -> float:
        """Estimate market impact of an order before execution.

        Useful for position sizing decisions.

        Args:
            quantity: Order size in shares
            book_snapshot: L2 book snapshot
            side: "bid", "ask", or "both" (use shallower side)

        Returns:
            Estimated impact as decimal (0.001 = 0.1%)
        """
        if side == "both":
            # Use minimum of bid/ask depth
            bid_depth = self._calculate_depth(book_snapshot, "bid", levels=5)
            ask_depth = self._calculate_depth(book_snapshot, "ask", levels=5)
            available_depth = min(bid_depth, ask_depth)
        else:
            available_depth = self._calculate_depth(book_snapshot, side, levels=5)

        if available_depth == 0:
            return 0.01  # 1% impact if no depth

        # Simple model: impact proportional to size / depth
        impact = (quantity / available_depth) * 0.001  # Baseline 0.1% for full consumption

        return min(impact, 0.05)  # Cap at 5%

    def _calculate_depth(
        self,
        book_snapshot: pd.Series,
        side: str,
        levels: int = 5,
    ) -> float:
        """Calculate total available depth at N levels."""
        total = 0.0

        for i in range(1, levels + 1):
            if side == "bid":
                size = book_snapshot.get(f"bid_sz_{i}")
            else:
                size = book_snapshot.get(f"ask_sz_{i}")

            if pd.notna(size):
                total += size

        return total

    def check_liquidity(
        self,
        book_snapshot: pd.Series,
        required_quantity: int,
    ) -> Dict[str, any]:
        """Check if book has sufficient liquidity.

        Args:
            book_snapshot: L2 book snapshot
            required_quantity: Quantity needed

        Returns:
            Dict with:
            - sufficient_bid: bool
            - sufficient_ask: bool
            - bid_depth: total bid shares
            - ask_depth: total ask shares
            - bid_levels: levels to fill on bid side
            - ask_levels: levels to fill on ask side
        """
        bid_depth = 0
        ask_depth = 0
        bid_levels = 0
        ask_levels = 0

        bid_remaining = required_quantity
        ask_remaining = required_quantity

        for i in range(1, self.max_levels + 1):
            # Check bid side
            bid_sz = book_snapshot.get(f"bid_sz_{i}", 0) or 0
            ask_sz = book_snapshot.get(f"ask_sz_{i}", 0) or 0

            if pd.notna(bid_sz) and bid_sz > 0:
                bid_depth += bid_sz
                if bid_remaining > 0:
                    bid_remaining -= bid_sz
                    bid_levels += 1

            if pd.notna(ask_sz) and ask_sz > 0:
                ask_depth += ask_sz
                if ask_remaining > 0:
                    ask_remaining -= ask_sz
                    ask_levels += 1

        return {
            "sufficient_bid": bid_depth >= required_quantity,
            "sufficient_ask": ask_depth >= required_quantity,
            "bid_depth": bid_depth,
            "ask_depth": ask_depth,
            "bid_levels": bid_levels if bid_depth >= required_quantity else None,
            "ask_levels": ask_levels if ask_depth >= required_quantity else None,
        }


def simulate_execution_batch(
    orders: List[Dict],
    l2_data: pd.DataFrame,
    simulator: L2ExecutionSimulator,
) -> List[FillResult]:
    """Simulate execution for multiple orders.

    Args:
        orders: List of {symbol, side, quantity, timestamp}
        l2_data: L2 snapshots with ts_utc, symbol, and book levels
        simulator: L2ExecutionSimulator instance

    Returns:
        List of FillResult, one per order
    """
    results = []

    for order in orders:
        symbol = order["symbol"]
        side = order["side"]
        quantity = order["quantity"]
        timestamp = order["timestamp"]

        # Find L2 snapshot for this symbol and time
        snapshot = l2_data[
            (l2_data["symbol"] == symbol) &
            (l2_data["ts_utc"] == timestamp)
        ]

        if snapshot.empty:
            # No L2 data - use fallback
            result = simulator._simulate_fixed_bps(side, 100.0)
        else:
            # Get reference price (mid)
            mid = (snapshot.iloc[0]["bid_px_1"] + snapshot.iloc[0]["ask_px_1"]) / 2
            result = simulator.simulate_fill(side, quantity, snapshot.iloc[0], mid)

        results.append(result)

    return results
