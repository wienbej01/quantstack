"""Rule-based regime detector with configurable thresholds and hysteresis.

Implements deterministic regime classification using streaming-friendly
features with persistence guards and cooldown logic to prevent excessive
regime switching.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..schemas import RegimeSignal, RegimeType
from ..utils import ts_to_date


@dataclass
class RegimeDetectorConfig:
    """Configuration for regime detection rules."""

    # Trend detection thresholds
    variance_ratio_bull: float = 1.2
    variance_ratio_bear: float = 0.8
    adx_trend_threshold: float = 30.0
    trend_confidence_min: float = 0.6

    # Volatility thresholds
    volatility_stress_threshold: float = 2.0
    volatility_high_threshold: float = 1.5
    volatility_low_threshold: float = 0.7

    # Stress detection thresholds
    stress_vol_threshold: float = 2.0
    stress_volume_threshold: float = 3.0
    stress_confidence_min: float = 0.8

    # Band position for sideways detection
    sideways_band_min: float = 0.2
    sideways_band_max: float = 0.8
    sideways_confidence_min: float = 0.5

    # Persistence and cooldown
    persistence_bars: int = 3
    cooldown_minutes: int = 15

    # Feature weights for confidence calculation
    variance_ratio_weight: float = 0.4
    adx_weight: float = 0.3
    volatility_weight: float = 0.2
    band_position_weight: float = 0.1


class RegimeDetectorRules:
    """Rule-based regime detector with hysteresis and persistence guards.

    Evaluates market conditions using regime features to classify into:
    - BULL: Strong upward trending with normal/low volatility
    - BEAR: Strong downward trending with normal/low volatility
    - SIDEWAYS: Range-bound market with balanced indicators
    - STRESS: High volatility or abnormal conditions (risk-off)
    - OFF: Regime detection disabled
    """

    def __init__(self, config: Optional[RegimeDetectorConfig] = None):
        """Initialize regime detector with configuration.

        Args:
            config: Detector configuration. Uses defaults if None.
        """
        self.config = config or RegimeDetectorConfig()

        # State tracking for persistence and cooldown
        self._regime_history: Dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._last_regime_change: Dict[str, int] = {}
        self._persistence_counters: Dict[str, Dict[RegimeType, int]] = defaultdict(
            lambda: {rt: 0 for rt in RegimeType}
        )
        self._aggregate_symbol = "__aggregate__"

        # Daily caching - regime determined once per trading day
        self._daily_regime_cache: Dict[str, RegimeSignal] = {}
        self._last_evaluation_date: Dict[str, str] = {}

        # Performance tracking
        self._evaluation_count = 0
        self._regime_changes = 0
        self._cache_hits = 0

    def evaluate(self, features_df: pd.DataFrame, ts: int) -> RegimeSignal:
        """Evaluate regime for a single timestamp across all symbols.

        Args:
            features_df: DataFrame with regime features for current timestamp
            ts: Current timestamp in nanoseconds

        Returns:
            RegimeSignal with classification and metadata
        """
        self._evaluation_count += 1

        # Convert timestamp to date string for daily caching
        current_date = ts_to_date(ts).strftime("%Y-%m-%d")

        # Check if we have a cached regime for this date
        if current_date in self._daily_regime_cache:
            self._cache_hits += 1
            cached_signal = self._daily_regime_cache[current_date]
            # Return cached signal with updated timestamp but same regime
            return self._clone_signal(cached_signal, ts, cached_signal.persistence_count)

        if features_df.empty:
            return self._create_signal(ts, RegimeType.OFF, 0.0, "No data available")

        # Check warmup status
        warmup_col = "f__regime__warmup_ok"
        if warmup_col in features_df.columns:
            valid_data = features_df[features_df[warmup_col]]
        else:
            valid_data = features_df

        if valid_data.empty:
            return self._create_signal(
                ts, RegimeType.OFF, 0.0, "Features not warmed up"
            )

        # Aggregate features across symbols
        agg_features = self._aggregate_features(valid_data)

        # Detect stress first (highest priority)
        stress_result = self._detect_stress(agg_features, ts)
        if stress_result.regime == RegimeType.STRESS:
            # Cache stress regime for the day
            self._daily_regime_cache[current_date] = stress_result
            self._last_evaluation_date[self._aggregate_symbol] = current_date
            return stress_result

        # Ensure required trend features are present
        required_trend_keys = [
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__band_pos_20_2.0",
        ]
        missing_keys = [key for key in required_trend_keys if key not in agg_features]
        if missing_keys:
            no_features_signal = self._create_signal(
                ts,
                RegimeType.OFF,
                0.0,
                f"Missing regime features: {', '.join(missing_keys)}",
            )
            # Cache OFF regime for the day
            self._daily_regime_cache[current_date] = no_features_signal
            self._last_evaluation_date[self._aggregate_symbol] = current_date
            return no_features_signal

        # Detect trend vs sideways
        trend_result = self._detect_trend_regime(agg_features, ts)

        # Apply persistence guard
        final_regime = self._apply_persistence_guard(trend_result, ts)

        # Cache the determined regime for the day
        self._daily_regime_cache[current_date] = final_regime
        self._last_evaluation_date[self._aggregate_symbol] = current_date

        return final_regime

    def evaluate_symbol(
        self, symbol: str, features: Dict[str, float], ts: int
    ) -> RegimeSignal:
        """Evaluate regime for a single symbol.

        Args:
            symbol: Symbol identifier
            features: Feature values for the symbol
            ts: Current timestamp in nanoseconds

        Returns:
            RegimeSignal for the symbol
        """
        self._evaluation_count += 1

        required_trend_keys = [
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__band_pos_20_2.0",
        ]

        # Detect stress first
        stress_result = self._detect_stress_for_symbol(features, ts)
        if stress_result.regime == RegimeType.STRESS:
            return stress_result

        missing_keys = [key for key in required_trend_keys if key not in features]
        if missing_keys:
            return self._create_signal(
                ts,
                RegimeType.OFF,
                0.0,
                f"Missing regime features: {', '.join(missing_keys)}",
            )

        # Detect trend regime
        trend_result = self._detect_trend_for_symbol(features, ts)

        # Apply persistence guard for symbol
        final_regime = self._apply_persistence_guard_for_symbol(
            symbol, trend_result, ts
        )

        return final_regime

    def reset_state(self) -> None:
        """Reset all internal state for fresh start."""
        self._regime_history.clear()
        self._last_regime_change.clear()
        self._persistence_counters.clear()
        self._daily_regime_cache.clear()
        self._last_evaluation_date.clear()
        self._evaluation_count = 0
        self._regime_changes = 0
        self._cache_hits = 0

    def get_statistics(self) -> Dict[str, Any]:
        """Get detector performance statistics.

        Returns:
            Dictionary with evaluation statistics
        """
        return {
            "evaluations": self._evaluation_count,
            "regime_changes": self._regime_changes,
            "change_rate": self._regime_changes / max(self._evaluation_count, 1),
            "cache_hits": self._cache_hits,
            "cache_hit_rate": self._cache_hits / max(self._evaluation_count, 1),
            "daily_regimes_cached": len(self._daily_regime_cache),
            "symbols_tracked": len(self._regime_history),
            "avg_persistence": self._calculate_avg_persistence(),
        }

    def _aggregate_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Aggregate features across all symbols."""
        agg = {}

        # Feature columns to aggregate
        feature_cols = [col for col in df.columns if col.startswith("f__regime__")]

        for col in feature_cols:
            if col in df.columns:
                # Use median for robust aggregation
                agg[col] = df[col].median()

        return agg

    def _detect_stress(self, features: Dict[str, float], ts: int) -> RegimeSignal:
        """Detect stress conditions across all symbols."""
        stress_score = 0.0
        stress_factors = []

        # Check volatility stress
        vol_key = "f__regime__mod_vol_30"
        if vol_key in features:
            vol_stress = max(
                0.0, (features[vol_key] - self.config.volatility_stress_threshold)
            )
            stress_score += vol_stress * self.config.volatility_weight
            stress_factors.append(f"volatility_stress={vol_stress:.3f}")

        # Check stress metrics
        stress_key = "f__regime__stress_10_10"
        if stress_key in features:
            direct_stress = features[stress_key]
            stress_score += direct_stress * self.config.stress_confidence_min
            stress_factors.append(f"direct_stress={direct_stress:.3f}")

        # Determine stress regime
        if stress_score >= self.config.stress_confidence_min:
            confidence = min(1.0, stress_score)
            reason = f"Stress detected: {', '.join(stress_factors)}"
            return self._create_signal(ts, RegimeType.STRESS, confidence, reason)

        return self._create_signal(ts, RegimeType.OFF, 0.0, "No stress conditions")

    def _detect_trend_regime(self, features: Dict[str, float], ts: int) -> RegimeSignal:
        """Detect trend vs sideways regime."""
        trend_score = 0.0
        volatility_level = "normal"
        band_position = 0.5  # Default to middle

        # Extract features
        var_ratio = features.get("f__regime__var_ratio_10_60", 1.0)
        adx = features.get("f__regime__adx_proxy_14", 25.0)
        volatility = features.get("f__regime__mod_vol_30", 1.0)
        band_pos = features.get("f__regime__band_pos_20_2.0", 0.5)

        # Determine volatility level
        if volatility >= self.config.volatility_high_threshold:
            volatility_level = "high"
        elif volatility <= self.config.volatility_low_threshold:
            volatility_level = "low"

        # Calculate trend strength
        if var_ratio > self.config.variance_ratio_bull:
            trend_score += self.config.variance_ratio_weight
        elif var_ratio < self.config.variance_ratio_bear:
            trend_score -= self.config.variance_ratio_weight

        # Add ADX contribution
        if adx >= self.config.adx_trend_threshold:
            adx_contribution = (
                adx - self.config.adx_trend_threshold
            ) / 50.0  # Normalize to 0-1
            trend_score += adx_contribution * self.config.adx_weight

        # Check for sideways conditions
        is_sideways = (
            self.config.sideways_band_min <= band_pos <= self.config.sideways_band_max
            and abs(trend_score) < 0.3
            and volatility_level == "normal"
        )

        if is_sideways:
            regime = RegimeType.SIDEWAYS
            confidence = self.config.sideways_confidence_min
            reason = f"Sideways market: band_pos={band_pos:.3f}, trend_score={trend_score:.3f}"
        else:
            # Determine trend direction
            if trend_score > 0.3:
                regime = RegimeType.BULL
                confidence = max(
                    self.config.trend_confidence_min,
                    min(1.0, abs(trend_score)),
                )
            elif trend_score < -0.3:
                regime = RegimeType.BEAR
                confidence = max(
                    self.config.trend_confidence_min,
                    min(1.0, abs(trend_score)),
                )
            else:
                # Ambiguous conditions - default to sideways
                regime = RegimeType.SIDEWAYS
                confidence = self.config.sideways_confidence_min

            reason = (
                f"Trend detected: score={trend_score:.3f}, "
                f"var_ratio={var_ratio:.3f}, adx={adx:.1f}, "
                f"volatility={volatility_level}"
            )

        return self._create_signal(ts, regime, confidence, reason, features)

    def _detect_stress_for_symbol(
        self, features: Dict[str, float], ts: int
    ) -> RegimeSignal:
        """Detect stress conditions for single symbol."""
        # Similar to _detect_stress but for single symbol
        stress_score = 0.0

        vol_key = "f__regime__mod_vol_30"
        if vol_key in features:
            vol_stress = max(
                0.0, (features[vol_key] - self.config.volatility_stress_threshold)
            )
            stress_score += vol_stress

        stress_key = "f__regime__stress_10_10"
        if stress_key in features:
            stress_score += features[stress_key] * self.config.stress_confidence_min

        if stress_score >= self.config.stress_confidence_min:
            confidence = min(1.0, stress_score)
            return self._create_signal(
                ts, RegimeType.STRESS, confidence, "Symbol stress"
            )

        return self._create_signal(ts, RegimeType.OFF, 0.0, "No symbol stress")

    def _detect_trend_for_symbol(
        self, features: Dict[str, float], ts: int
    ) -> RegimeSignal:
        """Detect trend regime for single symbol."""
        # Similar to _detect_trend_regime but for single symbol
        var_ratio = features.get("f__regime__var_ratio_10_60", 1.0)
        adx = features.get("f__regime__adx_proxy_14", 25.0)
        band_pos = features.get("f__regime__band_pos_20_2.0", 0.5)

        trend_score = 0.0

        if var_ratio > self.config.variance_ratio_bull:
            trend_score += self.config.variance_ratio_weight
        elif var_ratio < self.config.variance_ratio_bear:
            trend_score -= self.config.variance_ratio_weight

        if adx >= self.config.adx_trend_threshold:
            adx_contribution = (adx - self.config.adx_trend_threshold) / 50.0
            trend_score += adx_contribution * self.config.adx_weight

        is_sideways = (
            self.config.sideways_band_min <= band_pos <= self.config.sideways_band_max
            and abs(trend_score) < 0.3
        )

        if is_sideways:
            regime = RegimeType.SIDEWAYS
            confidence = self.config.sideways_confidence_min
        else:
            if trend_score > 0.3:
                regime = RegimeType.BULL
                confidence = max(
                    self.config.trend_confidence_min,
                    min(1.0, abs(trend_score)),
                )
            elif trend_score < -0.3:
                regime = RegimeType.BEAR
                confidence = max(
                    self.config.trend_confidence_min,
                    min(1.0, abs(trend_score)),
                )
            else:
                regime = RegimeType.SIDEWAYS
                confidence = self.config.sideways_confidence_min

        return self._create_signal(ts, regime, confidence, "Symbol trend", features)

    def _apply_persistence_guard(self, signal: RegimeSignal, ts: int) -> RegimeSignal:
        """Apply persistence guard to prevent excessive regime switching."""
        return self._apply_persistence_guard_for_symbol(
            self._aggregate_symbol, signal, ts
        )

    def _apply_persistence_guard_for_symbol(
        self, symbol: str, signal: RegimeSignal, ts: int
    ) -> RegimeSignal:
        """Apply persistence guard for individual symbol."""
        current_regime = signal.regime
        symbol_history = self._regime_history[symbol]

        # Get last regime for this symbol
        last_regime = symbol_history[-1].regime if symbol_history else RegimeType.OFF

        # Check if we're in cooldown period
        last_change_time = self._last_regime_change.get(symbol)
        cooldown_ns = (
            self.config.cooldown_minutes * 60 * 1_000_000_000
        )  # Convert to nanoseconds

        if (
            last_change_time is not None
            and (ts - last_change_time) < cooldown_ns
            and last_regime != current_regime
        ):
            # Still in cooldown, keep previous regime
            if symbol_history:
                last_signal = symbol_history[-1]
                return self._clone_signal(
                    last_signal,
                    ts,
                    last_signal.persistence_count,
                )
            else:
                return self._create_signal(ts, RegimeType.OFF, 0.0, "Cooldown period")

        # Update persistence counter
        self._persistence_counters[symbol][current_regime] += 1

        # Check if we have sufficient persistence
        persistence_count = self._persistence_counters[symbol][current_regime]

        if (
            persistence_count < self.config.persistence_bars
            and last_regime != RegimeType.OFF
        ):
            # Not enough persistence, keep previous regime
            if symbol_history:
                last_signal = symbol_history[-1]
                return self._clone_signal(
                    last_signal,
                    ts,
                    persistence_count,
                )

        # Regime change confirmed
        change_confirmed = False
        if current_regime != last_regime:
            self._last_regime_change[symbol] = ts
            # Reset counters for other regimes
            for regime in RegimeType:
                if regime != current_regime:
                    self._persistence_counters[symbol][regime] = 0
            change_confirmed = True

        # Create final signal with persistence count
        result = RegimeSignal(
            ts=ts,
            regime=current_regime,
            confidence=signal.confidence,
            features=signal.features,
            persistence_count=persistence_count,
            model_version=signal.model_version,
            src=signal.src,
        )

        # Add to history
        symbol_history.append(result)

        if change_confirmed and symbol == self._aggregate_symbol:
            self._regime_changes += 1

        return result

    def _create_signal(
        self,
        ts: int,
        regime: RegimeType,
        confidence: float,
        reason: str,
        features: Optional[Dict[str, float]] = None,
    ) -> RegimeSignal:
        """Create a RegimeSignal with standard fields."""
        feature_payload: Dict[str, float] = dict(features or {})
        if reason:
            feature_payload.setdefault("reason", reason)

        return RegimeSignal(
            ts=ts,
            regime=regime,
            confidence=confidence,
            features=feature_payload,
            persistence_count=0,
            model_version="rules_v1",
            src="regime",
        )

    def _calculate_avg_persistence(self) -> float:
        """Calculate average persistence across all symbols."""
        if not self._persistence_counters:
            return 0.0

        total_persistence = 0
        total_count = 0

        for symbol_counters in self._persistence_counters.values():
            for regime, count in symbol_counters.items():
                if count > 0:  # Only count regimes that have been observed
                    total_persistence += count
                    total_count += 1

        return total_persistence / max(total_count, 1)

    def _clone_signal(
        self,
        signal: RegimeSignal,
        ts: int,
        persistence_count: int,
    ) -> RegimeSignal:
        """Clone an existing signal with updated timestamp and persistence."""
        return RegimeSignal(
            ts=ts,
            regime=signal.regime,
            confidence=signal.confidence,
            features=dict(signal.features or {}),
            persistence_count=persistence_count,
            model_version=signal.model_version,
            src=signal.src,
        )


