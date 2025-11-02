import logging

import pandas as pd

logger = logging.getLogger(__name__)


def resample_data(df: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    """Resamples 1-minute bar data to a higher timeframe."""
    if df.empty:
        return pd.DataFrame()
    logger.info(f"Resampling {len(df)} 1-minute bars to {timeframe} bars...")
    logger.info(f"Input data min ts: {df['ts'].min()}, max ts: {df['ts'].max()}")
    df_copy = df.copy()
    if pd.api.types.is_datetime64_any_dtype(df_copy["ts"]):
        ts_series = df_copy["ts"]
        if ts_series.dt.tz is None:
            df_copy["ts"] = ts_series.dt.tz_localize("UTC")
        else:
            df_copy["ts"] = ts_series.dt.tz_convert("UTC")
    else:
        df_copy["ts"] = pd.to_datetime(df_copy["ts"], unit="ns", utc=True)

    resampled_df = (
        df_copy.set_index("ts")
        .groupby("symbol")
        .resample(timeframe)
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .reset_index()
    )
    resampled_df["ts"] = resampled_df["ts"].astype("int64", copy=False)
    logger.info(f"Resampled to {len(resampled_df)} {timeframe} bars.")
    return resampled_df
