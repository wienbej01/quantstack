"""Stable hashing utilities for dataframes."""

import hashlib
import json
from typing import Any

import numpy as np
import pandas as pd


def hash_dataframe(
    df: pd.DataFrame,
    cols: list[str] | None = None,
    index: bool = False,
    algo: str = "blake2b",
    precision: int = 6,
) -> str:
    """Compute stable hash of DataFrame.

    Args:
        df: DataFrame to hash
        cols: Columns to include in hash. If None, uses all columns.
        index: Whether to include index in hash
        algo: Hash algorithm, default "blake2b"
        precision: Decimal precision for float values to avoid hash differences due to floating point representation

    Returns:
        Hex string of hash
    """
    if cols is None:
        cols = list(df.columns)

    # Subset columns
    subset = df[cols].copy()

    # Include index if requested
    if index:
        subset = subset.reset_index()

    # Normalize dtypes to stable representations
    for col in subset.columns:
        if subset[col].dtype == "object":
            # Handle mixed object types
            if subset[col].apply(lambda x: isinstance(x, (list, dict))).any():
                # Convert complex objects to JSON string
                subset[col] = subset[col].apply(
                    lambda x: json.dumps(x, sort_keys=True, default=str)
                )
            else:
                subset[col] = subset[col].astype(str)
        elif pd.api.types.is_datetime64_any_dtype(subset[col]):
            # Normalize to UTC nanoseconds
            if subset[col].dt.tz is None:
                subset[col] = subset[col].dt.tz_localize("UTC")
            else:
                subset[col] = subset[col].dt.tz_convert("UTC")
            subset[col] = subset[col].astype("int64")  # nanoseconds since epoch
        elif pd.api.types.is_numeric_dtype(subset[col]):
            # Normalize numeric types to standard dtypes with controlled precision
            if pd.api.types.is_integer_dtype(subset[col]):
                subset[col] = subset[col].astype("int64")
            elif pd.api.types.is_float_dtype(subset[col]):
                # Round to avoid floating point precision issues
                subset[col] = np.round(subset[col].astype("float64"), precision)

    # Sort by standard columns for consistency
    sort_cols = []
    if "symbol" in subset.columns:
        sort_cols.append("symbol")
    if "ts" in subset.columns:
        sort_cols.append("ts")

    # If no standard columns, sort by all columns to ensure deterministic ordering
    if not sort_cols:
        sort_cols = list(subset.columns)

    subset = subset.sort_values(sort_cols).reset_index(drop=True)

    # Handle NaN values consistently
    subset = subset.fillna("__NaN__")

    # Convert to JSON for consistent serialization
    try:
        # Convert DataFrame to records, then to JSON string
        json_str = json.dumps(subset.to_dict("records"), sort_keys=True, default=str)
        data_bytes = json_str.encode("utf-8")
    except (TypeError, ValueError):
        # Fallback to pickle if JSON serialization fails
        import io

        buffer = io.BytesIO()
        subset.to_pickle(buffer, protocol=4)
        data_bytes = buffer.getvalue()

    # Compute hash
    if algo == "blake2b":
        return hashlib.blake2b(data_bytes, digest_size=32).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algo: {algo}")


def hash_dict(data: dict[str, Any], algo: str = "blake2b") -> str:
    """Compute stable hash of dictionary.

    Args:
        data: Dictionary to hash
        algo: Hash algorithm, default "blake2b"

    Returns:
        Hex string of hash
    """
    # Sort keys for consistent ordering
    json_str = json.dumps(data, sort_keys=True, default=str)
    data_bytes = json_str.encode("utf-8")

    if algo == "blake2b":
        return hashlib.blake2b(data_bytes, digest_size=32).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algo: {algo}")


def hash_list(data: list[Any], algo: str = "blake2b") -> str:
    """Compute stable hash of list.

    Args:
        data: List to hash
        algo: Hash algorithm, default "blake2b"

    Returns:
        Hex string of hash
    """
    json_str = json.dumps(data, sort_keys=True, default=str)
    data_bytes = json_str.encode("utf-8")

    if algo == "blake2b":
        return hashlib.blake2b(data_bytes, digest_size=32).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algo: {algo}")


def hash_string(text: str, algo: str = "blake2b") -> str:
    """Compute hash of string.

    Args:
        text: String to hash
        algo: Hash algorithm, default "blake2b"

    Returns:
        Hex string of hash
    """
    data_bytes = text.encode("utf-8")

    if algo == "blake2b":
        return hashlib.blake2b(data_bytes, digest_size=32).hexdigest()
    elif algo == "sha256":
        return hashlib.sha256(data_bytes).hexdigest()
    else:
        raise ValueError(f"Unsupported algo: {algo}")


