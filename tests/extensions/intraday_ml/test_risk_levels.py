"""Tests for ATR-based risk helper utilities."""

import pandas as pd
import pytest

from extensions.intraday_ml.risk_levels import compute_risk_levels


def test_compute_risk_levels_uses_support_reference():
    """Verify stop distance respects the provided support level."""
    row = pd.Series(
        {
            "close": 100.0,
            "low": 99.8,
            "high": 100.3,
            "f__vol__atr_6": 0.4,
        }
    )
    config = {
        "price_column": "close",
        "atr_feature": "f__vol__atr_6",
        "support_feature_long": "low",
        "resistance_feature_short": "high",
        "max_atr_multiple": 1.0,
        "support_buffer_atr": 0.0,
        "target_r_multiple": 1.5,
        "min_stop_pct": 0.0005,
        "max_stop_pct": 0.05,
    }

    result = compute_risk_levels(row=row, side="long", config=config)
    assert result is not None
    assert pytest.approx(result.stop_pct, rel=1e-6) == 0.002
    assert pytest.approx(result.take_profit_pct, rel=1e-6) == 0.003
    assert pytest.approx(result.expected_r, rel=1e-6) == 1.5
    assert result.metadata["risk_reference_level"] == 99.8
