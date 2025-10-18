"""Feature pack registry for applying feature compositions."""

from typing import Any

import pandas as pd

from qx_features.core_basics import (
    atr_m,
    compute_all_core_features,
    compute_warmup_masks,
    get_feature_name,
    rel_volume_m,
    vwap_m,
)
from qx_features.regime.features import (
    adx_proxy,
    band_position,
    compute_all_regime_features,
    mod_normalized_volatility,
    stress_metrics,
    variance_ratio,
)
from qx_features.vpa import compute_vpa_features


class FeatureRegistry:
    """Registry for managing feature packs and their application."""

    _FEATURE_FUNCTIONS = {
        "vwap": vwap_m,
        "rel_volume": rel_volume_m,
        "atr": atr_m,
        "mod_normalized_volatility": mod_normalized_volatility,
        "variance_ratio": variance_ratio,
        "adx_proxy": adx_proxy,
        "band_position": band_position,
        "stress_metrics": stress_metrics,
    }

    _PREDEFINED_PACKS = {
        "core_basics": {
            "vwap": {"lookback_m": 30},
            "rel_volume": {"lookback_m": 30},
            "atr": {"lookback_m": 14},
        },
        "fast_indicators": {
            "vwap": {"lookback_m": 10},
            "rel_volume": {"lookback_m": 10},
            "atr": {"lookback_m": 7},
        },
        "slow_indicators": {
            "vwap": {"lookback_m": 60},
            "rel_volume": {"lookback_m": 60},
            "atr": {"lookback_m": 21},
        },
        "regime_basics": {
            "mod_normalized_volatility": {"lookback_m": 30, "min_periods": 5},
            "variance_ratio": {"short_window": 10, "long_window": 60, "min_periods": 3},
            "adx_proxy": {"lookback_m": 14, "min_periods": 3},
            "band_position": {"window_m": 20, "std_dev": 2.0, "min_periods": 5},
            "stress_metrics": {
                "volatility_window": 10,
                "volume_window": 10,
                "vol_threshold": 2.0,
                "volume_threshold": 3.0,
                "min_periods": 3,
            },
        },
        "regime_fast": {
            "mod_normalized_volatility": {"lookback_m": 15, "min_periods": 3},
            "variance_ratio": {"short_window": 5, "long_window": 30, "min_periods": 2},
            "adx_proxy": {"lookback_m": 7, "min_periods": 2},
            "band_position": {"window_m": 10, "std_dev": 2.0, "min_periods": 3},
            "stress_metrics": {
                "volatility_window": 5,
                "volume_window": 5,
                "vol_threshold": 1.5,
                "volume_threshold": 2.0,
                "min_periods": 2,
            },
        },
        "regime_slow": {
            "mod_normalized_volatility": {"lookback_m": 60, "min_periods": 10},
            "variance_ratio": {
                "short_window": 20,
                "long_window": 120,
                "min_periods": 5,
            },
            "adx_proxy": {"lookback_m": 28, "min_periods": 5},
            "band_position": {"window_m": 40, "std_dev": 2.0, "min_periods": 10},
            "stress_metrics": {
                "volatility_window": 20,
                "volume_window": 20,
                "vol_threshold": 2.5,
                "volume_threshold": 3.5,
                "min_periods": 5,
            },
        },
        "vpa_patterns": {
            "volume_spike_threshold": 2.0,
            "price_breakout_window": 20,
            "divergence_window": 10,
            "absorption_lookback": 5,
            "climax_volume_pct": 0.95,
        },
    }

    @classmethod
    def list_available_features(cls) -> list[str]:
        """List all available feature types."""
        return list(cls._FEATURE_FUNCTIONS.keys())

    @classmethod
    def list_predefined_packs(cls) -> list[str]:
        """List all predefined feature packs."""
        return list(cls._PREDEFINED_PACKS.keys())

    @classmethod
    def get_predefined_pack(cls, pack_name: str) -> dict[str, dict[str, Any]]:
        """Get a predefined feature pack configuration."""
        if pack_name not in cls._PREDEFINED_PACKS:
            raise ValueError(f"Unknown predefined pack: {pack_name}")
        return cls._PREDEFINED_PACKS[pack_name].copy()

    @classmethod
    def register_feature(cls, name: str, func):
        """Register a custom feature function."""
        cls._FEATURE_FUNCTIONS[name] = func

    @classmethod
    def register_pack(cls, name: str, config: dict[str, dict[str, Any]]):
        """Register a custom feature pack configuration."""
        cls._PREDEFINED_PACKS[name] = config.copy()


