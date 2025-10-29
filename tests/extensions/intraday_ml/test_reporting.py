"""Unit tests for intraday ML reporting functionality."""

import json
import pathlib
import tempfile
from unittest.mock import Mock, patch

import numpy as np
import pandas as pd
import pytest

from extensions.intraday_ml.reporting import (
    ArtifactReader,
    MetricsCalculator,
    ABComparator,
    generate_experiment_report,
    read_single_run_metrics,
)


class TestArtifactReader:
    """Test artifact reading functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_test_artifacts(self, variant_name: str):
        """Create test artifacts for a variant."""
        variant_dir = self.temp_path / f"variant_{variant_name}"
        variant_dir.mkdir(exist_ok=True)

        # Create test DataFrames
        signals_df = pd.DataFrame({
            "ts": [1704230400000000000, 1704230460000000000],
            "symbol": ["AAPL", "MSFT"],
            "side": ["BUY", "SELL"],
            "close": [150.0, 250.0]
        })
        signals_df.to_parquet(variant_dir / "signals.parquet")

        orders_df = pd.DataFrame({
            "ts": [1704230400000000000, 1704230460000000000],
            "symbol": ["AAPL", "MSFT"],
            "side": ["BUY", "SELL"],
            "qty": [100, 50]
        })
        orders_df.to_parquet(variant_dir / "orders.parquet")

        trades_df = pd.DataFrame({
            "ts": [1704230400000000000, 1704230460000000000],
            "symbol": ["AAPL", "MSFT"],
            "side": ["BUY", "SELL"],
            "pnl": [10.0, -5.0],
            "stop_dist_ps": [2.0, 2.5],
            "qty": [100, 50]
        })
        trades_df.to_parquet(variant_dir / "trades.parquet")

        fills_df = pd.DataFrame({
            "ts": [1704230400000000000, 1704230460000000000],
            "symbol": ["AAPL", "MSFT"],
            "qty": [100, 50],
            "fees": [1.0, 0.5],
            "slippage_est": [0.01, 0.02]
        })
        fills_df.to_parquet(variant_dir / "fills.parquet")

        # Create metrics JSON
        metrics = {
            "trades": 2,
            "win_rate": 0.5,
            "total_pnl": 5.0,
            "avg_R": 2.5
        }
        with open(variant_dir / "metrics.json", 'w') as f:
            json.dump(metrics, f)

        # Create empty artifacts for missing ones
        for artifact_name in ["positions", "equity", "risk_rejects", "allocation_log"]:
            pd.DataFrame().to_parquet(variant_dir / f"{artifact_name}.parquet")

        return variant_dir

    def _create_test_experiment_structure(self):
        """Create complete experiment directory structure."""
        # Create variants
        self._create_test_artifacts("fast")
        self._create_test_artifacts("slow")

        # Create manifest
        manifest = {
            "experiment_id": "test-exp-123",
            "experiment_name": "test_experiment",
            "timestamp": "2024-01-15T10:00:00Z",
            "base_hashes": {
                "bars_hash": "test_bars",
                "features_hash": "test_features",
                "screener_hash": "test_screener",
                "config_hash": "test_config"
            },
            "checksum_validation": {"fair": True},
            "results_summary": {
                "fast": {"trades": 2, "win_rate": 0.6, "total_pnl": 6.0},
                "slow": {"trades": 1, "win_rate": 1.0, "total_pnl": 8.0}
            }
        }
        with open(self.temp_path / "manifest.json", 'w') as f:
            json.dump(manifest, f)

        # Create inputs checksum
        inputs_checksum = {
            "bars_norm_hash": "test_bars",
            "features_hash": "test_features",
            "sip_hash": "test_screener",
            "config_hash": "test_config",
            "seed": 42,
            "experiment_id": "test-exp-123"
        }
        with open(self.temp_path / "inputs_checksum.json", 'w') as f:
            json.dump(inputs_checksum, f)

    def test_init_missing_directory(self):
        """Test initialization with missing directory."""
        with pytest.raises(ValueError, match="Experiment directory not found"):
            ArtifactReader("/nonexistent/directory")

    def test_read_variant_artifacts(self):
        """Test reading variant artifacts."""
        self._create_test_artifacts("test_variant")
        reader = ArtifactReader(str(self.temp_path))

        artifacts = reader.read_variant_artifacts("test_variant")

        # Check that all expected artifacts are present
        expected_artifacts = [
            "signals", "orders", "fills", "positions",
            "equity", "trades", "risk_rejects", "allocation_log", "metrics"
        ]
        for artifact_name in expected_artifacts:
            assert artifact_name in artifacts

        # Check specific artifact content
        assert len(artifacts["signals"]) == 2
        assert len(artifacts["trades"]) == 2
        assert artifacts["metrics"]["trades"] == 2
        assert artifacts["metrics"]["total_pnl"] == 5.0

    def test_read_variant_missing_directory(self):
        """Test reading variant with missing directory."""
        reader = ArtifactReader(str(self.temp_path))

        with pytest.raises(ValueError, match="Variant directory not found"):
            reader.read_variant_artifacts("nonexistent_variant")

    def test_read_manifest(self):
        """Test reading experiment manifest."""
        self._create_test_experiment_structure()
        reader = ArtifactReader(str(self.temp_path))

        manifest = reader.read_manifest()

        assert manifest["experiment_id"] == "test-exp-123"
        assert manifest["experiment_name"] == "test_experiment"
        assert manifest["checksum_validation"]["fair"] is True

    def test_read_inputs_checksum(self):
        """Test reading inputs checksum."""
        self._create_test_experiment_structure()
        reader = ArtifactReader(str(self.temp_path))

        checksum = reader.read_inputs_checksum()

        assert checksum["seed"] == 42
        assert checksum["experiment_id"] == "test-exp-123"
        assert checksum["bars_norm_hash"] == "test_bars"


class TestMetricsCalculator:
    """Test metrics calculation functionality."""

    def test_calculate_basic_metrics_with_trades(self):
        """Test basic metrics calculation with trades data."""
        trades_df = pd.DataFrame({
            "pnl": [10.0, -5.0, 15.0, -8.0, 12.0],
            "qty": [100, 50, 200, 75, 150]
        })

        artifacts = {
            "trades": trades_df,
            "signals": pd.DataFrame({"ts": [1, 2, 3, 4, 5]}),
            "orders": pd.DataFrame({"ts": [1, 2, 3]}),
            "fills": pd.DataFrame({"ts": [1, 2, 3, 4]}),
        }

        metrics = MetricsCalculator.calculate_basic_metrics(artifacts)

        assert metrics["trades"] == 5
        assert metrics["win_rate"] == 0.6  # 3 wins out of 5
        assert metrics["total_pnl"] == 24.0
        assert metrics["avg_R"] == 4.8
        assert metrics["signals_count"] == 5
        assert metrics["orders_count"] == 3
        assert metrics["fills_count"] == 4

    def test_calculate_basic_metrics_empty_trades(self):
        """Test basic metrics calculation with empty trades."""
        artifacts = {
            "trades": pd.DataFrame(),
            "signals": pd.DataFrame(),
            "orders": pd.DataFrame(),
        }

        metrics = MetricsCalculator.calculate_basic_metrics(artifacts)

        assert metrics["trades"] == 0
        assert metrics["win_rate"] == 0.0
        assert metrics["total_pnl"] == 0.0
        assert metrics["avg_R"] == 0.0

    def test_calculate_basic_metrics_with_existing_metrics(self):
        """Test basic metrics calculation when metrics already exist."""
        existing_metrics = {
            "trades": 10,
            "win_rate": 0.7,
            "total_pnl": 100.0
        }
        artifacts = {"metrics": existing_metrics}

        metrics = MetricsCalculator.calculate_basic_metrics(artifacts)

        # Should return existing metrics unchanged
        assert metrics == existing_metrics

    def test_calculate_risk_metrics(self):
        """Test risk metrics calculation."""
        trades_df = pd.DataFrame({
            "stop_dist_ps": [2.0, 2.5, 1.8],
            "qty": [100, 50, 200]
        })
        risk_rejects_df = pd.DataFrame({"ts": [1, 2, 3]})

        artifacts = {
            "trades": trades_df,
            "risk_rejects": risk_rejects_df
        }

        metrics = MetricsCalculator.calculate_risk_metrics(artifacts)

        assert metrics["risk_rejections"] == 3
        assert metrics["avg_stop_distance"] == pytest.approx((2.0 + 2.5 + 1.8) / 3)
        assert metrics["max_position_size"] == 200

    def test_calculate_execution_metrics(self):
        """Test execution metrics calculation."""
        orders_df = pd.DataFrame({"ts": [1, 2, 3, 4]})
        fills_df = pd.DataFrame({
            "ts": [1, 2, 3],
            "fees": [1.0, 0.5, 1.2],
            "slippage_est": [0.01, 0.02, 0.015]
        })

        artifacts = {
            "orders": orders_df,
            "fills": fills_df
        }

        metrics = MetricsCalculator.calculate_execution_metrics(artifacts)

        assert metrics["order_fill_rate"] == 0.75  # 3 fills out of 4 orders
        assert metrics["avg_slippage"] == pytest.approx((0.01 + 0.02 + 0.015) / 3)
        assert metrics["total_fees"] == 2.7


class TestABComparator:
    """Test A/B comparison functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)
        self._create_test_experiment_structure()

    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_test_experiment_structure(self):
        """Create test experiment structure."""
        # Create variant directories with different performance
        for variant_name, metrics in [
            ("fast", {"trades": 10, "win_rate": 0.6, "total_pnl": 100.0, "avg_R": 10.0}),
            ("slow", {"trades": 5, "win_rate": 0.8, "total_pnl": 80.0, "avg_R": 16.0})
        ]:
            variant_dir = self.temp_path / f"variant_{variant_name}"
            variant_dir.mkdir(exist_ok=True)

            # Create minimal trades data
            trades_df = pd.DataFrame({
                "pnl": [10.0] * metrics["trades"],
                "stop_dist_ps": [2.0] * metrics["trades"],
                "qty": [100] * metrics["trades"]
            })
            trades_df.to_parquet(variant_dir / "trades.parquet")

            # Create metrics JSON
            with open(variant_dir / "metrics.json", 'w') as f:
                json.dump(metrics, f)

            # Create empty artifacts
            for artifact_name in ["signals", "orders", "fills", "positions", "equity", "risk_rejects", "allocation_log"]:
                pd.DataFrame().to_parquet(variant_dir / f"{artifact_name}.parquet")

        # Create manifest
        manifest = {
            "experiment_id": "test-comparison",
            "experiment_name": "test_comparison",
            "results_summary": {"fast": {}, "slow": {}}
        }
        with open(self.temp_path / "manifest.json", 'w') as f:
            json.dump(manifest, f)

        # Create inputs checksum
        inputs_checksum = {
            "bars_norm_hash": "test",
            "features_hash": "test",
            "sip_hash": "test",
            "config_hash": "test",
            "seed": 42
        }
        with open(self.temp_path / "inputs_checksum.json", 'w') as f:
            json.dump(inputs_checksum, f)

    def test_compare_variants(self):
        """Test variant comparison."""
        comparator = ABComparator(str(self.temp_path))

        comparison_df = comparator.compare_variants(["fast", "slow"])

        assert len(comparison_df) == 2
        assert "fast" in comparison_df.index
        assert "slow" in comparison_df.index
        assert comparison_df.loc["fast", "trades"] == 10
        assert comparison_df.loc["slow", "trades"] == 5

    def test_compare_variants_missing_variant(self):
        """Test comparison with missing variant."""
        comparator = ABComparator(str(self.temp_path))

        # Should handle missing variant gracefully
        comparison_df = comparator.compare_variants(["fast", "nonexistent"])

        assert len(comparison_df) == 1
        assert "fast" in comparison_df.index
        assert "nonexistent" not in comparison_df.index

    def test_calculate_differences(self):
        """Test difference calculation."""
        comparator = ABComparator(str(self.temp_path))
        comparison_df = comparator.compare_variants(["fast", "slow"])

        diff_df = comparator.calculate_differences(comparison_df, "slow")

        assert "trades_diff" in diff_df.columns
        assert "trades_pct_change" in diff_df.columns
        # Fast should have 5 more trades than slow (10 - 5)
        assert diff_df.loc["fast", "trades_diff"] == 5.0
        # 100% more trades than slow (5/5 * 100)
        assert diff_df.loc["fast", "trades_pct_change"] == 100.0

    def test_calculate_differences_missing_baseline(self):
        """Test difference calculation with missing baseline."""
        comparator = ABComparator(str(self.temp_path))
        comparison_df = comparator.compare_variants(["fast", "slow"])

        with pytest.raises(ValueError, match="Baseline variant 'missing' not found"):
            comparator.calculate_differences(comparison_df, "missing")

    def test_generate_summary_table(self):
        """Test summary table generation."""
        comparator = ABComparator(str(self.temp_path))
        comparison_df = comparator.compare_variants(["fast", "slow"])

        table = comparator.generate_summary_table(comparison_df)

        assert table is not None
        # Should have header row plus two variant rows
        assert len(table.rows) == 2


