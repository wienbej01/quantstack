"""Time and session utilities for quantitative trading."""

import datetime
from datetime import datetime as dt
from datetime import time, timedelta
from typing import Optional

import numpy as np
import pandas as pd

# Constants
UTC = datetime.UTC
US_EASTERN = datetime.timezone(datetime.timedelta(hours=-5))  # Simplified EST
US_CENTRAL = datetime.timezone(datetime.timedelta(hours=-6))  # Simplified CST
US_MOUNTAIN = datetime.timezone(datetime.timedelta(hours=-7))  # Simplified MST
US_PACIFIC = datetime.timezone(datetime.timedelta(hours=-8))  # Simplified PST

NANOSECONDS_PER_SECOND = 1_000_000_000
NANOSECONDS_PER_MICROSECOND = 1_000
MICROSECONDS_PER_SECOND = 1_000_000


def utc_now() -> dt:
    """Get current UTC time."""
    return dt.now(UTC)


def datetime_to_utc_ns(dt_input: dt | pd.Timestamp | str | int) -> int:
    """Convert datetime/timestamp to UTC nanoseconds.

    Args:
        dt_input: Input datetime, timestamp, string, or integer

    Returns:
        UTC nanoseconds since epoch
    """
    if isinstance(dt_input, int):
        # Assume already in nanoseconds
        return dt_input
    elif isinstance(dt_input, str):
        # Parse string
        dt_obj = pd.to_datetime(dt_input)
        if isinstance(dt_obj, pd.Timestamp):
            return int(dt_obj.value)
        else:
            return int(dt_obj.timestamp() * NANOSECONDS_PER_SECOND)
    elif isinstance(dt_input, pd.Timestamp):
        return int(dt_input.value)
    elif isinstance(dt_input, dt):
        if dt_input.tzinfo is None:
            dt_input = dt_input.replace(tzinfo=UTC)
        else:
            dt_input = dt_input.astimezone(UTC)
        return int(dt_input.timestamp() * NANOSECONDS_PER_SECOND)
    else:
        raise ValueError(f"Unsupported datetime type: {type(dt_input)}")


def utc_ns_to_datetime(ts_ns: int | np.ndarray) -> dt | list[dt]:
    """Convert UTC nanoseconds to datetime.

    Args:
        ts_ns: UTC nanoseconds since epoch (scalar or array)

    Returns:
        UTC datetime or list of datetimes
    """
    if isinstance(ts_ns, np.ndarray):
        return [dt.fromtimestamp(int(ts) / NANOSECONDS_PER_SECOND, UTC) for ts in ts_ns]
    else:
        return dt.fromtimestamp(int(ts_ns) / NANOSECONDS_PER_SECOND, UTC)


def utc_ns_to_timestamp(ts_ns: int) -> pd.Timestamp:
    """Convert UTC nanoseconds to pandas Timestamp.

    Args:
        ts_ns: UTC nanoseconds since epoch

    Returns:
        pandas Timestamp in UTC
    """
    return pd.Timestamp(ts_ns, tz=UTC, unit="ns")


def ts_to_date(ts_ns: int) -> dt:
    """Convert UTC nanoseconds to date (convenience function).

    Args:
        ts_ns: UTC nanoseconds since epoch

    Returns:
        UTC datetime object
    """
    return utc_ns_to_datetime(ts_ns)


def normalize_timestamps(df: pd.DataFrame, ts_col: str = "ts") -> pd.DataFrame:
    """Normalize timestamp column to UTC nanoseconds.

    Args:
        df: DataFrame with timestamp column
        ts_col: Name of timestamp column

    Returns:
        DataFrame with normalized timestamps
    """
    df = df.copy()
    df[ts_col] = df[ts_col].apply(datetime_to_utc_ns)
    return df


def get_session_bounds(
    date: dt | str | int,
    session_start: time = time(9, 30),  # 9:30 AM default
    session_end: time = time(16, 0),  # 4:00 PM default
    tz: datetime.timezone = US_EASTERN,
) -> tuple[int, int]:
    """Get session start and end times in UTC nanoseconds.

    Args:
        date: Date for session
        session_start: Session start time
        session_end: Session end time
        tz: Timezone for session times

    Returns:
        Tuple of (session_start_ns, session_end_ns) in UTC nanoseconds
    """
    if isinstance(date, str):
        date = pd.to_datetime(date).date()
    elif isinstance(date, int):
        date = utc_ns_to_datetime(date).date()
    elif isinstance(date, dt):
        date = date.date()

    # Create datetime objects for session bounds
    session_start_dt = dt.combine(date, session_start).replace(tzinfo=tz)
    session_end_dt = dt.combine(date, session_end).replace(tzinfo=tz)

    # Convert to UTC nanoseconds
    session_start_ns = datetime_to_utc_ns(session_start_dt)
    session_end_ns = datetime_to_utc_ns(session_end_dt)

    return session_start_ns, session_end_ns


