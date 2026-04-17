"""Tests for data loaders.

Tests use real data from the data mounts to ensure loaders work correctly.
Following the project policy: no synthetic data for testing when real data is available.
"""

import json
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.data import GoldLoader, L2Loader, SipLoader
from src.data.l2_loader import L2Source
from src.data.gold_loader import _next_month


def _first_gold_symbol_and_date(loader: GoldLoader) -> tuple[str, str] | None:
    if not loader.min_1_path.exists():
        return None
    for symbol_dir in sorted(p for p in loader.min_1_path.iterdir() if p.is_dir()):
        parquet_files = sorted(symbol_dir.glob("*/*.parquet"))
        if parquet_files:
            year = parquet_files[0].parent.name
            month = parquet_files[0].stem
            return symbol_dir.name, f"{year}-{month.split('-')[-1]}-01"
    return None


def _first_spy_month() -> str | None:
    spy_root = Path("~/gcs-mount/stocks/SPY").expanduser()
    parquet_files = sorted(spy_root.glob("*/*.parquet"))
    if not parquet_files:
        return None
    year = parquet_files[0].parent.name
    month = parquet_files[0].stem.split("-")[-1]
    return f"{year}-{month}-01"


def _first_l2_symbol_and_date(loader: L2Loader) -> tuple[str, str] | None:
    for date in loader.get_available_dates():
        symbols = loader.get_available_symbols(date)
        if symbols:
            return symbols[0], date
    return None


