"""Integration test for S2 Gold loader with real data."""

import os
import sys

import pandas as pd
import pytest

# Add qx-data to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-data", "src"))

from qx_data.gold_loader import list_available_dates, list_available_symbols, load_bars


class TestS2Integration:
    """Integration tests for S2 implementation."""

    def test_list_available_symbols_integration(self):
        """Test listing symbols from actual Gold data."""
        gold_root = "/home/jacobw/gcs-mount/gold"

        # Test that we can list symbols (if gold data exists)
        if os.path.exists(gold_root):
            symbols = list_available_symbols(gold_root, "bars_1m")
            assert isinstance(symbols, set)
            # Should have some symbols if data exists
            print(f"Found {len(symbols)} symbols in Gold data")
            if symbols:
                print(f"Sample symbols: {list(symbols)[:5]}")
        else:
            pytest.skip("Gold data not available at /home/jacobw/gcs-mount/gold")

    def test_list_available_dates_integration(self):
        """Test listing dates for a symbol from actual Gold data."""
        gold_root = "/home/jacobw/gcs-mount/gold"

        if not os.path.exists(gold_root):
            pytest.skip("Gold data not available")

        # Get available symbols first
        symbols = list_available_symbols(gold_root, "bars_1m")
        if not symbols:
            pytest.skip("No symbols found in Gold data")

        # Test dates for first symbol
        test_symbol = list(symbols)[0]
        dates = list_available_dates(gold_root, "bars_1m", test_symbol)

        assert isinstance(dates, set)
        if dates:
            print(f"Found {len(dates)} dates for {test_symbol}")
            print(f"Sample dates: {list(dates)[:3]}")

    def test_load_bars_integration(self):
        """Test loading bars from actual Gold data."""
        gold_root = "/home/jacobw/gcs-mount/gold"

        if not os.path.exists(gold_root):
            pytest.skip("Gold data not available")

        # Get available symbols and dates
        symbols = list_available_symbols(gold_root, "bars_1m")
        if not symbols:
            pytest.skip("No symbols found in Gold data")

        test_symbol = list(symbols)[0]
        dates = list_available_dates(gold_root, "bars_1m", test_symbol)
        if not dates:
            pytest.skip(f"No dates found for {test_symbol}")

        # Test loading a small amount of data
        test_dates = [list(dates)[0]]  # Load just one date

        try:
            bars = load_bars(
                root=gold_root,
                family="bars_1m",
                symbols=[test_symbol],
                dates=test_dates,
                validate=True,
            )

            # Basic validation of loaded data
            assert isinstance(bars, pd.DataFrame)
            assert len(bars) > 0, "No bars loaded"

            # Check required columns
            required_cols = {"ts", "symbol", "open", "high", "low", "close", "volume"}
            assert required_cols.issubset(
                bars.columns
            ), f"Missing required columns: {required_cols - set(bars.columns)}"

            # Check data types
            assert bars["ts"].dtype == "int64"
            assert bars["symbol"].dtype == "object"
            assert bars["volume"].dtype == "int64"

            # Check that we only have data for requested symbol
            assert set(bars["symbol"]) == {test_symbol}

            # Check that timestamps are positive
            assert (bars["ts"] > 0).all(), "Invalid timestamps found"

            # Check basic OHLC relationships
            assert (bars["high"] >= bars["low"]).all(), "High < Low found"
            assert (bars["high"] >= bars["open"]).all(), "High < Open found"
            assert (bars["high"] >= bars["close"]).all(), "High < Close found"
            assert (bars["low"] <= bars["open"]).all(), "Low > Open found"
            assert (bars["low"] <= bars["close"]).all(), "Low > Close found"

            print(
                f"Successfully loaded {len(bars)} bars for {test_symbol} on {test_dates[0]}"
            )
            print(f"Time range: {bars['ts'].min()} to {bars['ts'].max()}")

        except Exception as e:
            if "No parquet files could be read" in str(e):
                pytest.skip(
                    f"No parquet files found for {test_symbol} on {test_dates[0]}"
                )
            else:
                raise

    def test_load_bars_validation_disabled(self):
        """Test loading bars with validation disabled."""
        gold_root = "/home/jacobw/gcs-mount/gold"

        if not os.path.exists(gold_root):
            pytest.skip("Gold data not available")

        # Get available symbols and dates
        symbols = list_available_symbols(gold_root, "bars_1m")
        if not symbols:
            pytest.skip("No symbols found in Gold data")

        test_symbol = list(symbols)[0]
        dates = list_available_dates(gold_root, "bars_1m", test_symbol)
        if not dates:
            pytest.skip(f"No dates found for {test_symbol}")

        test_dates = [list(dates)[0]]

        try:
            bars = load_bars(
                root=gold_root,
                family="bars_1m",
                symbols=[test_symbol],
                dates=test_dates,
                validate=False,
            )

            assert isinstance(bars, pd.DataFrame)
            assert len(bars) > 0

        except Exception as e:
            if "No parquet files could be read" in str(e):
                pytest.skip(
                    f"No parquet files found for {test_symbol} on {test_dates[0]}"
                )
            else:
                raise


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