def is_market_session(
    ts_ns: int,
    session_start: time = time(9, 30),
    session_end: time = time(16, 0),
    tz: datetime.timezone = US_EASTERN,
) -> bool:
    """Check if timestamp is within market session.

    Args:
        ts_ns: UTC nanosecond timestamp
        session_start: Session start time
        session_end: Session end time
        tz: Timezone for session times

    Returns:
        True if timestamp is within session
    """
    utc_dt = utc_ns_to_datetime(ts_ns)
    local_dt = utc_dt.astimezone(tz)

    session_time = local_dt.time()
    return session_start <= session_time <= session_end


def is_trading_day(date: dt | str | int) -> bool:
    """Check if date is a weekday (simplified trading day check).

    Args:
        date: Date to check

    Returns:
        True if date is a weekday
    """
    if isinstance(date, str):
        date = pd.to_datetime(date).date()
    elif isinstance(date, int):
        date = utc_ns_to_datetime(date).date()
    elif isinstance(date, dt):
        date = date.date()

    return date.weekday() < 5  # 0-4 are Monday-Friday


def get_trading_days(start_date: dt | str, end_date: dt | str) -> list[dt]:
    """Get list of trading days between two dates.

    Args:
        start_date: Start date
        end_date: End date

    Returns:
        List of trading day dates
    """
    if isinstance(start_date, str):
        start_date = pd.to_datetime(start_date).date()
    elif isinstance(start_date, dt):
        start_date = start_date.date()

    if isinstance(end_date, str):
        end_date = pd.to_datetime(end_date).date()
    elif isinstance(end_date, dt):
        end_date = end_date.date()

    trading_days = []
    current_date = start_date

    while current_date <= end_date:
        if is_trading_day(current_date):
            trading_days.append(current_date)
        current_date += timedelta(days=1)

    return trading_days


def format_utc_ns(ts_ns: int, fmt: str = "%Y-%m-%d %H:%M:%S UTC") -> str:
    """Format UTC nanosecond timestamp as string.

    Args:
        ts_ns: UTC nanosecond timestamp
        fmt: Format string

    Returns:
        Formatted timestamp string
    """
    dt_obj = utc_ns_to_datetime(ts_ns)
    return dt_obj.strftime(fmt)


def parse_duration(duration_str: str) -> timedelta:
    """Parse duration string (e.g., "1h", "30m", "1d") to timedelta.

    Args:
        duration_str: Duration string

    Returns:
        timedelta object
    """
    duration_str = duration_str.lower().strip()

    if duration_str.endswith("ns"):
        return timedelta(microseconds=int(duration_str[:-2]) / 1000)
    elif duration_str.endswith("us"):
        return timedelta(microseconds=int(duration_str[:-2]))
    elif duration_str.endswith("ms"):
        return timedelta(milliseconds=int(duration_str[:-2]))
    elif duration_str.endswith("s"):
        return timedelta(seconds=int(duration_str[:-1]))
    elif duration_str.endswith("m"):
        return timedelta(minutes=int(duration_str[:-1]))
    elif duration_str.endswith("h"):
        return timedelta(hours=int(duration_str[:-1]))
    elif duration_str.endswith("d"):
        return timedelta(days=int(duration_str[:-1]))
    elif duration_str.endswith("w"):
        return timedelta(weeks=int(duration_str[:-1]))
    else:
        raise ValueError(f"Unsupported duration format: {duration_str}")


def add_time_bars(df: pd.DataFrame, interval: str = "1h") -> pd.DataFrame:
    """Add time bar columns to DataFrame.

    Args:
        df: DataFrame with timestamp column
        interval: Time bar interval (e.g., '1h', '30m', '1d')

    Returns:
        DataFrame with added time bar columns
    """
    df = df.copy()

    # Ensure timestamp is datetime
    if "ts" in df.columns:
        df["datetime"] = utc_ns_to_timestamp(df["ts"])
    else:
        raise ValueError("DataFrame must have 'ts' column")

    # Add time bar columns
    df["date"] = df["datetime"].dt.date
    df["hour"] = df["datetime"].dt.hour
    df["minute"] = df["datetime"].dt.minute

    # Add custom interval bars
    if interval.endswith("h"):
        hours = int(interval[:-1])
        df["time_bar"] = df["datetime"].dt.floor(f"{hours}H")
    elif interval.endswith("m"):
        minutes = int(interval[:-1])
        df["time_bar"] = df["datetime"].dt.floor(f"{minutes}min")
    elif interval.endswith("d"):
        days = int(interval[:-1])
        df["time_bar"] = df["datetime"].dt.floor(f"{days}D")

    return df