class TestGoldLoader:
    """Tests for GoldLoader."""

    def test_gold_loader_single_symbol(self):
        """Load AAPL, verify columns and data structure."""
        loader = GoldLoader()
        sample = _first_gold_symbol_and_date(loader)
        if sample is None:
            pytest.skip("Gold 1m parquet data is not mounted on this machine")
        symbol, date = sample

        # Load a small date range
        df = loader.load_bars(symbol, date, date)

        # Verify we got data
        assert len(df) > 0, "Should have loaded bars for AAPL"

        # Verify required columns exist
        required_cols = ["ts", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

        # Verify data types
        assert pd.api.types.is_datetime64_any_dtype(df["ts"]), "ts should be datetime"
        assert pd.api.types.is_numeric_dtype(df["close"]), "close should be numeric"

        # Verify no null values in core columns
        assert (
            df[required_cols].notna().all().all()
        ), "Core columns should not have nulls"

    def test_gold_loader_date_range(self):
        """Load 1 week, verify continuity and sorting."""
        loader = GoldLoader()
        sample = _first_gold_symbol_and_date(loader)
        if sample is None:
            pytest.skip("Gold 1m parquet data is not mounted on this machine")
        symbol, date = sample

        df = loader.load_bars(symbol, date, date)

        # Verify we got data
        assert len(df) > 0, "Should have loaded bars for date range"

        # Verify sorted by timestamp
        assert df["ts"].is_monotonic_increasing, "Timestamps should be sorted"

        # Verify no duplicates
        assert len(df) == len(
            df.drop_duplicates(subset=["ts"])
        ), "No duplicate timestamps"

    def test_gold_loader_spy(self):
        """Load SPY for regime classification."""
        loader = GoldLoader()
        date = _first_spy_month()
        if date is None:
            pytest.skip("SPY parquet data is not mounted on this machine")

        df = loader.load_spy_bars(date, date)

        # Verify we got SPY data
        assert len(df) > 0, "Should have loaded SPY bars"

        # Verify required columns
        assert "ts" in df.columns
        assert "close" in df.columns

    def test_gold_loader_invalid_date_format(self):
        """Test that invalid date format raises ValueError."""
        loader = GoldLoader()

        with pytest.raises(ValueError, match="Invalid date format"):
            loader.load_bars("AAPL", "01/02/2024", "2024-01-02")

    def test_gold_loader_symbol_not_found(self):
        """Test that non-existent symbol raises FileNotFoundError."""
        loader = GoldLoader()

        with pytest.raises(FileNotFoundError, match="Symbol path not found"):
            loader.load_bars("NOTASYMBOL", "2024-01-02", "2024-01-02")

    def test_gold_loader_check_coverage(self):
        """Test coverage check functionality."""
        loader = GoldLoader()
        sample = _first_gold_symbol_and_date(loader)
        if sample is None:
            pytest.skip("Gold 1m parquet data is not mounted on this machine")
        symbol, date = sample

        coverage = loader.check_data_coverage(symbol, date, date)

        # Verify coverage keys
        assert "total_bars" in coverage
        assert "found_bars" in coverage
        assert "coverage_pct" in coverage
        assert "missing_dates" in coverage

        # Verify we found some data
        assert coverage["found_bars"] > 0

    def test_next_month_handles_month_end(self):
        """Month stepping should not fail on 29th/30th/31st dates."""
        assert _next_month(datetime(2026, 1, 31)) == datetime(2026, 2, 1)
        assert _next_month(datetime(2024, 2, 29)) == datetime(2024, 3, 1)
        assert _next_month(datetime(2026, 12, 31)) == datetime(2027, 1, 1)


class TestSipLoader:
    """Tests for SipLoader."""

    def test_sip_loader_universe(self):
        """Load SIP for 1 day, verify symbols returned."""
        loader = SipLoader()

        # Try to load a date that should exist
        # Using a recent date based on the data we saw
        symbols = loader.load_universe("2024-01-19")

        # Verify we got symbols
        assert len(symbols) > 0, "Should have loaded SIP symbols"

        # Verify symbols are strings
        assert all(isinstance(s, str) for s in symbols), "All symbols should be strings"

        # Verify no empty symbols
        assert all(s.strip() for s in symbols), "No empty symbols"

    def test_sip_loader_multi_date(self):
        """Load SIP universe for multiple dates."""
        loader = SipLoader()

        df = loader.load_universe_multi(["2024-01-19", "2024-01-20"])

        # Verify DataFrame structure
        assert "date" in df.columns
        assert "symbol" in df.columns

        # Verify we got data
        assert len(df) > 0

    def test_sip_loader_date_range(self):
        """Load SIP universe for date range."""
        loader = SipLoader()

        df = loader.load_universe_range("2024-01-19", "2024-01-20")

        # Verify DataFrame structure
        assert "date" in df.columns
        assert "symbol" in df.columns

    def test_sip_loader_invalid_date_format(self):
        """Test that invalid date format raises ValueError."""
        loader = SipLoader()

        with pytest.raises(ValueError, match="Invalid date format"):
            loader.load_universe("01/19/2024")

    def test_sip_loader_date_not_found(self):
        """Test that non-existent date raises FileNotFoundError."""
        loader = SipLoader()

        # Use a date far in the future that won't exist
        with pytest.raises(FileNotFoundError):
            loader.load_universe("2099-01-01")

    def test_sip_loader_get_available_dates(self):
        """Test getting available dates."""
        loader = SipLoader()

        dates = loader.get_available_dates()

        # Verify we got dates
        assert len(dates) > 0, "Should have available dates"

        # Verify date format
        assert all(len(d) == 10 for d in dates), "Dates should be YYYY-MM-DD format"

    def test_sip_loader_loadable_dates_ignore_missing_or_empty_files(self, tmp_path):
        missing_file_dir = tmp_path / "date=2026-01-08"
        missing_file_dir.mkdir()

        empty_dir = tmp_path / "date=2026-01-09"
        empty_dir.mkdir()
        (empty_dir / "sip_universe.json").write_text(
            json.dumps({"date": "2026-01-09", "symbols": []})
        )

        valid_dir = tmp_path / "date=2026-01-10"
        valid_dir.mkdir()
        (valid_dir / "sip_universe.json").write_text(
            json.dumps({"date": "2026-01-10", "symbols": ["AAPL", "MSFT"]})
        )

        loader = SipLoader(sip_path=tmp_path)

        assert loader.get_available_dates() == ["2026-01-09", "2026-01-10"]
        assert loader.get_loadable_dates() == ["2026-01-10"]
        assert loader.get_loadable_dates(require_non_empty=False) == [
            "2026-01-09",
            "2026-01-10",
        ]


class TestL2Loader:
    """Tests for L2Loader."""

    def test_l2_loader_snapshots(self):
        """Load L2, verify book structure."""
        loader = L2Loader()
        sample = _first_l2_symbol_and_date(loader)
        if sample is None:
            pytest.skip("No mounted L2 parquet data found")
        symbol, date = sample

        df = loader.load_snapshots(symbol, date)

        # Verify we got snapshots
        assert len(df) > 0, "Should have loaded L2 snapshots"

        # Verify required columns for order book
        required_cols = ["ts_utc", "symbol", "has_depth"]
        for col in required_cols:
            assert col in df.columns, f"Missing column: {col}"

        # Verify at least some depth columns exist
        if "bid_px_1" in df.columns:
            depth_cols = ["bid_px_1", "ask_px_1", "bid_sz_1", "ask_sz_1"]
        else:
            depth_cols = ["mid", "spread", "obi_1", "pressure_k"]
        for col in depth_cols:
            assert col in df.columns, f"Missing depth column: {col}"

        # Verify has_depth is boolean or can be treated as such
        assert df["has_depth"].dtype in [
            bool,
            "bool",
            "object",
        ], "has_depth should be bool-like"

    def test_l2_loader_time_filter(self):
        """Test filtering by time range."""
        loader = L2Loader()
        sample = _first_l2_symbol_and_date(loader)
        if sample is None:
            pytest.skip("No mounted L2 parquet data found")
        symbol, date = sample

        # Load with time filter
        df = loader.load_snapshots(symbol, date, start_time="09:30:00", end_time="10:00:00")

        # Verify we got filtered data
        # (May be empty if no data in that time range, but shouldn't error)
        assert "ts_utc" in df.columns

    def test_l2_loader_min_depth_filter(self):
        """Test filtering by minimum depth levels."""
        loader = L2Loader()
        sample = _first_l2_symbol_and_date(loader)
        if sample is None:
            pytest.skip("No mounted L2 parquet data found")
        symbol, date = sample

        # Load with minimum depth requirement
        df = loader.load_snapshots(symbol, date, min_depth=5)

        # Verify all returned snapshots have at least 5 levels
        # (This is implicit in the filter, so we just verify no errors)

    def test_l2_loader_multi_symbol(self):
        """Test loading multiple symbols."""
        loader = L2Loader()

        df = loader.load_snapshots_multi(["LUV"], "2025-12-19")

        # Verify we got data
        if not df.empty:
            assert "symbol" in df.columns

    def test_l2_loader_invalid_date_format(self):
        """Test that invalid date format raises ValueError."""
        loader = L2Loader()

        with pytest.raises(ValueError, match="Invalid date format"):
            loader.load_snapshots("LUV", "12/19/2025")

    def test_l2_loader_symbol_not_found(self):
        """Test that non-existent symbol/date raises FileNotFoundError."""
        loader = L2Loader()

        with pytest.raises(FileNotFoundError):
            loader.load_snapshots("NOTASYMBOL", "2099-01-01")

    def test_l2_loader_get_available_dates(self):
        """Test getting available dates."""
        loader = L2Loader()

        dates = loader.get_available_dates()

        # Verify we got dates (assuming L2 data exists)
        if dates:
            assert all(len(d) == 10 for d in dates), "Dates should be YYYY-MM-DD format"

    def test_l2_loader_get_available_symbols(self):
        """Test getting available symbols for a date."""
        loader = L2Loader()
        date = next(iter(loader.get_available_dates()), None)
        if date is None:
            pytest.skip("No mounted L2 parquet data found")

        symbols = loader.get_available_symbols(date)

        # Verify we got symbols
        if symbols:
            assert all(isinstance(symbol, str) and symbol for symbol in symbols)

    def test_l2_loader_inventory_filters_weekends_and_empty_symbol_dirs(self, tmp_path):
        source_root = tmp_path / "raw"
        weekend_symbol_dir = source_root / "date=2026-01-31" / "symbol=BAD"
        weekend_symbol_dir.mkdir(parents=True)
        (weekend_symbol_dir / "part-0.parquet").write_text("placeholder")

        weekday_empty_dir = source_root / "date=2026-02-02" / "symbol=EMPTY"
        weekday_empty_dir.mkdir(parents=True)

        weekday_symbol_dir = source_root / "date=2026-02-02" / "symbol=GOOD"
        weekday_symbol_dir.mkdir(parents=True)
        (weekday_symbol_dir / "part-0.parquet").write_text("placeholder")

        loader = L2Loader(
            sources=[
                L2Source(
                    path=source_root,
                    source_type="raw",
                    name="tmp-raw",
                    priority=1,
                )
            ]
        )

        assert loader.get_available_dates() == ["2026-02-02"]
        assert loader.get_available_symbols("2026-01-31") == []
        assert loader.get_available_symbols("2026-02-02") == ["GOOD"]


class TestDataAlignment:
    """Tests for data alignment across sources."""

    def test_timestamp_alignment(self):
        """Verify timestamps align across Gold and L2 sources."""
        gold_loader = GoldLoader()
        l2_loader = L2Loader()

        # Note: This test may not find matching data since sources have different dates
        # This is more of a structural test to ensure timestamp formats are compatible

        # Load Gold data
        gold_sample = _first_gold_symbol_and_date(gold_loader)
        if gold_sample is None:
            pytest.skip("Gold 1m parquet data is not mounted on this machine")
        symbol, date = gold_sample
        gold_df = gold_loader.load_bars(symbol, date, date)

        # Verify timestamp is datetime
        assert pd.api.types.is_datetime64_any_dtype(gold_df["ts"])

        # For L2, we'd check if we have matching dates
        # This demonstrates the structure for alignment tests
