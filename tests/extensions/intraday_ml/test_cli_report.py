"""Unit tests for intraday ML reporting CLI interface."""

import json
import pathlib
import tempfile
from unittest.mock import Mock, patch

import pytest
from typer.testing import CliRunner

from extensions.intraday_ml.cli_report import app


class TestReportingCLI:
    """Test reporting CLI interface functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_version_command(self):
        """Test version command."""
        result = self.runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Intraday ML Reporting" in result.stdout

    def test_experiment_command_missing_dir(self):
        """Test experiment command with missing directory."""
        result = self.runner.invoke(app, [
            "experiment",
            "--exp-dir", "/nonexistent/directory"
        ])
        assert result.exit_code == 1
        assert "Experiment directory not found" in result.stdout

    def test_run_metrics_command_missing_dir(self):
        """Test run-metrics command with missing directory."""
        result = self.runner.invoke(app, [
            "run-metrics",
            "--run-dir", "/nonexistent/directory"
        ])
        assert result.exit_code == 1
        assert "Run directory not found" in result.stdout

    def test_compare_command_missing_dirs(self):
        """Test compare command with missing directories."""
        result = self.runner.invoke(app, [
            "compare",
            "--baseline", "/nonexistent/baseline",
            "--variant", "/nonexistent/variant"
        ])
        assert result.exit_code == 1
        assert "Baseline directory not found" in result.stdout

    @patch('extensions.intraday_ml.cli_report.generate_experiment_report')
    def test_experiment_command_success(self, mock_generate_report):
        """Test successful experiment command."""
        # Mock report generation
        mock_generate_report.return_value = None  # Console format returns None

        with tempfile.TemporaryDirectory() as tmp_dir:
            exp_dir = pathlib.Path(tmp_dir) / "test_experiment"
            exp_dir.mkdir()

            result = self.runner.invoke(app, [
                "experiment",
                "--exp-dir", str(exp_dir),
                "--format", "console"
            ])

            assert result.exit_code == 0
            mock_generate_report.assert_called_once_with(str(exp_dir), "console")

    @patch('extensions.intraday_ml.cli_report.generate_experiment_report')
    def test_experiment_command_with_output_file(self, mock_generate_report):
        """Test experiment command with output file."""
        # Mock report generation
        mock_report_data = {
            "experiment_info": {"experiment_name": "test"},
            "summary_metrics": {"best_total_pnl": 100.0}
        }
        mock_generate_report.return_value = mock_report_data

        with tempfile.TemporaryDirectory() as tmp_dir:
            exp_dir = pathlib.Path(tmp_dir) / "test_experiment"
            exp_dir.mkdir()
            output_file = pathlib.Path(tmp_dir) / "output.json"

            result = self.runner.invoke(app, [
                "experiment",
                "--exp-dir", str(exp_dir),
                "--format", "json",
                "--output", str(output_file)
            ])

            assert result.exit_code == 0
            assert output_file.exists()
            mock_generate_report.assert_called_once_with(str(exp_dir), "json")

    @patch('extensions.intraday_ml.cli_report.read_single_run_metrics')
    def test_run_metrics_command_success(self, mock_read_metrics):
        """Test successful run-metrics command."""
        # Mock metrics reading
        mock_metrics = {
            "trades": 5,
            "win_rate": 0.6,
            "total_pnl": 75.0
        }
        mock_read_metrics.return_value = mock_metrics

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = pathlib.Path(tmp_dir) / "test_run"
            run_dir.mkdir()

            result = self.runner.invoke(app, [
                "run-metrics",
                "--run-dir", str(run_dir),
                "--format", "console"
            ])

            assert result.exit_code == 0
            mock_read_metrics.assert_called_once_with(str(run_dir))

    @patch('extensions.intraday_ml.cli_report.read_single_run_metrics')
    def test_run_metrics_command_with_output_file(self, mock_read_metrics):
        """Test run-metrics command with output file."""
        # Mock metrics reading
        mock_metrics = {
            "trades": 5,
            "win_rate": 0.6,
            "total_pnl": 75.0
        }
        mock_read_metrics.return_value = mock_metrics

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = pathlib.Path(tmp_dir) / "test_run"
            run_dir.mkdir()
            output_file = pathlib.Path(tmp_dir) / "metrics.json"

            result = self.runner.invoke(app, [
                "run-metrics",
                "--run-dir", str(run_dir),
                "--format", "json",
                "--output", str(output_file)
            ])

            assert result.exit_code == 0
            assert output_file.exists()
            mock_read_metrics.assert_called_once_with(str(run_dir))

    def test_compare_command_placeholder(self):
        """Test compare command (placeholder implementation)."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            baseline_dir = pathlib.Path(tmp_dir) / "baseline"
            variant_dir = pathlib.Path(tmp_dir) / "variant"
            baseline_dir.mkdir()
            variant_dir.mkdir()

            result = self.runner.invoke(app, [
                "compare",
                "--baseline", str(baseline_dir),
                "--variant", str(variant_dir)
            ])

            assert result.exit_code == 0
            assert "placeholder" in result.stdout.lower()

    @patch('extensions.intraday_ml.cli_report.generate_experiment_report')
    def test_experiment_command_error_handling(self, mock_generate_report):
        """Test experiment command error handling."""
        # Mock report generation to raise exception
        mock_generate_report.side_effect = Exception("Test error")

        with tempfile.TemporaryDirectory() as tmp_dir:
            exp_dir = pathlib.Path(tmp_dir) / "test_experiment"
            exp_dir.mkdir()

            result = self.runner.invoke(app, [
                "experiment",
                "--exp-dir", str(exp_dir)
            ])

            assert result.exit_code == 1
            assert "Report generation failed" in result.stdout

    @patch('extensions.intraday_ml.cli_report.read_single_run_metrics')
    def test_run_metrics_command_error_handling(self, mock_read_metrics):
        """Test run-metrics command error handling."""
        # Mock metrics reading to raise exception
        mock_read_metrics.side_effect = Exception("Test error")

        with tempfile.TemporaryDirectory() as tmp_dir:
            run_dir = pathlib.Path(tmp_dir) / "test_run"
            run_dir.mkdir()

            result = self.runner.invoke(app, [
                "run-metrics",
                "--run-dir", str(run_dir)
            ])

            assert result.exit_code == 1
            assert "Metrics generation failed" in result.stdout


