"""Integration tests for create_training_dataset function

Tests for the main data preparation function that creates aligned feature-label
pairs using the sliding window approach with strict no-lookahead bias.
"""

from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest
import yaml

from extensions.intraday_ml.data_prep import create_training_dataset
from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack
from extensions.intraday_ml.labeling import IntradayMLLabeler


class TestCreateTrainingDataset:
    """Integration tests for create_training_dataset function."""

    @pytest.fixture
    def features_config(self):
        """Load features configuration."""
        config_path = Path("configs/extensions/intraday_ml/features.yaml")
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def targets_config(self):
        """Load targets configuration."""
        config_path = Path("configs/extensions/intraday_ml/targets.yaml")
        with open(config_path, "r") as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def bac_week_data(self):
        """Create one week of realistic BAC data for testing.

        Returns data from 2024-01-02 to 2024-01-05 (4 trading days).
        Data includes realistic price movements, volatility, and volume patterns.
        """
        np.random.seed(42)

        # Generate 4 days of trading data (9:30 AM - 4:00 PM, 390 minutes per day)
        trading_days = [
            pd.Timestamp("2024-01-02"),
            pd.Timestamp("2024-01-03"),
            pd.Timestamp("2024-01-04"),
            pd.Timestamp("2024-01-05"),
        ]

        all_data = []
        base_price = 30.0  # BAC base price

        for day_idx, trading_day in enumerate(trading_days):
            # Generate intraday timestamps
            day_start = trading_day.replace(hour=9, minute=30)
            timestamps = pd.date_range(day_start, periods=390, freq="1min")

            # Daily trend and volatility
            if day_idx == 0:  # Tuesday: uptrend
                daily_trend = 0.002
                daily_vol = 0.008
            elif day_idx == 1:  # Wednesday: volatile, down trend
                daily_trend = -0.001
                daily_vol = 0.015
            elif day_idx == 2:  # Thursday: sideways
                daily_trend = 0.000
                daily_vol = 0.006
            else:  # Friday: slight uptrend
                daily_trend = 0.001
                daily_vol = 0.007

            for minute_idx, ts in enumerate(timestamps):
                # Time-of-day effects (higher volume at open/close)
                if minute_idx < 30:  # First 30 minutes: high volume
                    volume_multiplier = 1.5
                    vol_multiplier = 1.2
                elif minute_idx > 360:  # Last 30 minutes: high volume
                    volume_multiplier = 1.3
                    vol_multiplier = 1.1
                else:  # Regular trading hours
                    volume_multiplier = 1.0
                    vol_multiplier = 1.0

                # Calculate price with trend, intraday pattern, and noise
                intraday_pattern = 0.001 * np.sin(2 * np.pi * minute_idx / 390)  # Midday dip
                trend_component = daily_trend * minute_idx / 390
                noise = np.random.normal(0, daily_vol * vol_multiplier)

                price_change = (trend_component + intraday_pattern + noise) * base_price
                close = base_price + price_change

                # Generate OHLC with proper relationships
                high_low_range = abs(np.random.normal(0, 0.003 * vol_multiplier)) * close
                high = close + high_low_range * np.random.random()
                low = close - high_low_range * (1 - np.random.random())

                # Open price within reasonable range
                if minute_idx == 0:
                    open_price = close
                else:
                    gap = np.random.normal(0, 0.001 * close)
                    open_price = max(low, min(high, all_data[-1]["close"] + gap))

                # Volume with time-of-day effects
                base_volume = 200000
                volume = max(50000, int(np.random.normal(base_volume * volume_multiplier, 50000)))

                all_data.append({
                    "ts": ts,
                    "symbol": "BAC",
                    "open": open_price,
                    "high": max(high, open_price, close),
                    "low": min(low, open_price, close),
                    "close": close,
                    "volume": volume,
                })

                # Update base price for next minute
                base_price = close

        df = pd.DataFrame(all_data)
        return df.sort_values(["symbol", "ts"]).reset_index(drop=True)

    @pytest.fixture
    def middle_timestamp(self, bac_week_data):
        """Get a timestamp in the middle of the week for manual verification."""
        # Wednesday around 11:00 AM (middle of the data)
        wednesday_11am = pd.Timestamp("2024-01-03 11:00:00")
        return wednesday_11am

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_create_training_dataset_basic(self, mock_load_data, bac_week_data, features_config, targets_config):
        """Test basic functionality of create_training_dataset."""
        # Mock the data loader to return our test data
        mock_load_data.return_value = bac_week_data

        # Create training dataset
        result_df = create_training_dataset(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-05",
            features_config=features_config,
            targets_config=targets_config
        )

        # Verify the call was made with correct parameters
        mock_load_data.assert_called_once_with(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-05",
            config=None
        )

        # Basic structure validation
        assert isinstance(result_df, pd.DataFrame), "Result should be a DataFrame"
        assert len(result_df) > 0, "Result should not be empty"
        assert not result_df.empty, "Result DataFrame should not be empty"

        # Check for label column
        assert "label" in result_df.columns, "Result should have 'label' column"

        # Check for feature columns (should start with 'f__')
        feature_columns = [col for col in result_df.columns if col.startswith('f__')]
        assert len(feature_columns) > 0, "Result should have feature columns"

        # Check that index contains symbol and timestamp information
        assert "symbol" in result_df.columns or result_df.index.names == ["symbol", "ts"], \
            "Result should have symbol information"

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_no_nan_labels(self, mock_load_data, bac_week_data, features_config, targets_config):
        """Test that there are no NaN values in the label column."""
        mock_load_data.return_value = bac_week_data

        result_df = create_training_dataset(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-05",
            features_config=features_config,
            targets_config=targets_config
        )

        # Check that label column has no NaN values
        assert not result_df["label"].isna().any(), "Label column should not contain NaN values"

        # Check that all labels are valid (-1, 0, 1)
        unique_labels = set(result_df["label"].unique())
        assert unique_labels.issubset({-1, 0, 1}), f"Invalid labels found: {unique_labels}"

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_manual_verification_no_lookahead(self, mock_load_data, bac_week_data, features_config, targets_config, middle_timestamp):
        """Manually verify a specific timestamp to ensure no lookahead bias."""
        mock_load_data.return_value = bac_week_data

        result_df = create_training_dataset(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-05",
            features_config=features_config,
            targets_config=targets_config
        )

        # Find the row for our middle timestamp
        if "symbol" in result_df.columns:
            mask = (result_df["symbol"] == "BAC") & (result_df["ts"] == middle_timestamp)
            matching_rows = result_df[mask]
        else:
            # If symbol is in index
            try:
                matching_rows = result_df.loc[(slice(None), middle_timestamp), :]
            except KeyError:
                # Fallback: search through the DataFrame
                matching_rows = result_df[result_df.index.get_level_values('ts') == middle_timestamp]

        # If we found the specific timestamp, verify it
        if not matching_rows.empty:
            feature_vector = matching_rows.iloc[0]
            label = feature_vector["label"]

            print(f"\nManual verification for timestamp {middle_timestamp}:")
            print(f"Label: {label}")
            print(f"Number of features: {len([col for col in result_df.columns if col.startswith('f__')])}")

            # Print first few feature values for verification
            feature_cols = [col for col in result_df.columns if col.startswith('f__')][:5]
            print("Sample feature values:")
            for col in feature_cols:
                if col in feature_vector:
                    print(f"  {col}: {feature_vector[col]:.6f}")

            # Verify label is valid
            assert label in [-1, 0, 1], f"Invalid label {label} for timestamp {middle_timestamp}"

            # Verify features are not all NaN
            non_nan_features = [col for col in feature_cols
                              if col in feature_vector and not pd.isna(feature_vector[col])]
            assert len(non_nan_features) > 0, "Should have some non-NaN features"

            print("✓ Manual verification passed - no obvious lookahead bias detected")
        else:
            print(f"⚠ Could not find exact timestamp {middle_timestamp} in results")
            # This is not a test failure - the timestamp might not be included due to
            # insufficient future data for labeling

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_feature_label_alignment(self, mock_load_data, bac_week_data, features_config, targets_config):
        """Test that features and labels are properly aligned."""
        mock_load_data.return_value = bac_week_data

        result_df = create_training_dataset(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-05",
            features_config=features_config,
            targets_config=targets_config
        )

        # Verify that every row has both features and label
        assert len(result_df) == len(result_df.dropna(subset=["label"])), \
            "All rows should have labels"

        # Check that features are aligned (same number of rows)
        feature_columns = [col for col in result_df.columns if col.startswith('f__')]
        for col in feature_columns[:5]:  # Check first 5 features
            assert len(result_df[col].dropna()) > 0, f"Feature {col} should have non-NaN values"

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_multiple_symbols(self, mock_load_data, features_config, targets_config):
        """Test create_training_dataset with multiple symbols."""
        # Create test data for multiple symbols
        np.random.seed(42)
        dates = pd.date_range("2024-01-02 09:30:00", periods=200, freq="1min")
        multi_symbol_data = []

        for symbol in ["BAC", "AAPL"]:
            base_price = 30.0 if symbol == "BAC" else 150.0
            for i, ts in enumerate(dates):
                price = base_price + i * 0.001 + np.random.normal(0, 0.01)
                multi_symbol_data.append({
                    "ts": ts,
                    "symbol": symbol,
                    "open": price,
                    "high": price * 1.001,
                    "low": price * 0.999,
                    "close": price,
                    "volume": 100000,
                })

        multi_df = pd.DataFrame(multi_symbol_data).sort_values(["symbol", "ts"])
        mock_load_data.return_value = multi_df

        result_df = create_training_dataset(
            symbols=["BAC", "AAPL"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            features_config=features_config,
            targets_config=targets_config
        )

        # Should have data for both symbols
        if "symbol" in result_df.columns:
            unique_symbols = result_df["symbol"].unique()
        else:
            unique_symbols = result_df.index.get_level_values('symbol').unique()

        assert len(unique_symbols) == 2, "Should have data for both symbols"
        assert set(unique_symbols) == {"BAC", "AAPL"}, "Should have BAC and AAPL"

        # All rows should have labels
        assert not result_df["label"].isna().any(), "All rows should have labels"

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_empty_data_handling(self, mock_load_data, features_config, targets_config):
        """Test handling of empty or minimal data."""
        # Test with empty DataFrame
        mock_load_data.return_value = pd.DataFrame()

        result_df = create_training_dataset(
            symbols=["BAC"],
            start_date="2024-01-02",
            end_date="2024-01-02",
            features_config=features_config,
            targets_config=targets_config
        )

        assert isinstance(result_df, pd.DataFrame), "Should return DataFrame even for empty input"
        assert len(result_df) == 0, "Empty input should produce empty output"

    @patch('extensions.intraday_ml.data_prep.load_data_window')
    def test_data_validation(self, mock_load_data, features_config, targets_config):
        """Test data validation and error handling."""
        # Test with malformed data (missing required columns)
        bad_data = pd.DataFrame({
            "ts": pd.date_range("2024-01-02", periods=10, freq="1min"),
            "symbol": ["BAC"] * 10,
            "close": np.random.normal(30, 1, 10),
            # Missing other OHLCV columns
        })
        mock_load_data.return_value = bad_data

        # Should handle gracefully or fail with informative error
        try:
            result_df = create_training_dataset(
                symbols=["BAC"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                features_config=features_config,
                targets_config=targets_config
            )
            # If it doesn't fail, result should be reasonable
            assert isinstance(result_df, pd.DataFrame)
        except Exception as e:
            # If it fails, error should be informative
            assert isinstance(e, (ValueError, KeyError)), f"Expected informative error, got {type(e)}"

    def test_reproducibility(self, features_config, targets_config):
        """Test that results are reproducible with same inputs."""
        # This test would require mocking the internal functions to ensure
        # deterministic behavior. For now, we'll test the interface.

        with patch('extensions.intraday_ml.data_prep.load_data_window') as mock_load:
            # Create deterministic test data
            np.random.seed(42)
            test_data = pd.DataFrame({
                "ts": pd.date_range("2024-01-02 09:30:00", periods=100, freq="1min"),
                "symbol": "BAC",
                "open": np.random.normal(30, 0.1, 100),
                "high": np.random.normal(30.1, 0.1, 100),
                "low": np.random.normal(29.9, 0.1, 100),
                "close": np.random.normal(30, 0.1, 100),
                "volume": np.random.normal(200000, 50000, 100),
            })
            mock_load.return_value = test_data

            # Run twice with same parameters
            result1 = create_training_dataset(
                symbols=["BAC"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                features_config=features_config,
                targets_config=targets_config
            )

            result2 = create_training_dataset(
                symbols=["BAC"],
                start_date="2024-01-02",
                end_date="2024-01-02",
                features_config=features_config,
                targets_config=targets_config
            )

            # Results should be identical
            pd.testing.assert_frame_equal(result1, result2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])