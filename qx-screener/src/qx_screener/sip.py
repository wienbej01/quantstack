"""SIP screener for universe selection."""

from typing import Dict, List, Optional, Set

import pandas as pd


def screen(df: pd.DataFrame, rvol_col: str, top_n: int = 5, whitelist: Optional[List[str]] = None) -> Dict[int, Set[str]]:
    """Screen universe based on relative volume.

    Args:
        df: DataFrame with ts, symbol, and rvol_col
        rvol_col: Column name for relative volume
        top_n: Number of top symbols to select per timestamp
        whitelist: Optional list of allowed symbols

    Returns:
        Dict mapping timestamp to set of selected symbols
    """
    universe = {}
    for ts, group in df.groupby('ts'):
        # Sort by rvol descending, then symbol ascending for deterministic ties
        sorted_group = group.sort_values([rvol_col, 'symbol'], ascending=[False, True])
        candidates = sorted_group['symbol'].head(top_n).tolist()

        # Apply whitelist if provided
        if whitelist:
            candidates = [s for s in candidates if s in whitelist]

        universe[ts] = set(candidates)

    return universe