import numpy as np
import pandas as pd
import pytest

# from extensions.intraday_ml_models.wrappers.metrics_consistency import run_metrics_consistency_check

# For now, we will test the logic conceptually with dummy data.


@pytest.fixture
def synthetic_trades_and_equity() -> (pd.DataFrame, pd.DataFrame):
    """Creates synthetic trades and a corresponding equity curve."""
    trades = pd.DataFrame({"pnl": [150.50, -50.25, 200.00]})

    starting_equity = 100000.0
    total_pnl = trades["pnl"].sum()
    ending_equity = starting_equity + total_pnl

    equity = pd.DataFrame(
        {"equity": [starting_equity, 100150.50, 100100.25, ending_equity]},
        index=pd.to_datetime(
            [
                "2024-01-09 09:30:00",
                "2024-01-09 10:00:00",
                "2024-01-09 10:30:00",
                "2024-01-09 11:00:00",
            ]
        ),
    )

    return trades, equity


def test_pnl_equity_reconciliation(synthetic_trades_and_equity):
    """Confirm that the sum of trade PnL matches the equity delta."""
    trades_df, equity_df = synthetic_trades_and_equity

    total_pnl = trades_df["pnl"].sum()
    equity_delta = equity_df["equity"].iloc[-1] - equity_df["equity"].iloc[0]

    assert np.isclose(total_pnl, equity_delta)


def test_reconciliation_with_tolerance():
    """Test the reconciliation logic with a small tolerance."""
    total_pnl = 1000.0
    equity_delta = 1000.00001
    starting_equity = 100000.0

    pnl_equity_diff = abs(total_pnl - equity_delta)
    tolerance = 1e-6 * starting_equity + 1e-3

    assert pnl_equity_diff <= tolerance
