"""Rule-based regime detector with configurable thresholds and hysteresis.

Implements deterministic regime classification using streaming-friendly
features with persistence guards and cooldown logic to prevent excessive
regime switching.
"""

from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from typing import Any

import pandas as pd

from ..schemas import RegimeSignal, RegimeType


class SessionSegment(str, Enum):
    """Half-day trading session buckets."""

    MORNING = "AM"
    AFTERNOON = "PM"


@dataclass
class RegimeDetectorConfig:
    """Configuration for regime detection rules."""

    # Trend detection thresholds
    variance_ratio_bull: float = 1.2
    variance_ratio_bear: float = 0.8
    adx_trend_threshold: float = 20.0
    trend_confidence_min: float = 0.6

    # Volatility thresholds
    volatility_stress_threshold: float = 2.0
    volatility_high_threshold: float = 1.6
    volatility_low_threshold: float = 0.8

    # Stress detection thresholds
    stress_vol_threshold: float = 2.0
    stress_volume_threshold: float = 3.0
    stress_confidence_min: float = 0.8

    # Band position for sideways detection
    sideways_band_min: float = 0.2
    sideways_band_max: float = 0.8
    sideways_confidence_min: float = 0.5

    # Persistence and cooldown
    persistence_bars: int = 2
    cooldown_minutes: int = 15

    # Feature weights for confidence calculation
    variance_ratio_weight: float = 0.4
    adx_weight: float = 0.3
    volatility_weight: float = 0.2
    band_position_weight: float = 0.1

    # Enhanced regime features (new from plan)
    avwap_bias_threshold: float = 0.02  # 2% deviation from AVWAP for bias
    value_acceptance_bars_min: int = 3  # Minimum bars in value area for acceptance
    ofi_confirmation_threshold: float = 0.1  # OFI trend threshold for confirmation
    regime_feature_weight: float = 0.15  # Weight for enhanced features in regime decisions


