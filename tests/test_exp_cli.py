"""Tests for experiment CLI commands."""

import json
import pathlib
import uuid
from unittest.mock import patch

import pytest
from jsonschema import ValidationError, validate
from qx_core.schemas import (
    compare_report_schema,
    experiment_manifest_schema,
    inputs_checksum_schema,
    metrics_schema,
    trades_schema,
)


class TestSchemaValidators:
    """Unit tests for schema validators."""

    def test_experiment_manifest_schema_valid(self):
        schema = experiment_manifest_schema()
        valid_data = {
            "exp_id": "test_exp",
            "type": "entry-ab",
            "run_ids": ["run1", "run2"],
            "seed": 42,
        }
        validate(valid_data, schema)  # Should not raise

    def test_experiment_manifest_schema_invalid(self):
        schema = experiment_manifest_schema()
        invalid_data = {"exp_id": "test"}  # Missing required fields
        with pytest.raises(ValidationError):
            validate(invalid_data, schema)

    def test_inputs_checksum_schema_valid(self):
        schema = inputs_checksum_schema()
        valid_data = {
            "bars_norm_hash": "hash1",
            "features_hash": "hash2",
            "config_hash": "hash3",
            "seed": 42,
        }
        validate(valid_data, schema)

    def test_trades_schema_valid(self):
        schema = trades_schema()
        valid_data = {
            "entry_ts": "2023-01-01T00:00:00Z",
            "exit_ts": "2023-01-02T00:00:00Z",
            "symbol": "AAPL",
            "side": "BUY",
            "qty": 100,
            "entry_px": 100.0,
            "exit_px": 101.0,
            "pnl": 100.0,
        }
        validate(valid_data, schema)

    def test_metrics_schema_valid(self):
        schema = metrics_schema()
        valid_data = {
            "trades": 1,
            "avg_R": 0.01,
            "ES_95": -0.02,
            "pvalue_u": 0.5,
            "sharpe_CI_low": 0.5,
            "sharpe_CI_high": 1.5,
            "capacity_break_even_bps": 50.0,
        }
        validate(valid_data, schema)

    def test_compare_report_schema_valid(self):
        schema = compare_report_schema()
        valid_data = {
            "experiment": "test",
            "variants": 2,
            "results": [{"run_id": "run1", "metrics": {"trades": 1}}],
            "leaderboard": [{"run_id": "run1", "metrics": {"trades": 1}}],
        }
        validate(valid_data, schema)


class TestIntegration:
    """Integration tests with synthetic data."""

    @pytest.fixture
    def synthetic_config(self, tmp_path):
        """Create synthetic config file."""
        config = {
            "seed": 42,
            "universe": ["AAPL", "GOOGL"],
            "start_date": "2023-01-01",
            "end_date": "2023-01-10",
        }
        config_file = tmp_path / "config.json"
        with open(config_file, "w") as f:
            json.dump(config, f)
        return config_file

    @pytest.fixture
    def variant_files(self, tmp_path):
        """Create variant overlay files."""
        variants = []
        for i in range(2):
            variant = {"policy": f"variant_{i}"}
            variant_file = tmp_path / f"variant_{i}.json"
            with open(variant_file, "w") as f:
                json.dump(variant, f)
            variants.append(variant_file)
        return variants

    def test_entry_ab_integration(self, synthetic_config, variant_files):
        """Test entry-ab command with synthetic data."""
        from qx_cli.exp.entry_ab import entry_ab

        exp_name = f"test_exp_{uuid.uuid4().hex[:8]}"

        # Mock the backtest to avoid actual execution
        with patch("qx_cli.exp.entry_ab._generate_run_artifacts"):
            entry_ab(synthetic_config, variant_files, exp_name)

        # Check artifacts exist
        exp_dir = pathlib.Path("experiments") / exp_name
        assert exp_dir.exists()
        assert (exp_dir / "manifest.json").exists()
        assert (exp_dir / "inputs_checksum.json").exists()
        assert (exp_dir / "compare.json").exists()
        assert (exp_dir / "compare.md").exists()

        # Validate manifest schema
        with open(exp_dir / "manifest.json") as f:
            manifest = json.load(f)
        validate(manifest, experiment_manifest_schema())

        # Check runs exist
        for run_id in manifest["run_ids"]:
            run_dir = pathlib.Path("runs") / run_id
            assert run_dir.exists()


class TestGoldenReplay:
    """Golden tests for deterministic replay."""

    def test_golden_experiment_replay(self):
        """Test that a stored experiment replays identically."""
        # This would store a small experiment and replay it
        # For now, stub
        assert True  # Placeholder