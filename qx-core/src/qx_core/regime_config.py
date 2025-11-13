"""Regime configuration schema and validation utilities.

Defines the configuration structure for regime detection parameters
and provides validation functions for experiment configurations.
"""

from typing import Any

from pydantic import BaseModel, Field, validator


class RegimeConfig(BaseModel):
    """Configuration for regime detection in experiments."""

    # Core settings
    enabled: bool = Field(False, description="Enable regime detection")
    model: str = Field("rules", description="Detector model: 'rules' or 'hsmm'")

    # Strategy mapping by regime
    strategy_map: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "BULL": ["vwap_momentum"],
            "BEAR": ["vwap_momentum"],
            "SIDEWAYS": ["vwap_revert"],
            "STRESS": [],
            "OFF": ["vwap_momentum", "vwap_revert"],
        },
        description="Strategies allowed in each regime",
    )

    # Persistence and cooldown
    persistence_bars: int = Field(3, ge=1, le=20, description="Minimum bars for regime persistence")
    cooldown_minutes: int = Field(
        15, ge=0, le=120, description="Cooldown period after regime changes"
    )

    # Feature configuration
    features: dict[str, Any] = Field(
        default_factory=lambda: {
            "volatility_window": 30,
            "trend_window": 60,
            "stress_threshold": 2.0,
            "vwap_window": 30,
            "atr_window": 14,
        },
        description="Feature computation parameters",
    )

    # Detector thresholds
    detector_params: dict[str, Any] = Field(
        default_factory=lambda: {
            "variance_ratio_bull": 1.2,
            "variance_ratio_bear": 0.8,
            "adx_trend_threshold": 20.0,
            "volatility_stress_threshold": 2.0,
            "volatility_high_threshold": 1.6,
            "volatility_low_threshold": 0.8,
            "stress_vol_threshold": 2.0,
            "stress_volume_threshold": 3.0,
            "sideways_band_min": 0.2,
            "sideways_band_max": 0.8,
            "variance_ratio_weight": 0.4,
            "adx_weight": 0.3,
            "volatility_weight": 0.2,
            "band_position_weight": 0.1,
        },
        description="Detector algorithm parameters",
    )

    @validator("strategy_map")
    def validate_strategy_map(cls, v):
        """Validate strategy mapping configuration."""
        allowed_regimes = {"BULL", "BEAR", "SIDEWAYS", "STRESS", "OFF"}

        for regime, strategies in v.items():
            if regime not in allowed_regimes:
                raise ValueError(f"Invalid regime in strategy_map: {regime}")

            if not isinstance(strategies, list):
                raise ValueError(f"Strategies for regime {regime} must be a list")

        return v

    @validator("features")
    def validate_features(cls, v):
        """Validate feature configuration."""
        # Check for valid window sizes
        window_params = [
            "volatility_window",
            "trend_window",
            "vwap_window",
            "atr_window",
        ]

        for param in window_params:
            if param in v and (not isinstance(v[param], int) or v[param] <= 0):
                raise ValueError(f"Feature parameter {param} must be a positive integer")

        # Check for valid thresholds
        threshold_params = ["stress_threshold"]
        for param in threshold_params:
            if param in v and (not isinstance(v[param], (int, float)) or v[param] <= 0):
                raise ValueError(f"Feature parameter {param} must be a positive number")

        return v

    @validator("detector_params")
    def validate_detector_params(cls, v):
        """Validate detector parameter configuration."""
        # Check ratio parameters
        ratio_params = ["variance_ratio_bull", "variance_ratio_bear"]
        for param in ratio_params:
            if param in v and (not isinstance(v[param], (int, float)) or v[param] <= 0):
                raise ValueError(f"Detector parameter {param} must be positive")

        # Check threshold parameters
        threshold_params = [
            "adx_trend_threshold",
            "volatility_stress_threshold",
            "volatility_high_threshold",
            "volatility_low_threshold",
            "stress_vol_threshold",
            "stress_volume_threshold",
        ]
        for param in threshold_params:
            if param in v and (not isinstance(v[param], (int, float)) or v[param] <= 0):
                raise ValueError(f"Detector parameter {param} must be positive")

        # Check weight parameters sum to approximately 1.0
        weight_params = [
            "variance_ratio_weight",
            "adx_weight",
            "volatility_weight",
            "band_position_weight",
        ]
        weight_values = [v.get(param) for param in weight_params if param in v]
        if weight_values:
            weight_sum = sum(weight_values)
            if abs(weight_sum - 1.0) > 0.1:  # Allow 10% tolerance
                raise ValueError(
                    f"Detector weights must sum to approximately 1.0, got {weight_sum}"
                )

        # Check band position bounds
        if "sideways_band_min" in v and "sideways_band_max" in v:
            if v["sideways_band_min"] >= v["sideways_band_max"]:
                raise ValueError("sideways_band_min must be less than sideways_band_max")

        return v


