"""SIP screener for universe selection."""

from typing import Dict, List, Optional

import pandas as pd


def screen(df: pd.DataFrame, rvol_col: str, top_n: int = 5, whitelist: Optional[List[str]] = None) -> Dict[pd.Timestamp, List[str]]:
    """Screen universe based on relative volume.

    Args:
        df: DataFrame with ts, symbol, and rvol_col
        rvol_col: Column name for relative volume
        top_n: Number of top symbols to select per timestamp
        whitelist: Optional list of allowed symbols

    Returns:
        Dict mapping timestamp to list of selected symbols
    """
    universe = {}
    for ts, group in df.groupby('ts'):
        # Sort by rvol descending
        sorted_group = group.sort_values(rvol_col, ascending=False)
        candidates = sorted_group['symbol'].head(top_n).tolist()

        # Apply whitelist if provided
        if whitelist:
            candidates = [s for s in candidates if s in whitelist]

        universe[ts] = candidates

    return universe