class TestExperimentReport:
    """Test experiment report generation."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_minimal_experiment(self):
        """Create minimal experiment structure."""
        exp_dir = self.temp_path / "test_experiment"
        exp_dir.mkdir()

        # Create manifest
        manifest = {
            "experiment_id": "test-report",
            "experiment_name": "test_report",
            "timestamp": "2024-01-15T10:00:00Z",
            "base_hashes": {"config_hash": "test"},
            "checksum_validation": {"fair": True},
            "results_summary": {"variant1": {"trades": 5}}
        }
        with open(exp_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f)

        # Create inputs checksum
        inputs_checksum = {
            "bars_norm_hash": "test",
            "features_hash": "test",
            "sip_hash": "test",
            "config_hash": "test",
            "seed": 42
        }
        with open(exp_dir / "inputs_checksum.json", 'w') as f:
            json.dump(inputs_checksum, f)

        # Create variant
        variant_dir = exp_dir / "variant_variant1"
        variant_dir.mkdir()
        with open(variant_dir / "metrics.json", 'w') as f:
            json.dump({"trades": 5, "win_rate": 0.6, "total_pnl": 50.0}, f)

        return str(exp_dir)

    def test_generate_experiment_report_console(self):
        """Test experiment report generation in console format."""
        exp_dir = self._create_minimal_experiment()

        # Should not raise exception and return None for console output
        result = generate_experiment_report(exp_dir, output_format="console")
        assert result is None

    def test_generate_experiment_report_dict(self):
        """Test experiment report generation in dict format."""
        exp_dir = self._create_minimal_experiment()

        result = generate_experiment_report(exp_dir, output_format="dict")

        assert isinstance(result, dict)
        assert "experiment_info" in result
        assert "checksum_validation" in result
        assert "inputs_checksum" in result
        assert "variant_comparison" in result
        assert "summary_metrics" in result

    def test_generate_experiment_report_json(self):
        """Test experiment report generation in JSON format."""
        exp_dir = self._create_minimal_experiment()

        result = generate_experiment_report(exp_dir, output_format="json")

        assert isinstance(result, dict)  # JSON returns dict, serialization handled by caller

    def test_generate_experiment_report_missing_dir(self):
        """Test report generation with missing directory."""
        with pytest.raises(ValueError, match="Experiment directory not found"):
            generate_experiment_report("/nonexistent/directory")

    def test_generate_experiment_report_no_variants(self):
        """Test report generation with no variants."""
        exp_dir = pathlib.Path(self.temp_dir) / "empty_experiment"
        exp_dir.mkdir()

        # Create minimal manifest without variants
        manifest = {"experiment_id": "empty", "results_summary": {}}
        with open(exp_dir / "manifest.json", 'w') as f:
            json.dump(manifest, f)

        with pytest.raises(ValueError, match="No variants found"):
            generate_experiment_report(str(exp_dir))


class TestSingleRunMetrics:
    """Test single run metrics reading."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_read_single_run_metrics_from_json(self):
        """Test reading metrics from metrics.json."""
        run_dir = self.temp_path / "test_run"
        run_dir.mkdir()

        metrics = {
            "trades": 8,
            "win_rate": 0.75,
            "total_pnl": 120.0,
            "avg_R": 15.0
        }
        with open(run_dir / "metrics.json", 'w') as f:
            json.dump(metrics, f)

        result = read_single_run_metrics(str(run_dir))

        assert result == metrics

    def test_read_single_run_metrics_from_artifacts(self):
        """Test reading metrics calculated from artifacts."""
        run_dir = self.temp_path / "test_run"
        run_dir.mkdir()

        # Create trades artifact
        trades_df = pd.DataFrame({
            "pnl": [10.0, -5.0, 15.0, -3.0],
            "stop_dist_ps": [2.0, 2.5, 1.8, 2.2],
            "qty": [100, 50, 200, 75]
        })
        trades_df.to_parquet(run_dir / "trades.parquet")

        # Create other artifacts
        signals_df = pd.DataFrame({"ts": [1, 2, 3, 4]})
        signals_df.to_parquet(run_dir / "signals.parquet")

        result = read_single_run_metrics(str(run_dir))

        assert result["trades"] == 4
        assert result["win_rate"] == 0.75  # 3 wins out of 4
        assert result["total_pnl"] == 17.0
        assert result["signals_count"] == 4

    def test_read_single_run_metrics_missing_dir(self):
        """Test reading metrics with missing directory."""
        with pytest.raises(ValueError, match="Run directory not found"):
            read_single_run_metrics("/nonexistent/directory")

    def test_read_single_run_metrics_no_data(self):
        """Test reading metrics with no data."""
        run_dir = self.temp_path / "empty_run"
        run_dir.mkdir()

        result = read_single_run_metrics(str(run_dir))

        assert result["trades"] == 0
        assert result["win_rate"] == 0.0
        assert result["total_pnl"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__])