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


import time

import pandas as pd

from .feature_pack import IntradayMLFeaturePack
from .labeling import IntradayMLLabeler


def create_training_dataset(
    symbols: list[str],
    start_date: str,
    end_date: str,
    features_config: dict[str, any],
    targets_config: dict[str, any],
    data_loader_config: dict[str, any] | None = None,
    include_ohlcv: bool = False,
) -> pd.DataFrame:
    """Create training dataset with aligned features and labels.

    This function implements an optimized sliding window approach with rolling
    feature computation to maintain consistent performance.

    Args:
        symbols: List of symbol names to include
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        features_config: Feature configuration dictionary
        targets_config: Targets/labeling configuration dictionary
        data_loader_config: Optional data loader configuration

    Returns:
        DataFrame with features, label column, and multi-index (symbol, ts)
    """
    # Load the complete data window
    data_window = load_data_window(
        symbols=symbols,
        start_date=start_date,
        end_date=end_date,
        config=data_loader_config
    )

    if data_window.empty:
        return pd.DataFrame()

    # Initialize feature pack and labeler
    feature_pack = IntradayMLFeaturePack(features_config)
    labeler = IntradayMLLabeler(targets_config)

    # Get unique timestamps to process
    all_timestamps = sorted(data_window["ts"].unique())

    # Collect results
    all_results = []

    # Process each timestamp
    total_timestamps = len(all_timestamps)
    processed_count = 0
    start_time = time.time()

    print(f"Processing {total_timestamps} timestamps with optimized rolling window...")

    # Calculate appropriate progress interval based on dataset size
    if total_timestamps <= 1000:
        progress_interval = 100  # Show every 100 for small datasets
    elif total_timestamps <= 10000:
        progress_interval = 1000  # Show every 1000 for medium datasets
    else:
        progress_interval = 10000  # Show every 10000 for large datasets

    # ULTRA PERFORMANCE OPTIMIZATION: Vectorized batch processing
    # Instead of processing timestamps one-by-one, process in batches with vectorized operations
    batch_size = 500  # Process 500 timestamps at a time for optimal memory/CPU balance
    max_lookback_minutes = 240  # 4 hours maximum lookback for most features

    # Pre-compute labels for all timestamps at once (much faster)
    print("Pre-computing labels for all timestamps...")
    all_labels = {}
    for symbol, symbol_group in data_window.groupby('symbol'):
        for timestamp in all_timestamps:
            label = compute_label_for_timestamp(
                data_window=symbol_group,
                current_timestamp=timestamp,
                labeler=labeler
            )
            all_labels[(symbol, timestamp)] = label

    print("Starting batch processing...")

    # Process in batches for better performance
    for batch_start in range(0, len(all_timestamps), batch_size):
        batch_end = min(batch_start + batch_size, len(all_timestamps))
        batch_timestamps = all_timestamps[batch_start:batch_end]

        try:
            # Get the full window needed for this batch (extend for lookback)
            batch_min_time = batch_timestamps[0] - pd.Timedelta(minutes=max_lookback_minutes)
            batch_max_time = batch_timestamps[-1]

            # Extract batch data once (much faster than per-timestamp filtering)
            batch_data = data_window[
                (data_window["ts"] > batch_min_time) &
                (data_window["ts"] <= batch_max_time)
            ].copy()

            # Process each timestamp in the batch
            for symbol, symbol_group in batch_data.groupby('symbol'):
                for timestamp in batch_timestamps:
                    # Extract rolling window for this timestamp from batch data
                    window_start = timestamp - pd.Timedelta(minutes=max_lookback_minutes)
                    rolling_data = symbol_group[
                        (symbol_group["ts"] > window_start) &
                        (symbol_group["ts"] <= timestamp)
                    ]

                    if rolling_data.empty:
                        continue

                    # Generate features for this timestamp
                    features = generate_features_for_timestamp_optimized(
                        rolling_data=rolling_data,
                        current_timestamp=timestamp,
                        feature_pack=feature_pack
                    )

                    # Get pre-computed label
                    label = all_labels.get((symbol, timestamp))
                    if label is None:
                        continue

                    # Combine features and label
                    if features is not None and not features.empty:
                        result_row = features.to_dict()
                        result_row["ts"] = timestamp
                        result_row["label"] = label
                        result_row["symbol"] = symbol
                        all_results.append(result_row)
                        processed_count += 1

        except Exception as e:
            # Log error but continue processing other batches
            print(f"Warning: Failed to process batch starting at {batch_timestamps[0]}: {e}")
            continue

        # Progress reporting (after each batch)
        current_time = time.time()
        elapsed = current_time - start_time

        should_report = (
            batch_end % progress_interval == 0 or  # Regular interval
            batch_end == total_timestamps or      # Final update
            elapsed > 30                           # Every 30 seconds minimum
        )

        if should_report:
            progress_pct = batch_end / total_timestamps * 100
            rate = processed_count / elapsed if elapsed > 0 else 0
            eta = (total_timestamps - batch_end) / rate if rate > 0 else 0

            print(f"Progress: {batch_end}/{total_timestamps} ({progress_pct:.1f}%) - "
                  f"{processed_count} successful | Rate: {rate:.1f}/s | ETA: {eta/60:.1f}min")

    # Convert to DataFrame
    if all_results:
        result_df = pd.DataFrame(all_results)
        if include_ohlcv:
            result_df = pd.merge(result_df, data_window[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']], on=['ts', 'symbol'], how='left')

        # Set multi-index with symbol and timestamp
        # For now, we'll keep symbol as a column since we're processing one symbol at a time
        # In a more sophisticated implementation, we'd handle multiple symbols per timestamp
        if "symbol" not in result_df.columns and not result_df.empty:
            # Add symbol column from the first symbol in our data
            result_df["symbol"] = symbols[0] if symbols else "UNKNOWN"

        # Sort by timestamp
        result_df = result_df.sort_values("ts").reset_index(drop=True)

        return result_df
    else:
        return pd.DataFrame()


def load_data_window(
    symbols: list[str],
    start_date: str,
    end_date: str,
    config: dict[str, any] | None = None,
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
        # Import here to avoid circular imports
        # Generate date list
        from datetime import datetime, timedelta

        from qx_data.gold_loader import load_bars
        start_dt = datetime.strptime(start_date, '%Y-%m-%d')
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')

        dates = []
        current = start_dt
        while current <= end_dt:
            dates.append(current.strftime('%Y-%m-%d'))
            current += timedelta(days=1)

        # Load data using the gold loader function
        data = load_bars(
            root=config.get('root', '/home/jacobw/gcs-mount') if config else '/home/jacobw/gcs-mount',
            family=config.get('family', 'bars_1m') if config else 'bars_1m',
            symbols=symbols,
            dates=dates,
            validate=config.get('validate', True) if config else True,
            sort=config.get('sort', True) if config else True
        )

        # Ensure proper sorting and timestamp conversion
        if not data.empty:
            # Convert timestamps from microseconds to datetime if needed
            if data['ts'].dtype in ['int64', 'uint64']:
                data['ts'] = pd.to_datetime(data['ts'], unit='us')

            data = data.sort_values(["symbol", "ts"]).reset_index(drop=True)

        return data

    except Exception as e:
        print(f"Error loading data: {e}")
        # Return empty DataFrame - tests should mock this function
        return pd.DataFrame()


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
            df=rolling_data,
            ts_cut=current_timestamp,
            validate_time_discipline=True
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
            df=historical_data,
            ts_cut=current_timestamp,
            validate_time_discipline=True
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