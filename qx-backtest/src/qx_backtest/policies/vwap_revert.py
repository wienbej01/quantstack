"""VWAP reversion policy."""

from typing import Dict, Optional

import pandas as pd


def generate_signals(df: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """Generate signals for VWAP reversion strategy.

    Args:
        df: DataFrame with bars and features
        params: Parameters dict with rvol_min, sip_universe (optional)

    Returns:
        DataFrame with signals
    """
    rvol_min = params.get('rvol_min', 1.0)
    sip_universe = params.get('sip_universe')  # Dict[ts, List[symbols]] or None

    signals = []

    for _, row in df.iterrows():
        ts = row['ts']
        symbol = row['symbol']
        close = row['close']
        vwap = row['f__ta__vwap_m']
        rvol = row['f__vol__rel_volume_m']

        # Check SIP filter
        if sip_universe and ts in sip_universe:
            if symbol not in sip_universe[ts]:
                continue  # Skip if not in universe

        # Entry condition
        if close < vwap and rvol >= rvol_min:
            signals.append({
                'ts': ts,
                'symbol': symbol,
                'side': 'BUY',
                'strength': 1.0,
                'entry_hint': close,
                'stop_hint': vwap,
                'tag': 'vwap_revert',
                'src': 'policy'
            })
        # Exit condition (simplified: when close >= vwap)
        elif close >= vwap:
            signals.append({
                'ts': ts,
                'symbol': symbol,
                'side': 'SELL',
                'strength': 0.0,
                'entry_hint': None,
                'stop_hint': None,
                'tag': 'vwap_revert_exit',
                'src': 'policy'
            })

    return pd.DataFrame(signals)