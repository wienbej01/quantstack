import json
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from extensions.intraday_ml_models.wrappers.backtest_runner import run as run_backtest
from extensions.intraday_ml_models.wrappers.metrics_consistency import (
    run_metrics_consistency_check,
)


@pytest.fixture
def setup_test_environment(tmp_path: Path) -> dict:
    """Sets up a test environment with synthetic data and configs."""
    # Create directories
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    features_dir = tmp_path / "features"
    features_dir.mkdir()
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    # Create synthetic features
    features_path = features_dir / "features.parquet"
    timestamps = pd.to_datetime(
        [
            "2024-01-09 15:55:00",
            "2024-01-09 15:56:00",
            "2024-01-10 09:30:00",
            "2024-01-10 09:31:00",
        ]
    )
    features_df = pd.DataFrame({"atr": [1.0, 1.0, 1.0, 1.0]}, index=timestamps)
    features_df.to_parquet(features_path)

    # Create configs
    policy_config = {
        "probability_threshold": 0.65,
        "expected_move_atr_lambda": 0.1,
        "cooldown_minutes": 5,
        "block_new_entries_after_et": "15:30",
        "min_bars_to_close": 2,
        "horizons_min": [30],
    }
    backtest_config = {
        "position_size": 1,
        "commission_per_order": 0.35,
        "slippage_bps": 0,
        "annualize": {"minute_bars_per_day": 390, "trading_days_per_year": 252},
        "equity": {"starting_equity": 100000.0},
        "timing": {
            "timezone": "America/New_York",
            "session_calendar": "XNYS",
            "eod_liquidation_time": "15:59:59",
        },
        "paths": {
            "model_dir": str(model_dir),
            "features": str(features_path),
            "labels": "",  # Not used
            "report_dir": str(report_dir),
        },
    }

    policy_config_path = tmp_path / "policy.yaml"
    with open(policy_config_path, "w") as f:
        json.dump(policy_config, f)

    backtest_config_path = tmp_path / "backtest.yaml"
    with open(backtest_config_path, "w") as f:
        json.dump(backtest_config, f)

    return {
        "policy_config_path": str(policy_config_path),
        "backtest_config_path": str(backtest_config_path),
        "report_dir": str(report_dir),
        "backtest_config": backtest_config,
    }


@patch("extensions.intraday_ml_models.wrappers.backtest_runner.load_model")
def test_runner_contract(mock_load_model, setup_test_environment):
    """Tests the I/O contract of the backtest runner and metrics consistency scripts."""
    # Arrange
    env = setup_test_environment

    class MockModel:
        def predict_proba(self, df):
            return pd.DataFrame({"prob_30": [0.7, 0.8, 0.9, 0.6]}, index=df.index)

    mock_load_model.return_value = MockModel()

    # Act: Run backtest
    run_backtest(env["policy_config_path"], env["backtest_config"])

    # Assert: Check outputs
    report_dir = Path(env["report_dir"])
    assert (report_dir / "trades.parquet").exists()
    assert (report_dir / "equity.parquet").exists()
    assert (report_dir / "run_meta.json").exists()

    trades_df = pd.read_parquet(report_dir / "trades.parquet")
    equity_df = pd.read_parquet(report_dir / "equity.parquet")
    with open(report_dir / "run_meta.json") as f:
        run_meta = json.load(f)

    assert not trades_df.empty
    assert not equity_df.empty
    assert run_meta["orders_submitted"] >= 1
    assert run_meta["orders_executed"] >= 1

    # Act: Run metrics consistency
    run_metrics_consistency_check(env["backtest_config"])


@patch("extensions.intraday_ml_models.wrappers.backtest_runner.load_model")
def test_no_orders_scenario(mock_load_model, setup_test_environment):
    """Tests that the backtest runner exits with a non-zero code if no orders are generated."""
    # Arrange
    env = setup_test_environment

    class MockModel:
        def predict_proba(self, df):
            return pd.DataFrame({"prob_30": [0.1, 0.2, 0.3, 0.4]}, index=df.index)

    mock_load_model.return_value = MockModel()

    # Act & Assert
    with pytest.raises(SystemExit) as e:
        run_backtest(env["policy_config_path"], env["backtest_config"])
    assert e.type == SystemExit
    assert e.value.code != 0
