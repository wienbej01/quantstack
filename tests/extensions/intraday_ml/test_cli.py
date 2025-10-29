"""Unit tests for intraday ML CLI interface."""

import json
import pathlib
import tempfile
import yaml
from unittest.mock import Mock, patch

import pytest
import typer
from typer.testing import CliRunner

from extensions.intraday_ml.cli import app, main


class TestCLIInterface:
    """Test CLI interface functionality."""

    def setup_method(self):
        """Set up test environment."""
        self.runner = CliRunner()

    def test_version_command(self):
        """Test version command."""
        result = self.runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "Intraday ML Extension" in result.stdout

    def test_entry_ab_missing_config(self):
        """Test entry-ab command with missing config file."""
        result = self.runner.invoke(app, [
            "entry-ab",
            "--cfg", "/nonexistent/config.yaml",
            "--variants", "nonexistent/*.yaml",
            "--name", "test"
        ])
        assert result.exit_code == 1
        assert "Config file not found" in result.stdout

    def test_entry_ab_missing_variants(self):
        """Test entry-ab command with missing variant files."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            tmp.write(b"data: test")
            tmp_path = tmp.name

        try:
            result = self.runner.invoke(app, [
                "entry-ab",
                "--cfg", tmp_path,
                "--variants", "/nonexistent/*.yaml",
                "--name", "test"
            ])
            assert result.exit_code == 1
            assert "No variant files found" in result.stdout
        finally:
            pathlib.Path(tmp_path).unlink()

    @patch('extensions.intraday_ml.cli.orchestration.ABOrchestrator')
    def test_entry_ab_success(self, mock_orchestrator_class):
        """Test successful entry-ab execution."""
        # Mock orchestrator
        mock_orchestrator = Mock()
        mock_orchestrator.run_experiment.return_value = {
            "experiment_id": "test-id",
            "run_results": [
                {
                    "run_id": "run_1",
                    "metrics": {
                        "trading": {"total_trades": 10},
                        "performance": {"win_rate": 0.6, "total_return": 0.05}
                    }
                }
            ]
        }
        mock_orchestrator_class.return_value = mock_orchestrator

        # Create temporary config and variant files
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = pathlib.Path(tmp_dir)

            # Create base config
            config_file = tmp_path / "config.yaml"
            config_file.write_text("""
data:
  symbols: ["AAPL"]
  dates: ["2024-01-02"]
""")

            # Create variant files
            variant_dir = tmp_path / "variants"
            variant_dir.mkdir()
            variant_file = variant_dir / "variant.yaml"
            variant_file.write_text("""
policy:
  deviation_threshold: 0.02
""")

            result = self.runner.invoke(app, [
                "entry-ab",
                "--cfg", str(config_file),
                "--variants", str(variant_dir / "*.yaml"),
                "--name", "test-experiment"
            ])

            assert result.exit_code == 0
            assert "Experiment Results: test-experiment" in result.stdout
            mock_orchestrator.run_experiment.assert_called_once()

    @patch('extensions.intraday_ml.cli.run_entry_ab_experiment')
    def test_entry_ab_dry_run(self, mock_run_experiment):
        """Test entry-ab dry run mode."""
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as tmp:
            tmp.write(b"data: test")
            tmp_path = tmp.name

        try:
            result = self.runner.invoke(app, [
                "entry-ab",
                "--cfg", tmp_path,
                "--variants", tmp_path,
                "--name", "test",
                "--dry-run"
            ])
            assert result.exit_code == 0
            assert "DRY RUN MODE" in result.stdout
            mock_run_experiment.assert_not_called()
        finally:
            pathlib.Path(tmp_path).unlink()

    @patch('extensions.intraday_ml.cli.validate_fairness')
    def test_validate_command_success(self, mock_validate):
        """Test validate command success."""
        mock_validate.return_value = {"valid": True}

        with tempfile.TemporaryDirectory() as tmp_dir:
            exp_dir = pathlib.Path(tmp_dir) / "test_experiment"
            exp_dir.mkdir()

            result = self.runner.invoke(app, [
                "validate",
                "--exp-dir", str(exp_dir)
            ])

            assert result.exit_code == 0
            assert "validation passed" in result.stdout

    def test_validate_command_missing_dir(self):
        """Test validate command with missing directory."""
        result = self.runner.invoke(app, [
            "validate",
            "--exp-dir", "/nonexistent/directory"
        ])
        assert result.exit_code == 1
        assert "Experiment directory not found" in result.stdout






if __name__ == "__main__":
    pytest.main([__file__])