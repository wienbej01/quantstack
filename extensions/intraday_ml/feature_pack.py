"""Intraday ML Feature Pack

Leakage-proof intraday feature pack with ≤150 features organized by families.
All features respect time discipline and use only data ≤ ts_cut.
"""

import math
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from qx_core.utils import utc_ns_to_datetime
from qx_features.core_basics import atr_m, rel_volume_m, vwap_m


class IntradayMLFeaturePack:
    """Leakage-proof feature pack for intraday ML.

    Computes features organized by families:
    - Returns & trend
    - Volatility & ranges
    - Volume/flow
    - VWAP distance & z-scores
    - Time-of-day seasonality
    - Cross-section signals
    """

    def __init__(self, config: Dict[str, Any]):
        """Initialize feature pack with configuration.

        Args:
            config: Feature configuration dictionary from features.yaml
        """
        self.config = config
        self.families = config.get("families", {})
        self.max_features = config.get("max_total_features", 150)

    def compute_features(
        self,
        df: pd.DataFrame,
        ts_cut: pd.Timestamp,
        validate_time_discipline: bool = True,
    ) -> pd.DataFrame:
        """Compute all enabled features respecting time discipline.

        Args:
            df: DataFrame with required OHLCV columns, sorted by [symbol, ts]
            ts_cut: Cut timestamp - features must only use data ≤ ts_cut
            validate_time_discipline: Whether to validate no forward look

        Returns:
            DataFrame with computed features, same index as input
        """
        if validate_time_discipline:
            self._validate_time_discipline(df, ts_cut)

        # Filter data to prevent leakage (ts should already be datetime)
        df_filtered = df[df["ts"] <= ts_cut].copy()

        features = []
        total_features = 0

        # Returns & trend features
        if self.families.get("returns_trend", {}).get("enabled", False):
            trend_features = self._compute_returns_trend(df_filtered)
            features.append(trend_features)
            total_features += len(trend_features.columns)

        # Volatility & range features
        if self.families.get("volatility_ranges", {}).get("enabled", False):
            vol_features = self._compute_volatility_ranges(df_filtered)
            features.append(vol_features)
            total_features += len(vol_features.columns)

        # Volume & flow features
        if self.families.get("volume_flow", {}).get("enabled", False):
            flow_features = self._compute_volume_flow(df_filtered)
            features.append(flow_features)
            total_features += len(flow_features.columns)

        # VWAP distance features
        if self.families.get("vwap_distance", {}).get("enabled", False):
            vwap_features = self._compute_vwap_distance(df_filtered)
            features.append(vwap_features)
            total_features += len(vwap_features.columns)

        # Time seasonality features
        if self.families.get("time_seasonality", {}).get("enabled", False):
            time_features = self._compute_time_seasonality(df_filtered)
            features.append(time_features)
            total_features += len(time_features.columns)

        # Cross-section features
        if self.families.get("cross_section", {}).get("enabled", False):
            cross_features = self._compute_cross_section(df_filtered)
            features.append(cross_features)
            total_features += len(cross_features.columns)

        # Price momentum features
        if self.families.get("price_momentum", {}).get("enabled", False):
            momentum_features = self._compute_price_momentum(df_filtered)
            features.append(momentum_features)
            total_features += len(momentum_features.columns)

        # Microstructure features
        if self.families.get("microstructure", {}).get("enabled", False):
            micro_features = self._compute_microstructure(df_filtered)
            features.append(micro_features)
            total_features += len(micro_features.columns)

        # Combine all features
        if features:
            all_features = pd.concat(features, axis=1)

            # Validate feature count
            if len(all_features.columns) > self.max_features:
                raise ValueError(
                    f"Generated {len(all_features.columns)} features, "
                    f"exceeding maximum of {self.max_features}"
                )

            # Filter back to original index (preserve rows after ts_cut)
            result = all_features.reindex(df.index)
            return result
        else:
            # Return empty DataFrame with original index
            return pd.DataFrame(index=df.index)

    def _validate_time_discipline(self, df: pd.DataFrame, ts_cut: pd.Timestamp):
        """Validate that input data respects time discipline."""
        # ts should already be datetime
        if df["ts"].max() > ts_cut:
            raise ValueError(
                f"Input data contains timestamps after ts_cut: "
                f"{df['ts'].max()} > {ts_cut}"
            )

    def _compute_returns_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute returns and trend features."""
        config = self.families["returns_trend"]
        windows = config.get("windows", [1, 5, 10, 20, 30])
        include_log = config.get("include_log", True)

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            for window in windows:
                # Simple returns
                simple_ret = group["close"].pct_change(window)
                features.append(
                    pd.Series(
                        simple_ret, index=group.index, name=f"f__ret__simple_{window}"
                    )
                )

                # Log returns (if enabled)
                if include_log:
                    log_ret = np.log(group["close"] / group["close"].shift(window))
                    features.append(
                        pd.Series(
                            log_ret, index=group.index, name=f"f__ret__log_{window}"
                        )
                    )

        return pd.concat(features, axis=1)

    def _compute_volatility_ranges(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute volatility and range features."""
        config = self.families["volatility_ranges"]
        atr_windows = config.get("atr_windows", [5, 14, 30])
        vol_windows = config.get("volatility_windows", [5, 10, 20, 30])
        range_ratios = config.get("range_ratios", [0.5, 1.0, 2.0])

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # ATR features (reuse qx_features primitive)
            for window in atr_windows:
                atr_single = atr_m(group, window)
                features.append(atr_single.rename(f"f__vol__atr_{window}"))

            # Rolling volatility
            for window in vol_windows:
                returns = group["close"].pct_change()
                volatility = returns.rolling(window).std() * np.sqrt(390)  # Annualized
                features.append(
                    pd.Series(
                        volatility,
                        index=group.index,
                        name=f"f__vol__rolling_std_{window}",
                    )
                )

            # Range ratios
            for ratio in range_ratios:
                high_low_range = group["high"] - group["low"]
                avg_range = high_low_range.rolling(20).mean()
                range_ratio = high_low_range / (avg_range * ratio + 1e-8)
                features.append(
                    pd.Series(
                        range_ratio, index=group.index, name=f"f__range__ratio_{ratio}"
                    )
                )

        return pd.concat(features, axis=1)

    def _compute_volume_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute volume and flow features."""
        config = self.families["volume_flow"]
        vol_windows = config.get("volume_windows", [5, 10, 20])
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        rvol_windows = config.get("relative_volume_windows", [10, 20, 30])

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Volume aggregations
            for window in vol_windows:
                vol_sum = group["volume"].rolling(window).sum()
                features.append(
                    pd.Series(vol_sum, index=group.index, name=f"f__vol__sum_{window}")
                )

            # VWAP features (reuse qx_features primitive)
            for window in vwap_windows:
                vwap_series = vwap_m(group, window)
                features.append(vwap_series.rename(f"f__vwap__value_{window}"))

            # Relative volume (custom implementation to avoid qx_features bug)
            for window in rvol_windows:
                # Compute relative volume using time-of-day averaging
                group_copy = group.copy()
                group_copy["tod_minutes"] = [
                    d.hour * 60 + d.minute
                    for d in utc_ns_to_datetime(group_copy["ts"].values)
                ]
                tod_avg_map = group_copy.groupby("tod_minutes")["volume"].mean()
                tod_avg_vol = group_copy["tod_minutes"].map(tod_avg_map)
                tod_avg_vol = tod_avg_vol.replace(0, 1)
                rvol = group_copy["volume"] / tod_avg_vol
                rvol = np.where(np.isnan(rvol), 1.0, rvol)
                rvol_series = pd.Series(
                    rvol, index=group.index, name=f"f__vol__rel_{window}"
                )
                features.append(rvol_series)

        return pd.concat(features, axis=1)

    def _compute_vwap_distance(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute VWAP distance and z-score features."""
        config = self.families["vwap_distance"]
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        zscore_windows = config.get("zscore_windows", [20, 30, 60])

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            for vwap_window in vwap_windows:
                # Compute VWAP
                vwap_series = vwap_m(group, vwap_window)

                # Distance from VWAP
                vwap_dist = (group["close"] - vwap_series) / group["close"]
                features.append(
                    pd.Series(
                        vwap_dist,
                        index=group.index,
                        name=f"f__vwap__dist_{vwap_window}",
                    )
                )

                # VWAP z-scores
                for z_window in zscore_windows:
                    vwap_returns = (group["close"] - vwap_series) / vwap_series
                    vwap_z = vwap_returns.rolling(z_window).apply(
                        lambda x: (x.iloc[-1] - x.mean()) / (x.std() + 1e-8)
                    )
                    features.append(
                        pd.Series(
                            vwap_z,
                            index=group.index,
                            name=f"f__vwap__z_{vwap_window}_{z_window}",
                        )
                    )

        return pd.concat(features, axis=1)

    def _compute_time_seasonality(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute time-of-day seasonality features."""
        config = self.families["time_seasonality"]
        include_hour = config.get("include_hour", True)
        include_minute = config.get("include_minute", True)
        include_day_of_week = config.get("include_day_of_week", True)
        cyclical_encoding = config.get("cyclical_encoding", True)

        features = []

        # Convert timestamps to datetime
        datetimes = utc_ns_to_datetime(df["ts"].values)

        if include_hour:
            hour_features = []
            if cyclical_encoding:
                # Cyclical encoding for hour
                hour_sin = np.sin(
                    2 * np.pi * np.array([d.hour for d in datetimes]) / 24
                )
                hour_cos = np.cos(
                    2 * np.pi * np.array([d.hour for d in datetimes]) / 24
                )
                hour_features.extend(
                    [
                        pd.Series(hour_sin, index=df.index, name="f__time__hour_sin"),
                        pd.Series(hour_cos, index=df.index, name="f__time__hour_cos"),
                    ]
                )
            else:
                # One-hot encoding for hour
                for hour in range(24):
                    hour_binary = [1 if d.hour == hour else 0 for d in datetimes]
                    hour_features.append(
                        pd.Series(
                            hour_binary, index=df.index, name=f"f__time__hour_{hour}"
                        )
                    )
            features.extend(hour_features)

        if include_minute:
            minute_features = []
            if cyclical_encoding:
                # Cyclical encoding for minute
                minute_sin = np.sin(
                    2 * np.pi * np.array([d.minute for d in datetimes]) / 60
                )
                minute_cos = np.cos(
                    2 * np.pi * np.array([d.minute for d in datetimes]) / 60
                )
                minute_features.extend(
                    [
                        pd.Series(
                            minute_sin, index=df.index, name="f__time__minute_sin"
                        ),
                        pd.Series(
                            minute_cos, index=df.index, name="f__time__minute_cos"
                        ),
                    ]
                )
            else:
                # One-hot encoding for minute (every 5 minutes)
                for minute in range(0, 60, 5):
                    minute_binary = [
                        1 if d.minute >= minute and d.minute < minute + 5 else 0
                        for d in datetimes
                    ]
                    minute_features.append(
                        pd.Series(
                            minute_binary,
                            index=df.index,
                            name=f"f__time__minute_{minute}",
                        )
                    )
            features.extend(minute_features)

        if include_day_of_week:
            day_features = []
            if cyclical_encoding:
                # Cyclical encoding for day of week
                day_sin = np.sin(
                    2 * np.pi * np.array([d.weekday() for d in datetimes]) / 7
                )
                day_cos = np.cos(
                    2 * np.pi * np.array([d.weekday() for d in datetimes]) / 7
                )
                day_features.extend(
                    [
                        pd.Series(day_sin, index=df.index, name="f__time__dow_sin"),
                        pd.Series(day_cos, index=df.index, name="f__time__dow_cos"),
                    ]
                )
            else:
                # One-hot encoding for day of week
                for day in range(7):
                    day_binary = [1 if d.weekday() == day else 0 for d in datetimes]
                    day_features.append(
                        pd.Series(
                            day_binary, index=df.index, name=f"f__time__dow_{day}"
                        )
                    )
            features.extend(day_features)

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_cross_section(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute cross-sectional ranking features."""
        config = self.families["cross_section"]
        percentile_windows = config.get("percentile_windows", [5, 20])
        include_zscores = config.get("include_zscores", True)

        features = []

        # For each timestamp, compute cross-sectional features
        for timestamp, group in df.groupby("ts"):
            if len(group) < 2:  # Need at least 2 symbols for cross-section
                continue

            for window in percentile_windows:
                # Cross-sectional percentile rank of returns
                if "close" in group.columns:
                    returns = (
                        group["close"].pct_change(window)
                        if window > 0
                        else group["close"]
                    )
                    percentiles = returns.rank(pct=True)

                    for idx, (orig_idx, percentile) in enumerate(
                        zip(group.index, percentiles)
                    ):
                        if not math.isnan(percentile):
                            feature_name = f"f__cross__ret_percentile_{window}"
                            if idx == 0:
                                features.append(
                                    pd.Series(
                                        [percentile],
                                        index=[orig_idx],
                                        name=feature_name,
                                    )
                                )
                            else:
                                # Append to existing series or create new
                                existing = [
                                    f for f in features if f.name == feature_name
                                ]
                                if existing:
                                    existing[0][orig_idx] = percentile
                                else:
                                    features.append(
                                        pd.Series(
                                            [percentile],
                                            index=[orig_idx],
                                            name=feature_name,
                                        )
                                    )

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_price_momentum(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute price momentum features."""
        config = self.families["price_momentum"]
        roc_windows = config.get("roc_windows", [1, 5, 10, 20])
        rsi_windows = config.get("rsi_windows", [14, 30])
        ma_windows = config.get("ma_windows", [5, 10, 20, 30])

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Rate of change
            for window in roc_windows:
                roc = group["close"].pct_change(window) * 100
                features.append(
                    pd.Series(roc, index=group.index, name=f"f__mom__roc_{window}")
                )

            # RSI
            for window in rsi_windows:
                delta = group["close"].diff()
                gain = delta.where(delta > 0, 0).rolling(window).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window).mean()
                rs = gain / (loss + 1e-8)
                rsi = 100 - (100 / (1 + rs))
                features.append(
                    pd.Series(rsi, index=group.index, name=f"f__mom__rsi_{window}")
                )

            # Moving averages and crossovers
            for window in ma_windows:
                ma = group["close"].rolling(window).mean()
                ma_ratio = group["close"] / ma
                features.append(
                    pd.Series(
                        ma_ratio, index=group.index, name=f"f__ma__ratio_{window}"
                    )
                )

        return pd.concat(features, axis=1)

    def _compute_microstructure(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute microstructure features."""
        config = self.families["microstructure"]
        spread_windows = config.get("spread_windows", [1, 5, 10])
        imbalance_windows = config.get("imbalance_windows", [1, 5, 10])
        include_vwap = config.get("include_vwap", True)

        features = []

        for symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Effective spread (simplified)
            for window in spread_windows:
                # Use high-low as proxy for spread
                spread = (group["high"] - group["low"]) / group["close"]
                avg_spread = spread.rolling(window).mean()
                features.append(
                    pd.Series(
                        avg_spread, index=group.index, name=f"f__micro__spread_{window}"
                    )
                )

            # Volume imbalance (buy vs sell pressure proxy)
            for window in imbalance_windows:
                # Use price change direction as proxy for buy/sell
                price_change = group["close"].diff()
                volume_weighted_change = price_change * group["volume"]
                imbalance = volume_weighted_change.rolling(window).sum()
                features.append(
                    pd.Series(
                        imbalance,
                        index=group.index,
                        name=f"f__micro__imbalance_{window}",
                    )
                )

            # VWAP features (if enabled)
            if include_vwap:
                vwap_5 = vwap_m(group, 5)
                features.append(vwap_5.rename("f__vwap__5m"))

        return pd.concat(features, axis=1)