def compute_consistent_checksum(
    bars_hash: str,
    features_hash: str,
    sip_hash: str | None = None,
    config_hash: str | None = None,
    seed: int = 42,
) -> str:
    """Compute consistent checksum for experiment inputs.

    Args:
        bars_hash: Hash of normalized bars
        features_hash: Hash of features
        sip_hash: Hash of SIP selection (optional)
        config_hash: Hash of configuration (optional)
        seed: Random seed

    Returns:
        Combined checksum string
    """
    components = [bars_hash, features_hash, str(seed)]

    if sip_hash is not None:
        components.insert(-1, sip_hash)
    if config_hash is not None:
        components.append(config_hash)

    return hash_dict(
        {
            "bars_norm_hash": bars_hash,
            "features_hash": features_hash,
            "sip_hash": sip_hash,
            "config_hash": config_hash,
            "seed": seed,
        }
    )


def verify_hash_stability(df: pd.DataFrame, iterations: int = 10) -> bool:
    """Verify that hash remains stable across multiple computations.

    Args:
        df: DataFrame to test
        iterations: Number of hash computations to perform

    Returns:
        True if all hashes are identical
    """
    hashes = []
    for _ in range(iterations):
        h = hash_dataframe(df)
        hashes.append(h)

    return len(set(hashes)) == 1


def hash_difference(df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
    """Check if two DataFrames have different hashes.

    Args:
        df1: First DataFrame
        df2: Second DataFrame

    Returns:
        True if hashes are different
    """
    hash1 = hash_dataframe(df1)
    hash2 = hash_dataframe(df2)
    return hash1 != hash2


def hash_sip_map(universe_map: dict[int, set[str]]) -> str:
    """Compute deterministic hash of SIP universe map.

    Args:
        universe_map: Dictionary mapping timestamp (int64 ns) to set of symbols

    Returns:
        Hex string of Blake2b hash (16 bytes)
    """
    # Convert to canonical form: sorted (ts, tuple(sorted(symbols)))
    items: list[tuple[int, tuple[str, ...]]] = []
    for ts, syms in universe_map.items():
        items.append((int(ts), tuple(sorted(map(str, syms)))))
    items.sort(key=lambda x: x[0])  # Sort by timestamp

    # Build byte representation
    b = bytearray()
    for ts, syms in items:
        # Timestamp as little-endian int64 (8 bytes)
        b.extend(ts.to_bytes(8, byteorder="little", signed=True))
        # Each symbol as UTF-8 followed by null terminator
        for s in syms:
            b.extend(s.encode("utf-8"))
            b.append(0x00)  # Null terminator
        b.append(0xFF)  # Record separator

    # Compute Blake2b hash with person tag
    return hashlib.blake2b(bytes(b), digest_size=16, person=b"qx_sip_v1").hexdigest()


# Unit tests
if __name__ == "__main__":
    import numpy as np

    # Test stability across shuffles
    df1 = pd.DataFrame(
        {
            "symbol": ["AAPL", "GOOGL", "MSFT"],
            "ts": pd.to_datetime(
                ["2023-01-01 10:00", "2023-01-01 10:01", "2023-01-01 10:02"], utc=True
            ),
            "close": [150.0, 2800.0, 300.0],
        }
    )
    df2 = df1.sample(frac=1, random_state=42).reset_index(drop=True)  # Shuffle rows

    hash1 = hash_dataframe(df1)
    hash2 = hash_dataframe(df2)
    assert hash1 == hash2, f"Hashes differ after shuffle: {hash1} != {hash2}"
    print("✓ Stability across shuffles")

    # Test dtype equivalent frames
    df3 = df1.copy()
    df3["close"] = df3["close"].astype("float32")  # Different dtype but equivalent values
    hash3 = hash_dataframe(df3)
    assert hash1 == hash3, f"Hashes differ for dtype equivalent: {hash1} != {hash3}"
    print("✓ Stability across dtype equivalents")

    # Test column subset
    hash_cols = hash_dataframe(df1, cols=["symbol", "close"])
    hash_cols2 = hash_dataframe(df2, cols=["symbol", "close"])
    assert hash_cols == hash_cols2, "Column subset hashes differ"
    print("✓ Column subset stability")

    print("All tests passed!")
