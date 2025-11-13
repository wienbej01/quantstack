"""Unit tests for gold loader functionality."""

import os
import sys
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest

# Add qx-data to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-data", "src"))

from qx_data.gold_loader import (
    OPTIONAL,
    REQUIRED,
    _get_parquet_paths,
    _normalize_in_memory,
    _read_parquet_with_validation,
    get_bars_hash,
    list_available_dates,
    list_available_symbols,
    load_bars,
)


class TestGoldLoaderBasics:
    """Test basic gold loader functionality."""

    def test_load_bars_empty_inputs(self):
        """Test load_bars with empty inputs."""
        with pytest.raises(ValueError, match="Symbols list cannot be empty"):
            load_bars("/fake/path", "bars_1m", [], ["2020-01"])

        with pytest.raises(ValueError, match="Dates list cannot be empty"):
            load_bars("/fake/path", "bars_1m", ["AAPL"], [])

    @patch("qx_data.gold_loader._get_parquet_paths")
    def test_load_bars_no_files_found(self, mock_get_paths):
        """Test load_bars when no files are found."""
        mock_get_paths.return_value = []

        with pytest.raises(RuntimeError, match="No parquet files could be read"):
            load_bars("/fake/path", "bars_1m", ["AAPL"], ["2020-01"])

    @patch("qx_data.gold_loader._get_parquet_paths")
    @patch("qx_data.gold_loader._read_parquet_with_validation")
    @patch("qx_data.gold_loader._normalize_in_memory")
    def test_load_bars_success(self, mock_normalize, mock_read, mock_get_paths):
        """Test successful load_bars execution."""
        # Setup mocks
        mock_get_paths.return_value = ["/fake/path/file.parquet"]

        sample_df = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "ts": [1640995200000000000],
                "open": [150.0],
                "high": [151.0],
                "low": [149.0],
                "close": [150.5],
                "volume": [1000],
            }
        )
        mock_read.return_value = sample_df
        mock_normalize.return_value = sample_df

        # Test
        result = load_bars("/fake/path", "bars_1m", ["AAPL"], ["2020-01"])

        assert isinstance(result, pd.DataFrame)
        assert len(result) == 1
        mock_get_paths.assert_called_once()
        mock_read.assert_called_once()
        mock_normalize.assert_called_once()

    @patch("qx_data.gold_loader._get_parquet_paths")
    @patch("qx_data.gold_loader._read_parquet_with_validation")
    @patch("qx_data.gold_loader._normalize_in_memory")
    @patch("qx_data.gold_loader.validate_bars_dataframe")
    def test_load_bars_with_validation(
        self, mock_validate, mock_normalize, mock_read, mock_get_paths
    ):
        """Test load_bars with validation enabled."""
        # Setup mocks
        mock_get_paths.return_value = ["/fake/path/file.parquet"]

        sample_df = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "ts": [1640995200000000000],
                "open": [150.0],
                "high": [151.0],
                "low": [149.0],
                "close": [150.5],
                "volume": [1000],
            }
        )
        mock_read.return_value = sample_df
        mock_normalize.return_value = sample_df

        # Test with validation (default)
        load_bars("/fake/path", "bars_1m", ["AAPL"], ["2020-01"], validate=True)
        mock_validate.assert_called_once()

        # Test without validation
        mock_validate.reset_mock()
        load_bars("/fake/path", "bars_1m", ["AAPL"], ["2020-01"], validate=False)
        mock_validate.assert_not_called()


class TestParquetPathResolution:
    """Test parquet path resolution logic."""

    def test_get_parquet_paths_bars_1m(self):
        """Test path resolution for bars_1m family."""
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = ["/fake/stocks/1m/AAPL/2020/2020-01.parquet"]

            paths = _get_parquet_paths("/fake", "bars_1m", "AAPL", "2020-01")

            expected_pattern = "/fake/stocks/1m/AAPL/2020/2020-01.parquet"
            called_patterns = [call.args[0] for call in mock_glob.call_args_list]
            assert expected_pattern in called_patterns
            assert paths == ["/fake/stocks/1m/AAPL/2020/2020-01.parquet"]

    def test_get_parquet_paths_bars_1m_with_day(self):
        """Test path resolution for bars_1m family with full date."""
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = ["/fake/stocks/1m/AAPL/2020/2020-01.parquet"]

            _get_parquet_paths("/fake", "bars_1m", "AAPL", "2020-01-15")

            expected_pattern = "/fake/stocks/1m/AAPL/2020/2020-01.parquet"
            called_patterns = [call.args[0] for call in mock_glob.call_args_list]
            assert expected_pattern in called_patterns

    def test_get_parquet_paths_other_families(self):
        """Test path resolution for non-bars_1m families."""
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = ["/fake/features/symbol=AAPL/date=2020-01-15/file.parquet"]

            _get_parquet_paths("/fake", "features", "AAPL", "2020-01-15")

            expected_pattern = "/fake/features/symbol=AAPL/date=2020-01-15/*.parquet"
            called_patterns = [call.args[0] for call in mock_glob.call_args_list]
            assert expected_pattern in called_patterns

    def test_get_parquet_paths_smoke_test(self):
        """Test path resolution for smoke test dates."""
        with patch("glob.glob") as mock_glob:
            mock_glob.return_value = ["/fake/test/symbol=AAPL/date=SMOKE/file.parquet"]

            _get_parquet_paths("/fake", "test", "AAPL", "SMOKE")

            expected_pattern = "/fake/test/symbol=AAPL/date=SMOKE/*.parquet"
            called_patterns = [call.args[0] for call in mock_glob.call_args_list]
            assert expected_pattern in called_patterns

    def test_get_parquet_paths_symbol_case_insensitive(self):
        """Symbols are resolved in a case-insensitive manner."""

        def side_effect(pattern):
            if "AAPL" in pattern:
                return ["/fake/stocks/1m/AAPL/2020/2020-01.parquet"]
            return []

        with patch("glob.glob", side_effect=side_effect) as mock_glob:
            paths = _get_parquet_paths("/fake", "bars_1m", "aapl", "2020-01")
            assert paths == ["/fake/stocks/1m/AAPL/2020/2020-01.parquet"]
            assert mock_glob.call_count >= 2