class RegimeDetectorRules:
    """Rule-based regime detector with hysteresis and persistence guards.

    Evaluates market conditions using regime features to classify into:
    - BULL: Strong upward trending with normal/low volatility
    - BEAR: Strong downward trending with normal/low volatility
    - SIDEWAYS: Range-bound market with balanced indicators
    - STRESS: High volatility or abnormal conditions (risk-off)
    - OFF: Regime detection disabled
    """

    def __init__(self, config: RegimeDetectorConfig | None = None):
        """Initialize regime detector with configuration.

        Args:
            config: Detector configuration. Uses defaults if None.
        """
        self.config = config or RegimeDetectorConfig()

        # State tracking for persistence and cooldown
        self._regime_history: dict[str, deque] = defaultdict(lambda: deque(maxlen=100))
        self._last_regime_change: dict[str, int] = {}
        self._persistence_counters: dict[str, dict[RegimeType, int]] = defaultdict(
            lambda: dict.fromkeys(RegimeType, 0)
        )
        self._aggregate_symbol = "__aggregate__"

        # Segment-level caching (morning/afternoon)
        self._segment_regime_cache: dict[str, RegimeSignal] = {}
        self._last_segment_evaluation: dict[str, str] = {}

        # Performance tracking
        self._evaluation_count = 0
        self._regime_changes = 0
        self._cache_hits = 0

    def _with_segment(self, symbol: str, segment: SessionSegment) -> str:
        """Create a segment-qualified key for symbol state tracking."""

        return f"{symbol}::{segment.value}"

    def _get_trading_day_and_segment(self, ts: int) -> tuple[str, SessionSegment]:
        """Map UTC nanoseconds to ET trading date and session segment."""

        timestamp_et = pd.Timestamp(ts, tz="UTC", unit="ns").tz_convert("America/New_York")
        trading_date = timestamp_et.date().isoformat()

        midday = timestamp_et.replace(hour=12, minute=30, second=0, microsecond=0)
        segment = SessionSegment.MORNING
        if timestamp_et >= midday:
            segment = SessionSegment.AFTERNOON

        return trading_date, segment

    def evaluate(self, features_df: pd.DataFrame, ts: int) -> RegimeSignal:
        """Evaluate regime for a single timestamp across all symbols.

        Args:
            features_df: DataFrame with regime features for current timestamp
            ts: Current timestamp in nanoseconds

        Returns:
            RegimeSignal with classification and metadata
        """
        self._evaluation_count += 1

        trading_date, segment = self._get_trading_day_and_segment(ts)
        cache_key = f"{trading_date}_{segment.value}"
        segment_symbol = self._with_segment(self._aggregate_symbol, segment)

        if features_df.empty:
            return self._create_signal(
                ts,
                RegimeType.OFF,
                0.0,
                "No data available",
                symbol=segment_symbol,
                segment=segment,
                session_date=trading_date,
            )

        # Check warmup status
        warmup_col = "f__regime__warmup_ok"
        if warmup_col in features_df.columns:
            valid_data = features_df[features_df[warmup_col]]
        else:
            valid_data = features_df

        if valid_data.empty:
            return self._create_signal(
                ts,
                RegimeType.OFF,
                0.0,
                "Features not warmed up",
                symbol=segment_symbol,
                segment=segment,
                session_date=trading_date,
            )

        # Aggregate features across symbols
        agg_features = self._aggregate_features(valid_data)

        # Detect stress first (highest priority)
        stress_result = self._detect_stress(
            agg_features,
            ts,
            symbol=segment_symbol,
            segment=segment,
            session_date=trading_date,
        )
        if stress_result.regime == RegimeType.STRESS:
            self._segment_regime_cache[cache_key] = stress_result
            self._last_segment_evaluation[segment_symbol] = trading_date
            return stress_result

        cached_signal = self._segment_regime_cache.get(cache_key)
        if cached_signal is not None:
            self._cache_hits += 1
            return self._clone_signal(
                cached_signal, ts, cached_signal.persistence_count, segment=segment
            )

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
                symbol=segment_symbol,
                segment=segment,
                session_date=trading_date,
            )
            self._segment_regime_cache[cache_key] = no_features_signal
            self._last_segment_evaluation[segment_symbol] = trading_date
            return no_features_signal

        # Detect trend vs sideways
        trend_result = self._detect_trend_regime(
            agg_features,
            ts,
            symbol=segment_symbol,
            segment=segment,
            session_date=trading_date,
        )

        # Apply persistence guard
        final_regime = self._apply_persistence_guard(trend_result, ts, segment_symbol)

        # Cache the determined regime for the segment
        self._segment_regime_cache[cache_key] = final_regime
        self._last_segment_evaluation[segment_symbol] = trading_date

        return final_regime

    def evaluate_symbol(self, symbol: str, features: dict[str, float], ts: int) -> RegimeSignal:
        """Evaluate regime for a single symbol.

        Args:
            symbol: Symbol identifier
            features: Feature values for the symbol
            ts: Current timestamp in nanoseconds

        Returns:
            RegimeSignal for the symbol
        """
        self._evaluation_count += 1

        trading_date, segment = self._get_trading_day_and_segment(ts)
        symbol_key = self._with_segment(symbol, segment)

        required_trend_keys = [
            "f__regime__var_ratio_10_60",
            "f__regime__adx_proxy_14",
            "f__regime__band_pos_20_2.0",
        ]

        # Detect stress first
        stress_result = self._detect_stress_for_symbol(
            symbol,
            features,
            ts,
            segment=segment,
            session_date=trading_date,
        )
        if stress_result.regime == RegimeType.STRESS:
            self._last_segment_evaluation[symbol_key] = trading_date
            return stress_result

        missing_keys = [key for key in required_trend_keys if key not in features]
        if missing_keys:
            return self._create_signal(
                ts,
                RegimeType.OFF,
                0.0,
                f"Missing regime features: {', '.join(missing_keys)}",
                symbol=symbol,
                segment=segment,
                session_date=trading_date,
            )

        # Detect trend regime
        trend_result = self._detect_trend_for_symbol(
            features,
            ts,
            symbol=symbol,
            segment=segment,
            session_date=trading_date,
        )

        # Apply persistence guard for symbol
        final_regime = self._apply_persistence_guard_for_symbol(symbol_key, trend_result, ts)
        self._last_segment_evaluation[symbol_key] = trading_date

        return final_regime

    def reset_state(self) -> None:
        """Reset all internal state for fresh start."""
        self._regime_history.clear()
        self._last_regime_change.clear()
        self._persistence_counters.clear()
        self._segment_regime_cache.clear()
        self._last_segment_evaluation.clear()
        self._evaluation_count = 0
        self._regime_changes = 0
        self._cache_hits = 0

    def get_statistics(self) -> dict[str, Any]:
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
            "cached_segments": len(self._segment_regime_cache),
            "symbols_tracked": len(self._regime_history),
            "avg_persistence": self._calculate_avg_persistence(),
            "regime_distribution": self._calculate_segment_distribution(),
        }

    def _aggregate_features(self, df: pd.DataFrame) -> dict[str, float]:
        """Aggregate features across all symbols with enhanced regime feature support."""
        agg = {}

        # Original regime features
        regime_feature_cols = [col for col in df.columns if col.startswith("f__regime__")]

        for col in regime_feature_cols:
            if col in df.columns:
                # Use median for robust aggregation, skip if all NaN
                valid_values = df[col].dropna()
                if not valid_values.empty:
                    agg[col] = valid_values.median()
                else:
                    # Skip columns with all NaN values
                    continue

        # Enhanced regime features from the new feature pack
        enhanced_feature_patterns = [
            "f__anchor__",  # AVWAP features
            "f__profile__",  # Volume profile features
            "f__ict__",  # ICT structure features
            "f__flow__",  # Order flow features
            "f__vpa__",  # VPA features
            "f__stress__",  # Stress contraction features
        ]

        enhanced_features = []
        for pattern in enhanced_feature_patterns:
            enhanced_features.extend([col for col in df.columns if col.startswith(pattern)])

        # Aggregate enhanced features with null safety
        for col in enhanced_features:
            if col in df.columns:
                # Use median for robust aggregation, handle null values
                valid_values = df[col].dropna()
                if not valid_values.empty:
                    agg[col] = valid_values.median()
                else:
                    agg[col] = 0.0  # Default for completely null features

        return agg

    def _detect_stress(
        self,
        features: dict[str, float],
        ts: int,
        *,
        symbol: str | None = None,
        segment: SessionSegment | None = None,
        session_date: str | None = None,
    ) -> RegimeSignal:
        """Detect stress conditions across all symbols."""
        stress_score = 0.0
        stress_factors = []

        # Check volatility stress
        vol_key = "f__regime__mod_vol_30"
        if vol_key in features:
            vol_stress = max(0.0, (features[vol_key] - self.config.volatility_stress_threshold))
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
            return self._create_signal(
                ts,
                RegimeType.STRESS,
                confidence,
                reason,
                symbol=symbol,
                segment=segment,
                session_date=session_date,
            )

        return self._create_signal(
            ts,
            RegimeType.OFF,
            0.0,
            "No stress conditions",
            symbol=symbol,
            segment=segment,
            session_date=session_date,
        )

    def _detect_trend_regime(
        self,
        features: dict[str, float],
        ts: int,
        *,
        symbol: str | None = None,
        segment: SessionSegment | None = None,
        session_date: str | None = None,
    ) -> RegimeSignal:
        """Detect trend vs sideways regime."""
        trend_score = 0.0
        volatility_level = "normal"

        # Extract features
        var_ratio = features.get("f__regime__var_ratio_10_60", 1.0)
        adx = features.get("f__regime__adx_proxy_14", 25.0)
        volatility = features.get("f__regime__mod_vol_30", 1.0)
        band_pos = features.get("f__regime__band_pos_20_2.0", 0.5)

        enhanced_notes: list[str] = []

        # OFI confirmation contributes to trend bias
        ofi_trend = features.get("f__flow__ofi_trend")
        if ofi_trend is not None:
            if ofi_trend >= self.config.ofi_confirmation_threshold:
                trend_score += self.config.regime_feature_weight
                enhanced_notes.append("ofi_positive")
            elif ofi_trend <= -self.config.ofi_confirmation_threshold:
                trend_score -= self.config.regime_feature_weight
                enhanced_notes.append("ofi_negative")

        # ICT premium/discount zones nudge direction
        if features.get("f__ict__in_discount"):
            trend_score += 0.5 * self.config.regime_feature_weight
            enhanced_notes.append("discount_bias")
        if features.get("f__ict__in_premium"):
            trend_score -= 0.5 * self.config.regime_feature_weight
            enhanced_notes.append("premium_bias")

        # Value acceptance favours sideways classification
        value_acceptance = features.get("f__profile__value_acceptance")

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
            adx_contribution = (adx - self.config.adx_trend_threshold) / 50.0  # Normalize to 0-1
            trend_score += adx_contribution * self.config.adx_weight

        # Check for sideways conditions
        is_sideways = (
            self.config.sideways_band_min <= band_pos <= self.config.sideways_band_max
            and abs(trend_score) < 0.3
            and volatility_level == "normal"
        )
        if value_acceptance and value_acceptance >= 0.5:
            is_sideways = is_sideways or abs(trend_score) < 0.4
            enhanced_notes.append("value_acceptance")

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

        if enhanced_notes:
            reason = f"{reason} | enhanced={'/'.join(enhanced_notes)}"

        return self._create_signal(
            ts,
            regime,
            confidence,
            reason,
            features,
            symbol=symbol,
            segment=segment,
            session_date=session_date,
        )

    def _detect_stress_for_symbol(
        self,
        symbol: str,
        features: dict[str, float],
        ts: int,
        *,
        segment: SessionSegment | None = None,
        session_date: str | None = None,
    ) -> RegimeSignal:
        """Detect stress conditions for single symbol."""
        # Similar to _detect_stress but for single symbol
        stress_score = 0.0

        vol_key = "f__regime__mod_vol_30"
        if vol_key in features:
            vol_stress = max(0.0, (features[vol_key] - self.config.volatility_stress_threshold))
            stress_score += vol_stress

        stress_key = "f__regime__stress_10_10"
        if stress_key in features:
            stress_score += features[stress_key] * self.config.stress_confidence_min

        if stress_score >= self.config.stress_confidence_min:
            confidence = min(1.0, stress_score)
            return self._create_signal(
                ts,
                RegimeType.STRESS,
                confidence,
                "Symbol stress",
                symbol=symbol,
                segment=segment,
                session_date=session_date,
            )

        return self._create_signal(
            ts,
            RegimeType.OFF,
            0.0,
            "No symbol stress",
            symbol=symbol,
            segment=segment,
            session_date=session_date,
        )

    def _detect_trend_for_symbol(
        self,
        features: dict[str, float],
        ts: int,
        *,
        symbol: str | None = None,
        segment: SessionSegment | None = None,
        session_date: str | None = None,
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
        elif trend_score > 0.3:
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

        return self._create_signal(
            ts,
            regime,
            confidence,
            "Symbol trend",
            features,
            symbol=symbol,
            segment=segment,
            session_date=session_date,
        )

    def _apply_persistence_guard(
        self, signal: RegimeSignal, ts: int, segment_symbol: str
    ) -> RegimeSignal:
        """Apply persistence guard to prevent excessive regime switching."""
        return self._apply_persistence_guard_for_symbol(segment_symbol, signal, ts)

    def _apply_persistence_guard_for_symbol(
        self, symbol: str, signal: RegimeSignal, ts: int
    ) -> RegimeSignal:
        """Apply persistence guard for individual symbol."""
        base_symbol = symbol
        segment_enum: SessionSegment | None = None
        if "::" in symbol:
            base_symbol, segment_token = symbol.split("::", 1)
            try:
                segment_enum = SessionSegment(segment_token)
            except ValueError:
                segment_enum = None

        current_regime = signal.regime
        symbol_history = self._regime_history[symbol]

        # Get last regime for this symbol
        last_regime = symbol_history[-1].regime if symbol_history else RegimeType.OFF

        # Check if we're in cooldown period
        last_change_time = self._last_regime_change.get(symbol)
        cooldown_ns = self.config.cooldown_minutes * 60 * 1_000_000_000  # Convert to nanoseconds

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
                    segment=segment_enum,
                )
            else:
                return self._create_signal(
                    ts,
                    RegimeType.OFF,
                    0.0,
                    "Cooldown period",
                    symbol=base_symbol,
                    segment=segment_enum,
                )

        # Update persistence counter
        self._persistence_counters[symbol][current_regime] += 1

        # Check if we have sufficient persistence
        persistence_count = self._persistence_counters[symbol][current_regime]

        if persistence_count < self.config.persistence_bars and last_regime != RegimeType.OFF:
            # Not enough persistence, keep previous regime
            if symbol_history:
                last_signal = symbol_history[-1]
                return self._clone_signal(
                    last_signal,
                    ts,
                    persistence_count,
                    segment=segment_enum,
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
        result = self._clone_signal(
            signal,
            ts,
            persistence_count,
            segment=segment_enum,
        )

        # Add to history
        symbol_history.append(result)

        if change_confirmed and base_symbol == self._aggregate_symbol:
            self._regime_changes += 1

        return result

    def _create_signal(
        self,
        ts: int,
        regime: RegimeType,
        confidence: float,
        reason: str,
        features: dict[str, float] | None = None,
        *,
        symbol: str | None = None,
        segment: SessionSegment | None = None,
        session_date: str | None = None,
    ) -> RegimeSignal:
        """Create a RegimeSignal with standard fields."""
        feature_payload: dict[str, float] = dict(features or {})
        if reason:
            feature_payload.setdefault("reason", reason)

        return RegimeSignal(
            ts=ts,
            symbol=symbol,
            regime=regime,
            confidence=confidence,
            features=feature_payload,
            persistence_count=0,
            model_version="rules_v1",
            src="regime",
            segment=segment.value if segment else None,
            session_date=session_date,
        )

    def _clone_signal(
        self,
        signal: RegimeSignal,
        ts: int,
        persistence_count: int,
        *,
        segment: SessionSegment | None = None,
    ) -> RegimeSignal:
        """Clone an existing signal with updated timestamp and persistence."""
        return RegimeSignal(
            ts=ts,
            symbol=signal.symbol,
            regime=signal.regime,
            confidence=signal.confidence,
            features=dict(signal.features or {}),
            persistence_count=persistence_count,
            model_version=signal.model_version,
            src=signal.src,
            segment=(segment.value if segment else signal.segment),
            session_date=signal.session_date,
        )

    def _calculate_avg_persistence(self) -> float:
        """Calculate average persistence across all symbols."""
        if not self._persistence_counters:
            return 0.0

        total_persistence = 0
        total_count = 0

        for symbol_counters in self._persistence_counters.values():
            for _regime, count in symbol_counters.items():
                if count > 0:  # Only count regimes that have been observed
                    total_persistence += count
                    total_count += 1

        return total_persistence / max(total_count, 1)

    def _calculate_segment_distribution(self) -> dict[str, int]:
        """Summarise cached regimes by segment."""

        distribution: dict[str, int] = {}
        for signal in self._segment_regime_cache.values():
            regime_value = (
                signal.regime.value if isinstance(signal.regime, RegimeType) else str(signal.regime)
            )
            distribution[regime_value] = distribution.get(regime_value, 0) + 1
        return distribution

    # Factory function for creating detectors from config


def create_regime_detector(config_dict: dict[str, Any] | None = None) -> RegimeDetectorRules:
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
        variance_ratio_bull=config_dict.get("variance_ratio_bull", 1.1),
        variance_ratio_bear=config_dict.get("variance_ratio_bear", 0.9),
        adx_trend_threshold=config_dict.get("adx_trend_threshold", 15.0),
        volatility_stress_threshold=config_dict.get("volatility_stress_threshold", 2.0),
        volatility_high_threshold=config_dict.get("volatility_high_threshold", 1.6),
        volatility_low_threshold=config_dict.get("volatility_low_threshold", 0.8),
        stress_vol_threshold=config_dict.get("stress_vol_threshold", 2.0),
        stress_volume_threshold=config_dict.get("stress_volume_threshold", 3.0),
        persistence_bars=config_dict.get("persistence_bars", 2),
        cooldown_minutes=config_dict.get("cooldown_minutes", 15),
        variance_ratio_weight=config_dict.get("variance_ratio_weight", 0.4),
        adx_weight=config_dict.get("adx_weight", 0.3),
        volatility_weight=config_dict.get("volatility_weight", 0.2),
        band_position_weight=config_dict.get("band_position_weight", 0.1),
        # Enhanced regime features
        avwap_bias_threshold=config_dict.get("avwap_bias_threshold", 0.02),
        value_acceptance_bars_min=config_dict.get("value_acceptance_bars_min", 3),
        ofi_confirmation_threshold=config_dict.get("ofi_confirmation_threshold", 0.1),
        regime_feature_weight=config_dict.get("regime_feature_weight", 0.15),
    )

    return RegimeDetectorRules(config)


# Convenience function for creating default detector
def create_default_detector() -> RegimeDetectorRules:
    """Create regime detector with default configuration."""
    return RegimeDetectorRules()