def apply(
    df: pd.DataFrame, packs: list[dict[str, Any]], sort_by_symbol_ts: bool = True
) -> pd.DataFrame:
    """Apply multiple feature packs to the dataframe.

    Args:
        df: Input dataframe with required columns
        packs: List of feature pack configurations
        sort_by_symbol_ts: Whether to sort by [symbol, ts] before applying features

    Returns:
        DataFrame with features added and warmup mask
    """
    if not packs:
        return df.copy()

    result = df.copy()

    # Sort if requested
    if sort_by_symbol_ts and "symbol" in result.columns and "ts" in result.columns:
        result = result.sort_values(["symbol", "ts"]).reset_index(drop=True)

    # Collect all feature windows for warmup calculation
    all_feature_windows = {}

    # Apply each feature pack
    for pack in packs:
        pack_type = pack.get("type", pack.get("name"))
        params = pack.get("params", pack.get("config", {}))

        if pack_type == "core_basics":
            # Special case for core_basics - use optimized function
            result = _apply_core_basics_optimized(result, params)
        elif pack_type == "regime_basics":
            # Special case for regime basics - use optimized function
            result = _apply_regime_features_optimized(result, params)
        elif pack_type == "regime_fast":
            # Special case for regime fast - use optimized function
            result = _apply_regime_features_optimized(result, params, variant="fast")
        elif pack_type == "regime_slow":
            # Special case for regime slow - use optimized function
            result = _apply_regime_features_optimized(result, params, variant="slow")
        elif pack_type == "vpa_patterns":
            # Special case for VPA patterns
            result = _apply_vpa_patterns(result, params)
        elif pack_type in FeatureRegistry._PREDEFINED_PACKS:
            # Apply predefined pack
            if pack_type == "vpa_patterns":
                # Special case for VPA patterns (not a feature pack)
                pack_config = FeatureRegistry.get_predefined_pack(pack_type)
                result = _apply_vpa_patterns(result, pack_config)
            else:
                pack_config = FeatureRegistry.get_predefined_pack(pack_type)
                result = _apply_feature_pack(result, pack_config)
        elif isinstance(pack_type, dict):
            # Direct feature specification
            result = _apply_feature_pack(result, pack_type)
        else:
            raise ValueError(f"Unknown feature pack: {pack_type}")

        # Track feature windows for warmup
        if pack_type == "core_basics":
            all_feature_windows.update(
                {
                    "vwap": params.get("vwap_window_m", params.get("vwap_window", 30)),
                    "rel_volume": params.get(
                        "rel_vol_window_m", params.get("rel_vol_window", 30)
                    ),
                    "atr": params.get("atr_window", params.get("atr_window", 14)),
                }
            )
        elif pack_type in FeatureRegistry._PREDEFINED_PACKS:
            if pack_type == "vpa_patterns":
                # VPA patterns don't use window-based warmup
                pass
            else:
                pack_config = FeatureRegistry.get_predefined_pack(pack_type)
                for feature, feature_params in pack_config.items():
                    window = feature_params.get(
                        "lookback_m", feature_params.get("window_m", 30)
                    )
                    all_feature_windows[feature] = max(
                        all_feature_windows.get(feature, 0), window
                    )

    # Compute final warmup mask if not already present
    if "f__warmup_ok" not in result.columns and all_feature_windows:
        result["f__warmup_ok"] = compute_warmup_masks(result, all_feature_windows)

    return result


def _apply_core_basics_optimized(
    df: pd.DataFrame, params: dict[str, Any]
) -> pd.DataFrame:
    """Apply core basics features using optimized function."""
    vwap_window = params.get("vwap_window_m", params.get("vwap_window", 30))
    rvol_window = params.get("rel_vol_window_m", params.get("rel_vol_window", 30))
    atr_window = params.get("atr_window_m", params.get("atr_window", 14))

    return compute_all_core_features(df, vwap_window, rvol_window, atr_window)


