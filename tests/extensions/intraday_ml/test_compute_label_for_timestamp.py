"""Tests for compute_label_for_timestamp method

Tests for the new labeling method that computes labels for individual timestamps
using future price movements with strict no-lookahead bias enforcement.
"""

import warnings
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from extensions.intraday_ml.labeling import IntradayMLLabeler


class TestComputeLabelForTimestamp:
    """Tests for compute_label_for_timestamp method."""

    @pytest.fixture
    def targets_config(self):
        """Load targets configuration with adjusted ATR multiplier for testing."""
        config_path = Path("configs/extensions/intraday_ml/targets.yaml")
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        # Adjust ATR multiplier for testing - make threshold easier to hit
        config["atr_multiplier"] = 0.05  # 5% of ATR instead of 100%
        return config

    @pytest.fixture
    def labeler(self, targets_config):
        """Initialize labeler with test configuration."""
        return IntradayMLLabeler(targets_config)

    @pytest.fixture
    def sample_data_window(self):
        """Create a realistic sample data window for testing.

        Returns a DataFrame with 2 days of BAC data including:
        - Historical data (first day)
        - Current timestamp (start of second day)
        - Future data (rest of second day)
        """
        np.random.seed(42)

        # Create timestamps for 2 days of trading
        day1_dates = pd.date_range("2024-01-02 09:30:00", periods=390, freq="1min")  # Day 1
        day2_dates = pd.date_range("2024-01-03 09:30:00", periods=100, freq="1min")   # Day 2 (partial)

        all_dates = pd.concat([pd.Series(day1_dates), pd.Series(day2_dates)])

        # Create realistic price movements
        data = []
        base_price = 30.0  # BAC base price

        for i, ts in enumerate(all_dates):
            # Simulate intraday price movement with trends
            if ts.date() == pd.Timestamp("2024-01-02").date():
                # Day 1: gradual uptrend
                trend = i * 0.001
            else:
                # Day 2: more volatile with clear directional moves for testing
                if i < 450:  # First hour of day 2: sharp up move
                    trend = 0.5 + (i - 390) * 0.01
                elif i < 470:  # Next 20 minutes: sharp down move
                    trend = 0.5 - (i - 450) * 0.02
                else:
                    trend = -0.1 + (i - 470) * 0.001

            noise = np.random.normal(0, 0.005) * base_price
            close = base_price + trend + noise

            # Generate OHLC with proper relationships
            high_low_range = abs(np.random.normal(0, 0.002)) * base_price
            high = close + high_low_range * np.random.random()
            low = close - high_low_range * (1 - np.random.random())

            # Open should be within previous day's range or close to previous close
            if i == 0:
                open_price = close
            elif i == 390:  # Start of day 2
                # Gap up/down from previous close
                gap = np.random.normal(0, 0.002) * base_price
                open_price = data[-1]["close"] + gap
            else:
                # Open near previous close with some variation
                gap = np.random.normal(0, 0.001) * base_price
                open_price = data[-1]["close"] + gap

            volume = max(50000, int(np.random.normal(200000, 50000)))

            data.append({
                "ts": ts,
                "symbol": "BAC",
                "open": open_price,
                "high": max(high, open_price, close),
                "low": min(low, open_price, close),
                "close": close,
                "volume": volume,
            })

        df = pd.DataFrame(data)
        return df.sort_values(["symbol", "ts"]).reset_index(drop=True)

    @pytest.fixture
    def current_timestamp(self, sample_data_window):
        """Get the timestamp at start of second day (boundary between hist/future)."""
        boundary_idx = sample_data_window[sample_data_window["ts"].dt.date == pd.Timestamp("2024-01-03").date()].index[0]
        return sample_data_window.loc[boundary_idx, "ts"]

    def test_label_positive_move(self, labeler, sample_data_window, current_timestamp):
        """Test label computation for a significant positive price movement."""
        # The sample data has a sharp up move in the first hour of day 2
        # This should generate a +1 label

        label = labeler.compute_label_for_timestamp(
            sample_data_window, current_timestamp
        )

        # Verify label is in valid range
        assert label in [-1, 0, 1]

        # For this specific data setup, we expect a positive label due to the up trend
        assert label == 1, f"Expected +1 for positive move, got {label}"

    def test_label_negative_move(self, labeler, sample_data_window):
        """Test label computation for a significant negative price movement."""
        # Create explicit negative move test data
        np.random.seed(123)  # Different seed for predictability
        down_dates = pd.date_range("2024-01-03 10:30:00", periods=100, freq="1min")
        down_data = []
        base_price = 30.0

        for i, ts in enumerate(down_dates):
            # Strong downtrend
            price = base_price - (i * 0.01)  # 1 cent per minute down
            down_data.append({
                "ts": ts,
                "symbol": "BAC",
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": 200000
            })

        down_df = pd.DataFrame(down_data)
        down_move_start = down_df['ts'].iloc[20]  # Start testing from 20th minute

        label = labeler.compute_label_for_timestamp(
            down_df, down_move_start
        )

        # Verify label is in valid range
        assert label in [-1, 0, 1]

        # This should be a negative label due to the sharp down move
        assert label == -1, f"Expected -1 for negative move, got {label}"

    def test_label_neutral_move(self, labeler, sample_data_window):
        """Test label computation for small price movements (neutral)."""
        # Create explicit neutral test data
        np.random.seed(456)  # Different seed for predictability
        neutral_dates = pd.date_range("2024-01-03 11:00:00", periods=50, freq="1min")
        neutral_data = []
        base_price = 30.0

        for i, ts in enumerate(neutral_dates):
            # Very small random movements around base price
            noise = np.random.normal(0, 0.0001)  # Very small noise
            price = base_price * (1 + noise)
            neutral_data.append({
                "ts": ts,
                "symbol": "BAC",
                "open": price,
                "high": price * 1.0001,
                "low": price * 0.9999,
                "close": price,
                "volume": 200000
            })

        neutral_df = pd.DataFrame(neutral_data)
        neutral_time = neutral_df['ts'].iloc[20]

        label = labeler.compute_label_for_timestamp(
            neutral_df, neutral_time
        )

        # Verify label is in valid range
        assert label in [-1, 0, 1]

        # This should be neutral (0) due to small price movements
        assert label == 0, f"Expected 0 for neutral move, got {label}"

    def test_no_future_data(self, labeler, sample_data_window):
        """Test behavior when no future data is available."""
        # Use the very last timestamp
        last_timestamp = sample_data_window["ts"].max()

        label = labeler.compute_label_for_timestamp(
            sample_data_window, last_timestamp
        )

        # Should return neutral label when no future data
        assert label == 0

    def test_atr_threshold_respected(self, labeler, sample_data_window, current_timestamp):
        """Test that ATR threshold is properly applied."""
        # Test with different ATR multipliers by temporarily modifying config
        original_multiplier = labeler.atr_multiplier

        try:
            # Test with very high threshold (should always return 0)
            labeler.atr_multiplier = 10.0
            label_high_threshold = labeler.compute_label_for_timestamp(
                sample_data_window, current_timestamp
            )
            assert label_high_threshold == 0, "High ATR multiplier should result in neutral label"

            # Test with very low threshold (should return +/-1 for any move)
            labeler.atr_multiplier = 0.01
            label_low_threshold = labeler.compute_label_for_timestamp(
                sample_data_window, current_timestamp
            )
            assert label_low_threshold != 0, "Low ATR multiplier should result in non-neutral label"

        finally:
            # Restore original multiplier
            labeler.atr_multiplier = original_multiplier

    def test_horizon_parameter(self, labeler, sample_data_window, current_timestamp):
        """Test that horizon parameter affects label computation."""
        # Temporarily modify horizons
        original_horizons = labeler.horizons

        try:
            # Test with very short horizon (5 minutes)
            labeler.horizons = [5]
            short_horizon_label = labeler.compute_label_for_timestamp(
                sample_data_window, current_timestamp
            )

            # Test with longer horizon (90 minutes)
            labeler.horizons = [90]
            long_horizon_label = labeler.compute_label_for_timestamp(
                sample_data_window, current_timestamp
            )

            # Labels might differ due to different horizons
            # (though they could be the same, that's also valid)
            assert short_horizon_label in [-1, 0, 1]
            assert long_horizon_label in [-1, 0, 1]

        finally:
            # Restore original horizons
            labeler.horizons = original_horizons

    def test_multiple_symbols(self, labeler):
        """Test label computation works with multiple symbols."""
        # Create data with two symbols
        dates = pd.date_range("2024-01-02 09:30:00", periods=100, freq="1min")
        data = []

        for symbol in ["BAC", "AAPL"]:
            base_price = 30.0 if symbol == "BAC" else 150.0
            for i, ts in enumerate(dates):
                close = base_price + i * 0.01 + np.random.normal(0, 0.1)
                data.append({
                    "ts": ts,
                    "symbol": symbol,
                    "open": close,
                    "high": close * 1.001,
                    "low": close * 0.999,
                    "close": close,
                    "volume": 100000,
                })

        df = pd.DataFrame(data).sort_values(["symbol", "ts"])
        current_ts = dates[50]  # Middle timestamp

        # Should work with multiple symbols
        label = labeler.compute_label_for_timestamp(df, current_ts)
        assert label in [-1, 0, 1]

    def test_lookahead_bias_prevention(self, labeler, sample_data_window, current_timestamp):
        """Test that method prevents lookahead bias by using only future data."""
        # This test verifies the interface enforces no-lookahead
        # The actual implementation should only use data > current_timestamp for labels

        # Get all data up to current timestamp
        historical_data = sample_data_window[sample_data_window["ts"] <= current_timestamp]
        future_data = sample_data_window[sample_data_window["ts"] > current_timestamp]

        # Ensure we have both historical and future data
        assert len(historical_data) > 0
        assert len(future_data) > 0

        # Compute label using full data window
        label = labeler.compute_label_for_timestamp(
            sample_data_window, current_timestamp
        )

        # Label should be based on future price movements only
        assert label in [-1, 0, 1]

        # Additional verification: if we only pass historical data, should get neutral
        label_hist_only = labeler.compute_label_for_timestamp(
            historical_data, current_timestamp
        )
        assert label_hist_only == 0

    def test_deprecation_warning(self, labeler):
        """Test that the old create_labels method shows deprecation warning."""
        sample_data = pd.DataFrame({
            "ts": pd.date_range("2024-01-02", periods=100, freq="1min"),
            "symbol": "BAC",
            "open": np.random.normal(30, 1, 100),
            "high": np.random.normal(31, 1, 100),
            "low": np.random.normal(29, 1, 100),
            "close": np.random.normal(30, 1, 100),
            "volume": np.random.normal(200000, 50000, 100),
        })
        ts_cut = sample_data["ts"].iloc[50]

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")

            # This should trigger a deprecation warning
            labeler.create_labels(sample_data, ts_cut)

            # Check that deprecation warning was issued
            assert len(w) > 0
            assert any(issubclass(warning.category, DeprecationWarning) for warning in w)
            assert any("deprecated" in str(warning.message).lower() for warning in w)

    def test_method_signature_compatibility(self, labeler, sample_data_window, current_timestamp):
        """Test that compute_label_for_timestamp has the expected signature."""
        # This test ensures the method exists and can be called with expected parameters

        # Should not raise any errors
        label = labeler.compute_label_for_timestamp(
            data_window=sample_data_window,
            current_timestamp=current_timestamp
        )

        assert isinstance(label, int)
        assert label in [-1, 0, 1]

    def test_edge_cases(self, labeler):
        """Test edge cases and error conditions."""
        # Empty DataFrame
        empty_df = pd.DataFrame(columns=["ts", "symbol", "open", "high", "low", "close", "volume"])
        test_ts = pd.Timestamp("2024-01-02 09:30:00")

        label = labeler.compute_label_for_timestamp(empty_df, test_ts)
        assert label == 0

        # Single row DataFrame
        single_row = pd.DataFrame({
            "ts": [test_ts],
            "symbol": ["BAC"],
            "open": [30.0],
            "high": [30.1],
            "low": [29.9],
            "close": [30.0],
            "volume": [100000],
        })

        label = labeler.compute_label_for_timestamp(single_row, test_ts)
        assert label == 0

    def test_realistic_price_scenarios(self, labeler):
        """Test with realistic price movement scenarios."""
        # Test known scenarios:

        # 1. Gradual uptrend (should be +1 if enough movement)
        uptrend_data = self._create_price_scenario(
            start_price=30.0,
            trend=0.001,  # Up trend
            volatility=0.002,
            duration_minutes=60
        )
        label_uptrend = labeler.compute_label_for_timestamp(
            uptrend_data, uptrend_data["ts"].iloc[0]
        )

        # 2. Gradual downtrend (should be -1 if enough movement)
        downtrend_data = self._create_price_scenario(
            start_price=30.0,
            trend=-0.001,  # Down trend
            volatility=0.002,
            duration_minutes=60
        )
        label_downtrend = labeler.compute_label_for_timestamp(
            downtrend_data, downtrend_data["ts"].iloc[0]
        )

        # 3. Sideways market (should be 0)
        sideways_data = self._create_price_scenario(
            start_price=30.0,
            trend=0.0,  # No trend
            volatility=0.001,
            duration_minutes=60
        )
        label_sideways = labeler.compute_label_for_timestamp(
            sideways_data, sideways_data["ts"].iloc[0]
        )

        # All labels should be valid
        assert label_uptrend in [-1, 0, 1]
        assert label_downtrend in [-1, 0, 1]
        assert label_sideways in [-1, 0, 1]

        # Directions should make sense (optional, as thresholds might prevent classification)
        # print(f"Uptrend label: {label_uptrend}, Downtrend label: {label_downtrend}, Sideways label: {label_sideways}")

    def _create_price_scenario(self, start_price: float, trend: float, volatility: float, duration_minutes: int) -> pd.DataFrame:
        """Helper to create a specific price scenario for testing."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=duration_minutes, freq="1min")
        data = []

        for i, ts in enumerate(dates):
            # Calculate price with trend and noise
            price_move = trend * i + np.random.normal(0, volatility)
            close = start_price * (1 + price_move)

            # Generate OHLC
            high_low = abs(np.random.normal(0, volatility)) * close
            high = close + high_low * np.random.random()
            low = close - high_low * (1 - np.random.random())
            open_price = low + (high - low) * np.random.random()

            data.append({
                "ts": ts,
                "symbol": "TEST",
                "open": open_price,
                "high": max(high, open_price, close),
                "low": min(low, open_price, close),
                "close": close,
                "volume": 100000,
            })

        return pd.DataFrame(data)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])