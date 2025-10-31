#!/usr/bin/env python3
"""
Test the logical flow of the OOS backtest script without running slow functions.
"""
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import sys
from pathlib import Path

# Add project root to path to allow importing run_oos_backtest
sys.path.insert(0, str(Path(__file__).parent.parent))

# Now we can import the script we want to test
import run_oos_backtest

@pytest.fixture
def mock_dependencies():
    """Mock all slow external dependencies."""
    with (patch('run_oos_backtest.joblib.load') as mock_joblib_load,
         patch('run_oos_backtest.create_feature_set') as mock_create_features,
         patch('run_oos_backtest.load_bars') as mock_load_bars,
         patch('run_oos_backtest.BacktestEngine') as mock_engine):

        # Configure mocks to return valid, empty data
        mock_joblib_load.return_value = MagicMock()
        mock_create_features.return_value = pd.DataFrame({
            'ts': [pd.Timestamp('2024-01-04 10:00:00')],
            'symbol': ['BAC'],
            'f__dummy': [1.0]
        })
        mock_load_bars.return_value = pd.DataFrame({
            'ts': [pd.Timestamp('2024-01-04 10:00:00')],
            'symbol': ['BAC'],
            'open': [100], 'high': [101], 'low': [99], 'close': [100], 'volume': [1000]
        })
        
        # Mock the engine's run result
        mock_engine_instance = mock_engine.return_value
        mock_engine_instance.run.return_value = MagicMock()
        mock_engine_instance.run.return_value.to_dict.return_value = {'performance': {'total_return': 0.0}}

        yield

def test_run_backtest_flow(mock_dependencies):
    """
    Test that run_backtest() executes without logical errors (like UnboundLocalError)
    when all slow dependencies are mocked.
    """
    try:
        run_oos_backtest.run_backtest(start_date="2024-01-04", end_date="2024-01-04")
    except (UnboundLocalError, TypeError, NameError) as e:
        pytest.fail(f"Script failed with a logical flow error: {e}")
    except Exception:
        # Other exceptions are ok for this test, we only care about logical flow
        pass
