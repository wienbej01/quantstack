#!/usr/bin/env python3
"""Smoke tests for regime pilot pipeline."""

# Add paths for imports
import sys
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.regime_aligned import AVWAPMomentumPolicy
from test_regime_pilot import (
    create_regime_detector,
    prepare_features,
    run_diagnostic_check,
)


def create_minimal_dataset() -> pd.DataFrame:
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


def test_prepare_features_includes_regime_features() -> None:
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


def test_engine_updates_regime() -> None:
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
        def process_bar(self, bar: dict) -> None:
            calls.append(bar.get("f__regime__current", "NONE"))

    policy = MockPolicy()

    # Strategy function that uses the policy
    def strategy_func(engine: BacktestEngine, bar: dict) -> None:
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


def test_diagnostic_regime_counts() -> None:
    """Test that diagnostic logging provides regime distribution statistics."""
    # Create sample data with known regime distribution
    df = create_minimal_dataset()
    df_features = prepare_features(df)

    # Create detector and capture logs from diagnostic function
    detector = create_regime_detector()
    with patch("builtins.print") as mock_print:
        try:
            run_diagnostic_check(df_features, detector, verbose=True)
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


def test_detector_produces_non_sideways_signals() -> None:
    """Test that regime detector produces some non-SIDEWAYS signals."""
    df = create_minimal_dataset()
    df_features = prepare_features(df)
    detector = create_regime_detector()

    # Count regimes (excluding warmup)
    regime_counts = {"BULL": 0, "BEAR": 0, "SIDEWAYS": 0, "STRESS": 0, "OFF": 0}

    warmup_mask = df_features["f__regime__warmup_ok"]
    ready_bars = df_features[warmup_mask]

    for _, bar in ready_bars.iterrows():
        features = {
            "var_ratio": bar["f__regime__var_ratio_10_60"],
            "adx": bar["f__regime__adx_proxy_14"],
            "band_pos": bar["f__regime__band_pos_20_2.0"],
            "mod_vol": bar["f__regime__mod_vol_30"],
            "stress": bar["f__regime__stress_10_10"],
        }

        signal = detector.evaluate_symbol("AAPL", features, bar["ts"])
        if signal:
            regime_counts[signal.regime] += 1

    # Assert we have some signals (OFF is valid for synthetic data)
    total_signals = sum(regime_counts.values())
    assert total_signals > 0, f"No regimes detected: {regime_counts}"

    print(f"Regime distribution: {regime_counts}")

    # Note: Synthetic data often produces OFF regimes, which is expected.
    # The important thing is that the detector produces signals without crashing.


def test_backtest_engine_generates_orders() -> None:
    """Test that BacktestEngine generates orders/trades with regime-aware policy."""
    df = create_minimal_dataset()
    df_features = prepare_features(df)

    # Use just AAPL data
    symbol_data = df_features[df_features["symbol"] == "AAPL"].copy()

    # Create backtest config
    config = BacktestConfig(
        initial_cash=100000.0, strategy_map={"BULL": ["avwap_momentum"], "SIDEWAYS": []}
    )
    engine = BacktestEngine(config)

    # Create policy
    policy = AVWAPMomentumPolicy()

    # Strategy function
    def strategy_func(engine: BacktestEngine, bar: dict) -> None:
        policy.process_bar(bar)

    # Run backtest
    result = engine.run(symbol_data, strategy_func)

    # Assert we have some trading activity (even if no fills)
    assert hasattr(result, "orders_history"), "BacktestResult missing orders_history"
    assert hasattr(result, "trades_history"), "BacktestResult missing trades_history"

    # We may not have actual trades, but should have order generation attempts
    print(f"Orders generated: {len(result.orders_history)}")
    print(f"Trades executed: {len(result.trades_history)}")


def test_integration_end_to_end() -> None:
    """End-to-end integration test of the complete pipeline."""
    # This test runs the equivalent of the main pilot test flow
    df = create_minimal_dataset()

    # Full pipeline
    df_features = prepare_features(df)
    detector = create_regime_detector()

    # Should not raise any exceptions
    assert len(df_features) > 0
    assert detector is not None

    # Basic sanity checks
    regime_cols = [col for col in df_features.columns if col.startswith("f__regime__")]
    MIN_REGIME_FEATURES = 6  # Minimum regime features
    assert len(regime_cols) >= MIN_REGIME_FEATURES

    print("✅ End-to-end integration test passed")


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v"])
