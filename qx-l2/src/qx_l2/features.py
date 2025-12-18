"""L2 feature engineering (migrated from transalpha/l2)."""

import logging
from collections import deque
from typing import Optional

logger = logging.getLogger(__name__)


class L2FeatureEngineer:
    """Compute L2 microstructure features."""

    def __init__(self, config: dict):
        feat_cfg = config.get("features", {})
        self.obi_levels = feat_cfg.get("obi_levels", [1, 3, 5, 10])
        self.delta_windows = feat_cfg.get("delta_windows_sec", [5, 30])

        # History for time deltas
        self.history = deque(maxlen=100)

    def compute(self, snapshot: dict, levels: int) -> Optional[dict]:
        """Compute L2 features from snapshot."""
        if not snapshot.get("has_depth"):
            return None

        features = {
            "ts_utc": snapshot["ts_utc"],
            "ts_epoch": snapshot["ts_epoch"],
            "date_et": snapshot["date_et"],
            "symbol": snapshot["symbol"],
            "exchange": snapshot["exchange"],
            "smart_depth": snapshot["smart_depth"],
            "has_depth": True,
        }

        # Basic microstructure
        mid = snapshot.get("l1_mid")
        spread = snapshot.get("l1_spread")

        if mid and spread:
            features["mid"] = mid
            features["spread"] = spread

            # Microprice (volume-weighted fair value)
            bid_px = snapshot.get("bid_px_1")
            ask_px = snapshot.get("ask_px_1")
            bid_sz = snapshot.get("bid_sz_1")
            ask_sz = snapshot.get("ask_sz_1")

            if all(x for x in [bid_px, ask_px, bid_sz, ask_sz]):
                microprice = (bid_px * ask_sz + ask_px * bid_sz) / (bid_sz + ask_sz)
                features["microprice"] = microprice
                features["micro_off"] = microprice - mid
            else:
                features["microprice"] = mid
                features["micro_off"] = 0.0

        # Depth aggregation
        total_bid_depth = 0
        total_ask_depth = 0

        for i in range(1, levels + 1):
            bid_sz = snapshot.get(f"bid_sz_{i}", 0) or 0
            ask_sz = snapshot.get(f"ask_sz_{i}", 0) or 0
            total_bid_depth += bid_sz
            total_ask_depth += ask_sz

        features["depth_bid_k"] = total_bid_depth
        features["depth_ask_k"] = total_ask_depth

        # Depth imbalance
        if total_bid_depth + total_ask_depth > 0:
            features["depth_imb_k"] = (total_bid_depth - total_ask_depth) / (
                total_bid_depth + total_ask_depth
            )
        else:
            features["depth_imb_k"] = 0.0

        # Pressure (simplified)
        features["pressure_k"] = total_bid_depth - total_ask_depth

        # Order Book Imbalance (OBI) at multiple levels
        for level in self.obi_levels:
            if level <= levels:
                bid_sz = snapshot.get(f"bid_sz_{level}", 0) or 0
                ask_sz = snapshot.get(f"ask_sz_{level}", 0) or 0

                if bid_sz + ask_sz > 0:
                    obi = (bid_sz - ask_sz) / (bid_sz + ask_sz)
                else:
                    obi = 0.0

                features[f"obi_{level}"] = obi

        # Time deltas (requires history)
        self._compute_deltas(features, snapshot)

        # Store in history
        self.history.append(
            {
                "ts_epoch": snapshot["ts_epoch"],
                "mid": features.get("mid"),
                "spread": features.get("spread"),
                "obi_1": features.get("obi_1"),
                "micro_off": features.get("micro_off"),
            }
        )

        return features

    def _compute_deltas(self, features: dict, snapshot: dict):
        """Compute time-based deltas."""
        current_ts = snapshot["ts_epoch"]

        for window_sec in self.delta_windows:
            # Find historical point
            target_ts = current_ts - window_sec
            hist_point = None

            for h in reversed(self.history):
                if h["ts_epoch"] <= target_ts:
                    hist_point = h
                    break

            if hist_point:
                # Compute deltas
                for field in ["mid", "spread", "obi_1", "micro_off"]:
                    current_val = features.get(field, 0)
                    hist_val = hist_point.get(field, 0)

                    if current_val is not None and hist_val is not None:
                        delta = current_val - hist_val
                    else:
                        delta = 0.0

                    features[f"d_{field}_{window_sec}s"] = delta
            else:
                # No history, set to zero
                for field in ["mid", "spread", "obi_1", "micro_off"]:
                    features[f"d_{field}_{window_sec}s"] = 0.0