def resample_bars(
    df: pd.DataFrame,
    interval: str = "1h",
    price_cols: list = None,
    volume_col: str = "volume",
) -> pd.DataFrame:
    """Resample bars to different time interval.

    Args:
        df: DataFrame with OHLCV data
        interval: Target interval (e.g., '1h', '30m', '1d')
        price_cols: Price column names
        volume_col: Volume column name

    Returns:
        Resampled DataFrame
    """
    if price_cols is None:
        price_cols = ["open", "high", "low", "close"]
    df = df.copy()

    # Ensure datetime index
    if "ts" in df.columns:
        df["datetime"] = utc_ns_to_timestamp(df["ts"])
        df = df.set_index("datetime")

    # Define aggregation functions
    agg_funcs = {}
    for col in price_cols:
        if col == "open":
            agg_funcs[col] = "first"
        elif col == "high":
            agg_funcs[col] = "max"
        elif col == "low":
            agg_funcs[col] = "min"
        elif col == "close":
            agg_funcs[col] = "last"
        else:
            agg_funcs[col] = "last"

    if volume_col in df.columns:
        agg_funcs[volume_col] = "sum"

    # Resample
    resampled = df.resample(interval).agg(agg_funcs).dropna()

    # Convert back to have ts column
    resampled = resampled.reset_index()
    resampled["ts"] = resampled["datetime"].apply(lambda x: int(x.value))
    resampled = resampled.drop("datetime", axis=1)

    return resampled


def get_time_buckets(start_ts: int, end_ts: int, interval: str = "1h") -> list[int]:
    """Get list of time bucket timestamps.

    Args:
        start_ts: Start UTC nanosecond timestamp
        end_ts: End UTC nanosecond timestamp
        interval: Time interval

    Returns:
        List of bucket start timestamps
    """
    start_dt = utc_ns_to_datetime(start_ts)
    end_dt = utc_ns_to_datetime(end_ts)

    delta = parse_duration(interval)

    buckets = []
    current_dt = start_dt

    while current_dt <= end_dt:
        buckets.append(datetime_to_utc_ns(current_dt))
        current_dt += delta

    return buckets


class TimeWindow:
    """Utility class for working with time windows."""

    def __init__(self, start: dt | str | int, end: dt | str | int):
        """Initialize time window.

        Args:
            start: Window start time
            end: Window end time
        """
        self.start_ns = datetime_to_utc_ns(start)
        self.end_ns = datetime_to_utc_ns(end)

        if self.start_ns >= self.end_ns:
            raise ValueError("Start time must be before end time")

    def contains(self, ts: dt | str | int) -> bool:
        """Check if timestamp is within window."""
        ts_ns = datetime_to_utc_ns(ts)
        return self.start_ns <= ts_ns <= self.end_ns

    def duration_ns(self) -> int:
        """Get window duration in nanoseconds."""
        return self.end_ns - self.start_ns

    def duration_seconds(self) -> float:
        """Get window duration in seconds."""
        return self.duration_ns() / NANOSECONDS_PER_SECOND

    def overlap(self, other: "TimeWindow") -> Optional["TimeWindow"]:
        """Get overlap with another time window."""
        overlap_start = max(self.start_ns, other.start_ns)
        overlap_end = min(self.end_ns, other.end_ns)

        if overlap_start < overlap_end:
            return TimeWindow(overlap_start, overlap_end)
        return None

    def __str__(self) -> str:
        return f"TimeWindow({format_utc_ns(self.start_ns)}, {format_utc_ns(self.end_ns)})"

    def __repr__(self) -> str:
        return self.__str__()


def get_market_sessions_for_date(
    date: dt | str | int,
    session_start: time = time(9, 30),
    session_end: time = time(16, 0),
    tz: datetime.timezone = US_EASTERN,
) -> TimeWindow:
    """Get market session time window for a date.

    Args:
        date: Date for session
        session_start: Session start time
        session_end: Session end time
        tz: Timezone for session times

    Returns:
        TimeWindow for the session
    """
    start_ns, end_ns = get_session_bounds(date, session_start, session_end, tz)
    return TimeWindow(start_ns, end_ns)
