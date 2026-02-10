"""L2 ratio filter using real-time L2 data from l2-scalping."""

from __future__ import annotations

import logging
import os
from datetime import date

from data.l2_reader import L2DataReader

logger = logging.getLogger(__name__)


class L2Filter:
    """L2 depth ratio filter using real-time data from l2-scalping."""

    def __init__(self, config: dict):
        l2_cfg = config.get("l2_filter", {})
        self.enabled = l2_cfg.get("enabled", True)
        self.ratio_long = l2_cfg.get("ratio_long", 1.165)
        self.ratio_short = l2_cfg.get("ratio_short", 0.858)

        l2_data_cfg = config.get("l2_data", {})
        default_root = os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2")
        default_path = f"{default_root}/l2_maximum/features"
        features_path = l2_data_cfg.get("features_path", default_path)
        self._reader = L2DataReader(features_path)

    def get_ratio(self, symbol: str, trade_date: date) -> float | None:
        """Get L2 depth ratio (depth_bid / depth_ask) for symbol."""
        if not self.enabled:
            return None
        return self._reader.get_l2_ratio(symbol, trade_date)

    def check_long(self, symbol: str, trade_date: date) -> bool:
        """Check if L2 filter passes for LONG entry."""
        if not self.enabled:
            return True

        ratio = self.get_ratio(symbol, trade_date)
        if ratio is None:
            logger.debug(f"No L2 data for {symbol}, rejecting LONG")
            return False

        passes = ratio >= self.ratio_long
        if passes:
            logger.info(f"L2 LONG filter PASS: {symbol} ratio={ratio:.3f} >= {self.ratio_long}")
        return passes

    def check_short(self, symbol: str, trade_date: date) -> bool:
        """Check if L2 filter passes for SHORT entry."""
        if not self.enabled:
            return True

        ratio = self.get_ratio(symbol, trade_date)
        if ratio is None:
            logger.debug(f"No L2 data for {symbol}, rejecting SHORT")
            return False

        passes = ratio <= self.ratio_short
        if passes:
            logger.info(f"L2 SHORT filter PASS: {symbol} ratio={ratio:.3f} <= {self.ratio_short}")
        return passes

    def reset_day(self) -> None:
        """Reset for new trading day."""
        self._reader.clear_cache()
