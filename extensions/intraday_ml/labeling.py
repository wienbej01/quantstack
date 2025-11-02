"""Intraday ML Labeling Module

Creates ATR-thresholded "prominent moves" labels with strict no-peek rules.
Implements first-hit logic for tri-class classification {-1, 0, +1}.
"""

import hashlib
import json
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from qx_features.core_basics import atr_m


@dataclass
class LabelResult:
    """Result of labeling operation with metadata."""

    labels: pd.Series
    metadata: dict[str, Any]
    targets_hash: str


class IntradayMLLabeler:
    """Creates ATR-thresholded labels with strict time discipline."""

    def __init__(self, targets_config: dict[str, Any]):
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
        # Issue deprecation warning for this method
        warnings.warn(
            (
                "create_labels method is deprecated. Use compute_label_for_timestamp "
                "for new implementations."
            ),
            DeprecationWarning,
            stacklevel=2,
        )

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

    def compute_label_for_timestamp(
        self, data_window: pd.DataFrame, current_timestamp: pd.Timestamp
    ) -> int:
        """Compute a tri-class label for a single timestamp using future data.

        Args:
            data_window: DataFrame with OHLCV data containing both historical
                        and future data relative to current_timestamp
            current_timestamp: Timestamp to compute label for; labels use only
                              data with timestamps > current_timestamp

        Returns:
            Label value: +1 (significant up move), -1 (significant down move),
            or 0 (neutral/no move)
        """
        if not isinstance(data_window, pd.DataFrame) or data_window.empty:
            return 0

        if "ts" not in data_window.columns or "symbol" not in data_window.columns:
            return 0

        required_columns = {"open", "high", "low", "close", "volume"}
        if not required_columns.issubset(data_window.columns):
            return 0

        labels = []

        for _, symbol_data in data_window.groupby("symbol"):
            symbol_sorted = symbol_data.sort_values("ts").reset_index(drop=True)

            if symbol_sorted.empty:
                continue

            label_series = self.compute_label_series(symbol_sorted)
            normalized_ts = pd.to_datetime(symbol_sorted["ts"], utc=True).dt.tz_convert(
                None
            )
            target_ts = pd.to_datetime(current_timestamp, utc=True).tz_convert(None)

            match_mask = normalized_ts == target_ts
            if not match_mask.any():
                continue

            label_idx = match_mask[match_mask].index[0]
            labels.append(int(label_series.iloc[label_idx]))

        if not labels:
            return 0

        label_counts = pd.Series(labels).value_counts()
        if len(label_counts) == 1 or label_counts.iloc[0] > label_counts.iloc[1]:
            return int(label_counts.index[0])

        return 0

    def compute_label_series(
        self,
        bars: pd.DataFrame,
        *,
        horizon: int | None = None,
    ) -> pd.Series:
        """Compute tri-class labels for every row in a single-symbol dataset.

        Args:
            bars: DataFrame with OHLCV data for a single symbol, sorted by timestamp
            horizon: Optional override for horizon minutes; defaults to min(self.horizons)

        Returns:
            Series of labels aligned with ``bars`` (values in {-1, 0, +1})
        """
        if bars.empty:
            return pd.Series(dtype=int)

        required_columns = {"ts", "open", "high", "low", "close", "volume", "symbol"}
        missing_columns = required_columns - set(bars.columns)
        if missing_columns:
            raise ValueError(
                f"Missing required columns for labeling: {sorted(missing_columns)}"
            )

        if bars["symbol"].nunique() != 1:
            raise ValueError(
                "compute_label_series expects data for a single symbol. "
                "Call per-symbol before aggregating."
            )

        working = bars.sort_values("ts").reset_index(drop=True)
        working["ts"] = pd.to_datetime(working["ts"], utc=True).dt.tz_convert(None)

        # Compute ATR once for the entire symbol history
        atr_values = atr_m(working, self.atr_window).reindex(working.index)

        fallback_atr = float(self.config.get("require_min_atr", 0.01))
        fallback_atr = max(fallback_atr, 1e-6)
        thresholds = atr_values.fillna(fallback_atr).to_numpy(dtype=float, copy=False)
        np.maximum(thresholds, fallback_atr, out=thresholds)
        thresholds *= float(self.atr_multiplier)
        threshold_floor = fallback_atr * float(self.atr_multiplier)

        closes = working["close"].to_numpy(dtype=float, copy=False)
        timestamps = working["ts"].to_numpy(dtype="datetime64[ns]", copy=False)

        horizon_minutes = int(horizon if horizon is not None else min(self.horizons))
        horizon_delta = np.timedelta64(horizon_minutes, "m")

        labels = np.zeros(len(working), dtype=np.int8)

        for idx in range(len(working)):
            start_price = closes[idx]
            if not np.isfinite(start_price) or start_price <= 0.0:
                continue

            threshold = (
                thresholds[idx] if np.isfinite(thresholds[idx]) else threshold_floor
            )
            if threshold <= 0.0:
                threshold = threshold_floor

            horizon_end = timestamps[idx] + horizon_delta
            next_idx = idx + 1

            while next_idx < len(working) and timestamps[next_idx] <= horizon_end:
                fwd_return = (closes[next_idx] - start_price) / start_price
                if fwd_return >= threshold:
                    labels[idx] = 1
                    break
                if fwd_return <= -threshold:
                    labels[idx] = -1
                    break
                next_idx += 1

        return pd.Series(labels, index=working.index, name="label")

    def _compute_atr_for_timestamp(
        self, historical_data: pd.DataFrame, current_timestamp: pd.Timestamp
    ) -> float | None:
        """Compute ATR value for a specific timestamp using historical data.

        Args:
            historical_data: Data with timestamps ≤ current_timestamp
            current_timestamp: The timestamp to compute ATR for

        Returns:
            ATR value or None if computation fails
        """
        if historical_data.empty:
            return None

        atr_values: list[float] = []

        for _, per_symbol in historical_data.groupby("symbol"):
            sorted_symbol = per_symbol.sort_values("ts")

            # Need enough data for ATR computation
            if len(sorted_symbol) < self.atr_window:
                continue

            try:
                symbol_atr = atr_m(sorted_symbol, self.atr_window)
                if not symbol_atr.empty:
                    # Get the most recent ATR value
                    latest_atr = symbol_atr.iloc[-1]
                    if not np.isnan(latest_atr) and latest_atr > 0:
                        atr_values.append(latest_atr)
            except Exception:
                continue

        # Return the median ATR across symbols
        if atr_values:
            return float(np.median(atr_values))
        return None

    def _get_current_prices(
        self, historical_data: pd.DataFrame, current_timestamp: pd.Timestamp
    ) -> dict[str, float]:
        """Get the most recent price for each symbol at or before current_timestamp.

        Args:
            historical_data: Historical data up to current_timestamp
            current_timestamp: The reference timestamp

        Returns:
            Dictionary mapping symbol to current price
        """
        current_prices: dict[str, float] = {}

        for symbol, symbol_frame in historical_data.groupby("symbol"):
            # Get data up to current_timestamp
            filtered_symbol = symbol_frame[
                symbol_frame["ts"] <= current_timestamp
            ].sort_values("ts")

            if not filtered_symbol.empty:
                # Use the most recent close price
                current_price = filtered_symbol.iloc[-1]["close"]
                if not np.isnan(current_price) and current_price > 0:
                    current_prices[symbol] = current_price

        return current_prices

    def _compute_single_symbol_label(
        self,
        future_symbol_data: pd.DataFrame,
        start_price: float,
        threshold: float,
        horizon: int,
        current_timestamp: pd.Timestamp,
    ) -> int:
        """Compute label for a single symbol using first-hit logic.

        Args:
            future_symbol_data: Future data for one symbol
            start_price: Starting price at current_timestamp
            threshold: ATR threshold for significant move
            horizon: Time horizon in minutes
            current_timestamp: Current timestamp

        Returns:
            Label: +1, -1, or 0
        """
        future_symbol_data = future_symbol_data.sort_values("ts")

        # Calculate horizon end
        horizon_end_ts = current_timestamp + pd.Timedelta(minutes=horizon)

        # Filter future data within horizon
        future_in_horizon = future_symbol_data[
            (future_symbol_data["ts"] > current_timestamp)
            & (future_symbol_data["ts"] <= horizon_end_ts)
        ]

        if future_in_horizon.empty:
            return 0

        # Track first threshold hit
        for _, future_row in future_in_horizon.iterrows():
            future_price = future_row["close"]

            # Calculate forward return
            fwd_return = (future_price - start_price) / start_price

            # Check if threshold is hit
            if fwd_return >= threshold:
                return 1
            elif fwd_return <= -threshold:
                return -1

        # No threshold hit within horizon
        return 0

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
        atr_values: list[pd.Series] = []

        for _, per_symbol in historical_bars.groupby("symbol"):
            sorted_symbol = per_symbol.sort_values("ts")
            symbol_atr = atr_m(sorted_symbol, self.atr_window)

            # Create mapping from timestamp to ATR value
            atr_map = pd.Series(symbol_atr.values, index=sorted_symbol.index)
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
    ) -> tuple[pd.Series, dict[str, Any]]:
        """Create labels for a specific horizon."""
        labels = []
        threshold_hits: dict[str, int] = {"positive": 0, "negative": 0, "neutral": 0}
        metadata: dict[str, Any] = {
            "horizon_minutes": horizon,
            "threshold_hits": threshold_hits,
        }

        for symbol, per_symbol in future_bars.groupby("symbol"):
            sorted_symbol = per_symbol.sort_values("ts")

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
            for _, row in sorted_symbol.iterrows():
                label = self._compute_first_hit_label(
                    sorted_symbol, row, threshold, horizon, ts_cut
                )
                labels.append(label)

                # Update metadata
                if label == 1:
                    threshold_hits["positive"] += 1
                elif label == -1:
                    threshold_hits["negative"] += 1
                else:
                    threshold_hits["neutral"] += 1

        if labels:
            label_series = pd.Series(
                labels, index=future_bars.index, name=f"label_{horizon}m"
            )
            return label_series, metadata
        else:
            return pd.Series(dtype=int), metadata

    def _get_latest_atr(self, atr_values: pd.Series, symbol: str) -> float | None:
        """Get the latest ATR value for a symbol."""
        # Find the most recent ATR value for this symbol
        symbol_atrs = atr_values[
            atr_values.index.isin(self._get_symbol_indices(atr_values, symbol))
        ]

        if len(symbol_atrs) > 0:
            return symbol_atrs.iloc[-1]
        else:
            return None

    def _get_symbol_indices(self, atr_values: pd.Series, symbol: str) -> list[int]:
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
        group.index.get_loc(current_idx)

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

        for _, future_row in future_bars.iterrows():
            # Calculate forward return
            fwd_return = (future_row["close"] - start_price) / start_price

            # Check if threshold is hit
            if fwd_return >= threshold:
                first_hit = 1
                future_row["ts"]
                break
            elif fwd_return <= -threshold:
                first_hit = -1
                future_row["ts"]
                break

        return first_hit if first_hit is not None else 0

    def _combine_horizon_labels(
        self, horizon_labels: dict[int, pd.Series]
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
        targets_config: dict[str, Any],
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
    targets_config: dict[str, Any],
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

    targets_str = json.dumps(targets_info, sort_keys=True, default=str)
    return hashlib.blake2b(targets_str.encode()).hexdigest()
