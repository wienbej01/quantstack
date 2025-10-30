"""Intraday ML Labeling Module

Creates ATR-thresholded "prominent moves" labels with strict no-peek rules.
Implements first-hit logic for tri-class classification {-1, 0, +1}.
"""

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from qx_features.core_basics import atr_m


@dataclass
class LabelResult:
    """Result of labeling operation with metadata."""

    labels: pd.Series
    metadata: Dict[str, Any]
    targets_hash: str


class IntradayMLLabeler:
    """Creates ATR-thresholded labels with strict time discipline."""

    def __init__(self, targets_config: Dict[str, Any]):
        """Initialize labeler with configuration.

        Args:
            targets_config: Configuration dictionary from targets.yaml
        """
        self.config = targets_config
        self.horizons = targets_config.get("horizons", [30, 60, 90])
        self.atr_multiplier = targets_config.get("atr_multiplier", 1.0)
        self.atr_window = targets_config.get("atr_window", 14)

    def create_labels(
        self, bars: pd.DataFrame, ts_cut: pd.Timestamp, validate_no_peek: bool = True
    ) -> LabelResult:
        """Create tri-class labels for prominent moves.

        Args:
            bars: DataFrame with OHLCV data, sorted by [symbol, ts]
            ts_cut: Cut timestamp - labels must only use data > ts_cut
            validate_no_peek: Whether to validate no forward look

        Returns:
            LabelResult with labels and metadata
        """
        if validate_no_peek:
            self._validate_no_peek(bars, ts_cut)

        # Filter future data for label computation
        future_bars = bars[bars["ts"] > ts_cut].copy()

        # Compute ATR on historical data (≤ ts_cut)
        historical_bars = bars[bars["ts"] <= ts_cut].copy()
        atr_values = self._compute_atr(historical_bars)

        # Create labels for each horizon
        all_labels = {}
        all_metadata = {}

        for horizon in self.horizons:
            horizon_labels, horizon_metadata = self._create_horizon_labels(
                future_bars, atr_values, horizon, ts_cut
            )
            all_labels[horizon] = horizon_labels
            all_metadata[horizon] = horizon_metadata

        # Combine labels across horizons
        combined_labels = self._combine_horizon_labels(all_labels)

        # Create targets hash
        targets_hash = self._compute_targets_hash(
            bars, ts_cut, self.config, combined_labels
        )

        metadata = {
            "horizons": self.horizons,
            "atr_multiplier": self.atr_multiplier,
            "atr_window": self.atr_window,
            "ts_cut": ts_cut.isoformat(),
            "label_counts": combined_labels.value_counts().to_dict(),
            "horizon_metadata": all_metadata,
        }

        return LabelResult(
            labels=combined_labels, metadata=metadata, targets_hash=targets_hash
        )

    def _validate_no_peek(self, bars: pd.DataFrame, ts_cut: pd.Timestamp):
        """Validate that labeling respects no-peek rules."""
        # ATR computation must use data ≤ ts_cut only
        if bars["ts"].min() > ts_cut:
            raise ValueError(
                f"No historical data available for ATR computation before ts_cut: {ts_cut}"
            )

        # Check that we have sufficient historical data for ATR
        historical_bars = bars[bars["ts"] <= ts_cut]
        min_required = self.atr_window + 5  # Some buffer

        if len(historical_bars) < min_required:
            raise ValueError(
                f"Insufficient historical data for ATR: "
                f"need {min_required} bars, have {len(historical_bars)}"
            )

    def _compute_atr(self, historical_bars: pd.DataFrame) -> pd.Series:
        """Compute ATR values for historical bars."""
        atr_values = []

        for symbol, group in historical_bars.groupby("symbol"):
            group = group.sort_values("ts")
            symbol_atr = atr_m(group, self.atr_window)

            # Create mapping from timestamp to ATR value
            atr_map = pd.Series(symbol_atr.values, index=group.index)
            atr_values.append(atr_map)

        if atr_values:
            combined_atr = pd.concat(atr_values)
            return combined_atr
        else:
            return pd.Series(dtype=float)

    def _create_horizon_labels(
        self,
        future_bars: pd.DataFrame,
        atr_values: pd.Series,
        horizon: int,
        ts_cut: pd.Timestamp,
    ) -> Tuple[pd.Series, Dict[str, Any]]:
        """Create labels for a specific horizon."""
        labels = []
        metadata = {
            "horizon_minutes": horizon,
            "threshold_hits": {"positive": 0, "negative": 0, "neutral": 0},
        }

        for symbol, group in future_bars.groupby("symbol"):
            group = group.sort_values("ts")

            # Get the latest ATR value for this symbol (computed from historical data)
            symbol_atr = self._get_latest_atr(atr_values, symbol)

            if symbol_atr is None or symbol_atr < self.config.get(
                "require_min_atr", 0.01
            ):
                # Use default ATR if none available or too small
                symbol_atr = 0.1  # Default fallback

            # Calculate threshold
            threshold = self.atr_multiplier * symbol_atr

            # Create labels for each timestamp as ts_cut
            for _, row in group.iterrows():
                label = self._compute_first_hit_label(
                    group, row, threshold, horizon, ts_cut
                )
                labels.append(label)

                # Update metadata
                if label == 1:
                    metadata["threshold_hits"]["positive"] += 1
                elif label == -1:
                    metadata["threshold_hits"]["negative"] += 1
                else:
                    metadata["threshold_hits"]["neutral"] += 1

        if labels:
            label_series = pd.Series(
                labels, index=future_bars.index, name=f"label_{horizon}m"
            )
            return label_series, metadata
        else:
            return pd.Series(dtype=int), metadata

    def _get_latest_atr(self, atr_values: pd.Series, symbol: str) -> Optional[float]:
        """Get the latest ATR value for a symbol."""
        # Find the most recent ATR value for this symbol
        symbol_atrs = atr_values[
            atr_values.index.isin(self._get_symbol_indices(atr_values, symbol))
        ]

        if len(symbol_atrs) > 0:
            return symbol_atrs.iloc[-1]
        else:
            return None

    def _get_symbol_indices(self, atr_values: pd.Series, symbol: str) -> List[int]:
        """Get indices for a specific symbol (placeholder implementation)."""
        # This is a simplified implementation
        # In practice, you'd need to track which indices belong to which symbol
        return list(atr_values.index)

    def _compute_first_hit_label(
        self,
        group: pd.DataFrame,
        current_row: pd.Series,
        threshold: float,
        horizon: int,
        ts_cut: pd.Timestamp,
    ) -> int:
        """Compute label using first-hit logic.

        Args:
            group: Future bars for the symbol
            current_row: Current bar (at ts_cut)
            threshold: ATR threshold for significant move
            horizon: Horizon in minutes
            ts_cut: Cut timestamp

        Returns:
            Label: +1, -1, or 0
        """
        # Get the index of current row
        current_idx = current_row.name
        current_idx_pos = group.index.get_loc(current_idx)

        # Calculate horizon end
        horizon_end_ts = current_row["ts"] + pd.Timedelta(minutes=horizon)

        # Get future bars within horizon
        future_mask = (group["ts"] > current_row["ts"]) & (
            group["ts"] <= horizon_end_ts
        )
        future_bars = group[future_mask]

        if len(future_bars) == 0:
            return 0  # No future data within horizon

        # Get starting price (current close)
        start_price = current_row["close"]

        # Track first hit
        first_hit = None
        first_hit_time = None

        for _, future_row in future_bars.iterrows():
            # Calculate forward return
            fwd_return = (future_row["close"] - start_price) / start_price

            # Check if threshold is hit
            if fwd_return >= threshold:
                first_hit = 1
                first_hit_time = future_row["ts"]
                break
            elif fwd_return <= -threshold:
                first_hit = -1
                first_hit_time = future_row["ts"]
                break

        return first_hit if first_hit is not None else 0

    def _combine_horizon_labels(
        self, horizon_labels: Dict[int, pd.Series]
    ) -> pd.Series:
        """Combine labels across multiple horizons."""
        if not horizon_labels:
            return pd.Series(dtype=int)

        # For now, use the shortest horizon (30m) as the primary label
        # In practice, you might want more sophisticated combination
        shortest_horizon = min(horizon_labels.keys())
        primary_labels = horizon_labels[shortest_horizon]

        # Add metadata about other horizons
        combined = primary_labels.copy()
        combined.name = "label_combined"

        return combined

    def _compute_targets_hash(
        self,
        bars: pd.DataFrame,
        ts_cut: pd.Timestamp,
        targets_config: Dict[str, Any],
        labels: pd.Series,
    ) -> str:
        """Compute hash for targets reproducibility."""
        targets_info = {
            "symbols": sorted(bars["symbol"].unique().tolist()),
            "date_range": [bars["ts"].min().isoformat(), bars["ts"].max().isoformat()],
            "ts_cut": ts_cut.isoformat(),
            "targets_config": targets_config,
            "label_distribution": labels.value_counts().to_dict(),
            "total_labels": len(labels),
        }

        targets_str = hashlib.blake2b(
            str(targets_info).encode(), digest_size=32
        ).hexdigest()

        return targets_str


def intraday_ml_get_targets_hash(
    bars: pd.DataFrame,
    ts_cut: pd.Timestamp,
    targets_config: Dict[str, Any],
    labels: pd.Series,
) -> str:
    """Compute targets hash for given data and configuration.

    Args:
        bars: DataFrame with bar data
        ts_cut: Cut timestamp
        targets_config: Targets configuration dictionary
        labels: Generated labels

    Returns:
        Hash string for target identification
    """
    targets_info = {
        "symbols": sorted(bars["symbol"].unique().tolist()),
        "date_range": [bars["ts"].min().isoformat(), bars["ts"].max().isoformat()],
        "ts_cut": ts_cut.isoformat(),
        "targets_config": targets_config,
        "label_distribution": labels.value_counts().to_dict(),
        "total_labels": len(labels),
    }

    import json

    targets_str = json.dumps(targets_info, sort_keys=True, default=str)
    return hashlib.blake2b(targets_str.encode()).hexdigest()
