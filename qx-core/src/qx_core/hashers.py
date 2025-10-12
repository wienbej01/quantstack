"""Stable hashing utilities for dataframes."""

import hashlib
from typing import List, Optional

import pandas as pd


def hash_dataframe(df: pd.DataFrame, cols: Optional[List[str]] = None, index: bool = False, algo: str = "blake2b") -> str:
    """Compute stable hash of DataFrame.

    Args:
        df: DataFrame to hash
        cols: Columns to include in hash. If None, uses all columns.
        index: Whether to include index in hash
        algo: Hash algorithm, default "blake2b"

    Returns:
        Hex string of hash
    """
    if cols is None:
        cols = list(df.columns)

    # Subset columns
    subset = df[cols].copy()

    # Normalize dtypes to stable representations
    for col in subset.columns:
        if subset[col].dtype == 'object':
            subset[col] = subset[col].astype(str)
        elif pd.api.types.is_datetime64_any_dtype(subset[col]):
            # Normalize to UTC nanoseconds
            if subset[col].dt.tz is None:
                subset[col] = subset[col].dt.tz_localize('UTC')
            else:
                subset[col] = subset[col].dt.tz_convert('UTC')
            subset[col] = subset[col].astype('int64')  # nanoseconds since epoch
        elif pd.api.types.is_numeric_dtype(subset[col]):
            # Normalize numeric types to standard dtypes
            if pd.api.types.is_integer_dtype(subset[col]):
                subset[col] = subset[col].astype('int64')
            elif pd.api.types.is_float_dtype(subset[col]):
                subset[col] = subset[col].astype('float64')

    # Sort by symbol, ts if present
    sort_cols = []
    if 'symbol' in subset.columns:
        sort_cols.append('symbol')
    if 'ts' in subset.columns:
        sort_cols.append('ts')
    if sort_cols:
        subset = subset.sort_values(sort_cols).reset_index(drop=True)

    # Serialize using pandas pickle for stability
    import io
    buffer = io.BytesIO()
    subset.to_pickle(buffer, protocol=4)  # Protocol 4 for stability
    data_bytes = buffer.getvalue()

    # Compute hash
    if algo == "blake2b":
        return hashlib.blake2b(data_bytes).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algo: {algo}")


# Unit tests
if __name__ == "__main__":
    import numpy as np

    # Test stability across shuffles
    df1 = pd.DataFrame({
        'symbol': ['AAPL', 'GOOGL', 'MSFT'],
        'ts': pd.to_datetime(['2023-01-01 10:00', '2023-01-01 10:01', '2023-01-01 10:02'], utc=True),
        'close': [150.0, 2800.0, 300.0]
    })
    df2 = df1.sample(frac=1, random_state=42).reset_index(drop=True)  # Shuffle rows

    hash1 = hash_dataframe(df1)
    hash2 = hash_dataframe(df2)
    assert hash1 == hash2, f"Hashes differ after shuffle: {hash1} != {hash2}"
    print("✓ Stability across shuffles")

    # Test dtype equivalent frames
    df3 = df1.copy()
    df3['close'] = df3['close'].astype('float32')  # Different dtype but equivalent values
    hash3 = hash_dataframe(df3)
    assert hash1 == hash3, f"Hashes differ for dtype equivalent: {hash1} != {hash3}"
    print("✓ Stability across dtype equivalents")

    # Test column subset
    hash_cols = hash_dataframe(df1, cols=['symbol', 'close'])
    hash_cols2 = hash_dataframe(df2, cols=['symbol', 'close'])
    assert hash_cols == hash_cols2, "Column subset hashes differ"
    print("✓ Column subset stability")

    print("All tests passed!")