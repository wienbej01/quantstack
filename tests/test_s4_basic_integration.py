"""Basic integration test for S4 SIP screener functionality."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-screener", "src"))

from qx_screener.sip import (
    ScreenerConfig,
    SipScreener,
    create_sample_universe_data,
    select_top_symbols,
)


class TestS4BasicIntegration:
    """Basic integration tests for S4 implementation."""

    def test_screener_package_imports(self):
        """Test that all screener components can be imported."""
        from qx_screener.sip import ScreenerConfig, SipScreener

        # Should be able to create instances without errors
        config = ScreenerConfig()
        screener = SipScreener(config)

        assert config is not None
        assert screener is not None

    def test_screener_basic_workflow(self):
        """Test basic screener workflow."""
        # Create sample data
        sample_data = create_sample_universe_data()

        # Configure screener with reasonable defaults
        config = ScreenerConfig(
            top_n=5, min_relative_volume=0.5, min_price=10.0, max_price=1000.0
        )

        # Create screener and run screening
        screener = SipScreener(config)
        result = screener.screen_universe(sample_data)

        # Verify results
        assert isinstance(result, pd.DataFrame)

        if not result.empty:
            # Should have expected columns
            expected_cols = [
                "symbol",
                "ts",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "relative_volume",
                "rvol_rank",
                "dollar_volume",
            ]
            for col in expected_cols:
                assert col in result.columns

            # Should respect top_n constraint
            assert len(result) <= config.top_n

            # Should meet all screening criteria
            assert (result["close"] >= config.min_price).all()
            assert (result["close"] <= config.max_price).all()
            assert (result["relative_volume"] >= config.min_relative_volume).all()

    def test_screener_with_different_configs(self):
        """Test screener with various configurations."""
        sample_data = create_sample_universe_data()

        # Test very restrictive config
        restrictive_config = ScreenerConfig(
            top_n=2,
            min_relative_volume=2.0,  # High RVOL requirement
            min_price=500.0,  # High minimum price
            max_price=100000.0,  # Very high maximum price
        )

        screener = SipScreener(restrictive_config)
        restrictive_result = screener.screen_universe(sample_data)

        # May return empty or very few results
        assert len(restrictive_result) <= 2

        # Test very permissive config
        permissive_config = ScreenerConfig(
            top_n=20,
            min_relative_volume=0.1,  # Low RVOL requirement
            min_price=1.0,  # Low minimum price
            max_price=10000.0,  # High maximum price
        )

        screener = SipScreener(permissive_config)
        permissive_result = screener.screen_universe(sample_data)

        # Should return more results than restrictive
        assert len(permissive_result) >= len(restrictive_result)
        assert len(permissive_result) <= 20

    def test_screener_deterministic_ranking(self):
        """Test that screener ranking is deterministic."""
        sample_data = create_sample_universe_data()

        # Run screening multiple times
        results = []
        for _ in range(3):
            screener = SipScreener(ScreenerConfig(top_n=5, min_relative_volume=0.1))
            result = screener.screen_universe(sample_data)

            if not result.empty:
                results.append(result["symbol"].tolist())

        # Results should be identical across runs
        if len(results) >= 2:
            for result in results[1:]:
                assert result == results[0]

    def test_screener_utility_functions(self):
        """Test screener utility functions."""
        sample_data = create_sample_universe_data()

        # Test select_top_symbols function
        top_symbols = select_top_symbols(sample_data, top_n=3, min_relative_volume=0.5)

        assert isinstance(top_symbols, list)
        assert len(top_symbols) <= 3
        assert all(isinstance(s, str) for s in top_symbols)

        # Test that selected symbols are actually in the data
        all_symbols = set(sample_data["symbol"].unique())
        assert all(s in all_symbols for s in top_symbols)

    def test_screener_edge_cases(self):
        """Test screener edge cases."""
        screener = SipScreener()

        # Test with empty DataFrame
        empty_result = screener.screen_universe(pd.DataFrame())
        assert empty_result.empty

        # Test with DataFrame that has only one symbol
        single_symbol_data = create_sample_universe_data()
        single_symbol = single_symbol_data["symbol"].iloc[0]
        single_symbol_df = single_symbol_data[
            single_symbol_data["symbol"] == single_symbol
        ].copy()

        single_result = screener.screen_universe(single_symbol_df)
        assert len(single_result) <= 1

        if not single_result.empty:
            assert single_result["symbol"].iloc[0] == single_symbol

    def test_screener_cross_sectional_consistency(self):
        """Test that screener results are cross-sectionally consistent."""
        sample_data = create_sample_universe_data()

        screener = SipScreener(ScreenerConfig(top_n=10))
        result = screener.screen_universe(sample_data)

        if not result.empty:
            # Check that ranking is consistent
            ranks = result["rvol_rank"].values
            assert all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))

            # Check that higher relative volume corresponds to better rank
            rvol_values = result["relative_volume"].values
            for i in range(len(rvol_values) - 1):
                if rvol_values[i] > rvol_values[i + 1]:
                    assert ranks[i] < ranks[i + 1]

            # Check that dollar volume is computed correctly
            expected_dollar_vol = result["close"] * result["volume"]
            actual_dollar_vol = result["dollar_volume"]
            assert np.allclose(expected_dollar_vol, actual_dollar_vol)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
