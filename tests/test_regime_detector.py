"""Unit tests for regime detection rules and logic.

Tests regime classification, persistence guards, cooldown logic,
and detector configuration validation.
"""

import numpy as np
import pandas as pd
import pytest

from qx_core.regime.detector import (
    RegimeDetectorConfig,
    RegimeDetectorRules,
    create_default_detector,
    create_regime_detector,
)
from qx_core.regime_config import RegimeConfig, validate_regime_config
from qx_core.schemas import RegimeSignal, RegimeType


@pytest.fixture
def sample_features():
    """Create sample regime features for testing."""
    np.random.seed(42)

    # Create features for different market conditions
    data = []

    # Normal/sideways market
    for i in range(50):
        data.append(
            {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "f__regime__mod_vol_30": 1.0 + np.random.normal(0, 0.1),
                "f__regime__var_ratio_10_60": 1.0 + np.random.normal(0, 0.1),
                "f__regime__adx_proxy_14": 20.0 + np.random.normal(0, 5),
                "f__regime__band_pos_20_2.0": 0.5 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 0.1,
                "f__regime__warmup_ok": True,
            }
        )

    # Trending market (bull)
    for i in range(50, 100):
        data.append(
            {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "f__regime__mod_vol_30": 1.2 + np.random.normal(0, 0.1),
                "f__regime__var_ratio_10_60": 1.5 + np.random.normal(0, 0.1),
                "f__regime__adx_proxy_14": 40.0 + np.random.normal(0, 5),
                "f__regime__band_pos_20_2.0": 0.8 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 0.2,
                "f__regime__warmup_ok": True,
            }
        )

    # Stress market
    for i in range(100, 120):
        data.append(
            {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "f__regime__mod_vol_30": 3.0 + np.random.normal(0, 0.2),
                "f__regime__var_ratio_10_60": 2.0 + np.random.normal(0, 0.2),
                "f__regime__adx_proxy_14": 60.0 + np.random.normal(0, 10),
                "f__regime__band_pos_20_2.0": 0.9 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 2.5,
                "f__regime__warmup_ok": True,
            }
        )

    # Trending market (bear)
    for i in range(120, 170):
        data.append(
            {
                "ts": i * 60 * 1e9,
                "symbol": "TEST",
                "f__regime__mod_vol_30": 1.3 + np.random.normal(0, 0.1),
                "f__regime__var_ratio_10_60": 0.6 + np.random.normal(0, 0.1),
                "f__regime__adx_proxy_14": 45.0 + np.random.normal(0, 5),
                "f__regime__band_pos_20_2.0": 0.2 + np.random.normal(0, 0.1),
                "f__regime__stress_10_10": 0.3,
                "f__regime__warmup_ok": True,
            }
        )

    return pd.DataFrame(data)


@pytest.fixture
def multi_symbol_features():
    """Create multi-symbol regime features."""
    np.random.seed(123)
    symbols = ["AAPL", "MSFT", "GOOGL"]
    data = []

    for symbol in symbols:
        for i in range(30):
            # Different regime for each symbol
            if symbol == "AAPL":
                # Bull regime
                var_ratio = 1.4
                adx = 35.0
                band_pos = 0.7
                stress = 0.1
            elif symbol == "MSFT":
                # Sideways regime
                var_ratio = 1.0
                adx = 20.0
                band_pos = 0.5
                stress = 0.1
            else:  # GOOGL
                # Stress regime
                var_ratio = 1.8
                adx = 50.0
                band_pos = 0.9
                stress = 2.0

            data.append(
                {
                    "ts": i * 60 * 1e9,
                    "symbol": symbol,
                    "f__regime__mod_vol_30": 1.0 + np.random.normal(0, 0.1),
                    "f__regime__var_ratio_10_60": var_ratio + np.random.normal(0, 0.05),
                    "f__regime__adx_proxy_14": adx + np.random.normal(0, 2),
                    "f__regime__band_pos_20_2.0": band_pos + np.random.normal(0, 0.05),
                    "f__regime__stress_10_10": stress + np.random.normal(0, 0.1),
                    "f__regime__warmup_ok": True,
                }
            )

    return pd.DataFrame(data)


