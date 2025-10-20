"""Tests for Bronze QA scanner."""

from unittest.mock import patch

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from qx_scan.bronze_qa_scan import (
    analyze_parquet_file,
    generate_normalization_plan,
    scan_bronze_qa,
)


class TestBronzeQAScan:
    """Test Bronze QA scanning functionality."""

    @pytest.fixture
    def sample_short_form(self, tmp_path):
        """Create sample short-form Parquet file."""
        df = pd.DataFrame(
            {
                "t": [1640995200000, 1640995260000],  # epoch ms
                "o": [100.0, 101.0],
                "h": [102.0, 103.0],
                "l": [99.0, 100.0],
                "c": [101.0, 102.0],
                "v": [1000, 1100],
                "vw": [100.5, 101.5],
                "n": [10, 11],
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "short_form.parquet"
        pq.write_table(table, file_path)
        return file_path

    @pytest.fixture
    def sample_long_form(self, tmp_path):
        """Create sample long-form Parquet file."""
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    ["2022-01-01 00:00:00", "2022-01-01 00:01:00"], utc=True
                ),
                "symbol": ["AAPL", "AAPL"],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 1100],
                "vwap": [100.5, 101.5],
                "trades": [10, 11],
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "long_form.parquet"
        pq.write_table(table, file_path)
        return file_path

    @pytest.fixture
    def sample_with_issues(self, tmp_path):
        """Create sample with issues: float volume, high < low."""
        df = pd.DataFrame(
            {
                "t": [1640995200000],
                "o": [100.0],
                "h": [99.0],  # high < low
                "l": [100.0],
                "c": [101.0],
                "v": [1000.5],  # float volume
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "issues.parquet"
        pq.write_table(table, file_path)
        return file_path

    def test_analyze_short_form(self, sample_short_form):
        """Test analysis of short-form file."""
        result = analyze_parquet_file(sample_short_form)

        assert result["schema_variant"] == "short"
        assert not result["ts_manual"]
        assert len(result["issues"]) == 0  # Should be clean
        assert result["metrics"]["row_count"] == 2
        assert "t" in result["metrics"]["columns"]

    def test_analyze_long_form(self, sample_long_form):
        """Test analysis of long-form file."""
        result = analyze_parquet_file(sample_long_form)

        assert result["schema_variant"] == "long"
        assert len(result["issues"]) == 0
        assert "ts" in result["metrics"]["columns"]

    def test_analyze_with_issues(self, sample_with_issues):
        """Test detection of issues."""
        result = analyze_parquet_file(sample_with_issues)

        assert "Volume is float (should be int)" in result["issues"]
        assert "High < Low detected" in result["issues"]

    def test_generate_normalization_plan(self):
        """Test normalization plan generation."""
        scan_results = {
            "bars_1m": {
                "files": [
                    {"schema_variant": "short", "issues": []},
                    {"schema_variant": "short", "issues": []},
                ]
            }
        }

        plan = generate_normalization_plan(scan_results)

        assert "bars_1m" in plan
        assert "short" in plan["bars_1m"]
        assert plan["bars_1m"]["short"]["rename_map"]["t"] == "ts"
        assert plan["bars_1m"]["short"]["cast_rules"]["volume"] == "int64"

    @patch("qx_scan.bronze_qa_scan.Path")
    def test_scan_bronze_qa_no_path(self, mock_path):
        """Test scan when path doesn't exist."""
        mock_path.return_value.exists.return_value = False

        result = scan_bronze_qa("/nonexistent")

        assert result == {}
