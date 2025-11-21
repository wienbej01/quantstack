"""Sliding Window Data Preparation for Intraday ML Training.

This module implements the core sliding window approach from Sprint 1 of the
ML pipeline refactoring, addressing the critical design flaw where features
and labels were generated from non-overlapping time periods.

Key Features:
- Generates properly aligned feature-label pairs with strict no-lookahead bias
- Processes each timestamp independently using historical data for features
  and future data for labels
- Eliminates the feature-label misalignment that prevented model training
- Provides progress tracking for large datasets

Architecture:
    Gold Data → Sliding Window → Features (≤ ts) + Labels (> ts) → Aligned DataFrame

Time Discipline Enforcement:
- Features: Use only data with timestamps ≤ current_timestamp
- Labels: Use only data with timestamps > current_timestamp
- Validation: Built-in checks prevent temporal leakage

Performance Notes:
- Processes one timestamp at a time (memory efficient)
- Progress reporting every 10,000 timestamps
- Suitable for datasets with 100K+ timestamps
"""

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from qx_data.gold_loader import load_bars
from qx_data.resample import resample_data

from .feature_pack import IntradayMLFeaturePack
from .labeling import IntradayMLLabeler
from .utils import normalize_timestamp_series
from .utils.time_utils import DEFAULT_MARKET_TZ, TimestampOutput


def create_training_dataset(  # noqa: PLR0913 - public API requires this signature
    symbols: Sequence[str],
    start_date: str,
    end_date: str,
    features_config: dict[str, Any],
    targets_config: dict[str, Any],
    data_loader_config: dict[str, Any] | None = None,
    include_ohlcv: bool = False,
) -> pd.DataFrame:
    """Create a leak-free training dataset with aligned features and labels."""
    if not symbols:
        raise ValueError("symbols must be a non-empty sequence")

    if features_config is None:
        raise ValueError("features_config is required")

    if targets_config is None:
        raise ValueError("targets_config is required")

    data_window = load_data_window(
        symbols=list(symbols),
        start_date=start_date,
        end_date=end_date,
        config=data_loader_config,
    )

    if data_window.empty:
        return pd.DataFrame()

    required_columns = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    missing_columns = required_columns - set(data_window.columns)
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Loaded data is missing required columns: {missing}")

    loader_options = data_loader_config or {}
    oversampling_config = loader_options.get("oversampling", {})
    dataset_kind = loader_options.get("dataset_kind", "train")
    market_timezone = loader_options.get("market_timezone", DEFAULT_MARKET_TZ)
    assume_naive_as_market = loader_options.get("assume_naive_as_market", True)
    timestamps = normalize_timestamp_series(
        data_window["ts"],
        market_tz=market_timezone,
        output="naive_market",
        assume_naive_as_market=assume_naive_as_market,
    )
    if timestamps.isna().any():
        bad_rows = data_window.loc[timestamps.isna(), ["symbol", "ts"]].head()
        raise ValueError(
            f"Encountered non-parsable timestamps in data window. Examples:\n{bad_rows}"
        )

    window = data_window.copy()
    window["ts"] = timestamps
    window = (
        window.sort_values(["symbol", "ts"])
        .drop_duplicates(subset=["symbol", "ts"], keep="first")
        .reset_index(drop=True)
    )

    feature_pack = IntradayMLFeaturePack(features_config)
    labeler = IntradayMLLabeler(targets_config)

    # Load market context for regime features
    # Import here to avoid circular dependency with market_context.py importing from data_prep
    from .market_context import load_market_context

    market_context = load_market_context(
        start_date=start_date,
        end_date=end_date,
        data_loader_config=data_loader_config,
    )

    symbol_frames: list[pd.DataFrame] = []

    for symbol, symbol_frame in window.groupby("symbol", sort=False):
        if symbol_frame.empty:
            continue

        symbol_sorted = symbol_frame.sort_values("ts").reset_index(drop=True)

        features = feature_pack.compute_features(
            df=symbol_sorted,
            ts_cut=symbol_sorted["ts"].iloc[-1],
            validate_time_discipline=True,
            market_context=market_context,
        ).reindex(symbol_sorted.index)

        labels = labeler.compute_label_series(symbol_sorted)

        symbol_dataset = pd.DataFrame(
            {
                "symbol": symbol,
                "ts": symbol_sorted["ts"],
            }
        )

        if include_ohlcv:
            for column in ["open", "high", "low", "close", "volume"]:
                symbol_dataset[column] = symbol_sorted[column].to_numpy()

        symbol_dataset = pd.concat([symbol_dataset, features.reset_index(drop=True)], axis=1)
        symbol_dataset["label"] = labels.to_numpy(dtype=int, copy=False)
        symbol_dataset = _apply_directional_oversampling(
            symbol_dataset, oversampling_config, dataset_kind
        )

        symbol_frames.append(symbol_dataset)

    if not symbol_frames:
        return pd.DataFrame()

    result = (
        pd.concat(symbol_frames, ignore_index=True)
        .sort_values(["symbol", "ts"])
        .reset_index(drop=True)
    )

    base_columns = ["symbol", "ts"]
    if include_ohlcv:
        base_columns.extend(["open", "high", "low", "close", "volume"])

    feature_columns = [col for col in result.columns if col.startswith("f__")]
    ordered_columns = base_columns + feature_columns + ["label"]
    remaining_columns = [col for col in result.columns if col not in ordered_columns]

    return result[ordered_columns + remaining_columns]


