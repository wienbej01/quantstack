"""Time handling utilities for intraday ML pipelines.

Provides flexible timestamp normalization that accepts heterogeneous inputs
and returns consistently localized datetimes for downstream processing.
"""

from __future__ import annotations

from typing import Iterable, Literal
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
from pandas.api.types import DatetimeTZDtype

DEFAULT_MARKET_TZ = "America/New_York"


TimestampOutput = Literal["aware_market", "aware_utc", "naive_market", "naive_utc"]


def normalize_timestamp_series(
    values: pd.Series | Iterable[pd.Timestamp] | Iterable[object],
    *,
    market_tz: str = DEFAULT_MARKET_TZ,
    output: TimestampOutput = "naive_market",
    assume_naive_as_market: bool = True,
) -> pd.Series:
    """Normalize assorted timestamp formats into a consistent representation.

    Args:
        values: Iterable or Series containing timestamp-like values.
        market_tz: Target market timezone for localization.
        output: Desired output representation. Options:
            - ``naive_market`` (default): naive datetimes in market timezone
            - ``aware_market``: timezone-aware datetimes in market timezone
            - ``aware_utc``: timezone-aware UTC datetimes
            - ``naive_utc``: naive datetimes interpreted as UTC
        assume_naive_as_market: If True, naive datetimes/strings are assumed
            to be expressed in the market timezone before conversion.

    Returns:
        Series with normalized timestamps.

    Raises:
        ValueError: If timestamps cannot be parsed into datetimes.
    """

    series = _coerce_to_series(values)
    if series.empty:
        return pd.Series([], index=series.index, name=series.name, dtype="datetime64[ns]")

    market_zone = ZoneInfo(market_tz)
    utc_series = _coerce_to_utc(series, market_zone, assume_naive_as_market)

    if utc_series.isna().any():
        bad = series[utc_series.isna()].head().tolist()
        raise ValueError(f"Failed to parse timestamps. Examples: {bad}")

    if output == "aware_utc":
        return utc_series
    if output == "naive_utc":
        return utc_series.dt.tz_localize(None)

    market_series = utc_series.dt.tz_convert(market_zone)
    if output == "aware_market":
        return market_series
    if output == "naive_market":
        return market_series.dt.tz_localize(None)

    raise ValueError(f"Unsupported output mode '{output}'")


def _coerce_to_series(values: pd.Series | Iterable[object]) -> pd.Series:
    if isinstance(values, pd.Series):
        return values
    return pd.Series(list(values))


def _coerce_to_utc(
    series: pd.Series,
    market_zone: ZoneInfo,
    assume_naive_as_market: bool,
) -> pd.Series:
    """Convert inputs to timezone-aware UTC pandas Series."""
    if isinstance(series.dtype, DatetimeTZDtype):
        return series.dt.tz_convert("UTC")

    if pd.api.types.is_datetime64_dtype(series):
        localized = series.dt.tz_localize(
            market_zone if assume_naive_as_market else ZoneInfo("UTC")
        )
        return localized.dt.tz_convert("UTC")

    if pd.api.types.is_numeric_dtype(series):
        numeric = pd.to_numeric(series, errors="coerce")
        unit = _infer_epoch_unit(numeric.dropna())
        utc_values = pd.to_datetime(numeric, unit=unit, utc=True, errors="coerce")
        return pd.Series(utc_values, index=series.index, name=series.name)

    parsed = pd.to_datetime(series, utc=False, errors="coerce")
    if parsed.dt.tz is None:
        localized = parsed.dt.tz_localize(
            market_zone if assume_naive_as_market else ZoneInfo("UTC")
        )
    else:
        localized = parsed
    return localized.dt.tz_convert("UTC")


def _infer_epoch_unit(series: pd.Series) -> str:
    """Infer epoch unit based on magnitude heuristics."""
    if series.empty:
        return "ns"

    max_abs = np.nanmax(np.abs(series.to_numpy(dtype="float64", copy=False)))

    if max_abs >= 1e18:
        return "ns"
    if max_abs >= 1e15:
        return "us"
    if max_abs >= 1e12:
        return "ms"
    if max_abs >= 1e9:
        return "s"
    return "s"
