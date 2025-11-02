#!/usr/bin/env python3
"""
Test the logical flow of the end-to-end train and backtest script.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import run_train_and_backtest


@pytest.fixture
def mock_dependencies():
    """Mock all slow external dependencies for the workflow script."""
    with (
        patch("run_train_and_backtest.load_bars") as mock_load_bars,
        patch("run_train_and_backtest.resample_data") as mock_resample_data,
        patch(
            "run_train_and_backtest.create_training_dataset"
        ) as mock_create_training_dataset,
        patch("run_train_and_backtest.LightGBMTrainer") as mock_trainer_class,
        patch("run_train_and_backtest.joblib.dump"),
        patch("run_train_and_backtest.joblib.load") as mock_joblib_load,
        patch("run_train_and_backtest.BacktestEngine") as mock_engine_class,
        patch("run_train_and_backtest.DecisionPolicy"),
        patch("run_train_and_backtest.add_regime_feature") as mock_add_regime_feature,
    ):
        # Mock data loading and resampling
        mock_load_bars.return_value = pd.DataFrame(
            {"ts": [1, 2, 3], "symbol": ["BAC", "BAC", "BAC"]}
        )
        mock_resample_data.return_value = pd.DataFrame(
            {"ts": [1, 2, 3], "symbol": ["BAC", "BAC", "BAC"]}
        )

        # Mock dataset and feature creation
        training_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    ["2023-01-01 09:30", "2023-01-01 09:40", "2023-01-01 09:50"]
                ),
                "symbol": ["BAC", "BAC", "BAC"],
                "f__dummy": [1.0, 2.0, 3.0],
                "label": [0, 1, -1],
            }
        )
        oos_df = pd.DataFrame(
            {
                "ts": pd.to_datetime(
                    ["2023-01-03 09:30", "2023-01-03 09:40", "2023-01-03 09:50"]
                ),
                "symbol": ["BAC", "BAC", "BAC"],
                "f__dummy": [4.0, 5.0, 6.0],
                "label": [0, 0, 1],
            }
        )
        mock_create_training_dataset.side_effect = [training_df, oos_df]

        # Mock regime feature addition
        mock_add_regime_feature.side_effect = lambda df: df

        # Mock trainer
        mock_trainer_instance = MagicMock()
        mock_trainer_instance.train_model.return_value = MagicMock(
            model=MagicMock(), metrics={"accuracy": 0.75}
        )
        mock_trainer_class.return_value = mock_trainer_instance

        # Mock model loading
        mock_joblib_load.return_value = MagicMock()
        mock_joblib_load.return_value.predict_proba.return_value = np.array(
            [[0.1, 0.2, 0.7], [0.6, 0.2, 0.2], [0.2, 0.5, 0.3]]
        )
        mock_joblib_load.return_value.classes_ = np.array([-1, 0, 1])

        # Mock backtest engine
        mock_engine_instance = MagicMock()
        mock_engine_instance.run.return_value = MagicMock(
            to_dict=lambda: {"performance": {"total_return": 0.0}}
        )
        mock_engine_class.return_value = mock_engine_instance

        yield


def test_run_workflow_flow(mock_dependencies):
    """
    Test that run_workflow() executes without logical errors.
    """
    try:
        run_train_and_backtest.run_workflow(
            train_start="2023-01-01",
            train_end="2023-01-02",
            test_start="2023-01-03",
            test_end="2023-01-03",
        )
    except Exception as e:
        pytest.fail(f"Script failed with an unexpected error: {e}")
