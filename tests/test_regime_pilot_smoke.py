#!/usr/bin/env python3
"""Smoke tests for regime pilot pipeline."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))

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


if __name__ == "__main__":
    # Run smoke tests
    pytest.main([__file__, "-v"])