# Factory function for creating detectors from config
def create_regime_detector(
    config_dict: Optional[Dict[str, Any]] = None
) -> RegimeDetectorRules:
    """Create regime detector from configuration dictionary.

    Args:
        config_dict: Configuration dictionary with detector parameters

    Returns:
        Configured RegimeDetectorRules instance
    """
    if config_dict is None:
        return RegimeDetectorRules()

    # Extract configuration parameters
    config = RegimeDetectorConfig(
        variance_ratio_bull=config_dict.get("variance_ratio_bull", 1.2),
        variance_ratio_bear=config_dict.get("variance_ratio_bear", 0.8),
        adx_trend_threshold=config_dict.get("adx_trend_threshold", 30.0),
        volatility_stress_threshold=config_dict.get("volatility_stress_threshold", 2.0),
        volatility_high_threshold=config_dict.get("volatility_high_threshold", 1.5),
        volatility_low_threshold=config_dict.get("volatility_low_threshold", 0.7),
        stress_vol_threshold=config_dict.get("stress_vol_threshold", 2.0),
        stress_volume_threshold=config_dict.get("stress_volume_threshold", 3.0),
        persistence_bars=config_dict.get("persistence_bars", 3),
        cooldown_minutes=config_dict.get("cooldown_minutes", 15),
        variance_ratio_weight=config_dict.get("variance_ratio_weight", 0.4),
        adx_weight=config_dict.get("adx_weight", 0.3),
        volatility_weight=config_dict.get("volatility_weight", 0.2),
        band_position_weight=config_dict.get("band_position_weight", 0.1),
    )

    return RegimeDetectorRules(config)


# Convenience function for creating default detector
def create_default_detector() -> RegimeDetectorRules:
    """Create regime detector with default configuration."""
    return RegimeDetectorRules()
