"""Integration tests for S4 SIP screener with other QuantStack components."""

import os
import sys

import numpy as np
import pandas as pd
import pytest

# Add required paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-screener", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "qx-features", "src"))

from qx_features.registry import apply
from qx_screener.sip import ScreenerConfig, SipScreener, create_sample_universe_data


class TestScreenerIntegration:
    """Test SIP screener integration with other QuantStack components."""

    def setup_method(self):
        """Setup test data for integration tests."""
        np.random.seed(42)
        self.sample_data = create_sample_universe_data()

    def test_screener_with_feature_engineering(self):
        """Test that screener works with feature engineering pipeline."""
        # Screen universe to get top symbols
        screener = SipScreener(ScreenerConfig(top_n=5, min_relative_volume=0.5))
        screened_symbols = screener.screen_universe(self.sample_data)

        if screened_symbols.empty:
            pytest.skip("No symbols passed screening criteria")

        # Filter original data to screened symbols
        top_symbols = screened_symbols["symbol"].tolist()
        filtered_data = self.sample_data[self.sample_data["symbol"].isin(top_symbols)].copy()

        # Apply features to filtered data
        feature_packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 10,
                    "rel_vol_window_m": 10,
                    "atr_window_m": 5,
                },
            }
        ]

        feature_data = apply(filtered_data, feature_packs)

        # Verify that features were computed
        assert "f__ta__vwap_10" in feature_data.columns
        assert "f__vol__rel_volume_10" in feature_data.columns
        assert "f__vol__atr_5" in feature_data.columns
        assert "f__warmup_ok" in feature_data.columns

        # Data should contain only screened symbols
        assert set(feature_data["symbol"].unique()) <= set(top_symbols)

    def test_screener_config_variations(self):
        """Test different screener configurations."""
        ScreenerConfig()

        # Test different top_n values
        for top_n in [3, 5, 10]:
            config = ScreenerConfig(top_n=top_n)
            screener = SipScreener(config)
            result = screener.screen_universe(self.sample_data)

            assert len(result) <= top_n

        # Test different relative volume thresholds
        for min_rvol in [0.5, 1.0, 2.0]:
            config = ScreenerConfig(min_relative_volume=min_rvol)
            screener = SipScreener(config)
            result = screener.screen_universe(self.sample_data)

            if not result.empty:
                assert (result["relative_volume"] >= min_rvol).all()

        # Test different price filters
        for min_price in [10.0, 50.0, 100.0]:
            config = ScreenerConfig(min_price=min_price)
            screener = SipScreener(config)
            result = screener.screen_universe(self.sample_data)

            if not result.empty:
                assert (result["close"] >= min_price).all()

    def test_screener_determinism(self):
        """Test that screener produces deterministic results."""
        # Run screening multiple times
        results = []
        for _ in range(5):
            screener = SipScreener(ScreenerConfig(top_n=5, min_relative_volume=0.5))
            result = screener.screen_universe(self.sample_data)
            if not result.empty:
                results.append(result["symbol"].tolist())

        # Results should be identical (if any symbols passed screening)
        if results:
            for result in results[1:]:
                assert result == results[0]

    def test_screener_with_feature_pre_computation(self):
        """Test screener using pre-computed features."""
        # First compute features on all data
        feature_packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 10,
                    "rel_vol_window_m": 10,
                    "atr_window_m": 5,
                },
            }
        ]

        feature_data = apply(self.sample_data, feature_packs)

        # Add relative_volume column for screener (rename from feature)
        feature_data["relative_volume"] = feature_data["f__vol__rel_volume_10"]

        # Now screen based on latest feature values
        screener = SipScreener(ScreenerConfig(top_n=5))

        # Get latest data per symbol with features
        latest_data = feature_data.sort_values(["symbol", "ts"], ascending=[True, False])
        latest_per_symbol = latest_data.groupby("symbol").head(1)

        # Apply filters using feature data
        filtered_data = screener._apply_filters(latest_per_symbol)

        if not filtered_data.empty:
            # Should have both original data and features
            assert "f__ta__vwap_10" in filtered_data.columns
            assert "f__vol__rel_volume_10" in filtered_data.columns
            assert "f__vol__atr_5" in filtered_data.columns

    def test_screener_performance_characteristics(self):
        """Test screener performance with different data sizes."""
        # Test with different amounts of data
        data_sizes = [100, 500, 1000]

        for size in data_sizes:
            # Create subset of data
            subset_data = self.sample_data.head(size)

            screener = SipScreener(ScreenerConfig(top_n=5))

            # Time the screening operation
            import time

            start_time = time.time()
            result = screener.screen_universe(subset_data)
            end_time = time.time()

            # Verify results are reasonable
            assert len(result) <= 5

            # Performance should be reasonable (less than 1 second for these sizes)
            processing_time = end_time - start_time
            assert processing_time < 1.0, f"Screener took {processing_time:.3f}s for {size} rows"

    def test_screener_edge_cases(self):
        """Test screener edge cases and boundary conditions."""
        screener = SipScreener()

        # Test with empty DataFrame
        empty_result = screener.screen_universe(pd.DataFrame())
        assert empty_result.empty

        # Test with data that has no symbols passing filters
        high_filter_config = ScreenerConfig(
            min_relative_volume=10.0,  # Very high threshold
            min_price=10000.0,  # Very high price
        )
        high_filter_screener = SipScreener(high_filter_config)
        high_filter_result = high_filter_screener.screen_universe(self.sample_data)

        # Should return empty DataFrame
        assert high_filter_result.empty

        # Test with single symbol
        single_symbol_data = self.sample_data[self.sample_data["symbol"] == "AAPL"].copy()
        single_result = screener.screen_universe(single_symbol_data)

        assert len(single_result) <= 1
        if not single_result.empty:
            assert single_result["symbol"].iloc[0] == "AAPL"

    def test_screener_cross_sectional_ranking(self):
        """Test cross-sectional ranking consistency."""
        screener = SipScreener(ScreenerConfig(top_n=10))
        result = screener.screen_universe(self.sample_data)

        if not result.empty:
            # Verify ranking is consistent
            ranks = result["rvol_rank"].values
            assert all(ranks[i] <= ranks[i + 1] for i in range(len(ranks) - 1))

            # Verify relative volume sorting
            rvol_values = result["relative_volume"].values
            for i in range(len(rvol_values) - 1):
                # Higher relative volume should have better (lower) rank
                if rvol_values[i] > rvol_values[i + 1]:
                    assert ranks[i] < ranks[i + 1]

    def test_screener_integration_workflow(self):
        """Test complete screener integration workflow."""
        # Step 1: Screen universe
        screener = SipScreener(ScreenerConfig(top_n=5, min_relative_volume=0.5, min_price=50.0))
        screened_data = screener.screen_universe(self.sample_data)

        if screened_data.empty:
            pytest.skip("No symbols passed screening criteria")

        # Step 2: Get selected symbols
        selected_symbols = screened_data["symbol"].tolist()

        # Step 3: Filter data to selected symbols
        filtered_data = self.sample_data[self.sample_data["symbol"].isin(selected_symbols)].copy()

        # Step 4: Apply feature engineering
        feature_packs = [
            {
                "type": "core_basics",
                "params": {
                    "vwap_window_m": 5,
                    "rel_vol_window_m": 5,
                    "atr_window_m": 3,
                },
            }
        ]

        feature_data = apply(filtered_data, feature_packs)

        # Step 5: Verify workflow results
        assert not feature_data.empty
        assert len(feature_data["symbol"].unique()) == len(selected_symbols)
        assert "f__ta__vwap_5" in feature_data.columns
        assert "f__vol__rel_volume_5" in feature_data.columns
        assert "f__vol__atr_3" in feature_data.columns

        # Step 6: Verify features are computed correctly
        for symbol in selected_symbols:
            symbol_data = feature_data[feature_data["symbol"] == symbol]
            if len(symbol_data) > 5:  # After warmup
                warmup_data = symbol_data[symbol_data["f__warmup_ok"]]
                if not warmup_data.empty:
                    # VWAP should be reasonable compared to close
                    vwap_values = warmup_data["f__ta__vwap_5"]
                    close_values = warmup_data["close"]

                    # VWAP should be positive and reasonable (not necessarily very close to close)
                    assert (vwap_values > 0).all()
                    # VWAP should be in same general magnitude as close price (with more lenient bounds for synthetic data)
                    vwap_close_ratio = vwap_values / close_values
                    assert (vwap_close_ratio >= 0.1).all() and (vwap_close_ratio <= 10.0).all()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