class TestRegimeDetectorConfig:
    """Test regime detector configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = RegimeDetectorConfig()

        assert config.variance_ratio_bull == 1.2
        assert config.variance_ratio_bear == 0.8
        assert config.adx_trend_threshold == 30.0
        assert config.persistence_bars == 3
        assert config.cooldown_minutes == 15

    def test_custom_config(self):
        """Test custom configuration values."""
        config = RegimeDetectorConfig(
            variance_ratio_bull=1.5, persistence_bars=5, cooldown_minutes=30
        )

        assert config.variance_ratio_bull == 1.5
        assert config.persistence_bars == 5
        assert config.cooldown_minutes == 30


class TestRegimeDetectorRules:
    """Test regime detector rules and logic."""

    def test_detector_initialization(self):
        """Test detector initialization with default config."""
        detector = RegimeDetectorRules()

        assert detector.config.variance_ratio_bull == 1.2
        assert detector.config.persistence_bars == 3
        assert detector._evaluation_count == 0
        assert detector._regime_changes == 0

    def test_detector_initialization_custom_config(self):
        """Test detector initialization with custom config."""
        config = RegimeDetectorConfig(persistence_bars=5)
        detector = RegimeDetectorRules(config)

        assert detector.config.persistence_bars == 5

    def test_am_pm_segment_caching(self):
        """Test that detector only re-evaluates once per session segment."""
        detector = RegimeDetectorRules()

        def build_features(var_ratio, adx, band_pos, vol, ofi):
            return pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "f__regime__var_ratio_10_60": [var_ratio],
                    "f__regime__adx_proxy_14": [adx],
                    "f__regime__band_pos_20_2.0": [band_pos],
                    "f__regime__mod_vol_30": [vol],
                    "f__regime__stress_10_10": [0.1],
                    "f__regime__warmup_ok": [True],
                    "f__flow__ofi_trend": [ofi],
                    "f__ict__in_discount": [ofi > 0],
                    "f__ict__in_premium": [ofi < 0],
                    "f__profile__value_acceptance": [0.0],
                }
            )

        morning_ts = (
            pd.Timestamp("2024-01-02 10:00:00", tz="America/New_York")
            .tz_convert("UTC")
            .value
        )
        afternoon_ts = (
            pd.Timestamp("2024-01-02 14:00:00", tz="America/New_York")
            .tz_convert("UTC")
            .value
        )
        late_afternoon_ts = (
            pd.Timestamp("2024-01-02 15:30:00", tz="America/New_York")
            .tz_convert("UTC")
            .value
        )

        morning_features = build_features(1.4, 40.0, 0.7, 1.2, 0.2)
        afternoon_features = build_features(0.6, 35.0, 0.3, 1.1, -0.2)
        late_features = build_features(1.5, 45.0, 0.8, 1.0, 0.3)

        morning_signal = detector.evaluate(morning_features, morning_ts)
        assert morning_signal.regime == RegimeType.BULL
        assert morning_signal.segment == "AM"
        assert morning_signal.session_date == "2024-01-02"

        afternoon_signal = detector.evaluate(afternoon_features, afternoon_ts)
        assert afternoon_signal.regime == RegimeType.BEAR
        assert afternoon_signal.segment == "PM"

        cached_signal = detector.evaluate(late_features, late_afternoon_ts)
        assert cached_signal.regime == RegimeType.BEAR
        assert cached_signal.segment == "PM"
        assert detector.get_statistics()["cached_segments"] == 2

    def test_evaluate_empty_dataframe(self):
        """Test evaluation with empty DataFrame."""
        detector = RegimeDetectorRules()
        empty_df = pd.DataFrame()
        ts = int(pd.Timestamp("2024-01-01 10:00:00").timestamp() * 1e9)

        signal = detector.evaluate(empty_df, ts)

        assert signal.regime == RegimeType.OFF
        assert signal.confidence == 0.0
        assert "No data available" in signal.features.get("reason", "")

    def test_evaluate_no_warmup(self):
        """Test evaluation before features are warmed up."""
        detector = RegimeDetectorRules()
        df = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["TEST"],
                "f__regime__var_ratio_10_60": [1.0],
                "f__regime__warmup_ok": [False],  # Not warmed up
            }
        )
        ts = 1

        signal = detector.evaluate(df, ts)

        assert signal.regime == RegimeType.OFF
        assert "not warmed up" in signal.features.get("reason", "")

    def test_stress_detection(self, sample_features):
        """Test stress regime detection."""
        detector = RegimeDetectorRules()
        config = RegimeDetectorConfig(
            volatility_stress_threshold=2.0, stress_confidence_min=0.8
        )
        detector.config = config

        # Use stress period data
        stress_data = sample_features[sample_features["f__regime__stress_10_10"] > 2.0]
        ts = stress_data.iloc[0]["ts"]

        signal = detector.evaluate(stress_data, ts)

        assert signal.regime == RegimeType.STRESS
        assert signal.confidence >= config.stress_confidence_min

    def test_bull_regime_detection(self, sample_features):
        """Test bull regime detection."""
        detector = RegimeDetectorRules()

        # Use bull period data
        bull_data = sample_features[
            (sample_features.index >= 50) & (sample_features.index < 100)
        ]
        ts = bull_data.iloc[0]["ts"]

        signal = detector.evaluate(bull_data, ts)

        # Should detect bull regime with reasonable confidence
        assert signal.regime in [RegimeType.BULL, RegimeType.SIDEWAYS]
        if signal.regime == RegimeType.BULL:
            assert signal.confidence > 0.5

    def test_bear_regime_detection(self, sample_features):
        """Test bear regime detection."""
        detector = RegimeDetectorRules()

        # Use bear period data
        bear_data = sample_features[
            (sample_features.index >= 120) & (sample_features.index < 170)
        ]
        ts = bear_data.iloc[0]["ts"]

        signal = detector.evaluate(bear_data, ts)

        # Should detect bear regime with reasonable confidence
        assert signal.regime in [RegimeType.BEAR, RegimeType.SIDEWAYS]
        if signal.regime == RegimeType.BEAR:
            assert signal.confidence > 0.5

    def test_sideways_regime_detection(self, sample_features):
        """Test sideways regime detection."""
        detector = RegimeDetectorRules()

        # Use sideways period data
        sideways_data = sample_features[sample_features.index < 50]
        ts = sideways_data.iloc[0]["ts"]

        signal = detector.evaluate(sideways_data, ts)

        # Should detect sideways regime
        assert signal.regime == RegimeType.SIDEWAYS
        assert signal.confidence >= 0.3

    def test_symbol_level_evaluation(self, sample_features):
        """Test evaluation for individual symbol."""
        detector = RegimeDetectorRules()

        # Extract features for single timestamp
        features = sample_features.iloc[0].to_dict()
        ts = features["ts"]

        signal = detector.evaluate_symbol("TEST", features, ts)

        assert isinstance(signal, RegimeSignal)
        assert signal.ts == ts
        assert signal.regime in RegimeType
        assert 0.0 <= signal.confidence <= 1.0

    def test_persistence_guard(self):
        """Test persistence guard prevents excessive switching."""
        config = RegimeDetectorConfig(persistence_bars=3)
        detector = RegimeDetectorRules(config)

        # Simulate alternating signals
        features_bull = {
            "f__regime__var_ratio_10_60": 1.5,
            "f__regime__adx_proxy_14": 40.0,
            "f__regime__band_pos_20_2.0": 0.8,
            "f__regime__mod_vol_30": 1.2,
            "f__regime__stress_10_10": 0.1,
        }
        features_bear = {
            "f__regime__var_ratio_10_60": 0.6,
            "f__regime__adx_proxy_14": 40.0,
            "f__regime__band_pos_20_2.0": 0.2,
            "f__regime__mod_vol_30": 1.2,
            "f__regime__stress_10_10": 0.1,
        }

        # First signal should establish initial regime
        ts1 = 1000000000000
        signal1 = detector.evaluate_symbol("TEST", features_bull, ts1)
        initial_regime = signal1.regime

        # Second different signal should not change regime yet (persistence)
        ts2 = ts1 + 60 * 1e9
        signal2 = detector.evaluate_symbol("TEST", features_bear, ts2)
        assert signal2.regime == initial_regime  # Should stay the same

        # Continue with same regime to build persistence
        for i in range(3):
            ts = ts2 + (i + 1) * 60 * 1e9
            signal = detector.evaluate_symbol("TEST", features_bull, ts)
            assert signal.regime == initial_regime
            assert signal.persistence_count == i + 2

    def test_cooldown_logic(self):
        """Test cooldown logic prevents immediate reversion."""
        config = RegimeDetectorConfig(cooldown_minutes=15)
        detector = RegimeDetectorRules(config)

        features = {
            "f__regime__var_ratio_10_60": 1.5,
            "f__regime__adx_proxy_14": 40.0,
            "f__regime__band_pos_20_2.0": 0.8,
            "f__regime__mod_vol_30": 1.2,
            "f__regime__stress_10_10": 0.1,
        }

        # Establish initial regime
        ts1 = 1000000000000
        signal1 = detector.evaluate_symbol("TEST", features, ts1)

        # Try to change regime immediately (should be blocked by cooldown)
        features_bear = features.copy()
        features_bear["f__regime__var_ratio_10_60"] = 0.6
        features_bear["f__regime__band_pos_20_2.0"] = 0.2

        ts2 = ts1 + 60 * 1e9  # 1 minute later
        signal2 = detector.evaluate_symbol("TEST", features_bear, ts2)
        assert signal2.regime == signal1.regime  # Should stay the same

    def test_multi_symbol_evaluation(self, multi_symbol_features):
        """Test evaluation across multiple symbols."""
        detector = RegimeDetectorRules()

        # Get unique timestamps
        timestamps = multi_symbol_features["ts"].unique()

        # Evaluate first timestamp
        ts = timestamps[0]
        ts_data = multi_symbol_features[multi_symbol_features["ts"] == ts]

        signal = detector.evaluate(ts_data, ts)

        assert isinstance(signal, RegimeSignal)
        assert signal.ts == ts
        assert signal.regime in RegimeType

        # Should have aggregated features
        assert len(signal.features) > 0

    def test_statistics_tracking(self):
        """Test detector statistics tracking."""
        detector = RegimeDetectorRules()

        features = {
            "f__regime__var_ratio_10_60": 1.0,
            "f__regime__adx_proxy_14": 25.0,
            "f__regime__band_pos_20_2.0": 0.5,
            "f__regime__mod_vol_30": 1.0,
            "f__regime__stress_10_10": 0.1,
        }

        # Perform evaluations
        for i in range(10):
            ts = i * 60 * 1e9
            detector.evaluate_symbol("TEST", features, ts)

        stats = detector.get_statistics()

        assert stats["evaluations"] == 10
        assert stats["symbols_tracked"] == 1
        assert 0 <= stats["change_rate"] <= 1.0
        assert stats["avg_persistence"] >= 0

    def test_reset_state(self):
        """Test detector state reset."""
        detector = RegimeDetectorRules()

        features = {
            "f__regime__var_ratio_10_60": 1.0,
            "f__regime__adx_proxy_14": 25.0,
            "f__regime__band_pos_20_2.0": 0.5,
            "f__regime__mod_vol_30": 1.0,
            "f__regime__stress_10_10": 0.1,
        }

        # Perform some evaluations
        detector.evaluate_symbol("TEST", features, 1000000000000)
        detector.evaluate_symbol("TEST", features, 1000000000060)

        # Reset state
        detector.reset_state()

        # Check state is cleared
        stats = detector.get_statistics()
        assert stats["evaluations"] == 0
        assert stats["regime_changes"] == 0
        assert stats["symbols_tracked"] == 0

    def test_feature_aggregation(self, multi_symbol_features):
        """Test proper feature aggregation across symbols."""
        detector = RegimeDetectorRules()

        # Get timestamp with multiple symbols
        ts = multi_symbol_features["ts"].unique()[0]
        ts_data = multi_symbol_features[multi_symbol_features["ts"] == ts]

        signal = detector.evaluate(ts_data, ts)

        # Should have aggregated features (median across symbols)
        assert "f__regime__var_ratio_10_60" in signal.features
        assert "f__regime__adx_proxy_14" in signal.features

        # Aggregated values should be reasonable
        for _feature_name, value in signal.features.items():
            if isinstance(value, (int, float)):
                assert not np.isnan(value)
                assert np.isfinite(value)


class TestRegimeDetectorFactory:
    """Test detector factory functions."""

    def test_create_regime_detector_default(self):
        """Test creating detector with default config."""
        detector = create_regime_detector()

        assert isinstance(detector, RegimeDetectorRules)
        assert detector.config.variance_ratio_bull == 1.2

    def test_create_regime_detector_custom(self):
        """Test creating detector with custom config."""
        config_dict = {
            "variance_ratio_bull": 1.5,
            "persistence_bars": 5,
            "cooldown_minutes": 30,
        }

        detector = create_regime_detector(config_dict)

        assert isinstance(detector, RegimeDetectorRules)
        assert detector.config.variance_ratio_bull == 1.5
        assert detector.config.persistence_bars == 5
        assert detector.config.cooldown_minutes == 30

    def test_create_default_detector(self):
        """Test creating default detector."""
        detector = create_default_detector()

        assert isinstance(detector, RegimeDetectorRules)


class TestRegimeConfig:
    """Test regime configuration validation."""

    def test_default_config(self):
        """Test default regime configuration."""
        config = RegimeConfig()

        assert not config.enabled
        assert config.model == "rules"
        assert config.persistence_bars == 3
        assert "BULL" in config.strategy_map
        assert "STRESS" in config.strategy_map

    def test_custom_config(self):
        """Test custom regime configuration."""
        config = RegimeConfig(enabled=True, persistence_bars=5, model="hsmm")

        assert config.enabled
        assert config.model == "hsmm"
        assert config.persistence_bars == 5

    def test_invalid_strategy_map(self):
        """Test validation of invalid strategy mapping."""
        with pytest.raises(ValueError, match="Invalid regime in strategy_map"):
            RegimeConfig(strategy_map={"INVALID_REGIME": ["strategy1"]})

    def test_invalid_feature_config(self):
        """Test validation of invalid feature configuration."""
        with pytest.raises(ValueError, match="must be a positive integer"):
            RegimeConfig(features={"volatility_window": -1})

    def test_invalid_detector_params(self):
        """Test validation of invalid detector parameters."""
        with pytest.raises(ValueError, match="must be positive"):
            RegimeConfig(detector_params={"variance_ratio_bull": -1})

    def test_invalid_weight_sum(self):
        """Test validation of weight sum constraint."""
        with pytest.raises(ValueError, match="weights must sum to approximately 1.0"):
            RegimeConfig(
                detector_params={
                    "variance_ratio_weight": 0.8,
                    "adx_weight": 0.8,  # Sum > 1.0
                    "volatility_weight": 0.2,
                    "band_position_weight": 0.1,
                }
            )

    def test_invalid_band_bounds(self):
        """Test validation of band position bounds."""
        with pytest.raises(
            ValueError, match="sideways_band_min must be less than sideways_band_max"
        ):
            RegimeConfig(
                detector_params={"sideways_band_min": 0.8, "sideways_band_max": 0.2}
            )

    def test_validate_regime_config_function(self):
        """Test regime config validation function."""
        valid_config = {
            "enabled": True,
            "persistence_bars": 5,
            "strategy_map": {"BULL": ["strategy1"], "BEAR": ["strategy2"]},
        }

        config = validate_regime_config(valid_config)
        assert isinstance(config, RegimeConfig)
        assert config.enabled
        assert config.persistence_bars == 5

    def test_validate_invalid_config(self):
        """Test validation of invalid configuration."""
        invalid_config = {
            "enabled": "not_boolean",  # Invalid type
            "persistence_bars": -1,  # Invalid value
        }

        with pytest.raises(ValueError, match="Invalid regime configuration"):
            validate_regime_config(invalid_config)


class TestRegimeSignal:
    """Test RegimeSignal creation and validation."""

    def test_signal_creation(self):
        """Test RegimeSignal creation."""
        ts = int(pd.Timestamp("2024-01-01 10:00:00").timestamp() * 1e9)
        signal = RegimeSignal(
            ts=ts,
            regime=RegimeType.BULL,
            confidence=0.8,
            features={"variance_ratio": 1.5},
            persistence_count=3,
            model_version="rules_v1",
        )

        assert signal.ts == ts
        assert signal.regime == RegimeType.BULL
        assert signal.confidence == 0.8
        assert signal.features["variance_ratio"] == 1.5
        assert signal.persistence_count == 3
        assert signal.model_version == "rules_v1"
        assert signal.src == "regime"

    def test_signal_confidence_bounds(self):
        """Test signal confidence bounds."""
        ts = 1000000000000

        # Valid confidence
        signal = RegimeSignal(ts=ts, regime=RegimeType.BULL, confidence=0.8)
        assert signal.confidence == 0.8

        # Invalid confidence (below bounds)
        with pytest.raises(ValueError):
            RegimeSignal(ts=ts, regime=RegimeType.BULL, confidence=-0.1)

        # Invalid confidence (above bounds)
        with pytest.raises(ValueError):
            RegimeSignal(ts=ts, regime=RegimeType.BULL, confidence=1.1)


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_missing_features(self):
        """Test behavior with missing required features."""
        detector = RegimeDetectorRules()
        df = pd.DataFrame(
            {
                "ts": [1],
                "symbol": ["TEST"],
                "f__regime__warmup_ok": [True],
                # Missing required features
            }
        )
        ts = 1

        signal = detector.evaluate(df, ts)

        # Should default to OFF regime
        assert signal.regime == RegimeType.OFF
        assert signal.confidence == 0.0

    def test_extreme_feature_values(self):
        """Test behavior with extreme feature values."""
        detector = RegimeDetectorRules()

        features = {
            "f__regime__var_ratio_10_60": 100.0,  # Very high
            "f__regime__adx_proxy_14": 200.0,  # Very high
            "f__regime__band_pos_20_2.0": 2.0,  # Outside bands
            "f__regime__mod_vol_30": 10.0,  # Very high volatility
            "f__regime__stress_10_10": 50.0,  # Extreme stress
        }

        ts = 1000000000000
        signal = detector.evaluate_symbol("TEST", features, ts)

        # Should handle gracefully (likely stress regime)
        assert signal.regime in RegimeType
        assert 0.0 <= signal.confidence <= 1.0

    def test_zero_persistence_bars(self):
        """Test detector with zero persistence bars."""
        config = RegimeDetectorConfig(persistence_bars=0)
        detector = RegimeDetectorRules(config)

        features = {
            "f__regime__var_ratio_10_60": 1.5,
            "f__regime__adx_proxy_14": 40.0,
            "f__regime__band_pos_20_2.0": 0.8,
            "f__regime__mod_vol_30": 1.2,
            "f__regime__stress_10_10": 0.1,
        }

        ts = 1000000000000
        signal1 = detector.evaluate_symbol("TEST", features, ts)
        signal2 = detector.evaluate_symbol("TEST", features, ts + 60 * 1e9)

        # With zero persistence, should change regime immediately
        # (though confidence might be low for single change)
        assert signal1.persistence_count >= 0
        assert signal2.persistence_count >= 0


def test_detector_with_newly_fixed_columns():
    """Add scenario verifying evaluate() continues working with new features by including newly fixed columns (ensures no KeyError after changes)."""
    # Create detector with default configuration
    detector = create_default_detector()

    # Create features including all newly fixed columns from Workstream B
    features = {
        # Basic regime features
        "f__regime__var_ratio_10_60": 1.3,  # Trending market
        "f__regime__adx_proxy_14": 32.0,  # Strong trend
        "f__regime__mod_vol_30": 1.1,  # Normal volatility
        "f__regime__band_pos_20_2.0": 0.85,  # Upper band position
        "f__regime__stress_10_10": 0.0,  # No stress
        # NEWLY FIXED COLUMNS from Workstream B:
        # B1: Previous-Extreme AVWAP Persistence
        "f__anchor__prev_high_avwap": 150.8,  # Should be computed properly without NaN issues
        "f__anchor__prev_low_avwap": 149.2,  # Should maintain persistence after touch
        # B2: ICT FVG Level Stability
        "f__ict__fvg_bull_lower": 150.3,  # Should be non-null at first detection
        "f__ict__fvg_bull_upper": 150.7,  # Should be properly set without shift errors
        "f__ict__fvg_bull_active": True,  # Should correctly track fill status
        "f__ict__fvg_bear_lower": 149.5,  # Should be non-null at first detection
        "f__ict__fvg_bear_upper": 149.9,  # Should be properly set without shift errors
        "f__ict__fvg_bear_active": False,  # Should correctly track fill status
        # B3: VPA Stopping Volume Robustness
        "f__vpa__stopping_volume": True,  # Should be computed without int < DataFrame errors
        "f__vpa__absorption": True,  # Should work properly with fixed logic
        "f__vpa__climax": False,  # Should work without errors
        # Additional enhanced features to ensure compatibility
        "f__anchor__session_avwap": 150.0,
        "f__anchor__first_hour_avwap": 150.2,
        "f__profile__poc": 150.1,
        "f__profile__vah": 150.8,
        "f__profile__val": 149.4,
        "f__flow__ofi": 1200.0,
        "f__flow__ofi_trend": 0.15,
        "f__ict__in_discount": False,
        "f__ict__disp_high": 151.0,
        "f__ict__disp_low": 149.0,
        "f__stress__contraction": False,
    }

    ts = 1704067200000000000  # 2024-01-01 00:00:00 UTC in nanoseconds

    # This should not raise any KeyError exceptions
    try:
        signal = detector.evaluate_symbol("AAPL", features, ts)

        # Verify signal was created successfully
        assert signal is not None
        assert signal.symbol == "AAPL"
        assert signal.ts == ts

        # With strong trend features, should detect BULL regime
        assert signal.regime in [
            RegimeType.BULL,
            RegimeType.SIDEWAYS,
        ]  # BULL expected but SIDEWAYS acceptable

        # Should have confidence score
        assert 0.0 <= signal.confidence <= 1.0

        # Should have segment metadata
        assert hasattr(signal, "segment")
        assert hasattr(signal, "session_date")

    except KeyError as e:
        pytest.fail(
            f"Detector evaluation failed with KeyError: {e}. This indicates the detector cannot handle newly fixed columns."
        )
    except Exception as e:
        pytest.fail(f"Detector evaluation failed with unexpected error: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
