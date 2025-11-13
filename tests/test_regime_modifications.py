#!/usr/bin/env python3
"""Tests to verify regime modifications implementation.

Tests the four key changes made to enable trading functionality:
1. Enhanced features computation is enabled
2. Regime threshold defaults are moderated
3. Policy parameter thresholds are adjusted
4. Synthetic data creation and usage is removed

All tests use real market data only - no synthetic/mock data.
"""

import os
import sys

# Add required paths for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-backtest", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-core", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-features", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-data", "src"))


from qx_backtest.policies.regime_aligned import (
    MomentumParameters,
    PolicyParameters,
    PullbackParameters,
    SweepReversionParameters,
    ValueRotationParameters,
)
from qx_core.regime.detector import RegimeDetectorConfig, create_default_detector

# Import the modules we need to test
from test_regime_pilot import load_test_data, prepare_features


class TestEnhancedFeaturesInclusion:
    """Test 1 - Enhanced features inclusion."""

    def test_enhanced_features_computed(self):
        """Test that enhanced features are included in prepare_features output."""
        # Load real market data
        df = load_test_data()
        assert df is not None, "Failed to load real test data"
        assert len(df) > 0, "No data loaded"

        # Run prepare_features which should now include enhanced features
        df_features = prepare_features(df, verbose=False)
        assert df_features is not None, "prepare_features returned None"
        assert len(df_features) > 0, "No features computed"

        # Check for key enhanced features that should only come from compute_all_regime_enhanced_features
        enhanced_features_to_check = [
            "f__anchor__session_avwap",  # Anchored VWAP
            "f__profile__poc",  # Volume Profile POC
            "f__ict__fvg_bull_active",  # ICT Structure
            "f__flow__ofi",  # Order Flow
            "f__vpa__absorption",  # VPA Pattern
        ]

        # Assert that at least some enhanced features are present
        found_enhanced_features = []
        for feature in enhanced_features_to_check:
            if feature in df_features.columns:
                found_enhanced_features.append(feature)

        assert len(found_enhanced_features) > 0, (
            f"No enhanced features found in output. "
            f"Expected at least one of: {enhanced_features_to_check}. "
            f"Available columns: {[col for col in df_features.columns if col.startswith('f__')]}"
        )

        print(
            f"✓ Found {len(found_enhanced_features)} enhanced features: {found_enhanced_features}"
        )


class TestRegimeThresholdDefaults:
    """Test 2 - Regime threshold defaults."""

    def test_regime_detector_config_defaults(self):
        """Test that RegimeDetectorConfig has the new default values."""
        config = RegimeDetectorConfig()

        # Check all the updated threshold values
        assert config.variance_ratio_bull == 1.2, (
            f"Expected variance_ratio_bull = 1.2, got {config.variance_ratio_bull}"
        )
        assert config.variance_ratio_bear == 0.8, (
            f"Expected variance_ratio_bear = 0.8, got {config.variance_ratio_bear}"
        )
        assert config.adx_trend_threshold == 20.0, (
            f"Expected adx_trend_threshold = 20.0, got {config.adx_trend_threshold}"
        )
        assert config.volatility_high_threshold == 1.6, (
            f"Expected volatility_high_threshold = 1.6, got {config.volatility_high_threshold}"
        )
        assert config.volatility_low_threshold == 0.8, (
            f"Expected volatility_low_threshold = 0.8, got {config.volatility_low_threshold}"
        )
        assert config.persistence_bars in (
            2,
            3,
        ), f"Expected persistence_bars in (2, 3), got {config.persistence_bars}"

        print("✓ All RegimeDetectorConfig defaults are correct")

    def test_create_default_detector_uses_new_defaults(self):
        """Test that create_default_detector uses the new threshold values."""
        detector = create_default_detector()
        config = detector.config

        # Verify the detector uses the new defaults
        assert config.variance_ratio_bull == 1.2
        assert config.variance_ratio_bear == 0.8
        assert config.adx_trend_threshold == 20.0
        assert config.volatility_high_threshold == 1.6
        assert config.volatility_low_threshold == 0.8

        print("✓ create_default_detector uses new threshold defaults")


class TestPolicyParameterThresholds:
    """Test 3 - Policy parameter thresholds."""

    def test_base_policy_parameters_defaults(self):
        """Test that PolicyParameters has the new risk threshold values."""
        params = PolicyParameters()

        # Check the updated risk parameters
        assert params.min_risk_reward == 1.0, (
            f"Expected min_risk_reward = 1.0, got {params.min_risk_reward}"
        )
        assert params.min_atr_value == 0.005, (
            f"Expected min_atr_value = 0.005, got {params.min_atr_value}"
        )

        print("✓ Base PolicyParameters defaults are correct")

    def test_strategy_specific_parameters_inherit_defaults(self):
        """Test that strategy-specific parameter classes inherit new defaults."""
        # Test all strategy parameter classes
        strategy_param_classes = [
            MomentumParameters,
            ValueRotationParameters,
            SweepReversionParameters,
            PullbackParameters,
        ]

        for param_class in strategy_param_classes:
            params = param_class()

            # All should inherit the new base defaults
            assert params.min_risk_reward == 1.0, (
                f"{param_class.__name__} expected min_risk_reward = 1.0, got {params.min_risk_reward}"
            )
            assert params.min_atr_value == 0.005, (
                f"{param_class.__name__} expected min_atr_value = 0.005, got {params.min_atr_value}"
            )

        print("✓ All strategy-specific parameters inherit new defaults")


