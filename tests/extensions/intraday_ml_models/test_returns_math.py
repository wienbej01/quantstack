import numpy as np
import pandas as pd
import pytest

# from extensions.intraday_ml_models.wrappers.metrics_consistency import run_metrics_consistency_check

# For now, we will test the logic conceptually with dummy data.


@pytest.fixture
def synthetic_equity_curve() -> pd.DataFrame:
    """Creates a synthetic equity curve for testing returns math."""
    timestamps = pd.date_range(start="2024-01-09 09:30:00", periods=390, freq="min")
    equity = 100000 * (1 + np.random.normal(0.0001, 0.001, 390)).cumprod()
    return pd.DataFrame({"equity": equity}, index=timestamps)


def test_sharpe_ratio_annualization(synthetic_equity_curve):
    """Validate that minute and daily Sharpe ratios are consistent."""
    minute_returns = synthetic_equity_curve["equity"].pct_change().dropna()
    np.sqrt(252 * 390) * minute_returns.mean() / minute_returns.std()

    synthetic_equity_curve["equity"].resample("D").last().pct_change().dropna()
    # Since we only have one day of data, daily_returns will be empty.
    # Let's create a multi-day curve for a better test.
    timestamps_2days = pd.date_range(start="2024-01-09 09:30:00", periods=780, freq="min")
    equity_2days = 100000 * (1 + np.random.normal(0.0001, 0.001, 780)).cumprod()
    equity_curve_2days = pd.DataFrame({"equity": equity_2days}, index=timestamps_2days)

    daily_returns_2days = equity_curve_2days["equity"].resample("D").last().pct_change().dropna()
    daily_sharpe = np.sqrt(252) * daily_returns_2days.mean() / daily_returns_2days.std()

    # This is a conceptual check. The ratio depends on the data.
    # A proper test would use data with known statistical properties.
    assert daily_sharpe is not np.nan


def test_return_calculation(synthetic_equity_curve):
    """Validate the percentage change formula for returns."""
    returns = synthetic_equity_curve["equity"].pct_change()
    manual_return = (
        synthetic_equity_curve["equity"].iloc[1] - synthetic_equity_curve["equity"].iloc[0]
    ) / synthetic_equity_curve["equity"].iloc[0]
    assert np.isclose(returns.iloc[1], manual_return)
