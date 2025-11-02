"""Tests for intraday ML time utilities."""

from __future__ import annotations

from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from extensions.intraday_ml.utils import normalize_timestamp_series


def test_normalize_microsecond_epoch_to_market_naive():
    series = pd.Series([1704205800000000])  # 2024-01-02 14:30:00 UTC
    result = normalize_timestamp_series(series, output="naive_market")
    assert result.dtype == "datetime64[ns]"
    assert result.iloc[0] == pd.Timestamp("2024-01-02 09:30:00")


def test_normalize_ns_epoch_to_market_aware():
    # 2024-01-02 14:40:00 UTC expressed in nanoseconds
    series = pd.Series([1704206400000000000])
    result = normalize_timestamp_series(series, output="aware_market")
    expected = pd.Timestamp("2024-01-02 09:40:00", tz=ZoneInfo("America/New_York"))
    assert result.iloc[0] == expected


def test_normalize_string_with_timezone_to_utc():
    series = pd.Series(["2024-01-02T09:45:00-05:00"])
    result = normalize_timestamp_series(series, output="aware_utc")
    expected = pd.Timestamp("2024-01-02 14:45:00", tz="UTC")
    assert result.iloc[0] == expected


def test_normalize_naive_series_assumed_market_timezone():
    series = pd.Series(pd.to_datetime(["2024-03-11 10:00:00"]))
    result = normalize_timestamp_series(series, output="aware_utc")
    expected = pd.Timestamp("2024-03-11 14:00:00", tz="UTC")
    assert result.iloc[0] == expected


def test_normalize_invalid_values_raises():
    series = pd.Series(["not-a-timestamp"])
    with pytest.raises(ValueError):
        normalize_timestamp_series(series)
