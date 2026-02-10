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

from ..utils.time_utils import DEFAULT_MARKET_TZ


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
        self.atr_window = targets_config.get("atr_window", 14)
        self.atr_multiplier = float(targets_config.get("atr_multiplier", 1.0))
        self.base_long_multiplier = float(
            targets_config.get("atr_multiplier_long", self.atr_multiplier)
        )
        self.base_short_multiplier = float(
            targets_config.get("atr_multiplier_short", self.atr_multiplier)
        )
        self.volatility_scaling_config = targets_config.get("volatility_scaling", {})
        self.directional_balance_config = targets_config.get("directional_balance", {})
        self.volatility_scaling_enabled = bool(self.volatility_scaling_config.get("enabled", False))
        self.directional_balance_enabled = bool(
            self.directional_balance_config.get("enabled", False)
        )
        self.risk_reward_config = targets_config.get("risk_reward", {}) or {}
        self.risk_reward_enabled = bool(self.risk_reward_config.get("enabled", False))
        self.min_r_multiple = float(max(self.risk_reward_config.get("min_r_multiple", 1.0), 1.0))
        rr_bounds = self.risk_reward_config.get("atr_return_bounds", {}) or {}
        self.atr_return_min = float(max(rr_bounds.get("min", 0.0) or 0.0, 0.0))
        self.atr_return_max = float(
            max(rr_bounds.get("max", 0.3) or 0.3, self.atr_return_min + 1e-6)
        )
        self.target_buffer = float(self.risk_reward_config.get("target_buffer", 0.0))
        self.session_constraints = targets_config.get("session_constraints", {}) or {}
        self.session_filter_enabled = bool(self.session_constraints.get("enabled", True))
        self.session_timezone = self.session_constraints.get("timezone", DEFAULT_MARKET_TZ)
        self.session_open = self.session_constraints.get("session_open", "09:30")
        self.session_close = self.session_constraints.get("session_close", "16:00")
        self.min_minutes_after_open = float(
            self.session_constraints.get("min_minutes_after_open", 0.0)
        )
        self.max_minutes_before_close = float(
            self.session_constraints.get("max_minutes_before_close", 0.0)
        )
        self.min_realized_return_pct = float(
            targets_config.get("min_realized_return_pct", 0.0)
        )
        self._last_directional_stats: dict[str, Any] | None = None

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
        self._last_directional_stats = None

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
        targets_hash = self._compute_targets_hash(bars, ts_cut, self.config, combined_labels)

        metadata = {
            "horizons": self.horizons,
            "atr_multiplier": self.atr_multiplier,
            "atr_window": self.atr_window,
            "ts_cut": ts_cut.isoformat(),
            "label_counts": combined_labels.value_counts().to_dict(),
            "horizon_metadata": all_metadata,
        }

        if self._last_directional_stats is not None:
            metadata["directional_balancing"] = self._last_directional_stats
        if self.risk_reward_enabled:
            metadata["risk_reward"] = {
                "min_r_multiple": self.min_r_multiple,
                "stop_atr_multiplier_long": self._stop_multiplier("long"),
                "stop_atr_multiplier_short": self._stop_multiplier("short"),
            }

        return LabelResult(labels=combined_labels, metadata=metadata, targets_hash=targets_hash)

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
            normalized_ts = pd.to_datetime(symbol_sorted["ts"], utc=True).dt.tz_convert(None)
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
            raise ValueError(f"Missing required columns for labeling: {sorted(missing_columns)}")

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
        atr_array = atr_values.fillna(fallback_atr).to_numpy(dtype=float, copy=False)
        np.maximum(atr_array, fallback_atr, out=atr_array)

        closes = working["close"].to_numpy(dtype=float, copy=False)
        timestamps = working["ts"].to_numpy(dtype="datetime64[ns]", copy=False)

        horizon_minutes = int(horizon if horizon is not None else min(self.horizons))
        horizon_delta = np.timedelta64(horizon_minutes, "m")

        base_long = self.base_long_multiplier
        base_short = self.base_short_multiplier
        volatility_multiplier = None

        if self.volatility_scaling_enabled:
            volatility_multiplier = self._compute_volatility_scaled_multiplier(working, atr_values)
            if volatility_multiplier is not None and np.isfinite(volatility_multiplier):
                base_long = float(volatility_multiplier)
                base_short = float(volatility_multiplier)

        (
            final_long,
            final_short,
            labels_array,
        ) = self._calibrate_directional_multipliers(
            closes=closes,
            timestamps=timestamps,
            atr_array=atr_array,
            fallback_atr=fallback_atr,
            horizon_delta=horizon_delta,
            base_long=base_long,
            base_short=base_short,
        )

        labels_series = pd.Series(labels_array, index=working.index, name="label")

        self._last_directional_stats = {
            "base_long_multiplier": base_long,
            "base_short_multiplier": base_short,
            "final_long_multiplier": final_long,
            "final_short_multiplier": final_short,
            "volatility_scaled_multiplier": volatility_multiplier,
            "long_count": int((labels_array == 1).sum()),
            "short_count": int((labels_array == -1).sum()),
            "neutral_count": int((labels_array == 0).sum()),
            "risk_reward_enabled": self.risk_reward_enabled,
            "min_r_multiple": (self.min_r_multiple if self.risk_reward_enabled else None),
        }

        return labels_series.astype(np.int8, copy=False)

    def _compute_volatility_scaled_multiplier(
        self, bars: pd.DataFrame, atr_values: pd.Series
    ) -> float | None:
        """Scale ATR multiplier by symbol volatility to support multi-ticker training."""
        if not self.volatility_scaling_enabled:
            return None

        config = self.volatility_scaling_config
        target_move_pct = float(config.get("target_move_pct", 0.0075))
        price_quantile = float(config.get("price_quantile", 0.5))
        atr_quantile = float(config.get("atr_quantile", 0.7))
        mix = float(config.get("mix", 0.6))
        bounds = config.get("multiplier_bounds", {})
        min_multiplier = float(bounds.get("min", 1e-4))
        max_multiplier = float(bounds.get("max", 0.12))

        closes = pd.to_numeric(bars["close"], errors="coerce")
        atr_series = pd.to_numeric(atr_values, errors="coerce")
        valid_mask = closes.notna() & closes.gt(0.0) & atr_series.notna() & atr_series.gt(0.0)
        if not valid_mask.any():
            return None

        close_ref = float(closes[valid_mask].quantile(price_quantile))
        atr_ref = float(atr_series[valid_mask].quantile(atr_quantile))

        if (
            not np.isfinite(close_ref)
            or not np.isfinite(atr_ref)
            or close_ref <= 0.0
            or atr_ref <= 0.0
        ):
            return None

        raw_multiplier = target_move_pct * close_ref / atr_ref
        if not np.isfinite(raw_multiplier) or raw_multiplier <= 0.0:
            return None

        mix = min(max(mix, 0.0), 1.0)
        base_multiplier = float(self.atr_multiplier)
        scaled_multiplier = (base_multiplier ** (1.0 - mix)) * (raw_multiplier**mix)
        return float(np.clip(scaled_multiplier, min_multiplier, max_multiplier))

    def _calibrate_directional_multipliers(  # noqa: PLR0913
        self,
        *,
        closes: np.ndarray,
        timestamps: np.ndarray,
        atr_array: np.ndarray,
        fallback_atr: float,
        horizon_delta: np.timedelta64,
        base_long: float,
        base_short: float,
    ) -> tuple[float, float, np.ndarray]:
        """Iteratively adjust long/short multipliers to balance directional depth."""
        long_multiplier = float(max(base_long, 1e-6))
        short_multiplier = float(max(base_short, 1e-6))

        labels = self._label_with_multipliers(
            closes=closes,
            timestamps=timestamps,
            atr_array=atr_array,
            fallback_atr=fallback_atr,
            horizon_delta=horizon_delta,
            long_multiplier=long_multiplier,
            short_multiplier=short_multiplier,
        )

        if (
            not self.directional_balance_enabled
            or len(closes) == 0
            or not np.isfinite(closes).any()
        ):
            return long_multiplier, short_multiplier, labels

        config = self.directional_balance_config
        max_iterations = int(config.get("max_iterations", 6))
        adjust_step = float(config.get("adjust_step", 0.12))
        tolerance = float(config.get("tolerance", 0.25))
        target_ratio = float(config.get("target_ratio", 1.0))
        min_directional = int(config.get("min_directional", 40))
        multiplier_bounds = config.get("multiplier_bounds", {})
        min_multiplier = float(multiplier_bounds.get("min", 0.002))
        max_multiplier = float(multiplier_bounds.get("max", 0.08))
        growth_factor = float(config.get("growth_factor", 0.5))

        adjust_step = max(0.0, min(adjust_step, 0.9))
        growth_factor = max(0.0, min(growth_factor, 1.5))

        best_labels = labels
        for _ in range(max_iterations):
            long_count = int((labels == 1).sum())
            short_count = int((labels == -1).sum())
            directional_total = long_count + short_count

            if directional_total < max(min_directional, 1):
                scale_down = max(1.0 - adjust_step, 0.05)
                long_multiplier = max(long_multiplier * scale_down, min_multiplier)
                short_multiplier = max(short_multiplier * scale_down, min_multiplier)
            else:
                if short_count == 0 and long_count == 0:
                    break

                if short_count == 0:
                    short_multiplier = max(short_multiplier * (1.0 - adjust_step), min_multiplier)
                elif long_count == 0:
                    long_multiplier = max(long_multiplier * (1.0 - adjust_step), min_multiplier)
                else:
                    ratio = long_count / short_count
                    if abs(ratio - target_ratio) <= tolerance:
                        break

                    if ratio < target_ratio:
                        long_multiplier = max(long_multiplier * (1.0 - adjust_step), min_multiplier)
                        short_multiplier = min(
                            short_multiplier * (1.0 + adjust_step * max(growth_factor, 0.1)),
                            max_multiplier,
                        )
                    else:
                        short_multiplier = max(
                            short_multiplier * (1.0 - adjust_step), min_multiplier
                        )
                        long_multiplier = min(
                            long_multiplier * (1.0 + adjust_step * max(growth_factor, 0.1)),
                            max_multiplier,
                        )

            labels = self._label_with_multipliers(
                closes=closes,
                timestamps=timestamps,
                atr_array=atr_array,
                fallback_atr=fallback_atr,
                horizon_delta=horizon_delta,
                long_multiplier=long_multiplier,
                short_multiplier=short_multiplier,
            )
            best_labels = labels

        return (
            float(np.clip(long_multiplier, min_multiplier, max_multiplier)),
            float(np.clip(short_multiplier, min_multiplier, max_multiplier)),
            best_labels,
        )

    def _label_with_multipliers(  # noqa: PLR0913
        self,
        *,
        closes: np.ndarray,
        timestamps: np.ndarray,
        atr_array: np.ndarray,
        fallback_atr: float,
        horizon_delta: np.timedelta64,
        long_multiplier: float,
        short_multiplier: float,
    ) -> np.ndarray:
        """Compute labels using separate ATR multipliers for long/short directions."""
        count = len(closes)
        labels = np.zeros(count, dtype=np.int8)
        if count == 0:
            return labels

        long_multiplier = max(float(long_multiplier), 1e-6)
        short_multiplier = max(float(short_multiplier), 1e-6)
        fallback_atr = max(float(fallback_atr), 1e-8)

        for idx in range(count):
            start_price = closes[idx]
            if not np.isfinite(start_price) or start_price <= 0.0:
                continue

            if not self._is_session_allowed(pd.Timestamp(timestamps[idx])):
                continue

            atr_value = atr_array[idx] if np.isfinite(atr_array[idx]) else fallback_atr
            if atr_value <= 0.0:
                atr_value = fallback_atr

            fallback_return = max(fallback_atr / max(start_price, 1e-6), 1e-6)
            atr_return = atr_value / max(start_price, 1e-6)
            atr_return = self._normalize_atr_return(atr_return, fallback_return)

            threshold_long = self._resolve_return_threshold(
                atr_return=atr_return,
                fallback_return=fallback_return,
                base_multiplier=long_multiplier,
                direction="long",
            )
            threshold_short = self._resolve_return_threshold(
                atr_return=atr_return,
                fallback_return=fallback_return,
                base_multiplier=short_multiplier,
                direction="short",
            )

            horizon_end = timestamps[idx] + horizon_delta
            next_idx = idx + 1

            while next_idx < count and timestamps[next_idx] <= horizon_end:
                fwd_return = (closes[next_idx] - start_price) / start_price
                if np.isfinite(fwd_return):
                    if fwd_return >= threshold_long and self._meets_realized_return(fwd_return):
                        labels[idx] = 1
                        break
                    if fwd_return <= -threshold_short and self._meets_realized_return(fwd_return):
                        labels[idx] = -1
                        break
                next_idx += 1

        return labels

    def _normalize_atr_return(self, atr_return: float, fallback_return: float) -> float:
        """Clamp ATR-derived returns to the configured bounds."""
        if not np.isfinite(atr_return) or atr_return <= 0.0:
            atr_return = fallback_return
        atr_return = max(atr_return, fallback_return)
        lower = max(self.atr_return_min, 1e-6)
        upper = max(self.atr_return_max, lower + 1e-6)
        return float(np.clip(atr_return, lower, upper))

    def _resolve_return_threshold(
        self,
        *,
        atr_return: float,
        fallback_return: float,
        base_multiplier: float,
        direction: str,
    ) -> float:
        """Translate ATR volatility into a minimum move threshold."""
        ratio = atr_return if np.isfinite(atr_return) and atr_return > 0 else fallback_return
        ratio = max(ratio, fallback_return)
        base_multiplier = max(base_multiplier, 1e-6)
        threshold = ratio * base_multiplier
        if not self.risk_reward_enabled:
            return threshold

        stop_multiplier = self._stop_multiplier(direction)
        stop_distance = ratio * stop_multiplier
        min_r = max(self.min_r_multiple, 1.0)
        target_buffer = max(self.target_buffer, 0.0)
        threshold = max(threshold, stop_distance * min_r + target_buffer)

        max_threshold = self.risk_reward_config.get("max_return_threshold")
        if max_threshold is not None:
            threshold = min(threshold, float(max_threshold))

        return threshold

    def _stop_multiplier(self, direction: str) -> float:
        """Return stop ATR multiplier for the requested direction."""
        if direction not in {"long", "short"}:
            raise ValueError(f"Unsupported direction '{direction}' for risk thresholds.")
        key = "stop_atr_multiplier_long" if direction == "long" else "stop_atr_multiplier_short"
        value = self.risk_reward_config.get(key)
        if value is None:
            value = self.risk_reward_config.get("stop_atr_multiplier")
        if value is None:
            base = self.base_long_multiplier if direction == "long" else self.base_short_multiplier
            value = base / max(self.min_r_multiple, 1.0)
        value = float(value)
        return float(max(value, 1e-6))

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
            filtered_symbol = symbol_frame[symbol_frame["ts"] <= current_timestamp].sort_values(
                "ts"
            )

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

            if symbol_atr is None or symbol_atr < self.config.get("require_min_atr", 0.01):
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
            label_series = pd.Series(labels, index=future_bars.index, name=f"label_{horizon}m")
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
        # Session/time filters
        if not self._is_session_allowed(current_row["ts"]):
            return 0

        # Get the index of current row
        current_idx = current_row.name
        group.index.get_loc(current_idx)

        # Calculate horizon end
        horizon_end_ts = current_row["ts"] + pd.Timedelta(minutes=horizon)

        # Get future bars within horizon
        future_mask = (group["ts"] > current_row["ts"]) & (group["ts"] <= horizon_end_ts)
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
            if fwd_return >= threshold and self._meets_realized_return(fwd_return):
                first_hit = 1
                break
            if fwd_return <= -threshold and self._meets_realized_return(fwd_return):
                first_hit = -1
                break

        return first_hit if first_hit is not None else 0

    def _is_session_allowed(self, timestamp: pd.Timestamp) -> bool:
        """Return True when timestamp is within configured session filters."""

        if not self.session_filter_enabled or pd.isna(timestamp):
            return True

        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is None:
            ts = ts.tz_localize(self.session_timezone)
        else:
            ts = ts.tz_convert(self.session_timezone)

        open_parts = self.session_open.split(":")
        close_parts = self.session_close.split(":")
        open_hour = int(open_parts[0])
        open_minute = int(open_parts[1]) if len(open_parts) > 1 else 0
        close_hour = int(close_parts[0])
        close_minute = int(close_parts[1]) if len(close_parts) > 1 else 0

        session_start = ts.replace(hour=open_hour, minute=open_minute, second=0, microsecond=0)
        session_end = ts.replace(hour=close_hour, minute=close_minute, second=0, microsecond=0)

        if ts < session_start or ts > session_end:
            return False

        minutes_since_open = (ts - session_start).total_seconds() / 60.0
        minutes_before_close = (session_end - ts).total_seconds() / 60.0

        return (
            minutes_since_open >= self.min_minutes_after_open
            and minutes_before_close >= self.max_minutes_before_close
        )

    def _meets_realized_return(self, fwd_return: float) -> bool:
        """Ensure realized forward move satisfies configured minimum."""

        if self.min_realized_return_pct <= 0:
            return True

        return abs(float(fwd_return)) >= self.min_realized_return_pct

    def _combine_horizon_labels(self, horizon_labels: dict[int, pd.Series]) -> pd.Series:
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

        targets_str = hashlib.blake2b(str(targets_info).encode(), digest_size=32).hexdigest()

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
