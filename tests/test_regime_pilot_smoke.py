#!/usr/bin/env python3
"""Smoke tests for regime pilot pipeline."""

import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))

from qx_backtest.engine import BacktestConfig, BacktestEngine
from test_regime_pilot import prepare_features


def create_minimal_dataset():
    """Create minimal test dataset with realistic features."""
    np.random.seed(42)  # Deterministic

    # Create 200 bars (enough for warmup + signals)
    timestamps = pd.date_range(
        "2024-04-01 09:30:00", periods=200, freq="1min", tz="America/New_York"
    )

    data = []
    base_price = 150.0

    for i, ts in enumerate(timestamps):
        # Simple price process with some trend
        trend = 0.1 * np.sin(i * 0.05)  # Sinusoidal trend
        noise = np.random.randn() * 0.2
        price = base_price + trend + noise

        high = price + abs(np.random.randn() * 0.1)
        low = price - abs(np.random.randn() * 0.1)
        open_price = low + (high - low) * np.random.random()
        close = low + (high - low) * np.random.random()
        volume = np.random.randint(1000, 5000)

        data.append(
            {
                "ts": int(ts.tz_convert("UTC").timestamp() * 1e9),
                "symbol": "AAPL",
                "open": open_price,
                "high": high,
                "low": low,
                "close": close,
                "volume": volume,
            }
        )

    return pd.DataFrame(data)


def test_prepare_features_includes_regime_features():
    """Test that prepare_features includes all required regime features."""
    df = create_minimal_dataset()

    # Process features
    result = prepare_features(df)

    # Assert regime features are present
    expected_regime_features = [
        "f__regime__var_ratio_10_60",
        "f__regime__adx_proxy_14",
        "f__regime__band_pos_20_2.0",
        "f__regime__mod_vol_30",
        "f__regime__stress_10_10",
        "f__regime__warmup_ok",
    ]

    for feature in expected_regime_features:
        assert feature in result.columns, f"Missing regime feature: {feature}"

    # Assert warmup mask exists and has some True values
    assert "f__regime__warmup_ok" in result.columns
    warmup_true = result["f__regime__warmup_ok"].sum()
    assert warmup_true > 0, "No bars marked as ready past warmup"


def test_engine_updates_regime():
    """Test that BacktestEngine properly runs regime detection through engine.run()."""
    # Create backtest config with regime detection enabled
    config = BacktestConfig(initial_cash=100000.0, regime_config={"enabled": True})
    engine = BacktestEngine(config)

    # Create sample data with regime features
    df = create_minimal_dataset()
    df_features = prepare_features(df)

    # Mock policy to capture regime calls
    calls = []

    class MockPolicy:
        def process_bar(self, bar):
            calls.append(bar.get("f__regime__current", "NONE"))

    policy = MockPolicy()

    # Strategy function that uses the policy
    def strategy_func(engine, bar):
        policy.process_bar(bar)

    # Run backtest through engine.run (should handle regime detection automatically)
    engine.run(df_features, strategy_func)

    # Verify regime detection occurred and we got some calls
    assert len(calls) > 0, "No bars were processed"
    print(f"Regime calls captured: {len(calls)} total")

    # Check that regime detection worked (should have regimes beyond just 'NONE')
    unique_regimes = {str(call) for call in calls if call != "NONE"}
    print(f"Unique regimes detected: {unique_regimes}")

    # The test passes if the engine processes bars and detects regimes
    assert len(unique_regimes) > 0, "No regimes detected"


def test_diagnostic_regime_counts():
    """Test that diagnostic logging provides regime distribution statistics."""
    # Create sample data with known regime distribution
    df = create_minimal_dataset()
    df_features = prepare_features(df)

    # Capture logs from diagnostic function (should fail initially)
    with patch("builtins.print") as mock_print:
        try:
            from test_regime_pilot import run_diagnostic_check

            run_diagnostic_check(df_features, verbose=True)
        except ImportError:
            # Function doesn't exist yet - test should fail
            pytest.fail(
                "run_diagnostic_check function not found in test_regime_pilot.py"
            )

    # Assert regime counts were logged
    log_calls = [str(call) for call in mock_print.call_args_list]

    # Should contain diagnostic header
    assert any(
        "DIAGNOSTIC" in call and "Regime Signal Distribution" in call
        for call in log_calls
    ), "Diagnostic header not found in logs"

    # Should contain regime counts (format: "BULL: 0 (0.0%)")
    assert any(
        "BULL:" in call for call in log_calls
    ), "BULL regime count not found in logs"

    # Should contain ready bars count
    assert any(
        "Ready bars" in call for call in log_calls
    ), "Ready bars count not found in logs"


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v"])
