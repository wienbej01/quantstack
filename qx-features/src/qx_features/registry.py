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
            result = _apply_core_basics(result, params)
        else:
            raise ValueError(f"Unknown feature pack: {name}")

    return result


def _apply_core_basics(df: pd.DataFrame, params: Dict[str, Any]) -> pd.DataFrame:
    """Apply core basics features."""
    from qx_features.core_basics import vwap_m, rel_volume_m, atr_m

    vwap_window = params.get('vwap_window_m', 30)
    rel_vol_window = params.get('rel_vol_window_m', 30)
    atr_window = params.get('atr_window', 14)

    # Add features
    df = df.assign(**{f'f__ta__vwap_{vwap_window}': vwap_m(df, vwap_window)})
    df = df.assign(**{f'f__vol__rel_volume_{rel_vol_window}': rel_volume_m(df, rel_vol_window)})
    df = df.assign(**{f'f__vol__atr_{atr_window}': atr_m(df, atr_window)})

    # Warmup flag: assume ok after max window
    max_window = max(vwap_window, rel_vol_window, atr_window)
    df = df.assign(f__warmup_ok=df.groupby('symbol').cumcount() >= max_window)

    return df