class TestDataNormalization:
    """Test data normalization functionality."""

    def test_normalize_basic_dataframe(self):
        """Test normalization of basic DataFrame."""
        df = pd.DataFrame(
            {
                "T": ["AAPL", "GOOGL"],
                "t": [1640995200000000000, 1640995260000000000],
                "o": [150.0, 2800.0],
                "h": [151.0, 2810.0],
                "l": [149.0, 2790.0],
                "c": [150.5, 2805.0],
                "v": [1000, 500],
            }
        )

        result = _normalize_in_memory(df)

        # Check column renaming
        assert "symbol" in result.columns
        assert "ts" in result.columns
        assert "open" in result.columns
        assert "high" in result.columns
        assert "low" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns

        # Check data types
        assert result["symbol"].dtype == "object"
        assert result["ts"].dtype == "int64"
        assert pd.api.types.is_numeric_dtype(result["open"])
        assert result["volume"].dtype == "int64"

        # Check values (lowercase conversion happens)
        assert result["symbol"].iloc[0] == "aapl"  # T -> t -> lowercase
        assert result["ts"].iloc[0] == 1640995200000000000
        assert result["open"].iloc[0] == 150.0

    def test_normalize_missing_required_columns(self):
        """Test normalization with missing required columns."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "ts": [1640995200000000000],
                "open": [150.0],
                # Missing high, low, close, volume
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            _normalize_in_memory(df)

    def test_normalize_datetime_timestamps(self):
        """Test normalization with datetime timestamps."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "ts": [pd.Timestamp("2023-01-01 10:00:00", tz="UTC")],
                "open": [150.0],
                "high": [151.0],
                "low": [149.0],
                "close": [150.5],
                "volume": [1000],
            }
        )

        result = _normalize_in_memory(df)

        assert result["ts"].dtype == "int64"
        # Calculate expected timestamp: 2023-01-01 10:00:00 UTC in nanoseconds
        expected_timestamp = pd.Timestamp("2023-01-01 10:00:00", tz="UTC").value
        assert result["ts"].iloc[0] == expected_timestamp

    def test_normalize_with_optional_columns(self):
        """Test normalization with optional columns present."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL"],
                "ts": [1640995200000000000],
                "open": [150.0],
                "high": [151.0],
                "low": [149.0],
                "close": [150.5],
                "volume": [1000],
                "vwap": [150.2],
                "trades": [50],
                "session": ["regular"],
            }
        )

        result = _normalize_in_memory(df)

        assert "vwap" in result.columns
        assert "trades" in result.columns
        assert "session" in result.columns
        assert pd.api.types.is_numeric_dtype(result["vwap"])
        assert result["trades"].dtype == "int64"
        assert result["session"].dtype == "object"

    def test_normalize_invalid_data_removal(self):
        """Test removal of invalid data during normalization."""
        df = pd.DataFrame(
            {
                "symbol": ["AAPL", "GOOGL", "MSFT", "INVALID"],
                "ts": [
                    1640995200000000000,
                    1640995260000000000,
                    -1,
                    1640995320000000000,
                ],  # Negative timestamp
                "open": [150.0, 2800.0, 300.0, -100.0],  # Negative price
                "high": [151.0, 2810.0, 301.0, -90.0],
                "low": [149.0, 2790.0, 299.0, -110.0],
                "close": [150.5, 2805.0, 300.5, -95.0],
                "volume": [1000, 500, 750, 100],
            }
        )

        # Should not raise exception but print warnings
        result = _normalize_in_memory(df)

        # Should have removed rows with invalid data
        assert len(result) >= 1  # At least one valid row should remain


class TestParquetReading:
    """Test parquet reading functionality."""

    def test_read_parquet_with_symbol_injection(self):
        """Test parquet reading with symbol injection."""
        # Create a temporary parquet file
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
            df = pd.DataFrame(
                {
                    "ts": [1640995200000000000],
                    "open": [150.0],
                    "high": [151.0],
                    "low": [149.0],
                    "close": [150.5],
                    "volume": [1000],
                    # No symbol column
                }
            )
            df.to_parquet(tmp_file.name)

            try:
                result = _read_parquet_with_validation(tmp_file.name, "AAPL")

                assert "symbol" in result.columns
                assert result["symbol"].iloc[0] == "AAPL"
                assert len(result) == 1
            finally:
                os.unlink(tmp_file.name)

    def test_read_parquet_empty_file(self):
        """Test reading empty parquet file."""
        # Create an empty DataFrame and save it
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
            df = pd.DataFrame()
            df.to_parquet(tmp_file.name)

            try:
                with pytest.raises(Exception, match="is empty"):
                    _read_parquet_with_validation(tmp_file.name, "AAPL")
            finally:
                os.unlink(tmp_file.name)

    def test_read_parquet_with_column_selection(self):
        """Test reading parquet with column selection."""
        # Create a temporary parquet file
        with tempfile.NamedTemporaryFile(suffix=".parquet", delete=False) as tmp_file:
            df = pd.DataFrame(
                {
                    "ts": [1640995200000000000],
                    "symbol": "AAPL",
                    "open": [150.0],
                    "high": [151.0],
                    "low": [149.0],
                    "close": [150.5],
                    "volume": [1000],
                    "extra_col": ["ignore_me"],
                }
            )
            df.to_parquet(tmp_file.name)

            try:
                columns = ["ts", "open", "close", "volume"]
                result = _read_parquet_with_validation(tmp_file.name, "AAPL", columns)

                # Symbol is always injected if not in columns
                expected_cols = ["ts", "open", "close", "volume", "symbol"]
                assert list(result.columns) == expected_cols
                assert "extra_col" not in result.columns
                assert len(result) == 1
            finally:
                os.unlink(tmp_file.name)


class TestUtilityFunctions:
    """Test utility functions."""

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_available_symbols_bars_1m(self, mock_listdir, mock_exists):
        """Test listing available symbols for bars_1m."""
        mock_exists.return_value = True
        mock_listdir.side_effect = [
            ["A"],  # Letter directories
            ["AAPL", "AMZN"],  # Symbols in A directory
            ["AAPL", "AMZN"],  # isdir check results
            ["AAPL", "AMZN"],  # isdir check results
        ]

        symbols = list_available_symbols("/fake", "bars_1m")

        assert "AAPL" in symbols
        assert "AMZN" in symbols
        assert len(symbols) == 2

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_available_symbols_other_families(self, mock_listdir, mock_exists):
        """Test listing available symbols for other families."""
        mock_exists.return_value = True
        mock_listdir.return_value = ["symbol=AAPL", "symbol=GOOGL"]

        symbols = list_available_symbols("/fake", "features")

        assert "AAPL" in symbols
        assert "GOOGL" in symbols
        assert len(symbols) == 2

    @patch("os.path.exists")
    @patch("os.listdir")
    def test_list_available_dates_bars_1m(self, mock_listdir, mock_exists):
        """Test listing available dates for bars_1m."""
        mock_exists.return_value = True
        mock_listdir.side_effect = [
            ["2020"],  # Year directories
            ["2020-01.parquet", "2020-02.parquet"],  # Parquet files
        ]

        dates = list_available_dates("/fake", "bars_1m", "AAPL")

        assert "2020-01" in dates
        assert "2020-02" in dates
        assert len(dates) == 2

    def test_get_bars_hash(self):
        """Test getting bars hash."""
        with patch("qx_data.gold_loader.load_bars") as mock_load:
            sample_df = pd.DataFrame(
                {
                    "symbol": ["AAPL"],
                    "ts": [1640995200000000000],
                    "open": [150.0],
                    "high": [151.0],
                    "low": [149.0],
                    "close": [150.5],
                    "volume": [1000],
                }
            )
            mock_load.return_value = sample_df

            hash_value = get_bars_hash("/fake", "bars_1m", ["AAPL"], ["2020-01"])

            assert isinstance(hash_value, str)
            assert len(hash_value) == 64  # blake2b hash length
            mock_load.assert_called_once_with(
                "/fake", "bars_1m", ["AAPL"], ["2020-01"], validate=False
            )


class TestConstants:
    """Test constant definitions."""

    def test_required_columns(self):
        """Test required columns definition."""
        expected = {"ts", "symbol", "open", "high", "low", "close", "volume"}
        assert set(REQUIRED) == expected

    def test_optional_columns(self):
        """Test optional columns definition."""
        expected = {"trades", "vwap", "session", "date_et"}
        assert set(OPTIONAL) == expected


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
