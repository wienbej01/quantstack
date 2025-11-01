
import numpy as np
import pandas as pd
from qx_data.resample import resample_data


def test_resample_data():
    """Tests the resample_data function."""
    dates = pd.to_datetime(pd.date_range("2024-01-01 09:30:00", periods=10, freq="1min"))
    data = {
        "ts": dates.astype(np.int64),
        "symbol": ["AAPL"] * 10,
        "open": [150.0] * 10,
        "high": [151.0] * 10,
        "low": [149.0] * 10,
        "close": [150.5] * 10,
        "volume": [1000] * 10,
    }
    df = pd.DataFrame(data)

    resampled_df = resample_data(df, "5min")

    assert len(resampled_df) == 2
    assert resampled_df.iloc[0]["open"] == 150.0
    assert resampled_df.iloc[0]["high"] == 151.0
    assert resampled_df.iloc[0]["low"] == 149.0
    assert resampled_df.iloc[0]["close"] == 150.5
    assert resampled_df.iloc[0]["volume"] == 5000