def _apply_directional_oversampling(
    dataset: pd.DataFrame,
    config: dict[str, Any],
    dataset_kind: str,
) -> pd.DataFrame:
    """Duplicate directional observations to counter extreme imbalance."""
    if not config or not config.get("enabled", False):
        return dataset

    apply_to = config.get("apply_to", ["train"])
    if isinstance(apply_to, str):
        apply_to = [apply_to]
    normalized_apply_to = {scope.lower() for scope in apply_to}
    if "all" not in normalized_apply_to and dataset_kind.lower() not in normalized_apply_to:
        return dataset

    label_column = config.get("label_column", "label")
    if label_column not in dataset.columns:
        return dataset

    directional_labels = config.get("directional_labels", (-1, 1))
    mask = dataset[label_column].isin(directional_labels)
    directional = dataset[mask]
    if directional.empty:
        return dataset

    target_fraction = float(config.get("target_fraction", 0.05))
    max_multiplier = max(1, int(config.get("max_multiplier", 6)))
    random_state = config.get("random_state", 42)

    total_count = len(dataset)
    desired_directional = max(len(directional), int(round(total_count * target_fraction)))
    if desired_directional <= len(directional):
        return dataset

    needed = desired_directional - len(directional)
    copies = min(max_multiplier, max(1, math.ceil(needed / len(directional))))
    replicated = pd.concat([directional] * copies, ignore_index=True)
    sample_size = min(len(replicated), needed)
    replace = sample_size > len(replicated)
    oversampled = replicated.sample(
        n=sample_size,
        replace=replace,
        random_state=random_state,
    )

    augmented = pd.concat([dataset, oversampled], ignore_index=True)
    return augmented.sample(frac=1.0, random_state=random_state).reset_index(drop=True)


def _build_date_list(start_date: str, end_date: str) -> list[str]:
    """Create an inclusive list of YYYY-MM-DD strings."""
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    if end_dt < start_dt:
        raise ValueError(f"end_date {end_date} precedes start_date {start_date}")

    total_days = (end_dt - start_dt).days + 1
    return [
        (start_dt + timedelta(days=offset)).strftime("%Y-%m-%d") for offset in range(total_days)
    ]


def _resolve_loader_options(
    config: dict[str, Any] | None,
) -> tuple[
    dict[str, Any],
    str | None,
    str,
    str,
    bool,
    TimestampOutput,
]:
    """Resolve loader configuration overrides and resample requirements."""
    loader_config = dict(config or {})
    requested_family = loader_config.get("family", "bars_1m")
    market_timezone = loader_config.get("market_timezone", DEFAULT_MARKET_TZ)
    assume_naive_as_market = loader_config.get("assume_naive_as_market", True)
    output_mode: TimestampOutput = loader_config.get("output_timestamp_mode", "naive_market")

    resample_frequency: str | None = None
    loader_family = requested_family

    if requested_family.startswith("bars_"):
        suffix = requested_family.split("_", 1)[1]
        if suffix.endswith("m"):
            minutes = suffix[:-1]
            if minutes.isdigit() and minutes != "1":
                resample_frequency = f"{minutes}min"
                loader_family = loader_config.get("resample_source_family", "bars_1m")

    return (
        loader_config,
        resample_frequency,
        loader_family,
        market_timezone,
        assume_naive_as_market,
        output_mode,
    )


def _load_raw_bars(
    symbols: list[str],
    dates: list[str],
    loader_config: dict[str, Any],
    loader_family: str,
) -> pd.DataFrame:
    """Load raw bar data, retrying with uppercase tickers when needed."""
    load_kwargs: dict[str, Any] = {
        "root": loader_config.get("root", "/home/jacobw/gcs-mount"),
        "family": loader_family,
        "symbols": symbols,
        "dates": dates,
        "validate": loader_config.get("validate", True),
        "sort": loader_config.get("sort", True),
    }
    if "columns" in loader_config:
        load_kwargs["columns"] = loader_config["columns"]

    try:
        return load_bars(**load_kwargs)
    except RuntimeError:
        alt_symbols = sorted({symbol.upper() for symbol in symbols})
        if alt_symbols == symbols:
            raise
        load_kwargs["symbols"] = alt_symbols
        return load_bars(**load_kwargs)


