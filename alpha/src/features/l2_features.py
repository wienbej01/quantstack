"""L2 order book features for Alpha hypothesis testing.

Extends qx_l2.L2FeatureEngineer with additional features for:
- Book imbalance at multiple levels
- Depth ratio calculations
- Book slope (price decay across levels)
- Large order detection
- Depth drop detection (liquidity vacuum signal)

These features support the three hypotheses:
1. Order Flow Imbalance - book_imbalance, depth_ratio
2. Whale Following - detect_large_orders
3. Liquidity Fade - detect_depth_drop
"""

import logging
from collections import deque
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class AlphaL2Features:
    """Compute L2 microstructure features for Alpha hypothesis testing.

    Extends qx_l2.L2FeatureEngineer with alpha-specific features.
    Can be used standalone or in conjunction with qx_l2.L2FeatureEngineer.
    """

    def __init__(self, config: dict):
        """Initialize L2 feature engineer with configuration.

        Args:
            config: Configuration dict with optional keys:
                - large_order_threshold_mult: Multiplier for avg size to detect large orders (default: 3)
                - depth_drop_threshold: Fractional drop to detect liquidity vacuum (default: 0.5)
                - depth_levels: Number of levels to analyze (default: 10)
                - history_len: Number of snapshots to keep for comparison (default: 100)
        """
        feat_cfg = config.get("features", {})
        self.large_order_threshold_mult = feat_cfg.get("large_order_threshold_mult", 3)
        self.depth_drop_threshold = feat_cfg.get("depth_drop_threshold", 0.5)
        self.depth_levels = feat_cfg.get("depth_levels", 10)
        self.history_len = feat_cfg.get("history_len", 100)

        # Rolling history for depth comparisons
        self.history: deque = deque(maxlen=self.history_len)

        # Track average sizes for large order detection
        self.avg_bid_sizes: Dict[int, deque] = {
            i: deque(maxlen=50) for i in range(1, 11)
        }
        self.avg_ask_sizes: Dict[int, deque] = {
            i: deque(maxlen=50) for i in range(1, 11)
        }

    def compute_book_imbalance(self, snapshot: pd.Series, levels: int = 5) -> float:
        """Compute order book imbalance at specified levels.

        OBI = (bid_volume - ask_volume) / (bid_volume + ask_volume)

        Range: [-1, 1]
        - Positive: More bids (buying pressure)
        - Negative: More asks (selling pressure)
        - Zero: Balanced

        Args:
            snapshot: L2 snapshot as pandas Series with bid_sz_N, ask_sz_N columns
            levels: Number of levels to aggregate (default: 5)

        Returns:
            Float in range [-1, 1], or 0.0 if no depth
        """
        total_bid = 0.0
        total_ask = 0.0

        for i in range(1, min(levels, self.depth_levels) + 1):
            bid_sz = snapshot.get(f"bid_sz_{i}") or 0
            ask_sz = snapshot.get(f"ask_sz_{i}") or 0

            # Handle NaN values
            if pd.isna(bid_sz):
                bid_sz = 0
            if pd.isna(ask_sz):
                ask_sz = 0

            total_bid += bid_sz
            total_ask += ask_sz

        if total_bid + total_ask == 0:
            return 0.0

        return (total_bid - total_ask) / (total_bid + total_ask)

    def compute_depth_ratio(self, snapshot: pd.Series, levels: int = 5) -> float:
        """Compute depth ratio (bid depth / ask depth) at specified levels.

        Ratio > 1: More bids than asks
        Ratio < 1: More asks than bids
        Ratio = 1: Balanced

        Args:
            snapshot: L2 snapshot as pandas Series
            levels: Number of levels to aggregate (default: 5)

        Returns:
            Float depth ratio, or 1.0 if no ask depth
        """
        total_bid = 0.0
        total_ask = 0.0

        for i in range(1, min(levels, self.depth_levels) + 1):
            bid_sz = snapshot.get(f"bid_sz_{i}") or 0
            ask_sz = snapshot.get(f"ask_sz_{i}") or 0

            if pd.isna(bid_sz):
                bid_sz = 0
            if pd.isna(ask_sz):
                ask_sz = 0

            total_bid += bid_sz
            total_ask += ask_sz

        if total_ask == 0:
            return 1.0 if total_bid > 0 else 1.0

        return total_bid / total_ask

    def compute_book_slope(
        self, snapshot: pd.Series, levels: int = 5
    ) -> Tuple[float, float]:
        """Compute order book slope (price decay across levels).

        Slope measures how quickly prices deteriorate as you go deeper into the book.
        Steeper negative slope: More illiquid (worse execution for large orders)
        Flatter slope: More liquid (better execution for large orders)

        Computed via linear regression of (level, price) for bids and asks.

        Args:
            snapshot: L2 snapshot as pandas Series
            levels: Number of levels to analyze (default: 5)

        Returns:
            Tuple of (bid_slope, ask_slope)
            Negative values indicate decreasing/increasing prices away from best
        """
        bid_prices = []
        ask_prices = []

        for i in range(1, min(levels, self.depth_levels) + 1):
            bid_px = snapshot.get(f"bid_px_{i}")
            ask_px = snapshot.get(f"ask_px_{i}")

            if pd.notna(bid_px):
                bid_prices.append((i, bid_px))
            if pd.notna(ask_px):
                ask_prices.append((i, ask_px))

        # Compute slope via linear regression
        def _slope(points: List[Tuple[int, float]]) -> float:
            if len(points) < 2:
                return 0.0

            x = np.array([p[0] for p in points])
            y = np.array([p[1] for p in points])

            # Simple linear regression: y = mx + b
            # slope m = cov(x,y) / var(x)
            if len(x) == 0 or np.var(x) == 0:
                return 0.0

            covariance = np.cov(x, y, bias=True)[0, 1]
            variance = np.var(x)

            return covariance / variance if variance != 0 else 0.0

        return _slope(bid_prices), _slope(ask_prices)

    def detect_large_orders(
        self,
        snapshot: pd.Series,
        threshold_mult: Optional[float] = None,
    ) -> Dict[str, bool]:
        """Detect large institutional orders at any level.

        An order is considered "large" if its size exceeds threshold_mult
        times the rolling average size for that level.

        Args:
            snapshot: L2 snapshot as pandas Series
            threshold_mult: Override default threshold multiplier

        Returns:
            Dict with keys:
            - has_large_bid: bool
            - has_large_ask: bool
            - large_bid_levels: list of levels with large bids
            - large_ask_levels: list of levels with large asks
        """
        threshold = threshold_mult or self.large_order_threshold_mult

        large_bid_levels = []
        large_ask_levels = []

        for i in range(1, self.depth_levels + 1):
            bid_sz = snapshot.get(f"bid_sz_{i}") or 0
            ask_sz = snapshot.get(f"ask_sz_{i}") or 0

            if pd.isna(bid_sz):
                bid_sz = 0
            if pd.isna(ask_sz):
                ask_sz = 0

            # Update rolling averages
            if bid_sz > 0:
                self.avg_bid_sizes[i].append(bid_sz)
            if ask_sz > 0:
                self.avg_ask_sizes[i].append(ask_sz)

            # Check against average
            if bid_sz > 0 and len(self.avg_bid_sizes[i]) > 5:
                avg_bid = np.mean(list(self.avg_bid_sizes[i]))
                if bid_sz >= avg_bid * threshold:
                    large_bid_levels.append(i)

            if ask_sz > 0 and len(self.avg_ask_sizes[i]) > 5:
                avg_ask = np.mean(list(self.avg_ask_sizes[i]))
                if ask_sz >= avg_ask * threshold:
                    large_ask_levels.append(i)

        return {
            "has_large_bid": len(large_bid_levels) > 0,
            "has_large_ask": len(large_ask_levels) > 0,
            "large_bid_levels": large_bid_levels,
            "large_ask_levels": large_ask_levels,
        }

    def detect_depth_drop(
        self,
        current_snapshot: pd.Series,
        threshold: Optional[float] = None,
    ) -> Dict[str, any]:
        """Detect sudden liquidity withdrawal (liquidity vacuum).

        Compares current depth to recent history. A significant drop
        indicates market makers pulling liquidity - potential mean-reversion signal.

        Args:
            current_snapshot: Current L2 snapshot as pandas Series
            threshold: Override default depth drop threshold (fractional)

        Returns:
            Dict with keys:
            - depth_drop_detected: bool
            - bid_drop_pct: float (percent drop in bid depth)
            - ask_drop_pct: float (percent drop in ask depth)
            - current_bid_depth: float
            - current_ask_depth: float
            - avg_bid_depth: float
            - avg_ask_depth: float
        """
        threshold = threshold or self.depth_drop_threshold

        # Compute current depth
        current_bid_depth = 0.0
        current_ask_depth = 0.0

        for i in range(1, self.depth_levels + 1):
            bid_sz = current_snapshot.get(f"bid_sz_{i}") or 0
            ask_sz = current_snapshot.get(f"ask_sz_{i}") or 0

            if pd.isna(bid_sz):
                bid_sz = 0
            if pd.isna(ask_sz):
                ask_sz = 0

            current_bid_depth += bid_sz
            current_ask_depth += ask_sz

        # Compare to history
        if len(self.history) < 10:
            # Not enough history
            return {
                "depth_drop_detected": False,
                "bid_drop_pct": 0.0,
                "ask_drop_pct": 0.0,
                "current_bid_depth": current_bid_depth,
                "current_ask_depth": current_ask_depth,
                "avg_bid_depth": current_bid_depth,
                "avg_ask_depth": current_ask_depth,
            }

        # Compute average depth from history
        avg_bid_depth = np.mean([h["bid_depth"] for h in self.history])
        avg_ask_depth = np.mean([h["ask_depth"] for h in self.history])

        # Compute percentage drops
        if avg_bid_depth > 0:
            bid_drop_pct = (avg_bid_depth - current_bid_depth) / avg_bid_depth
        else:
            bid_drop_pct = 0.0

        if avg_ask_depth > 0:
            ask_drop_pct = (avg_ask_depth - current_ask_depth) / avg_ask_depth
        else:
            ask_drop_pct = 0.0

        # Detect significant drop
        drop_detected = (bid_drop_pct > threshold) or (ask_drop_pct > threshold)

        return {
            "depth_drop_detected": drop_detected,
            "bid_drop_pct": bid_drop_pct,
            "ask_drop_pct": ask_drop_pct,
            "current_bid_depth": current_bid_depth,
            "current_ask_depth": current_ask_depth,
            "avg_bid_depth": avg_bid_depth,
            "avg_ask_depth": avg_ask_depth,
        }

    def update_history(self, snapshot: pd.Series) -> None:
        """Update rolling history with current snapshot depth.

        Args:
            snapshot: L2 snapshot as pandas Series
        """
        bid_depth = 0.0
        ask_depth = 0.0

        for i in range(1, self.depth_levels + 1):
            bid_sz = snapshot.get(f"bid_sz_{i}") or 0
            ask_sz = snapshot.get(f"ask_sz_{i}") or 0

            if pd.isna(bid_sz):
                bid_sz = 0
            if pd.isna(ask_sz):
                ask_sz = 0

            bid_depth += bid_sz
            ask_depth += ask_sz

        self.history.append(
            {
                "bid_depth": bid_depth,
                "ask_depth": ask_depth,
            }
        )

    def compute_all_features(
        self,
        snapshot: pd.Series,
    ) -> Dict[str, any]:
        """Compute all L2 features for a snapshot.

        Handles both raw L2 data (with full depth) and pre-computed features.

        Args:
            snapshot: L2 snapshot as pandas Series. Can be:
                - Raw data: bid_sz_N, ask_sz_N, bid_px_N, ask_px_N for N=1..10
                - Pre-computed features: obi_1, obi_5, mid, spread, depth_bid, depth_ask, pressure

        Returns:
            Dict of all computed features
        """
        features = {}

        # Check if this is pre-computed feature data or raw data
        is_precomputed = "obi_5" in snapshot.index or "obi_1" in snapshot.index

        if is_precomputed:
            # Use pre-computed features directly (faster, already computed)
            logger.debug("Using pre-computed L2 features")

            # Order book imbalance (pre-computed)
            features["book_imbalance_1"] = float(snapshot.get("obi_1", 0))
            features["book_imbalance_5"] = float(snapshot.get("obi_5", 0))
            # Estimate other levels from available
            features["book_imbalance_3"] = features["book_imbalance_1"]  # Approximation
            features["book_imbalance_10"] = features[
                "book_imbalance_5"
            ]  # Approximation

            # Depth ratio from pre-computed depth values
            depth_bid = float(snapshot.get("depth_bid", 0))
            depth_ask = float(snapshot.get("depth_ask", 0))
            if depth_ask > 0:
                features["depth_ratio_5"] = depth_bid / depth_ask
            else:
                features["depth_ratio_5"] = 1.0

            # Spread and mid price (pre-computed)
            features["spread"] = float(snapshot.get("spread", 0))
            features["mid_price"] = float(snapshot.get("mid", 0))

            # Pressure metric (if available)
            if "pressure" in snapshot.index:
                features["pressure"] = float(snapshot.get("pressure", 0))

            # Bid/Ask prices and sizes (L1 level)
            features["bid_price"] = float(snapshot.get("bid", 0))
            features["ask_price"] = float(snapshot.get("ask", 0))
            features["bid_size"] = float(snapshot.get("bid_size", 0))
            features["ask_size"] = float(snapshot.get("ask_size", 0))

            # For pre-computed features, we can't compute slope, large orders, or depth drop
            # Set reasonable defaults
            features["bid_slope_5"] = 0.0
            features["ask_slope_5"] = 0.0
            features["has_large_bid"] = False
            features["has_large_ask"] = False
            features["large_bid_count"] = 0
            features["large_ask_count"] = 0
            features["depth_drop_detected"] = False
            features["bid_drop_pct"] = 0.0
            features["ask_drop_pct"] = 0.0

        else:
            # Compute features from raw L2 data
            # Compute spread from bid_px_1 and ask_px_1 (fallback to l1_bid/l1_ask if available)
            bid_price = snapshot.get("bid_px_1") or snapshot.get("l1_bid")
            ask_price = snapshot.get("ask_px_1") or snapshot.get("l1_ask")

            if (
                bid_price
                and ask_price
                and not pd.isna(bid_price)
                and not pd.isna(ask_price)
            ):
                features["spread"] = float(ask_price - bid_price)
                features["mid_price"] = float((bid_price + ask_price) / 2)
            else:
                features["spread"] = 0.0
                features["mid_price"] = 0.0

            # Basic book imbalance at multiple levels
            for levels in [1, 3, 5, 10]:
                features[f"book_imbalance_{levels}"] = self.compute_book_imbalance(
                    snapshot, levels
                )

            # Depth ratio
            features["depth_ratio_5"] = self.compute_depth_ratio(snapshot, levels=5)

            # Book slope
            bid_slope, ask_slope = self.compute_book_slope(snapshot, levels=5)
            features["bid_slope_5"] = bid_slope
            features["ask_slope_5"] = ask_slope

            # Large order detection
            large_orders = self.detect_large_orders(snapshot)
            features["has_large_bid"] = large_orders["has_large_bid"]
            features["has_large_ask"] = large_orders["has_large_ask"]
            features["large_bid_count"] = len(large_orders["large_bid_levels"])
            features["large_ask_count"] = len(large_orders["large_ask_levels"])

            # Depth drop detection
            depth_drop = self.detect_depth_drop(snapshot)
            features["depth_drop_detected"] = depth_drop["depth_drop_detected"]
            features["bid_drop_pct"] = depth_drop["bid_drop_pct"]
            features["ask_drop_pct"] = depth_drop["ask_drop_pct"]

            # Update history for next iteration
            self.update_history(snapshot)

        return features
