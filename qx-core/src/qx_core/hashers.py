"""Stable hashing utilities for dataframes."""

import hashlib
from typing import List, Optional

import pandas as pd


def hash_dataframe(df: pd.DataFrame, cols: Optional[List[str]] = None) -> str:
    """Compute stable hash of DataFrame.

    Args:
        df: DataFrame to hash
        cols: Columns to include in hash. If None, uses all columns.

    Returns:
        Hex string of SHA256 hash
    """
    if cols is None:
        cols = list(df.columns)

    # Ensure consistent column order
    cols = sorted(cols)

    # Convert to string representation, sorted by index for determinism
    data_str = df[cols].sort_index().to_csv(index=False)

    # Compute hash
    return hashlib.sha256(data_str.encode('utf-8')).hexdigest()