class TestReportingCLIIntegration:
    """Integration tests for reporting CLI."""

    def setup_method(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.temp_path = pathlib.Path(self.temp_dir)

    def teardown_method(self):
        """Clean up test environment."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def _create_test_experiment_structure(self):
        """Create complete test experiment structure."""
        exp_dir = self.temp_path / "test_experiment"
        exp_dir.mkdir()

        # Create manifest
        manifest = {
            "experiment_id": "test-cli-exp",
            "experiment_name": "test_cli_experiment",
            "timestamp": "2024-01-15T10:00:00Z",
            "base_hashes": {
                "config_hash": "test_config"
            },
            "checksum_validation": {"fair": True},
            "results_summary": {
                "fast": {"trades": 10, "win_rate": 0.6, "total_pnl": 100.0},
                "slow": {"trades": 5, "win_rate": 0.8, "total_pnl": 80.0}
            }
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

        # Create variants
        for variant_name, metrics in manifest["results_summary"].items():
            variant_dir = exp_dir / f"variant_{variant_name}"
            variant_dir.mkdir()

            # Create metrics JSON
            with open(variant_dir / "metrics.json", 'w') as f:
                json.dump(metrics, f)

            # Create empty artifacts
            import pandas as pd
            for artifact_name in ["signals", "orders", "fills", "positions", "equity", "trades", "risk_rejects", "allocation_log"]:
                pd.DataFrame().to_parquet(variant_dir / f"{artifact_name}.parquet")

        return str(exp_dir)

    def test_experiment_command_end_to_end(self):
        """Test experiment command end-to-end with real data."""
        from extensions.intraday_ml.cli_report import generate_experiment_report

        exp_dir = self._create_test_experiment_structure()

        # Test console format
        result = generate_experiment_report(exp_dir, output_format="console")
        assert result is None

        # Test dict format
        result = generate_experiment_report(exp_dir, output_format="dict")
        assert isinstance(result, dict)
        assert "experiment_info" in result
        assert result["experiment_info"]["experiment_name"] == "test_cli_experiment"

    def test_run_metrics_command_end_to_end(self):
        """Test run-metrics command end-to-end with real data."""
        from extensions.intraday_ml.cli_report import read_single_run_metrics

        run_dir = self.temp_path / "test_run"
        run_dir.mkdir()

        # Create metrics JSON
        metrics = {
            "trades": 8,
            "win_rate": 0.75,
            "total_pnl": 120.0,
            "avg_R": 15.0,
            "risk_rejections": 2,
            "order_fill_rate": 0.9,
            "avg_slippage": 0.015,
            "total_fees": 8.5
        }
        with open(run_dir / "metrics.json", 'w') as f:
            json.dump(metrics, f)

        result = read_single_run_metrics(str(run_dir))
        assert result == metrics


if __name__ == "__main__":
    pytest.main([__file__])