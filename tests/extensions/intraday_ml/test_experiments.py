"""Unit tests for intraday ML experiment orchestration."""

import json
import pathlib
import tempfile
from unittest.mock import patch

import pandas as pd
import pytest
import yaml

from extensions.intraday_ml.experiments import (
    _compute_base_hashes,
    _deep_merge_configs,
    _generate_signals,
    _hash_config,
    _load_base_data,
    _run_single_pipeline,
    run_entry_ab_experiment,
    validate_fairness,
)


class TestExperimentOrchestration:
    """Test experiment orchestration functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _create_test_config(self, **overrides):
        """Create test configuration with optional overrides."""
        base_config = {
            "data": {
                "symbols": ["AAPL", "MSFT"],
                "dates": ["2024-01-02", "2024-01-03"],
                "gold_root": "/tmp/test_gold",
                "family": "equities",
            },
            "features": {"feature_pack": "core_basics", "config": {"vwap_window": 20}},
            "screener": {"top_n": 2, "min_relative_volume": 1.0},
            "policy": {"vwap_window": 20, "deviation_threshold": 0.02},
            "risk": {"max_risk_frac": 0.02, "atr_mult": 2.0},
            "backtest": {"initial_cash": 1000000.0, "costs": {"bps": 0.001}},
            "seed": 42,
        }

        base_config.update(overrides)
        return base_config

    def _create_test_bars(self):
        """Create test bars DataFrame."""
        return pd.DataFrame(
            {
                "ts": [1704230400000000000, 1704230460000000000]
                * 2,  # 2 timestamps for 2 symbols
                "symbol": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "open": [150.0, 151.0, 250.0, 251.0],
                "high": [152.0, 153.0, 252.0, 253.0],
                "low": [149.0, 150.0, 249.0, 250.0],
                "close": [151.0, 152.0, 251.0, 252.0],
                "volume": [1000000, 1100000, 800000, 850000],
            }
        )

    @patch("extensions.intraday_ml.experiments.intraday_ml_load_bars")
    def test_load_base_data(self, mock_load_bars):
        """Test base data loading."""
        test_bars = self._create_test_bars()
        mock_load_bars.return_value = test_bars

        config = self._create_test_config()
        result = _load_base_data(config)

        assert "bars" in result
        assert len(result["bars"]) == len(test_bars)
        mock_load_bars.assert_called_once_with(
            symbols=config["data"]["symbols"],
            dates=config["data"]["dates"],
            gold_root=config["data"]["gold_root"],
            family=config["data"]["family"],
        )

    @patch("extensions.intraday_ml.experiments.intraday_ml_get_data_hash")
    @patch("extensions.intraday_ml.experiments.intraday_ml_get_features_hash")
    @patch("extensions.intraday_ml.experiments.intraday_ml_get_screener_hash")
    @patch("extensions.intraday_ml.experiments.intraday_ml_apply_features")
    @patch("extensions.intraday_ml.experiments.intraday_ml_screen_universe")
    def test_compute_base_hashes(
        self,
        mock_screen,
        mock_features,
        mock_screener_hash,
        mock_features_hash,
        mock_data_hash,
    ):
        """Test base hash computation."""
        test_bars = self._create_test_bars()
        base_data = {"bars": test_bars}
        config = self._create_test_config()

        # Mock hash functions
        mock_data_hash.return_value = "bars_hash_123"
        mock_features_hash.return_value = "features_hash_456"
        mock_screener_hash.return_value = "screener_hash_789"
        mock_features.return_value = test_bars.copy()
        mock_screen.return_value = pd.DataFrame({"symbol": ["AAPL"]})

        result = _compute_base_hashes(base_data, config)

        assert result["bars_hash"] == "bars_hash_123"
        assert result["features_hash"] == "features_hash_456"
        assert result["screener_hash"] == "screener_hash_789"
        assert "config_hash" in result

    def test_generate_signals(self):
        """Test signal generation."""
        test_bars = self._create_test_bars()

        # Add VWAP for signal generation
        test_bars["vwap"] = test_bars["close"]  # Simple VWAP
        test_bars["deviation"] = (test_bars["close"] - test_bars["vwap"]) / test_bars[
            "vwap"
        ]

        screened_universe = pd.DataFrame({"symbol": ["AAPL", "MSFT"]})
        config = self._create_test_config()

        signals = _generate_signals(test_bars, screened_universe, config)

        assert isinstance(signals, pd.DataFrame)
        if not signals.empty:
            required_cols = ["ts", "symbol", "side", "close", "vwap", "deviation"]
            for col in required_cols:
                assert col in signals.columns
            assert signals["side"].isin(["BUY", "SELL"]).all()

    def test_deep_merge_configs(self):
        """Test configuration deep merge."""
        base = {
            "level1": {"level2": {"value": "base"}},
            "list": [1, 2, 3],
            "simple": "base_value",
        }

        overlay = {
            "level1": {"level2": {"new_value": "overlay"}},
            "list": [4, 5],
            "new_key": "overlay_value",
        }

        result = _deep_merge_configs(base, overlay)

        assert result["level1"]["level2"]["value"] == "base"
        assert result["level1"]["level2"]["new_value"] == "overlay"
        assert result["list"] == [4, 5]  # Simple replacement
        assert result["simple"] == "base_value"
        assert result["new_key"] == "overlay_value"

    def test_hash_config(self):
        """Test configuration hashing."""
        config = {"key1": "value1", "key2": 42}
        result = _hash_config(config)

        assert isinstance(result, str)
        assert len(result) > 0

    @patch("extensions.intraday_ml.experiments._run_single_pipeline")
    @patch("extensions.intraday_ml.experiments._compute_base_hashes")
    @patch("extensions.intraday_ml.experiments._load_base_data")
    def test_run_entry_ab_experiment(self, mock_load_data, mock_hashes, mock_pipeline):
        """Test full A/B experiment execution."""
        # Set up mocks
        test_bars = self._create_test_bars()
        mock_load_data.return_value = {"bars": test_bars}
        mock_hashes.return_value = {
            "bars_hash": "test_bars",
            "features_hash": "test_features",
            "screener_hash": "test_screener",
            "config_hash": "test_config",
        }
        mock_pipeline.return_value = {
            "metrics": {"trades": 5, "win_rate": 0.6},
            "variant_dir": "/tmp/variant_test",
            "checksum": "test_checksum",
        }

        # Create config files
        base_config = self._create_test_config()
        base_config_path = self.temp_path / "base_config.yaml"
        with open(base_config_path, "w") as f:
            yaml.dump(base_config, f)

        variant_config = {"policy": {"deviation_threshold": 0.03}}
        variant_path = self.temp_path / "variant.yaml"
        with open(variant_path, "w") as f:
            yaml.dump(variant_config, f)

        # Run experiment
        result = run_entry_ab_experiment(
            base_config_path=str(base_config_path),
            variant_paths=[str(variant_path)],
            experiment_name="test_experiment",
        )

        # Verify results
        assert "experiment_id" in result
        assert "variants" in result
        assert "checksums" in result
        assert result["experiment_name"] == "test_experiment"

        # Verify experiment directory created
        exp_dir = pathlib.Path("experiments/intraday_ml/test_experiment")
        assert exp_dir.exists()

        # Verify manifest created
        manifest_path = exp_dir / "manifest.json"
        assert manifest_path.exists()

        with open(manifest_path) as f:
            manifest = json.load(f)
        assert manifest["experiment_name"] == "test_experiment"

        # Clean up
        import shutil

        shutil.rmtree("experiments")

    def test_validate_fairness_success(self):
        """Test successful fairness validation."""
        # Create experiment directory structure
        exp_dir = self.temp_path / "test_experiment"
        exp_dir.mkdir()

        # Create manifest
        manifest = {
            "experiment_id": "test_id",
            "base_hashes": {"bars_hash": "test"},
            "checksum_validation": {"fair": True},
        }
        with open(exp_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        # Create inputs checksum
        inputs_checksum = {
            "bars_norm_hash": "test",
            "features_hash": "test",
            "sip_hash": "test",
            "config_hash": "test",
            "seed": 42,
        }
        with open(exp_dir / "inputs_checksum.json", "w") as f:
            json.dump(inputs_checksum, f)

        result = validate_fairness(str(exp_dir))

        assert result["valid"] is True
        assert "checksums" in result

    def test_validate_fairness_missing_files(self):
        """Test fairness validation with missing files."""
        exp_dir = self.temp_path / "empty_experiment"
        exp_dir.mkdir()

        result = validate_fairness(str(exp_dir))

        assert result["valid"] is False
        assert "manifest.json not found" in result["issues"]

    def test_validate_fairness_invalid_manifest(self):
        """Test fairness validation with invalid manifest."""
        exp_dir = self.temp_path / "invalid_experiment"
        exp_dir.mkdir()

        # Create invalid manifest
        manifest = {"incomplete": "data"}
        with open(exp_dir / "manifest.json", "w") as f:
            json.dump(manifest, f)

        result = validate_fairness(str(exp_dir))

        assert result["valid"] is False
        assert result["issues"]  # Check that there are some issues


class TestPipelineExecution:
    """Test individual pipeline execution."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()

    def teardown_method(self):
        """Clean up test environment."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def _create_test_pipeline_data(self):
        """Create test data for pipeline execution."""
        bars = pd.DataFrame(
            {
                "ts": [1704230400000000000, 1704230460000000000] * 2,
                "symbol": ["AAPL", "AAPL", "MSFT", "MSFT"],
                "open": [150.0, 151.0, 250.0, 251.0],
                "high": [152.0, 153.0, 252.0, 253.0],
                "low": [149.0, 150.0, 249.0, 250.0],
                "close": [151.0, 152.0, 251.0, 252.0],
                "volume": [1000000, 1100000, 800000, 850000],
            }
        )

        base_data = {"bars": bars}
        config = {
            "features": {"feature_pack": "core_basics"},
            "screener": {"top_n": 2},
            "policy": {"deviation_threshold": 0.02},
            "risk": {"max_risk_frac": 0.02},
            "backtest": {"initial_cash": 1000000.0},
        }

        return base_data, config

    @patch("extensions.intraday_ml.experiments.intraday_ml_run_backtest")
    @patch("extensions.intraday_ml.experiments.intraday_ml_size_orders")
    @patch("extensions.intraday_ml.experiments.intraday_ml_screen_universe")
    @patch("extensions.intraday_ml.experiments.intraday_ml_apply_features")
    def test_run_single_pipeline(
        self, mock_features, mock_screen, mock_risk, mock_backtest
    ):
        """Test single variant pipeline execution."""
        base_data, config = self._create_test_pipeline_data()

        # Set up mocks
        mock_features.return_value = base_data["bars"].copy()
        mock_screen.return_value = pd.DataFrame({"symbol": ["AAPL"]})
        mock_risk.return_value = pd.DataFrame(
            {
                "ts": [1704230400000000000],
                "symbol": ["AAPL"],
                "side": ["BUY"],
                "qty": [100],
            }
        )
        mock_backtest.return_value = {
            "metrics": {"trades": 1, "win_rate": 1.0},
            "signals": pd.DataFrame(),
            "orders": pd.DataFrame(),
            "fills": pd.DataFrame(),
            "positions": pd.DataFrame(),
            "equity": pd.DataFrame(),
            "trades": pd.DataFrame(),
            "risk_rejects": pd.DataFrame(),
            "allocation_log": pd.DataFrame(),
        }

        exp_dir = pathlib.Path(self.temp_dir) / "test_experiment"
        exp_dir.mkdir()

        result = _run_single_pipeline(
            base_data=base_data,
            config=config,
            variant_name="test_variant",
            exp_dir=exp_dir,
            seed=42,
        )

        assert "metrics" in result
        assert "variant_dir" in result
        assert "checksum" in result
        assert result["metrics"]["trades"] == 1

        # Verify artifacts were written
        variant_dir = exp_dir / "variant_test_variant"
        assert variant_dir.exists()
        assert (variant_dir / "metrics.json").exists()


if __name__ == "__main__":
    pytest.main([__file__])