def _apply_vpa_patterns(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Apply VPA pattern features."""
    return compute_vpa_features(df, **params)


def _apply_regime_features_optimized(
    df: pd.DataFrame, params: dict[str, Any], variant: str = "basics"
) -> pd.DataFrame:
    """Apply regime features using optimized function."""
    if variant == "fast":
        return compute_all_regime_features(
            df,
            volatility_window=params.get("volatility_window", 15),
            variance_short=params.get("variance_short", 5),
            variance_long=params.get("variance_long", 30),
            adx_window=params.get("adx_window", 7),
            band_window=params.get("band_window", 10),
            stress_vol_window=params.get("stress_vol_window", 5),
            stress_vol_threshold=params.get("stress_vol_threshold", 1.5),
            stress_volume_threshold=params.get("stress_volume_threshold", 2.0),
        )
    elif variant == "slow":
        return compute_all_regime_features(
            df,
            volatility_window=params.get("volatility_window", 60),
            variance_short=params.get("variance_short", 20),
            variance_long=params.get("variance_long", 120),
            adx_window=params.get("adx_window", 28),
            band_window=params.get("band_window", 40),
            stress_vol_window=params.get("stress_vol_window", 20),
            stress_vol_threshold=params.get("stress_vol_threshold", 2.5),
            stress_volume_threshold=params.get("stress_volume_threshold", 3.5),
        )
    else:  # basics
        return compute_all_regime_features(
            df,
            volatility_window=params.get("volatility_window", 30),
            variance_short=params.get("variance_short", 10),
            variance_long=params.get("variance_long", 60),
            adx_window=params.get("adx_window", 14),
            band_window=params.get("band_window", 20),
            stress_vol_window=params.get("stress_vol_window", 10),
            stress_vol_threshold=params.get("stress_vol_threshold", 2.0),
            stress_volume_threshold=params.get("stress_volume_threshold", 3.0),
        )


def _apply_feature_pack(
    df: pd.DataFrame, config: dict[str, dict[str, Any]]
) -> pd.DataFrame:
    """Apply a feature pack configuration."""
    result = df.copy()

    for feature_name, params in config.items():
        if feature_name not in FeatureRegistry._FEATURE_FUNCTIONS:
            raise ValueError(f"Unknown feature: {feature_name}")

        feature_func = FeatureRegistry._FEATURE_FUNCTIONS[feature_name]

        # Get window parameter for naming
        window = params.get("lookback_m", params.get("window_m", 30))
        feature_col_name = get_feature_name(feature_name, params)

        # Compute feature
        feature_values = feature_func(result, window)
        result[feature_col_name] = feature_values

    return result


def apply_feature_packs(df: pd.DataFrame, packs: list[dict[str, Any]]) -> pd.DataFrame:
    """Legacy compatibility function - use apply() instead."""
    return apply(df, packs)


def _apply_core_basics(df: pd.DataFrame, params: dict[str, Any]) -> pd.DataFrame:
    """Legacy compatibility function for core basics."""
    return _apply_core_basics_optimized(df, params)


def compute_feature_hashes(
    df: pd.DataFrame, feature_cols: list[str] | None = None
) -> dict[str, str]:
    """Compute hashes for feature columns.

    Args:
        df: DataFrame with features
        feature_cols: List of feature columns to hash (auto-detected if None)

    Returns:
        Dictionary mapping feature names to hashes
    """
    from qx_core.hashers import hash_dataframe

    if feature_cols is None:
        # Auto-detect feature columns (those starting with 'f__')
        feature_cols = [col for col in df.columns if col.startswith("f__")]

    hashes = {}
    for col in feature_cols:
        if col in df.columns:
            # Hash just this column + symbol + ts for context
            cols_to_hash = ["symbol", "ts", col]
            available_cols = [c for c in cols_to_hash if c in df.columns]
            if available_cols:
                hashes[col] = hash_dataframe(df[available_cols])

    return hashes


def validate_feature_pack_config(config: dict[str, Any]) -> None:
    """Validate feature pack configuration.

    Args:
        config: Feature pack configuration

    Raises:
        ValueError: If configuration is invalid
    """
    if not isinstance(config, dict):
        raise ValueError("Feature pack config must be a dictionary")

    if "type" not in config and "name" not in config:
        raise ValueError("Feature pack must have 'type' or 'name' field")

    pack_type = config.get("type", config.get("name"))

    if pack_type == "core_basics":
        # Validate core basics parameters
        params = config.get("params", {})
        for param in ["vwap_window_m", "rel_vol_window_m", "atr_window"]:
            if param in params:
                if not isinstance(params[param], int) or params[param] <= 0:
                    raise ValueError(f"Parameter {param} must be a positive integer")

    elif pack_type in FeatureRegistry._PREDEFINED_PACKS:
        # Predefined packs are already validated
        pass

    else:
        # Validate custom feature pack
        if "features" not in config:
            raise ValueError("Custom feature pack must have 'features' field")

        features = config["features"]
        if not isinstance(features, dict):
            raise ValueError("Features must be a dictionary")

        for feature_name, feature_params in features.items():
            if feature_name not in FeatureRegistry._FEATURE_FUNCTIONS:
                raise ValueError(f"Unknown feature: {feature_name}")

            if not isinstance(feature_params, dict):
                raise ValueError(
                    f"Feature parameters must be a dictionary: {feature_name}"
                )

            # Validate lookback_m parameter
            lookback = feature_params.get(
                "lookback_m", feature_params.get("window_m", 30)
            )
            if not isinstance(lookback, int) or lookback <= 0:
                raise ValueError(
                    f"lookback_m must be a positive integer for {feature_name}"
                )


def create_feature_pack_config(pack_type: str, **params) -> dict[str, Any]:
    """Create a standardized feature pack configuration.

    Args:
        pack_type: Type of feature pack ('core_basics', 'fast_indicators', etc.)
        **params: Additional parameters for the pack

    Returns:
        Standardized feature pack configuration
    """
    if pack_type == "core_basics":
        return {
            "type": "core_basics",
            "params": {
                "vwap_window_m": params.get("vwap_window_m", 30),
                "rel_vol_window_m": params.get("rel_vol_window_m", 30),
                "atr_window_m": params.get("atr_window_m", 14),
            },
        }
    elif pack_type in FeatureRegistry._PREDEFINED_PACKS:
        return {"type": pack_type, "params": params}
    else:
        # Custom pack
        return {"type": "custom", "features": params}
