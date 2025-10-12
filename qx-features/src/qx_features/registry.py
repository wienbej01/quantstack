"""Feature pack registry."""

from typing import Any, Dict, List

import pandas as pd


def apply_feature_packs(df: pd.DataFrame, packs: List[Dict[str, Any]]) -> pd.DataFrame:
    """Apply multiple feature packs to the dataframe.

    Args:
        df: Input dataframe
        packs: List of dicts with 'name' and 'params'

    Returns:
        DataFrame with features added
    """
    result = df.copy()
    for pack in packs:
        name = pack['name']
        params = pack.get('params', {})

        if name == 'core_basics':
            from qx_features.core_basics import add_core_basics
            result = add_core_basics(result, **params)
        else:
            raise ValueError(f"Unknown feature pack: {name}")

    return result