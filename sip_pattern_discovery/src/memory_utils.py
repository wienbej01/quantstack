"""Memory utilities for large dataframe processing."""

from __future__ import annotations

import pandas as pd


def optimize_dataframe(
    df: pd.DataFrame,
    *,
    exclude_cols: set[str] | None = None,
) -> pd.DataFrame:
    """Downcast numeric columns and use categorical for symbols to reduce memory.

    This function operates in-place and returns the same DataFrame.
    """
    if exclude_cols is None:
        exclude_cols = set()

    for col in df.columns:
        if col in exclude_cols:
            continue

        if col == "symbol" and df[col].dtype == "object":
            df[col] = df[col].astype("category")
            continue

        dtype = df[col].dtype
        if dtype.kind == "f":
            df[col] = pd.to_numeric(df[col], downcast="float")
        elif dtype.kind == "i":
            df[col] = pd.to_numeric(df[col], downcast="integer")

    return df
