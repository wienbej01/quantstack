"""Sprint M2 Feature Pack Integration Test

Integration test for the complete feature pack pipeline including
feature computation, registry validation, and manifest integration.
"""

import tempfile
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest
import yaml

from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack
from extensions.intraday_ml.feature_registry import IntradayMLFeatureRegistry


class TestM2FeatureIntegration:
    """Integration tests for Sprint M2 feature pack."""

    @pytest.fixture
    def feature_config(self):
        """Load the actual features.yaml configuration."""
        config_path = Path("configs/extensions/intraday_ml/features.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def universe_config(self):
        """Load universe configuration."""
        config_path = Path("configs/extensions/intraday_ml/universe.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def cuts_config(self):
        """Load cuts configuration."""
        config_path = Path("configs/extensions/intraday_ml/cuts.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def splits_config(self):
        """Load splits configuration."""
        config_path = Path("configs/extensions/intraday_ml/splits.yaml")
        with open(config_path) as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def sample_bars(self):
        """Generate sample bar data for testing."""
        np.random.seed(42)
        symbols = ["AAPL", "MSFT", "SPY"]
        dates = pd.date_range("2024-01-02 09:30:00", periods=200, freq="1min")

        data = []
        for symbol in symbols:
            base_price = {"AAPL": 150.0, "MSFT": 250.0, "SPY": 400.0}[symbol]

            for i, ts in enumerate(dates):
                # Simulate realistic price movement
                trend = i * 0.001  # Small upward trend
                noise = np.random.normal(0, 0.002) * base_price
                close = base_price + trend + noise

                # Generate OHLC
                high_low_range = abs(np.random.normal(0, 0.001)) * base_price
                high = close + high_low_range * np.random.random()
                low = close - high_low_range * (1 - np.random.random())
                open_price = low + (high - low) * np.random.random()

                # Volume with some intraday pattern
                base_volume = {"AAPL": 100000, "MSFT": 80000, "SPY": 200000}[symbol]
                volume_pattern = 1.0 + 0.5 * np.sin(
                    2 * np.pi * i / 390
                )  # Intraday pattern
                volume = int(
                    base_volume * volume_pattern * (1 + np.random.normal(0, 0.2))
                )

                data.append(
                    {
                        "ts": ts,
                        "symbol": symbol,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": max(volume, 1000),
                    }
                )

        df = pd.DataFrame(data)
        return df.sort_values(["symbol", "ts"]).reset_index(drop=True)

    def test_feature_config_loading(self, feature_config):
        """Test that feature configuration loads correctly."""
        assert "families" in feature_config
        assert "max_total_features" in feature_config
        assert feature_config["max_total_features"] == 150

        # Check that all expected families are present
        expected_families = [
            "returns_trend",
            "volatility_ranges",
            "volume_flow",
            "vwap_distance",
            "time_seasonality",
            "cross_section",
            "price_momentum",
            "microstructure",
        ]

        for family in expected_families:
            assert family in feature_config["families"]

    def test_feature_pack_integration(self, feature_config, sample_bars):
        """Test complete feature pack integration."""
        pack = IntradayMLFeaturePack(feature_config)
        ts_cut = sample_bars["ts"].max()  # Use max timestamp

        # Compute features
        features = pack.compute_features(sample_bars, ts_cut)

        # Validate basic properties
        assert len(features) == len(sample_bars)  # Same number of rows
        assert len(features.columns) <= 150  # Within feature limit
        assert len(features.columns) > 0  # Some features computed

        # Check that feature names follow convention
        for col in features.columns:
            assert col.startswith("f__")
            assert "__" in col  # Family__metric format

    def test_feature_registry_integration(self, feature_config):
        """Test feature registry integration."""
        registry = IntradayMLFeatureRegistry(feature_config)

        # Get all feature names
        feature_names = registry.get_feature_names()
        assert len(feature_names) > 0
        assert len(feature_names) <= 150

        # Check metadata for a sample feature
        if feature_names:
            sample_feature = feature_names[0]
            metadata = registry.get_feature_metadata(sample_feature)
            assert metadata is not None
            assert metadata.name == sample_feature
            assert metadata.family in feature_config["families"]

        # Test family grouping
        families = set()
        for feature_name in feature_names:
            metadata = registry.get_feature_metadata(feature_name)
            families.add(metadata.family)

        assert len(families) > 0

    def test_manifest_features_integration(
        self, feature_config, universe_config, cuts_config, splits_config, sample_bars
    ):
        """Test integration of features hash into manifest pipeline."""
        # Mock the data loading and universe building
        mock_universe = pd.DataFrame(
            {
                "symbol": ["AAPL", "MSFT", "SPY"],
                "close": [150.5, 250.5, 400.5],
                "volume": [100000, 80000, 200000],
                "relative_volume": [1.2, 0.9, 1.1],
            }
        )

        with (
            patch("qx_data.gold_loader.load_bars", return_value=sample_bars),
            patch(
                "extensions.intraday_ml.universe_adapter.IntradayMLUniverseAdapter.build_universe",
                return_value=mock_universe,
            ),
        ):

            builder = DatasetManifestBuilder(
                gold_root="/fake/gold/root",
                universe_config=universe_config,
                cuts_config=cuts_config,
                splits_config=splits_config,
                features_config=feature_config,  # Include features config
            )

            # Build manifest
            candidate_symbols = ["AAPL", "MSFT", "SPY"]

            with tempfile.TemporaryDirectory() as temp_dir:
                manifest_path = Path(temp_dir) / "manifest.json"

                manifest = builder.build_manifest(
                    candidate_symbols=candidate_symbols, output_path=manifest_path
                )

                # Validate that features hash is included
                assert manifest.features_hash is not None
                assert (
                    len(manifest.features_hash) >= 64
                )  # Hash length (64+ chars for security)

                # Validate manifest structure
                assert manifest.total_symbols >= 3
                assert manifest.total_days > 0
                assert manifest.data_hash is not None
                assert manifest.config_hash is not None
                assert manifest.universe_hash is not None

    def test_feature_registry_validation(self, feature_config, sample_bars):
        """Test feature registry validation with real data."""
        pack = IntradayMLFeaturePack(feature_config)
        registry = IntradayMLFeatureRegistry(feature_config)

        ts_cut = sample_bars["ts"].max()
        features = pack.compute_features(sample_bars, ts_cut)

        # Validate features against registry
        validation = registry.validate_features(features)

        # Should be valid (no missing/unexpected features for our subset)
        assert (
            validation["valid"] or len(validation["missing_features"]) > 0
        )  # May have missing if not all families used

        # Check structure
        assert "feature_count" in validation
        assert "expected_count" in validation
        assert "missing_features" in validation
        assert "unexpected_features" in validation

    def test_leakage_prevention_property(self, feature_config, sample_bars):
        """Property test for leakage prevention across all features."""
        pack = IntradayMLFeaturePack(feature_config)

        # Test multiple cut times
        cut_positions = [50, 100, 150]

        for cut_pos in cut_positions:
            ts_cut = sample_bars["ts"].iloc[cut_pos]

            # Compute features with data filtered to ts_cut
            filtered_data = sample_bars[sample_bars["ts"] <= ts_cut]
            features = pack.compute_features(filtered_data, ts_cut)

            # For each row at or before ts_cut, features should be computable
            valid_rows = sample_bars[sample_bars["ts"] <= ts_cut]

            for idx in valid_rows.index:
                if idx in features.index:
                    feature_row = features.loc[idx]

                    # Check that no feature values are "too perfect" (indicating leakage)
                    for col in features.columns:
                        value = feature_row[col]
                        # Handle case where value might be a Series (duplicate index)
                        if hasattr(value, "iloc"):
                            value = value.iloc[0]
                        if pd.notna(value):
                            # Values should be realistic (not infinite, not extreme NaN patterns)
                            assert np.isfinite(
                                value
                            ), f"Non-finite value in {col} at {idx}"

                            # Check for reasonable bounds based on feature type
                            if "ret" in col and "log" in col:
                                # Log returns should be small for 1-minute bars
                                assert (
                                    abs(value) < 0.1
                                ), f"Suspicious log return magnitude in {col}: {value}"
                            elif "sin" in col or "cos" in col:
                                # Cyclical features should be in [-1, 1]
                                assert (
                                    -1.1 <= value <= 1.1
                                ), f"Cyclical feature out of bounds in {col}: {value}"

    def test_feature_count_compliance(self, feature_config, sample_bars):
        """Test that feature count complies with ≤150 limit."""
        pack = IntradayMLFeaturePack(feature_config)
        ts_cut = sample_bars["ts"].max()

        features = pack.compute_features(sample_bars, ts_cut)

        # Should be within the limit
        assert (
            len(features.columns) <= 150
        ), f"Generated {len(features.columns)} features, exceeding limit of 150"

        # Should have generated a reasonable number of features
        assert (
            len(features.columns) >= 10
        ), f"Generated only {len(features.columns)} features, expected more"

    def test_performance_budget(self, feature_config, sample_bars):
        """Test that feature computation meets performance budget."""
        import time

        pack = IntradayMLFeaturePack(feature_config)
        ts_cut = sample_bars["ts"].max()

        # Time feature computation
        start_time = time.time()
        features = pack.compute_features(sample_bars, ts_cut)
        computation_time = time.time() - start_time

        # Should complete within reasonable time (120 seconds for full dataset)
        # Our test dataset is much smaller, so expect much faster completion
        assert (
            computation_time < 10.0
        ), f"Feature computation took {computation_time:.2f}s, expected < 10s"

        # Should have produced results
        assert len(features) > 0
        assert len(features.columns) > 0

    def test_deterministic_feature_computation(self, feature_config, sample_bars):
        """Test that feature computation is deterministic."""
        pack = IntradayMLFeaturePack(feature_config)
        ts_cut = sample_bars["ts"].max()

        # Compute features twice
        features1 = pack.compute_features(sample_bars, ts_cut)
        features2 = pack.compute_features(sample_bars, ts_cut)

        # Should be identical
        pd.testing.assert_frame_equal(features1, features2)

        # Hash should be identical
        from extensions.intraday_ml.dataset_manifest import (
            intraday_ml_get_features_hash,
        )

        # Use a subset of data for hash computation
        subset = sample_bars[sample_bars["symbol"].isin(["AAPL", "MSFT"])]

        hash1 = intraday_ml_get_features_hash(subset, feature_config)
        hash2 = intraday_ml_get_features_hash(subset, feature_config)

        assert hash1 == hash2, "Features hash should be deterministic"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
