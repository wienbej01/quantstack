"""Intraday ML Feature Pack

Leakage-proof intraday feature pack with ≤150 features organized by families.
All features respect time discipline and use only data ≤ ts_cut.
"""

import math
from typing import Any

import numpy as np
import pandas as pd

from qx_core.utils import utc_ns_to_datetime
from qx_features.core_basics import atr_m, vwap_m


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

    def __init__(self, config: dict[str, Any]):
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
        market_context: pd.DataFrame | None = None,
    ) -> pd.DataFrame:
        """Compute all enabled features respecting time discipline.

        Args:
            df: DataFrame with required OHLCV columns, sorted by [symbol, ts]
            ts_cut: Cut timestamp - features must only use data ≤ ts_cut
            validate_time_discipline: Whether to validate no forward look
            market_context: Optional DataFrame with market data (SPY, VIX, etc.)
                          indexed by timestamp, for regime features.

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

        if self.families.get("conviction_signals", {}).get("enabled", False):
            conviction_features = self._compute_conviction_signals(df_filtered)
            features.append(conviction_features)
            total_features += len(conviction_features.columns)

        # Market Relative Strength
        if (
            self.families.get("market_relative_strength", {}).get("enabled", False)
            and market_context is not None
        ):
            rel_str_features = self._compute_market_relative_strength(
                df_filtered, market_context
            )
            features.append(rel_str_features)
            total_features += len(rel_str_features.columns)

        # Market Regime
        if (
            self.families.get("market_regime", {}).get("enabled", False)
            and market_context is not None
        ):
            regime_features = self._compute_market_regime(df_filtered, market_context)
            features.append(regime_features)
            total_features += len(regime_features.columns)

        # Price/Volume Proxy (VPA)
        if self.families.get("price_volume_proxy", {}).get("enabled", False):
            vpa_features = self._compute_price_volume_proxy(df_filtered)
            features.append(vpa_features)
            total_features += len(vpa_features.columns)

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
                f"Input data contains timestamps after ts_cut: {df['ts'].max()} > {ts_cut}"
            )

    def _compute_market_relative_strength(
        self, df: pd.DataFrame, market_context: pd.DataFrame
    ) -> pd.DataFrame:
        """Compute relative strength against market benchmark (SPY)."""
        # Align market data to symbol timestamps
        # We use merge_asof with direction='backward' to ensure no lookahead
        # However, since both are expected to be aligned by minute, simple join works
        # if indexes match. But df has 'ts' column, market_context has 'ts' index.

        # Optimized: Filter market context to relevant range first
        min_ts = df["ts"].min()
        max_ts = df["ts"].max()
        relevant_market = market_context[
            (market_context.index >= min_ts) & (market_context.index <= max_ts)
        ]

        # Merge on timestamp
        merged = pd.merge_asof(
            df.sort_values("ts"),
            relevant_market.sort_index(),
            left_on="ts",
            right_index=True,
            direction="backward",
        )
        # Ensure we respect the original df index
        merged.index = df.index

        features = []

        # Relative Strength 15m
        if "SPY_close" in merged.columns:
            spy_ret_15m = merged["SPY_close"].pct_change(15)
            sym_ret_15m = merged["close"].pct_change(15)
            rel_str = sym_ret_15m - spy_ret_15m
            features.append(rel_str.rename("f__mkt__rel_str_15m"))

            # Beta-Adjusted RS
            # Rolling Beta: Cov(Sym, SPY) / Var(SPY)
            sym_ret_1m = merged["close"].pct_change()
            spy_ret_1m = merged["SPY_close"].pct_change()

            rolling_cov = sym_ret_1m.rolling(60).cov(spy_ret_1m)
            rolling_var = spy_ret_1m.rolling(60).var()
            beta = rolling_cov / (rolling_var + 1e-8)

            beta_adj_rs = sym_ret_1m - (beta * spy_ret_1m)
            features.append(beta_adj_rs.rename("f__mkt__beta_adj_rs_60m"))

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_market_regime(
        self, df: pd.DataFrame, market_context: pd.DataFrame
    ) -> pd.DataFrame:
        """Compute market regime features (VIX, SPY Trends)."""
        min_ts = df["ts"].min()
        max_ts = df["ts"].max()
        relevant_market = market_context[
            (market_context.index >= min_ts) & (market_context.index <= max_ts)
        ]

        merged = pd.merge_asof(
            df.sort_values("ts"),
            relevant_market.sort_index(),
            left_on="ts",
            right_index=True,
            direction="backward",
        )
        merged.index = df.index

        features = []

        # VIX Level & Change
        if "VIX_close" in merged.columns:
            features.append(merged["VIX_close"].rename("f__regime__vix_level"))
            vix_roc = merged["VIX_close"].pct_change(60)
            features.append(vix_roc.rename("f__regime__vix_roc_60m"))

        # SPY Distance from VWAP
        # We approximate VWAP if not in market_context, but ideally market_context has it.
        # If not, we calculate simple distance from MA as proxy if VWAP missing
        if "SPY_close" in merged.columns:
            spy_ma_60 = merged["SPY_close"].rolling(60).mean()
            spy_dist = (merged["SPY_close"] - spy_ma_60) / spy_ma_60
            features.append(spy_dist.rename("f__regime__spy_dist_ma60"))

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_price_volume_proxy(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute proxies for order flow using Price/Volume Analysis (VPA)."""
        features = []
        
        # 1. Ease of Movement (Inverse Effort)
        # (High - Low) / (Volume + epsilon)
        # Normalized by price to make it comparable across assets? 
        # Actually, let's stick to the sprint spec: (High - Low) / Volume
        # We normalize by Price to make it percentage range per volume unit
        price_range_pct = (df["high"] - df["low"]) / df["close"]
        # Log volume to compress scale
        log_vol = np.log1p(df["volume"])
        ease_of_movement = price_range_pct / (log_vol + 1e-8)
        features.append(ease_of_movement.rename("f__vpa__ease_of_movement"))

        # 2. NR7 (Narrowest Range of last 7)
        price_range = df["high"] - df["low"]
        min_prev_6 = price_range.rolling(7).min() # window 7 includes current
        # But we want to check if current is narrower than previous 6
        # Shift rolling min of 6
        prev_6_min = price_range.shift(1).rolling(6).min()
        nr7 = (price_range < prev_6_min).astype(int)
        features.append(nr7.rename("f__vpa__nr7"))

        # 3. Buying Pressure (Close Location)
        # (Close - Low) / (High - Low)
        range_len = df["high"] - df["low"]
        close_loc = (df["close"] - df["low"]) / (range_len + 1e-8)
        features.append(close_loc.rename("f__vpa__close_loc"))

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_returns_trend(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute returns and trend features."""
        config = self.families["returns_trend"]
        windows = config.get("windows", [1, 5, 10, 20, 30])
        include_log = config.get("include_log", True)

        features = []

        for _symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            for window in windows:
                # Simple returns
                simple_ret = group["close"].pct_change(window)
                features.append(
                    pd.Series(simple_ret, index=group.index, name=f"f__ret__simple_{window}")
                )

                # Log returns (if enabled)
                if include_log:
                    log_ret = np.log(group["close"] / group["close"].shift(window))
                    features.append(
                        pd.Series(log_ret, index=group.index, name=f"f__ret__log_{window}")
                    )

        return pd.concat(features, axis=1)

    def _compute_volatility_ranges(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute volatility and range features."""
        config = self.families["volatility_ranges"]
        atr_windows = config.get("atr_windows", [5, 14, 30])
        vol_windows = config.get("volatility_windows", [5, 10, 20, 30])
        range_ratios = config.get("range_ratios", [0.5, 1.0, 2.0])

        features = []

        for _symbol, group in df.groupby("symbol"):
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
                    pd.Series(range_ratio, index=group.index, name=f"f__range__ratio_{ratio}")
                )

        return pd.concat(features, axis=1)

    def _compute_volume_flow(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute volume and flow features."""
        config = self.families["volume_flow"]
        vol_windows = config.get("volume_windows", [5, 10, 20])
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        rvol_windows = config.get("relative_volume_windows", [10, 20, 30])

        features = []

        for _symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Volume aggregations
            for window in vol_windows:
                vol_sum = group["volume"].rolling(window).sum()
                features.append(pd.Series(vol_sum, index=group.index, name=f"f__vol__sum_{window}"))

            # VWAP features (reuse qx_features primitive)
            for window in vwap_windows:
                vwap_series = vwap_m(group, window)
                features.append(vwap_series.rename(f"f__vwap__value_{window}"))

            # Relative volume (custom implementation to avoid qx_features bug)
            for window in rvol_windows:
                # Compute relative volume using time-of-day averaging
                group_copy = group.copy()
                group_copy["tod_minutes"] = [
                    d.hour * 60 + d.minute for d in utc_ns_to_datetime(group_copy["ts"].values)
                ]
                tod_avg_map = group_copy.groupby("tod_minutes")["volume"].mean()
                tod_avg_vol = group_copy["tod_minutes"].map(tod_avg_map)
                tod_avg_vol = tod_avg_vol.replace(0, 1)
                rvol = group_copy["volume"] / tod_avg_vol
                rvol = np.where(np.isnan(rvol), 1.0, rvol)
                rvol_series = pd.Series(rvol, index=group.index, name=f"f__vol__rel_{window}")
                features.append(rvol_series)

        return pd.concat(features, axis=1)

    def _compute_vwap_distance(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute VWAP distance and z-score features."""
        config = self.families["vwap_distance"]
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        zscore_windows = config.get("zscore_windows", [20, 30, 60])

        features = []

        for _symbol, group in df.groupby("symbol"):
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
                hour_sin = np.sin(2 * np.pi * np.array([d.hour for d in datetimes]) / 24)
                hour_cos = np.cos(2 * np.pi * np.array([d.hour for d in datetimes]) / 24)
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
                        pd.Series(hour_binary, index=df.index, name=f"f__time__hour_{hour}")
                    )
            features.extend(hour_features)

        if include_minute:
            minute_features = []
            if cyclical_encoding:
                # Cyclical encoding for minute
                minute_sin = np.sin(2 * np.pi * np.array([d.minute for d in datetimes]) / 60)
                minute_cos = np.cos(2 * np.pi * np.array([d.minute for d in datetimes]) / 60)
                minute_features.extend(
                    [
                        pd.Series(minute_sin, index=df.index, name="f__time__minute_sin"),
                        pd.Series(minute_cos, index=df.index, name="f__time__minute_cos"),
                    ]
                )
            else:
                # One-hot encoding for minute (every 5 minutes)
                for minute in range(0, 60, 5):
                    minute_binary = [
                        1 if d.minute >= minute and d.minute < minute + 5 else 0 for d in datetimes
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
                day_sin = np.sin(2 * np.pi * np.array([d.weekday() for d in datetimes]) / 7)
                day_cos = np.cos(2 * np.pi * np.array([d.weekday() for d in datetimes]) / 7)
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
                        pd.Series(day_binary, index=df.index, name=f"f__time__dow_{day}")
                    )
            features.extend(day_features)

        return pd.concat(features, axis=1) if features else pd.DataFrame(index=df.index)

    def _compute_cross_section(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute cross-sectional ranking features."""
        config = self.families["cross_section"]
        percentile_windows = config.get("percentile_windows", [5, 20])
        config.get("include_zscores", True)

        features = []

        # For each timestamp, compute cross-sectional features
        for _timestamp, group in df.groupby("ts"):
            if len(group) < 2:  # Need at least 2 symbols for cross-section
                continue

            for window in percentile_windows:
                # Cross-sectional percentile rank of returns
                if "close" in group.columns:
                    returns = group["close"].pct_change(window) if window > 0 else group["close"]
                    percentiles = returns.rank(pct=True)

                    for idx, (orig_idx, percentile) in enumerate(
                        zip(group.index, percentiles, strict=False)
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
                                existing = [f for f in features if f.name == feature_name]
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

        for _symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Rate of change
            for window in roc_windows:
                roc = group["close"].pct_change(window) * 100
                features.append(pd.Series(roc, index=group.index, name=f"f__mom__roc_{window}"))

            # RSI
            for window in rsi_windows:
                delta = group["close"].diff()
                gain = delta.where(delta > 0, 0).rolling(window).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window).mean()
                rs = gain / (loss + 1e-8)
                rsi = 100 - (100 / (1 + rs))
                features.append(pd.Series(rsi, index=group.index, name=f"f__mom__rsi_{window}"))

            # Moving averages and crossovers
            for window in ma_windows:
                ma = group["close"].rolling(window).mean()
                ma_ratio = group["close"] / ma
                features.append(
                    pd.Series(ma_ratio, index=group.index, name=f"f__ma__ratio_{window}")
                )

        return pd.concat(features, axis=1)

    def _compute_microstructure(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute microstructure features."""
        config = self.families["microstructure"]
        spread_windows = config.get("spread_windows", [1, 5, 10])
        imbalance_windows = config.get("imbalance_windows", [1, 5, 10])
        include_vwap = config.get("include_vwap", True)

        features = []

        for _symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")

            # Effective spread (simplified)
            for window in spread_windows:
                # Use high-low as proxy for spread
                spread = (group["high"] - group["low"]) / group["close"]
                avg_spread = spread.rolling(window).mean()
                features.append(
                    pd.Series(avg_spread, index=group.index, name=f"f__micro__spread_{window}")
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

    def _compute_conviction_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute conviction-oriented features to boost directional separation."""
        config = self.families["conviction_signals"]
        windows = config.get("windows", [3, 6, 12])

        feature_frames: list[pd.Series] = []

        for _symbol, group in df.groupby("symbol"):
            group = group.sort_values("ts")
            close = group["close"].astype(float)
            open_ = group["open"].astype(float)
            high = group["high"].astype(float)
            low = group["low"].astype(float)
            volume = group["volume"].astype(float)
            price_range = (high - low).replace(0.0, np.nan)
            safe_range = price_range.fillna(1e-8)

            # Pre-compute candlestick components used across windows
            body = close - open_
            upper_body = pd.concat([close, open_], axis=1).max(axis=1)
            lower_body = pd.concat([close, open_], axis=1).min(axis=1)
            upper_wick = high - upper_body
            lower_wick = lower_body - low
            wick_skew = (lower_wick - upper_wick) / (safe_range + 1e-8)
            body_strength = body / (safe_range + 1e-8)

            # Volume adjusted directional flow (Accumulation/Distribution)
            adl_component = ((close - low) - (high - close)) / (safe_range + 1e-8) * volume

            # On-balance volume style accumulator for conviction
            price_direction = np.sign(close.diff().fillna(0.0))
            obv = (price_direction * volume).fillna(0.0).cumsum()

            for window in windows:
                rolling_mean = close.rolling(window).mean()
                rolling_std = close.rolling(window).std(ddof=0).replace(0, np.nan)
                zscore = (close - rolling_mean) / (rolling_std + 1e-8)
                feature_frames.append(
                    pd.Series(zscore, index=group.index, name=f"f__conv__zscore_{window}")
                )

                momentum = close.pct_change(window)
                vol_mean = volume.rolling(window).mean()
                vol_ratio = volume / (vol_mean + 1e-8)
                feature_frames.append(
                    pd.Series(
                        momentum * vol_ratio,
                        index=group.index,
                        name=f"f__conv__mom_vol_{window}",
                    )
                )

                rolling_range = (high - low).rolling(window).sum()
                close_position = (close - low.rolling(window).min()) / (rolling_range + 1e-8)
                feature_frames.append(
                    pd.Series(
                        close_position,
                        index=group.index,
                        name=f"f__conv__range_pos_{window}",
                    )
                )

                # Directional body dominance (positive near 1 indicates strong bullish closes)
                body_strength_mean = body_strength.rolling(window).mean()
                feature_frames.append(
                    pd.Series(
                        body_strength_mean,
                        index=group.index,
                        name=f"f__conv__body_strength_{window}",
                    )
                )

                # Wick asymmetry (positive when lower wick dominates signalling absorption)
                wick_skew_mean = wick_skew.rolling(window).mean()
                feature_frames.append(
                    pd.Series(
                        wick_skew_mean,
                        index=group.index,
                        name=f"f__conv__wick_skew_{window}",
                    )
                )

                # Rolling accumulation/distribution normalised by volume
                adl_strength = adl_component.rolling(window).sum() / (
                    volume.rolling(window).sum() + 1e-8
                )
                feature_frames.append(
                    pd.Series(
                        adl_strength,
                        index=group.index,
                        name=f"f__conv__adl_strength_{window}",
                    )
                )

                # OBV momentum scaled by traded volume
                obv_momentum = obv.diff(window) / (volume.rolling(window).sum() + 1e-8)
                feature_frames.append(
                    pd.Series(
                        obv_momentum,
                        index=group.index,
                        name=f"f__conv__obv_mom_{window}",
                    )
                )

        return pd.concat(feature_frames, axis=1) if feature_frames else pd.DataFrame(index=df.index)