def validate_regime_config(config: dict[str, Any]) -> RegimeConfig:
    """Validate and create RegimeConfig from dictionary.

    Args:
        config: Raw configuration dictionary

    Returns:
        Validated RegimeConfig instance

    Raises:
        ValueError: If configuration is invalid
    """
    try:
        return RegimeConfig(**config)
    except Exception as e:
        raise ValueError(f"Invalid regime configuration: {e}")


def create_default_regime_config() -> dict[str, Any]:
    """Create default regime configuration.

    Returns:
        Default regime configuration dictionary
    """
    config = RegimeConfig()
    return config.dict()


def merge_regime_config(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Merge regime configuration overlay into base configuration.

    Args:
        base: Base configuration
        overlay: Overlay configuration to merge

    Returns:
        Merged configuration dictionary
    """
    merged = base.copy()

    for key, value in overlay.items():
        if key in ["strategy_map", "features", "detector_params"]:
            # Deep merge for nested dictionaries
            if key not in merged:
                merged[key] = {}
            if isinstance(merged[key], dict) and isinstance(value, dict):
                merged[key].update(value)
            else:
                merged[key] = value
        else:
            # Direct replacement for scalar values
            merged[key] = value

    return merged


# Configuration schema for JSON validation
def regime_config_json_schema() -> dict[str, Any]:
    """Get JSON schema for regime configuration validation.

    Returns:
        JSON schema dictionary
    """
    return {
        "type": "object",
        "properties": {
            "enabled": {"type": "boolean"},
            "model": {"type": "string", "enum": ["rules", "hsmm"]},
            "strategy_map": {
                "type": "object",
                "patternProperties": {
                    "^(BULL|BEAR|SIDEWAYS|STRESS|OFF)$": {
                        "type": "array",
                        "items": {"type": "string"},
                    }
                },
            },
            "persistence_bars": {"type": "integer", "minimum": 1, "maximum": 20},
            "cooldown_minutes": {"type": "integer", "minimum": 0, "maximum": 120},
            "features": {
                "type": "object",
                "properties": {
                    "volatility_window": {"type": "integer", "minimum": 1},
                    "trend_window": {"type": "integer", "minimum": 1},
                    "stress_threshold": {"type": "number", "minimum": 0},
                    "vwap_window": {"type": "integer", "minimum": 1},
                    "atr_window": {"type": "integer", "minimum": 1},
                },
            },
            "detector_params": {
                "type": "object",
                "properties": {
                    "variance_ratio_bull": {"type": "number", "minimum": 0},
                    "variance_ratio_bear": {"type": "number", "minimum": 0},
                    "adx_trend_threshold": {"type": "number", "minimum": 0},
                    "volatility_stress_threshold": {"type": "number", "minimum": 0},
                    "volatility_high_threshold": {"type": "number", "minimum": 0},
                    "volatility_low_threshold": {"type": "number", "minimum": 0},
                    "stress_vol_threshold": {"type": "number", "minimum": 0},
                    "stress_volume_threshold": {"type": "number", "minimum": 0},
                    "sideways_band_min": {"type": "number", "minimum": 0, "maximum": 1},
                    "sideways_band_max": {"type": "number", "minimum": 0, "maximum": 1},
                    "variance_ratio_weight": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                    "adx_weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "volatility_weight": {"type": "number", "minimum": 0, "maximum": 1},
                    "band_position_weight": {
                        "type": "number",
                        "minimum": 0,
                        "maximum": 1,
                    },
                },
            },
        },
    }