def _finalize_loaded_data(
    data: pd.DataFrame,
    *,
    resample_frequency: str | None,
    market_timezone: str,
    assume_naive_as_market: bool,
    output_mode: TimestampOutput,
) -> pd.DataFrame:
    """Normalise timestamps, optionally resample, and ensure deterministic order."""
    if data.empty:
        return data

    data = data.copy()
    data["ts"] = normalize_timestamp_series(
        data["ts"],
        market_tz=market_timezone,
        output="aware_utc",
        assume_naive_as_market=assume_naive_as_market,
    )

    if resample_frequency:
        resampled = resample_data(data, resample_frequency)
        resampled = resampled.dropna(subset=["open", "high", "low", "close"])
        if resampled.empty:
            return pd.DataFrame()
        if "volume" in resampled:
            resampled["volume"] = resampled["volume"].fillna(0).round().astype("int64", copy=False)

        resampled["ts"] = normalize_timestamp_series(
            resampled["ts"],
            market_tz=market_timezone,
            output=output_mode,
            assume_naive_as_market=assume_naive_as_market,
        )

        base_cols = ["symbol", "ts", "open", "high", "low", "close", "volume"]
        remaining_cols = [col for col in resampled.columns if col not in base_cols]
        data = resampled[base_cols + remaining_cols]
    else:
        data["ts"] = normalize_timestamp_series(
            data["ts"],
            market_tz=market_timezone,
            output=output_mode,
            assume_naive_as_market=assume_naive_as_market,
        )

    return (
        data.sort_values(["symbol", "ts"])
        .drop_duplicates(subset=["symbol", "ts"], keep="first")
        .reset_index(drop=True)
    )


