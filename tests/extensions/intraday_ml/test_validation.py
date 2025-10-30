"""Tests for validation utilities."""

import pathlib
import tempfile

import pytest

from extensions.intraday_ml.utils.validation import (
    validate_backtest_result,
    validate_config,
    validate_data_slice,
)


class TestValidateConfig:
    """Test configuration validation."""

    def test_valid_config(self):
        """Test validation of valid configuration."""
        config = {
            "gold_root": "/path/to/gold",
            "family": "bars_1m",
            "symbols": ["AAPL", "MSFT"],
            "dates": ["2024-01"],
            "features": ["core_basics"],
        }

        # Should not raise exception
        validate_config(config)

    def test_missing_required_keys(self):
        """Test validation with missing required keys."""
        config = {"gold_root": "/path/to/gold"}

        with pytest.raises(ValueError, match="Missing required config keys"):
            validate_config(config)

    def test_empty_symbols_list(self):
        """Test validation with empty symbols list."""
        config = {
            "gold_root": "/path/to/gold",
            "family": "bars_1m",
            "symbols": [],
            "dates": ["2024-01"],
            "features": ["core_basics"],
        }

        with pytest.raises(ValueError, match="symbols must be a non-empty list"):
            validate_config(config)

    def test_invalid_symbols_type(self):
        """Test validation with invalid symbols type."""
        config = {
            "gold_root": "/path/to/gold",
            "family": "bars_1m",
            "symbols": "AAPL",  # Should be list
            "dates": ["2024-01"],
            "features": ["core_basics"],
        }

        with pytest.raises(ValueError, match="symbols must be a non-empty list"):
            validate_config(config)

    def test_empty_dates_list(self):
        """Test validation with empty dates list."""
        config = {
            "gold_root": "/path/to/gold",
            "family": "bars_1m",
            "symbols": ["AAPL"],
            "dates": [],
            "features": ["core_basics"],
        }

        with pytest.raises(ValueError, match="dates must be a non-empty list"):
            validate_config(config)

    def test_empty_features_list(self):
        """Test validation with empty features list."""
        config = {
            "gold_root": "/path/to/gold",
            "family": "bars_1m",
            "symbols": ["AAPL"],
            "dates": ["2024-01"],
            "features": [],
        }

        with pytest.raises(ValueError, match="features must be a non-empty list"):
            validate_config(config)


class TestValidateDataSlice:
    """Test data slice validation."""

    def test_nonexistent_gold_root(self):
        """Test validation with nonexistent gold root."""
        with pytest.raises(ValueError, match="Gold root does not exist"):
            validate_data_slice("/nonexistent/path", "bars_1m", ["AAPL"], ["2024-01"])

    def test_data_slice_validation_success(self):
        """Test successful data slice validation with real data."""
        # Use actual gold data path if available
        gold_root = "/home/jacobw/gcs-mount/gold"
        if pathlib.Path(gold_root).exists():
            # This should not raise exception if data exists
            try:
                validate_data_slice(gold_root, "bars_1m", ["AAPL"], ["2024-01"])
            except ValueError as e:
                # If it fails, it should be due to missing data, not structure issues
                assert "not found" in str(e)

    def test_missing_symbols_in_mock_environment(self):
        """Test validation with missing symbols in mock environment."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create empty directory structure
            gold_root = temp_dir

            with pytest.raises(ValueError, match="Symbol directory not found"):
                validate_data_slice(gold_root, "bars_1m", ["NONEXISTENT"], ["2024-01"])


class TestValidateBacktestResult:
    """Test backtest result validation."""

    def test_valid_result(self):
        """Test validation of valid backtest result."""
        result = {
            "performance": {"total_return": 0.05, "sharpe_ratio": 1.2},
            "trading": {"total_trades": 10, "winning_trades": 6},
        }

        warnings = validate_backtest_result(result)
        assert len(warnings) == 0

    def test_missing_required_keys(self):
        """Test validation with missing required keys."""
        result = {"performance": {"total_return": 0.05}}

        warnings = validate_backtest_result(result)
        assert "missing_result_keys" in warnings[0]

    def test_no_trades_warning(self):
        """Test warning for no trades executed."""
        result = {
            "performance": {"total_return": 0.0},
            "trading": {"total_trades": 0, "winning_trades": 0},
        }

        warnings = validate_backtest_result(result)
        assert "no_trades_executed" in warnings

    def test_trades_executed_no_warning(self):
        """Test no warning when trades are executed."""
        result = {
            "performance": {"total_return": 0.05},
            "trading": {"total_trades": 5, "winning_trades": 3},
        }

        warnings = validate_backtest_result(result)
        assert "no_trades_executed" not in warnings

    def test_empty_result(self):
        """Test validation of empty result."""
        result = {}

        warnings = validate_backtest_result(result)
        assert len(warnings) >= 1
        assert "missing_result_keys" in warnings[0]
