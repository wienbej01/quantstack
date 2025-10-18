"""Regime detection module for market state classification.

Provides rule-based regime detection with configurable thresholds,
hysteresis, and persistence guards to prevent excessive regime switching.
"""

from .detector import (
    RegimeDetectorConfig,
    RegimeDetectorRules,
    create_default_detector,
    create_regime_detector,
)

__all__ = [
    "RegimeDetectorConfig",
    "RegimeDetectorRules",
    "create_regime_detector",
    "create_default_detector",
]