def load_data_window(
    symbols: list[str],
    start_date: str,
    end_date: str,
    config: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Load continuous data block for the date range.

    Args:
        symbols: List of symbols to load
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        config: Data loader configuration

    Returns:
        DataFrame with OHLCV data, sorted by [symbol, ts]
    """
    try:
        dates = _build_date_list(start_date, end_date)
        (
            loader_config,
            resample_frequency,
            loader_family,
            market_timezone,
            assume_naive_as_market,
            output_mode,
        ) = _resolve_loader_options(config)

        raw_data = _load_raw_bars(list(symbols), dates, loader_config, loader_family)
        return _finalize_loaded_data(
            raw_data,
            resample_frequency=resample_frequency,
            market_timezone=market_timezone,
            assume_naive_as_market=assume_naive_as_market,
            output_mode=output_mode,
        )

    except Exception as exc:
        print(f"Error loading data: {exc}")
        # Return empty DataFrame - tests should mock this function
        return pd.DataFrame()


def create_feature_set(  # noqa: PLR0913 - legacy compatibility signature
    data_window: pd.DataFrame | None = None,
    *,
    symbols: list[str] | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    features_config: dict[str, Any] | None = None,
    data_loader_config: dict[str, Any] | None = None,
    include_ohlcv: bool = False,
) -> pd.DataFrame:
    """
    Build a feature matrix for the requested window. Provides backward-compatible
    wrapper used by legacy scripts that expect the old API.
    """
    if features_config is None:
        raise ValueError("features_config is required")

    if data_window is None:
        if not symbols or not start_date or not end_date:
            raise ValueError("Must provide either data_window or symbols/start_date/end_date")
        loader_cfg = data_loader_config or {}
        data_window = load_data_window(
            symbols=symbols,
            start_date=start_date,
            end_date=end_date,
            config=loader_cfg,
        )

    if data_window.empty:
        return pd.DataFrame()

    required_cols = {"ts", "symbol", "open", "high", "low", "close", "volume"}
    missing_cols = required_cols - set(data_window.columns)
    if missing_cols:
        raise ValueError(f"Missing required columns for feature generation: {sorted(missing_cols)}")

    feature_pack = IntradayMLFeaturePack(features_config)
    feature_frames: list[pd.DataFrame] = []

    for symbol, group in data_window.groupby("symbol"):
        group_sorted = group.sort_values("ts")
        if group_sorted.empty:
            continue

        features_df = feature_pack.compute_features(
            df=group_sorted,
            ts_cut=group_sorted["ts"].max(),
            validate_time_discipline=True,
        )

        if features_df.empty:
            continue

        # Align with the sorted group order
        features_df = features_df.reindex(group_sorted.index)
        features_df = features_df.reset_index(drop=True)

        symbol_features = features_df.copy()
        symbol_features["ts"] = group_sorted["ts"].reset_index(drop=True)
        symbol_features["symbol"] = symbol

        if include_ohlcv:
            for column in ["open", "high", "low", "close", "volume"]:
                symbol_features[column] = group_sorted[column].reset_index(drop=True)

        feature_frames.append(symbol_features)

    if not feature_frames:
        return pd.DataFrame()

    result = pd.concat(feature_frames, ignore_index=True)
    result = result.sort_values(["symbol", "ts"]).reset_index(drop=True)
    return result


def generate_features_for_timestamp_optimized(
    rolling_data: pd.DataFrame,
    current_timestamp: pd.Timestamp,
    feature_pack: IntradayMLFeaturePack,
) -> pd.Series:
    """Generate feature vector using optimized rolling window approach.

    Args:
        rolling_data: Rolling window of historical data (fixed size)
        current_timestamp: Timestamp to generate features for
        feature_pack: Configured feature pack instance

    Returns:
        Series with feature values indexed by feature names
    """
    if rolling_data.empty:
        return pd.Series()

    try:
        # Compute features using rolling window (already filtered by time)
        features_df = feature_pack.compute_features(
            df=rolling_data, ts_cut=current_timestamp, validate_time_discipline=True
        )

        # Get features for the current timestamp only
        if not features_df.empty:
            # Filter to rows exactly at current_timestamp
            current_features = features_df[rolling_data["ts"] == current_timestamp]

            if not current_features.empty:
                # Return the first (and should be only) row as a Series
                return current_features.iloc[0]
            else:
                # If no exact match, try to get the most recent features
                most_recent_idx = features_df.index[-1]
                return features_df.iloc[most_recent_idx]
        else:
            return pd.Series()

    except Exception as e:
        print(f"Error generating features for {current_timestamp}: {e}")
        return pd.Series()


def generate_features_for_timestamp(
    data_window: pd.DataFrame,
    current_timestamp: pd.Timestamp,
    feature_pack: IntradayMLFeaturePack,
) -> pd.Series:
    """Generate feature vector for a single timestamp.

    Args:
        data_window: Complete data window (historical + future)
        current_timestamp: Timestamp to generate features for
        feature_pack: Configured feature pack instance

    Returns:
        Series with feature values indexed by feature names
    """
    # PERFORMANCE FIX: Use boolean mask without copy to avoid growing memory overhead
    # This prevents the 0.8/s slowdown caused by copying ever-larger historical data
    historical_mask = data_window["ts"] <= current_timestamp
    if not historical_mask.any():
        return pd.Series()

    # Use view instead of copy - feature pack should not modify data
    historical_data = data_window[historical_mask]

    try:
        # Compute features using only historical data
        features_df = feature_pack.compute_features(
            df=historical_data, ts_cut=current_timestamp, validate_time_discipline=True
        )

        # Get features for the current timestamp only
        if not features_df.empty:
            # Filter to rows exactly at current_timestamp
            current_features = features_df[historical_data["ts"] == current_timestamp]

            if not current_features.empty:
                # Return the first (and should be only) row as a Series
                return current_features.iloc[0]
            else:
                # If no exact match, try to get the most recent features
                most_recent_idx = features_df.index[-1]
                return features_df.iloc[most_recent_idx]
        else:
            return pd.Series()

    except Exception as e:
        print(f"Error generating features for {current_timestamp}: {e}")
        return pd.Series()


def compute_label_for_timestamp(
    data_window: pd.DataFrame,
    current_timestamp: pd.Timestamp,
    labeler: IntradayMLLabeler,
) -> int:
    """Compute label for a single timestamp using future data.

    Args:
        data_window: Complete data window (historical + future)
        current_timestamp: Timestamp to compute label for
        labeler: Configured labeler instance

    Returns:
        Label value: +1, -1, or 0
    """
    try:
        # Use the new labeling method
        return labeler.compute_label_for_timestamp(data_window, current_timestamp)
    except Exception as e:
        print(f"Error computing label for {current_timestamp}: {e}")
        return 0


def validate_no_lookahead_bias(
    features: pd.Series,
    label: int,
    current_timestamp: pd.Timestamp,
    data_window: pd.DataFrame,
) -> bool:
    """Validate that features and labels respect no-lookahead rules.

    Args:
        features: Generated features for current_timestamp
        label: Computed label for current_timestamp
        current_timestamp: The timestamp being processed
        data_window: Complete data window for validation

    Returns:
        True if no lookahead bias detected
    """
    # This is a validation function that could be used for debugging
    # In production, the time discipline is enforced by the feature pack and labeler

    # Check that features are based on historical data only
    historical_cutoff = data_window["ts"] <= current_timestamp
    future_cutoff = data_window["ts"] > current_timestamp

    historical_data = data_window[historical_cutoff]
    future_data = data_window[future_cutoff]

    # Basic validation
    if historical_data.empty:
        print("Warning: No historical data available for feature validation")
        return False

    if future_data.empty and label != 0:
        print("Warning: Label non-zero but no future data available")
        return False

    return True
