"""Unit tests for SIP screener functionality."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add qx-screener to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-screener", "src"))

from qx_screener.sip import (
    ScreenerConfig,
    SipScreener,
    compute_relative_volume_rank,
    create_sample_universe_data,
    screen,
    select_top_symbols,
)


class TestScreenerConfig:
    """Test screener configuration."""

    def test_default_config(self):
        """Test default configuration values."""
        config = ScreenerConfig()

        assert config.top_n == 10
        assert config.min_relative_volume == 1.0
        assert config.min_price == 10.0
        assert config.max_price == 1000.0
        assert config.min_dollar_volume == 1_000_000
        assert config.lookback_days == 20
        assert config.volume_window == 30
        assert config.exclude_symbols == []

    def test_custom_config(self):
        """Test custom configuration values."""
        config = ScreenerConfig(
            top_n=5,
            min_relative_volume=1.5,
            min_price=5.0,
            max_price=500.0,
            exclude_symbols=["STOCK1", "STOCK2"],
        )

        assert config.top_n == 5
        assert config.min_relative_volume == 1.5
        assert config.min_price == 5.0
        assert config.max_price == 500.0
        assert config.exclude_symbols == ["STOCK1", "STOCK2"]


class TestSipScreener:
    """Test SIP screener functionality."""

    def setup_method(self):
        """Setup test data."""
        self.screener = SipScreener()

        # Create test data with different volume levels
        np.random.seed(42)
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]
        dates = pd.date_range("2023-01-01", "2023-01-10", freq="D")

        bars = []
        for i, symbol in enumerate(symbols):
            base_volume = 1_000_000 * (i + 1)  # Different base volumes per symbol
            base_price = 100 + i * 50  # Different prices per symbol

            for date in dates:
                if date.weekday() >= 5:  # Skip weekends
                    continue

                # Create realistic volume with time-of-day pattern
                tod_factor = (
                    1.0 + 0.5 * np.sin(2 * np.pi * date.hour / 24) if hasattr(date, "hour") else 1.0
                )
                volume = int(base_volume * tod_factor * (1 + np.random.normal(0, 0.2)))

                # Price data
                close = base_price * (1 + np.random.normal(0, 0.02))
                high = close * 1.01
                low = close * 0.99
                open_price = close

                bars.append(
                    {
                        "ts": date.value,
                        "symbol": symbol,
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": max(volume, 1000),  # Ensure positive volume
                    }
                )

        self.test_df = pd.DataFrame(bars).sort_values(["symbol", "ts"]).reset_index(drop=True)

    def test_screen_universe_basic(self):
        """Test basic universe screening."""
        result = self.screener.screen_universe(self.test_df)

        assert not result.empty
        assert "symbol" in result.columns
        assert "relative_volume" in result.columns
        assert "rvol_rank" in result.columns
        assert len(result) <= self.screener.config.top_n

    def test_screen_universe_with_reference_date(self):
        """Test screening with reference date."""
        reference_date = "2023-01-05"
        result = self.screener.screen_universe(self.test_df, reference_date)

        # Should only consider data up to reference date
        assert not result.empty
        max_ts = result["ts"].max()
        reference_ts = pd.Timestamp(reference_date).value
        assert max_ts <= reference_ts

    def test_screen_universe_empty_dataframe(self):
        """Test screening with empty DataFrame."""
        empty_df = pd.DataFrame()
        result = self.screener.screen_universe(empty_df)

        assert result.empty

    def test_screen_universe_missing_columns(self):
        """Test screening with missing required columns."""
        incomplete_df = pd.DataFrame(
            {
                "ts": [1, 2, 3],
                "symbol": ["A", "B", "C"],
                # Missing OHLCV columns
            }
        )

        with pytest.raises(ValueError, match="Missing required columns"):
            self.screener.screen_universe(incomplete_df)

    def test_add_relative_volume(self):
        """Test relative volume calculation."""
        bars_with_rvol = self.screener._add_relative_volume(self.test_df)

        assert "relative_volume" in bars_with_rvol.columns
        assert len(bars_with_rvol) == len(self.test_df)
        assert (bars_with_rvol["relative_volume"] > 0).all()

    def test_get_latest_per_symbol(self):
        """Test getting latest data per symbol."""
        latest_data = self.screener._get_latest_per_symbol(self.test_df)

        # Should have one row per symbol
        unique_symbols = self.test_df["symbol"].nunique()
        assert len(latest_data) == unique_symbols

        # Each symbol should appear only once
        assert latest_data["symbol"].nunique() == len(latest_data)

    def test_apply_filters(self):
        """Test filtering application."""
        # Create data that will pass some filters
        test_data = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "close": [5.0, 50.0, 500.0, 5000.0],  # Some below min, some above max
                "relative_volume": [0.5, 1.0, 1.5, 2.0],  # Some below min
                "volume": [100_000, 1_000_000, 10_000_000, 100_000_000],
            }
        )

        filtered_data = self.screener._apply_filters(test_data)

        # Should filter out rows that don't meet criteria
        assert len(filtered_data) <= len(test_data)

        # Remaining rows should meet all criteria
        if not filtered_data.empty:
            assert (filtered_data["close"] >= self.screener.config.min_price).all()
            assert (filtered_data["close"] <= self.screener.config.max_price).all()
            assert (
                filtered_data["relative_volume"] >= self.screener.config.min_relative_volume
            ).all()

    def test_rank_by_relative_volume(self):
        """Test ranking by relative volume."""
        test_data = pd.DataFrame(
            {
                "symbol": ["A", "B", "C", "D"],
                "relative_volume": [2.0, 1.0, 3.0, 1.5],
                "close": [100.0, 200.0, 300.0, 400.0],
            }
        )

        ranked_data = self.screener._rank_by_relative_volume(test_data)

        assert "rvol_rank" in ranked_data.columns

        # Should be sorted by relative volume descending
        rvol_values = ranked_data["relative_volume"].values
        assert all(rvol_values[i] >= rvol_values[i + 1] for i in range(len(rvol_values) - 1))

        # Highest relative volume should have rank 1
        max_rvol_symbol = ranked_data.iloc[0]["symbol"]
        assert ranked_data[ranked_data["symbol"] == max_rvol_symbol]["rvol_rank"].iloc[0] == 1

    def test_custom_config_screener(self):
        """Test screener with custom configuration."""
        custom_config = ScreenerConfig(top_n=2, min_relative_volume=0.5, min_price=20.0)
        custom_screener = SipScreener(custom_config)

        result = custom_screener.screen_universe(self.test_df)

        assert len(result) <= 2  # top_n constraint
        if not result.empty:
            assert (result["close"] >= 20.0).all()  # min_price constraint


class TestUtilityFunctions:
    """Test utility functions."""

    def setup_method(self):
        """Setup test data."""
        np.random.seed(42)
        self.test_df = create_sample_universe_data()

    def test_create_sample_universe_data(self):
        """Test sample universe data creation."""
        sample_data = create_sample_universe_data()

        assert not sample_data.empty
        required_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        for col in required_cols:
            assert col in sample_data.columns

        # Should have multiple symbols
        assert sample_data["symbol"].nunique() > 1

        # Should be sorted by symbol and timestamp
        assert sample_data.equals(sample_data.sort_values(["symbol", "ts"]))

    def test_select_top_symbols(self):
        """Test top symbols selection function."""
        top_symbols = select_top_symbols(self.test_df, top_n=5)

        assert isinstance(top_symbols, list)
        assert len(top_symbols) <= 5
        assert all(isinstance(s, str) for s in top_symbols)

    def test_compute_relative_volume_rank(self):
        """Test relative volume ranking computation."""
        ranking = compute_relative_volume_rank(self.test_df)

        assert not ranking.empty
        assert "symbol" in ranking.columns
        assert "relative_volume" in ranking.columns
        assert "rvol_rank" in ranking.columns
        assert "dollar_volume" in ranking.columns

        # Should be sorted by rank
        ranks = ranking["rvol_rank"].values
        assert all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))

    def test_screen_legacy_function(self):
        """Test legacy screen function for backward compatibility."""
        # Create data with ts and relative volume
        test_data = pd.DataFrame(
            {
                "ts": [1640995200000000000, 1640995260000000000] * 3,
                "symbol": ["AAPL", "GOOGL", "MSFT"] * 2,
                "relative_volume": [2.0, 1.5, 1.0, 3.0, 2.5, 0.8],
            }
        )

        result = screen(test_data, "relative_volume", top_n=2)

        assert isinstance(result, dict)

        # Check each timestamp has correct number of symbols
        for _ts, symbols in result.items():
            assert len(symbols) <= 2
            assert all(isinstance(s, str) for s in symbols)

    def test_screen_with_whitelist(self):
        """Test legacy screen function with whitelist."""
        test_data = pd.DataFrame(
            {
                "ts": [1640995200000000000] * 4,
                "symbol": ["AAPL", "GOOGL", "MSFT", "AMZN"],
                "relative_volume": [2.0, 1.5, 1.0, 3.0],
            }
        )

        whitelist = ["AAPL", "MSFT"]
        result = screen(test_data, "relative_volume", top_n=3, whitelist=whitelist)

        assert isinstance(result, dict)
        for _ts, symbols in result.items():
            # All selected symbols should be in whitelist
            assert all(s in whitelist for s in symbols)


class TestIntegration:
    """Integration tests for complete screener workflow."""

    def test_end_to_end_screening_workflow(self):
        """Test complete screening workflow."""
        # Create sample data
        sample_data = create_sample_universe_data()

        # Configure screener
        config = ScreenerConfig(top_n=5, min_relative_volume=0.8, min_price=50.0, max_price=1000.0)

        # Screen universe
        screener = SipScreener(config)
        result = screener.screen_universe(sample_data)

        # Verify results
        assert not result.empty
        assert len(result) <= 5

        # Check that all constraints are met
        if not result.empty:
            assert (result["close"] >= 50.0).all()
            assert (result["close"] <= 1000.0).all()
            assert (result["relative_volume"] >= 0.8).all()

    def test_deterministic_selection(self):
        """Test that selection is deterministic."""
        sample_data = create_sample_universe_data()

        # Run screening multiple times with same data
        results = []
        for _ in range(3):
            screener = SipScreener(ScreenerConfig(top_n=5, min_relative_volume=0.5))
            result = screener.screen_universe(sample_data)
            results.append(result["symbol"].tolist())

        # Results should be identical
        assert results[0] == results[1] == results[2]

    def test_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Test with single symbol
        single_symbol_df = pd.DataFrame(
            {
                "ts": [1640995200000000000],
                "symbol": ["AAPL"],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1_000_000],
            }
        )

        screener = SipScreener()
        result = screener.screen_universe(single_symbol_df)

        # Should handle single symbol gracefully
        assert len(result) <= 1
        if not result.empty:
            assert result["symbol"].iloc[0] == "AAPL"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
