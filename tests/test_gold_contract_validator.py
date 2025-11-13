"""Tests for Gold contract validator."""

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from qx_scan.gold_contract_validator import validate_gold_file


class TestGoldContractValidator:
    """Test Gold contract validation."""

    @pytest.fixture
    def valid_gold_data(self, tmp_path):
        """Create valid Gold data."""
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2022-01-01 09:30:00", "2022-01-01 09:31:00"], utc=True),
                "symbol": ["AAPL", "AAPL"],
                "open": [100.0, 101.0],
                "high": [102.0, 103.0],
                "low": [99.0, 100.0],
                "close": [101.0, 102.0],
                "volume": [1000, 1100],
                "turnover": [101000.0, 112200.0],  # close * volume
                "session": ["regular", "regular"],
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "bars_1m" / "valid.parquet"
        file_path.parent.mkdir()
        pq.write_table(table, file_path)
        return file_path

    @pytest.fixture
    def invalid_extra_column(self, tmp_path):
        """Create data with extra forbidden column."""
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2022-01-01 09:30:00"], utc=True),
                "symbol": ["AAPL"],
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000],
                "signal": [1.0],  # Forbidden
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "invalid_extra.parquet"
        pq.write_table(table, file_path)
        return file_path

    @pytest.fixture
    def invalid_turnover(self, tmp_path):
        """Create data with incorrect turnover derivation."""
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2022-01-01 09:30:00"], utc=True),
                "symbol": ["AAPL"],
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000],
                "turnover": [99999.0],  # Wrong: should be 101000
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "invalid_turnover.parquet"
        pq.write_table(table, file_path)
        return file_path

    @pytest.fixture
    def invalid_timestamp_alignment(self, tmp_path):
        """Create data with misaligned timestamps."""
        df = pd.DataFrame(
            {
                "ts": pd.to_datetime(["2022-01-01 09:30:30"], utc=True),  # Not on minute boundary
                "symbol": ["AAPL"],
                "open": [100.0],
                "high": [102.0],
                "low": [99.0],
                "close": [101.0],
                "volume": [1000],
            }
        )
        table = pa.Table.from_pandas(df)
        file_path = tmp_path / "bars_1m" / "invalid_ts.parquet"
        file_path.parent.mkdir()
        pq.write_table(table, file_path)
        return file_path

    def test_valid_gold_file(self, valid_gold_data):
        """Test validation passes for valid Gold data."""
        issues = validate_gold_file(valid_gold_data)
        assert len(issues) == 0

    def test_invalid_extra_column(self, invalid_extra_column):
        """Test validation fails for extra columns."""
        issues = validate_gold_file(invalid_extra_column)
        assert any("Extra columns" in issue for issue in issues)

    def test_invalid_turnover(self, invalid_turnover):
        """Test validation fails for incorrect turnover."""
        issues = validate_gold_file(invalid_turnover)
        assert any("turnover column not correctly derived" in issue for issue in issues)

    def test_invalid_timestamp_alignment(self, invalid_timestamp_alignment):
        """Test validation fails for misaligned timestamps."""
        issues = validate_gold_file(invalid_timestamp_alignment)
        assert any("not aligned" in issue for issue in issues)
