"""Intraday ML Feature Registry

Registry that enumerates features, windows, dependencies, dtypes, and null policies.
Provides schema validation and feature metadata for the ML pipeline.
"""

from typing import Any

import pandas as pd

from .feature_pack import IntradayMLFeaturePack


class FeatureMetadata:
    """Metadata for a single feature."""

    def __init__(
        self,
        name: str,
        family: str,
        description: str,
        dtype: str,
        window: int | None = None,
        dependencies: list[str] | None = None,
        null_policy: str = "forward_fill",
        min_non_null_ratio: float = 0.9,
    ):
        """Initialize feature metadata.

        Args:
            name: Feature name
            family: Feature family (e.g., 'returns_trend')
            description: Human-readable description
            dtype: Expected data type ('float', 'int', 'bool')
            window: Lookback window in minutes (if applicable)
            dependencies: List of required input columns
            null_policy: How to handle null values
            min_non_null_ratio: Minimum ratio of non-null values required
        """
        self.name = name
        self.family = family
        self.description = description
        self.dtype = dtype
        self.window = window
        self.dependencies = dependencies or []
        self.null_policy = null_policy
        self.min_non_null_ratio = min_non_null_ratio


class IntradayMLFeatureRegistry:
    """Registry for intraday ML features with validation and metadata."""

    def __init__(self, config: dict[str, Any]):
        """Initialize feature registry.

        Args:
            config: Feature configuration from features.yaml
        """
        self.config = config
        self.families = config.get("families", {})
        self.feature_pack = IntradayMLFeaturePack(config)
        self._feature_metadata: dict[str, FeatureMetadata] = {}
        self._initialize_metadata()

    def _initialize_metadata(self):
        """Initialize feature metadata based on configuration."""
        # Returns & trend features
        if self.families.get("returns_trend", {}).get("enabled", False):
            self._add_returns_trend_metadata()

        # Volatility & range features
        if self.families.get("volatility_ranges", {}).get("enabled", False):
            self._add_volatility_ranges_metadata()

        # Volume & flow features
        if self.families.get("volume_flow", {}).get("enabled", False):
            self._add_volume_flow_metadata()

        # VWAP distance features
        if self.families.get("vwap_distance", {}).get("enabled", False):
            self._add_vwap_distance_metadata()

        # Time seasonality features
        if self.families.get("time_seasonality", {}).get("enabled", False):
            self._add_time_seasonality_metadata()

        # Cross-section features
        if self.families.get("cross_section", {}).get("enabled", False):
            self._add_cross_section_metadata()

        # Price momentum features
        if self.families.get("price_momentum", {}).get("enabled", False):
            self._add_price_momentum_metadata()

        # Microstructure features
        if self.families.get("microstructure", {}).get("enabled", False):
            self._add_microstructure_metadata()

    def _add_returns_trend_metadata(self):
        """Add metadata for returns and trend features."""
        config = self.families["returns_trend"]
        windows = config.get("windows", [1, 5, 10, 20, 30])
        include_log = config.get("include_log", True)

        for window in windows:
            # Simple returns
            self._feature_metadata[f"f__ret__simple_{window}"] = FeatureMetadata(
                name=f"f__ret__simple_{window}",
                family="returns_trend",
                description=f"Simple {window}-minute return",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

            # Log returns (if enabled)
            if include_log:
                self._feature_metadata[f"f__ret__log_{window}"] = FeatureMetadata(
                    name=f"f__ret__log_{window}",
                    family="returns_trend",
                    description=f"Log {window}-minute return",
                    dtype="float",
                    window=window,
                    dependencies=["close"],
                    null_policy="forward_fill",
                )

    def _add_volatility_ranges_metadata(self):
        """Add metadata for volatility and range features."""
        config = self.families["volatility_ranges"]
        atr_windows = config.get("atr_windows", [5, 14, 30])
        vol_windows = config.get("volatility_windows", [5, 10, 20, 30])
        range_ratios = config.get("range_ratios", [0.5, 1.0, 2.0])

        # ATR features
        for window in atr_windows:
            self._feature_metadata[f"f__vol__atr_{window}"] = FeatureMetadata(
                name=f"f__vol__atr_{window}",
                family="volatility_ranges",
                description=f"Average True Range over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["high", "low", "close"],
                null_policy="forward_fill",
            )

        # Rolling volatility
        for window in vol_windows:
            self._feature_metadata[f"f__vol__rolling_std_{window}"] = FeatureMetadata(
                name=f"f__vol__rolling_std_{window}",
                family="volatility_ranges",
                description=f"Rolling standard deviation over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

        # Range ratios
        for ratio in range_ratios:
            self._feature_metadata[f"f__range__ratio_{ratio}"] = FeatureMetadata(
                name=f"f__range__ratio_{ratio}",
                family="volatility_ranges",
                description=f"High-low range ratio (multiplier: {ratio})",
                dtype="float",
                dependencies=["high", "low"],
                null_policy="forward_fill",
            )

    def _add_volume_flow_metadata(self):
        """Add metadata for volume and flow features."""
        config = self.families["volume_flow"]
        vol_windows = config.get("volume_windows", [5, 10, 20])
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        rvol_windows = config.get("relative_volume_windows", [10, 20, 30])

        # Volume aggregations
        for window in vol_windows:
            self._feature_metadata[f"f__vol__sum_{window}"] = FeatureMetadata(
                name=f"f__vol__sum_{window}",
                family="volume_flow",
                description=f"Sum of volume over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["volume"],
                null_policy="forward_fill",
            )

        # VWAP features
        for window in vwap_windows:
            self._feature_metadata[f"f__vwap__value_{window}"] = FeatureMetadata(
                name=f"f__vwap__value_{window}",
                family="volume_flow",
                description=f"Volume-weighted average price over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["close", "volume"],
                null_policy="forward_fill",
            )

        # Relative volume
        for window in rvol_windows:
            self._feature_metadata[f"f__vol__rel_{window}"] = FeatureMetadata(
                name=f"f__vol__rel_{window}",
                family="volume_flow",
                description=f"Relative volume over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["volume", "ts"],
                null_policy="forward_fill",
            )

    def _add_vwap_distance_metadata(self):
        """Add metadata for VWAP distance features."""
        config = self.families["vwap_distance"]
        vwap_windows = config.get("vwap_windows", [5, 10, 20, 30])
        zscore_windows = config.get("zscore_windows", [20, 30, 60])

        for vwap_window in vwap_windows:
            # VWAP distance
            self._feature_metadata[f"f__vwap__dist_{vwap_window}"] = FeatureMetadata(
                name=f"f__vwap__dist_{vwap_window}",
                family="vwap_distance",
                description=f"Distance from {vwap_window}-minute VWAP",
                dtype="float",
                window=vwap_window,
                dependencies=["close", "volume"],
                null_policy="forward_fill",
            )

            # VWAP z-scores
            for z_window in zscore_windows:
                name = f"f__vwap__z_{vwap_window}_{z_window}"
                self._feature_metadata[name] = FeatureMetadata(
                    name=name,
                    family="vwap_distance",
                    description=f"VWAP z-score ({vwap_window}m VWAP, {z_window}m window)",
                    dtype="float",
                    window=max(vwap_window, z_window),
                    dependencies=["close", "volume"],
                    null_policy="forward_fill",
                )

    def _add_time_seasonality_metadata(self):
        """Add metadata for time seasonality features."""
        config = self.families["time_seasonality"]
        cyclical_encoding = config.get("cyclical_encoding", True)

        if config.get("include_hour", True):
            if cyclical_encoding:
                self._feature_metadata["f__time__hour_sin"] = FeatureMetadata(
                    name="f__time__hour_sin",
                    family="time_seasonality",
                    description="Sine encoding of hour of day",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
                self._feature_metadata["f__time__hour_cos"] = FeatureMetadata(
                    name="f__time__hour_cos",
                    family="time_seasonality",
                    description="Cosine encoding of hour of day",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
            else:
                for hour in range(24):
                    name = f"f__time__hour_{hour}"
                    self._feature_metadata[name] = FeatureMetadata(
                        name=name,
                        family="time_seasonality",
                        description=f"One-hot encoding for hour {hour}",
                        dtype="int",
                        dependencies=["ts"],
                        null_policy="zero_fill",
                    )

        if config.get("include_minute", True):
            if cyclical_encoding:
                self._feature_metadata["f__time__minute_sin"] = FeatureMetadata(
                    name="f__time__minute_sin",
                    family="time_seasonality",
                    description="Sine encoding of minute of hour",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
                self._feature_metadata["f__time__minute_cos"] = FeatureMetadata(
                    name="f__time__minute_cos",
                    family="time_seasonality",
                    description="Cosine encoding of minute of hour",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
            else:
                for minute in range(0, 60, 5):
                    name = f"f__time__minute_{minute}"
                    self._feature_metadata[name] = FeatureMetadata(
                        name=name,
                        family="time_seasonality",
                        description=f"One-hot encoding for minute {minute}-{minute+4}",
                        dtype="int",
                        dependencies=["ts"],
                        null_policy="zero_fill",
                    )

        if config.get("include_day_of_week", True):
            if cyclical_encoding:
                self._feature_metadata["f__time__dow_sin"] = FeatureMetadata(
                    name="f__time__dow_sin",
                    family="time_seasonality",
                    description="Sine encoding of day of week",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
                self._feature_metadata["f__time__dow_cos"] = FeatureMetadata(
                    name="f__time__dow_cos",
                    family="time_seasonality",
                    description="Cosine encoding of day of week",
                    dtype="float",
                    dependencies=["ts"],
                    null_policy="zero_fill",
                )
            else:
                for day in range(7):
                    name = f"f__time__dow_{day}"
                    self._feature_metadata[name] = FeatureMetadata(
                        name=name,
                        family="time_seasonality",
                        description=f"One-hot encoding for day {day}",
                        dtype="int",
                        dependencies=["ts"],
                        null_policy="zero_fill",
                    )

    def _add_cross_section_metadata(self):
        """Add metadata for cross-sectional features."""
        config = self.families["cross_section"]
        percentile_windows = config.get("percentile_windows", [5, 20])

        for window in percentile_windows:
            name = f"f__cross__ret_percentile_{window}"
            self._feature_metadata[name] = FeatureMetadata(
                name=name,
                family="cross_section",
                description=f"Cross-sectional percentile rank of {window}-minute returns",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

    def _add_price_momentum_metadata(self):
        """Add metadata for price momentum features."""
        config = self.families["price_momentum"]
        roc_windows = config.get("roc_windows", [1, 5, 10, 20])
        rsi_windows = config.get("rsi_windows", [14, 30])
        ma_windows = config.get("ma_windows", [5, 10, 20, 30])

        # Rate of change
        for window in roc_windows:
            self._feature_metadata[f"f__mom__roc_{window}"] = FeatureMetadata(
                name=f"f__mom__roc_{window}",
                family="price_momentum",
                description=f"Rate of change over {window} minutes (%)",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

        # RSI
        for window in rsi_windows:
            self._feature_metadata[f"f__mom__rsi_{window}"] = FeatureMetadata(
                name=f"f__mom__rsi_{window}",
                family="price_momentum",
                description=f"Relative Strength Index over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

        # Moving average ratios
        for window in ma_windows:
            self._feature_metadata[f"f__ma__ratio_{window}"] = FeatureMetadata(
                name=f"f__ma__ratio_{window}",
                family="price_momentum",
                description=f"Price to {window}-minute moving average ratio",
                dtype="float",
                window=window,
                dependencies=["close"],
                null_policy="forward_fill",
            )

    def _add_microstructure_metadata(self):
        """Add metadata for microstructure features."""
        config = self.families["microstructure"]
        spread_windows = config.get("spread_windows", [1, 5, 10])
        imbalance_windows = config.get("imbalance_windows", [1, 5, 10])

        # Effective spread
        for window in spread_windows:
            self._feature_metadata[f"f__micro__spread_{window}"] = FeatureMetadata(
                name=f"f__micro__spread_{window}",
                family="microstructure",
                description=f"Effective spread over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["high", "low", "close"],
                null_policy="forward_fill",
            )

        # Volume imbalance
        for window in imbalance_windows:
            self._feature_metadata[f"f__micro__imbalance_{window}"] = FeatureMetadata(
                name=f"f__micro__imbalance_{window}",
                family="microstructure",
                description=f"Volume imbalance over {window} minutes",
                dtype="float",
                window=window,
                dependencies=["close", "volume"],
                null_policy="forward_fill",
            )

        # VWAP (if enabled)
        if config.get("include_vwap", True):
            self._feature_metadata["f__vwap__5m"] = FeatureMetadata(
                name="f__vwap__5m",
                family="microstructure",
                description="5-minute VWAP",
                dtype="float",
                window=5,
                dependencies=["close", "volume"],
                null_policy="forward_fill",
            )

    def get_feature_names(self) -> list[str]:
        """Get list of all registered feature names."""
        return list(self._feature_metadata.keys())

    def get_features_by_family(self, family: str) -> list[str]:
        """Get feature names belonging to a specific family."""
        return [
            name
            for name, meta in self._feature_metadata.items()
            if meta.family == family
        ]

    def get_feature_metadata(self, feature_name: str) -> FeatureMetadata | None:
        """Get metadata for a specific feature."""
        return self._feature_metadata.get(feature_name)

    def get_all_metadata(self) -> dict[str, FeatureMetadata]:
        """Get all feature metadata."""
        return self._feature_metadata.copy()

    def validate_features(self, df: pd.DataFrame) -> dict[str, Any]:
        """Validate computed features against registry metadata.

        Args:
            df: DataFrame with computed features

        Returns:
            Validation results with any issues found
        """
        validation_results = {
            "valid": True,
            "issues": [],
            "feature_count": len(df.columns),
            "expected_count": len(self._feature_metadata),
            "missing_features": [],
            "unexpected_features": [],
            "null_ratio_issues": [],
            "dtype_issues": [],
        }

        # Check for missing features
        expected_features = set(self.get_feature_names())
        actual_features = set(df.columns)
        validation_results["missing_features"] = list(
            expected_features - actual_features
        )
        validation_results["unexpected_features"] = list(
            actual_features - expected_features
        )

        if validation_results["missing_features"]:
            validation_results["valid"] = False
            validation_results["issues"].append(
                f"Missing {len(validation_results['missing_features'])} expected features"
            )

        # Validate each feature's properties
        for feature_name in actual_features:
            if feature_name in self._feature_metadata:
                metadata = self._feature_metadata[feature_name]
                feature_data = df[feature_name]

                # Check null ratio
                if hasattr(feature_data, "columns"):  # DataFrame case
                    # Take first column if multiple
                    first_col = feature_data.iloc[:, 0]
                    non_null_count = first_col.notna().sum()
                    total_count = len(first_col)
                    non_null_ratio = float(
                        non_null_count / total_count if total_count > 0 else 0.0
                    )
                elif hasattr(feature_data, "index"):  # Series case
                    non_null_count = feature_data.notna().sum()
                    # Handle case where sum() returns a Series (duplicate data)
                    if hasattr(non_null_count, "iloc"):
                        non_null_count = non_null_count.iloc[0]
                    total_count = len(feature_data)
                    non_null_ratio = float(
                        non_null_count / total_count if total_count > 0 else 0.0
                    )
                else:  # Scalar case
                    non_null_ratio = float(feature_data)

                min_ratio = float(metadata.min_non_null_ratio)
                if non_null_ratio < min_ratio:
                    validation_results["null_ratio_issues"].append(
                        {
                            "feature": feature_name,
                            "actual_ratio": non_null_ratio,
                            "min_required": metadata.min_non_null_ratio,
                        }
                    )
                    validation_results["valid"] = False

                # Check dtype (basic check)
                expected_dtype = metadata.dtype

                # Handle both Series and DataFrame cases
                if hasattr(feature_data, "columns"):  # DataFrame case
                    actual_dtype = (
                        str(feature_data.dtypes.iloc[0])
                        if len(feature_data.columns) > 0
                        else "unknown"
                    )
                else:  # Series case
                    actual_dtype = str(feature_data.dtype)

                if expected_dtype == "float" and not pd.api.types.is_float_dtype(
                    feature_data
                ) or expected_dtype == "int" and not pd.api.types.is_integer_dtype(
                    feature_data
                ):
                    validation_results["dtype_issues"].append(
                        {
                            "feature": feature_name,
                            "expected": expected_dtype,
                            "actual": actual_dtype,
                        }
                    )

        if validation_results["null_ratio_issues"]:
            validation_results["issues"].append(
                f"Found {len(validation_results['null_ratio_issues'])} features with null ratio issues"
            )

        if validation_results["dtype_issues"]:
            validation_results["issues"].append(
                f"Found {len(validation_results['dtype_issues'])} features with dtype issues"
            )

        return validation_results

    def get_max_window(self) -> int:
        """Get maximum lookback window across all features."""
        max_window = 0
        for metadata in self._feature_metadata.values():
            if metadata.window and metadata.window > max_window:
                max_window = metadata.window
        return max_window

    def count_features_by_family(self) -> dict[str, int]:
        """Count features by family."""
        counts = {}
        for metadata in self._feature_metadata.values():
            counts[metadata.family] = counts.get(metadata.family, 0) + 1
        return counts