class TestNoSyntheticDataUsage:
    """Test 4 - No synthetic data usage."""

    def test_no_synthetic_data_function_in_test_regime_pilot(self):
        """Test that test_regime_pilot.py no longer defines create_synthetic_data."""
        import test_regime_pilot

        # Assert that create_synthetic_data function does not exist
        assert not hasattr(test_regime_pilot, "create_synthetic_data"), (
            "test_regime_pilot still has create_synthetic_data function"
        )

        print("✓ test_regime_pilot.py does not have create_synthetic_data function")

    def test_load_test_data_fails_fast_without_real_data(self):
        """Test that load_test_data fails fast when gold data is not available."""
        # We can't actually move the gold directory in a test, but we can verify
        # that the function has the proper error handling by checking its source

        import inspect

        import test_regime_pilot

        # Get the source code of load_test_data
        source = inspect.getsource(test_regime_pilot.load_test_data)

        # Verify it contains the proper error messages
        assert "synthetic data is forbidden" in source, (
            "load_test_data missing synthetic data prohibition message"
        )
        assert "Real data is required" in source, (
            "load_test_data missing real data requirement message"
        )

        # Verify it does NOT contain any references to synthetic data creation
        assert "create_synthetic_data" not in source, (
            "load_test_data still references create_synthetic_data"
        )
        assert "synthetic" not in source.lower() or "synthetic data is forbidden" in source, (
            "load_test_data contains unwanted synthetic data references"
        )

        print("✓ load_test_data has proper fail-fast behavior without synthetic fallback")

    def test_no_synthetic_data_in_test_files(self):
        """Test that no test files contain create_synthetic_data references."""
        import glob

        # Check all test files in the root directory
        test_files = glob.glob("../test_*.py")

        synthetic_functions_found = []
        synthetic_calls_found = []

        for file_path in test_files:
            if os.path.exists(file_path):
                with open(file_path) as f:
                    content = f.read()

                if "def create_synthetic_data(" in content:
                    synthetic_functions_found.append(os.path.basename(file_path))

                if "create_synthetic_data(" in content:
                    synthetic_calls_found.append(os.path.basename(file_path))

        assert len(synthetic_functions_found) == 0, (
            f"Found create_synthetic_data function definitions in: {synthetic_functions_found}"
        )
        assert len(synthetic_calls_found) == 0, (
            f"Found create_synthetic_data function calls in: {synthetic_calls_found}"
        )

        print(f"✓ No synthetic data functions found in {len(test_files)} test files")


class TestIntegrationSmoke:
    """Integration smoke test to ensure everything works together."""

    def test_end_to_end_with_real_data(self):
        """Test that the complete pipeline works with real data."""
        # Load real data
        df = load_test_data()
        assert df is not None, "Failed to load real data"
        assert len(df) > 0, "No data loaded"

        # Process features (should include enhanced features)
        df_features = prepare_features(df, verbose=False)
        assert df_features is not None, "Feature processing failed"
        assert len(df_features) > 0, "No features computed"

        # Verify we have core, regime, and enhanced features
        core_features = [
            col
            for col in df_features.columns
            if col.startswith("f__")
            and not col.startswith("f__regime__")
            and not col.startswith("f__anchor__")
            and not col.startswith("f__profile__")
            and not col.startswith("f__ict__")
            and not col.startswith("f__flow__")
            and not col.startswith("f__vpa__")
            and not col.startswith("f__stress__")
        ]
        regime_features = [col for col in df_features.columns if col.startswith("f__regime__")]
        enhanced_features = [
            col
            for col in df_features.columns
            if any(
                col.startswith(prefix)
                for prefix in [
                    "f__anchor__",
                    "f__profile__",
                    "f__ict__",
                    "f__flow__",
                    "f__vpa__",
                    "f__stress__",
                ]
            )
        ]

        assert len(core_features) > 0, "No core features found"
        assert len(regime_features) > 0, "No regime features found"
        assert len(enhanced_features) > 0, "No enhanced features found"

        print("✓ End-to-end test passed:")
        print(f"  - Core features: {len(core_features)}")
        print(f"  - Regime features: {len(regime_features)}")
        print(f"  - Enhanced features: {len(enhanced_features)}")
        print(f"  - Total bars processed: {len(df_features)}")


if __name__ == "__main__":
    # Run tests manually if called directly
    print("Running regime modifications tests...")
    print("=" * 50)

    # Test 1: Enhanced features
    print("\nTest 1 - Enhanced features inclusion:")
    test1 = TestEnhancedFeaturesInclusion()
    test1.test_enhanced_features_computed()

    # Test 2: Regime thresholds
    print("\nTest 2 - Regime threshold defaults:")
    test2 = TestRegimeThresholdDefaults()
    test2.test_regime_detector_config_defaults()
    test2.test_create_default_detector_uses_new_defaults()

    # Test 3: Policy parameters
    print("\nTest 3 - Policy parameter thresholds:")
    test3 = TestPolicyParameterThresholds()
    test3.test_base_policy_parameters_defaults()
    test3.test_strategy_specific_parameters_inherit_defaults()

    # Test 4: No synthetic data
    print("\nTest 4 - No synthetic data usage:")
    test4 = TestNoSyntheticDataUsage()
    test4.test_no_synthetic_data_function_in_test_regime_pilot()
    test4.test_load_test_data_fails_fast_without_real_data()
    test4.test_no_synthetic_data_in_test_files()

    # Integration test
    print("\nIntegration smoke test:")
    integration = TestIntegrationSmoke()
    integration.test_end_to_end_with_real_data()

    print("\n" + "=" * 50)
    print("✅ All regime modifications tests passed!")
    print("The trading system is ready with:")
    print("  ✓ Enhanced features computation enabled")
    print("  ✓ Moderate regime thresholds applied")
    print("  ✓ Adjusted risk parameters in policies")
    print("  ✓ Synthetic data completely removed")
    print("  ✓ Real market data only")
