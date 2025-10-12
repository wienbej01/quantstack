"""VWAP reversion policy."""

from typing import Dict, Optional

import pandas as pd


def generate_signals(df: pd.DataFrame, params: Dict) -> pd.DataFrame:
    """Generate signals for VWAP reversion strategy.

    Args:
        df: DataFrame with bars and features
        params: Parameters dict with rvol_min, vwap_col, rvol_col, timeout_bars, sip_universe (optional)

    Returns:
        DataFrame with signals: ts, symbol, signal (1=long, 0=flat), and diagnostic columns
    """
    rvol_min = params.get('rvol_min', 1.0)
    vwap_col = params.get('vwap_col', 'f__ta__vwap_30')
    rvol_col = params.get('rvol_col', 'f__vol__rel_volume_30')
    timeout_bars = params.get('timeout_bars', 10)
    sip_universe = params.get('sip_universe')  # Dict[ts, Set[symbols]] or None

    signals = []
    position_tracker = {}  # symbol -> {'entry_ts': ts, 'bars_held': int}

    for idx, row in df.iterrows():
        ts = row['ts']
        symbol = row['symbol']
        close = row['close']
        vwap = row[vwap_col]
        rvol = row[rvol_col]
        warmup_ok = row.get('f__warmup_ok', True)

        # Check SIP filter
        in_sip = True
        if sip_universe and ts in sip_universe:
            in_sip = symbol in sip_universe[ts]

        # Current position
        pos = position_tracker.get(symbol, {'entry_ts': None, 'bars_held': 0})

        # Decision logic
        decision = 'hold'
        if pos['entry_ts'] is not None:
            # In position
            pos['bars_held'] += 1
            if close >= vwap or pos['bars_held'] >= timeout_bars:
                decision = 'exit'
                position_tracker[symbol] = {'entry_ts': None, 'bars_held': 0}
        else:
            # Flat
            if close < vwap and rvol >= rvol_min and in_sip and warmup_ok:
                decision = 'enter'
                position_tracker[symbol] = {'entry_ts': ts, 'bars_held': 0}

        # Signal: 1 for long, 0 for flat
        signal = 1 if pos['entry_ts'] is not None else 0

        # Diagnostic columns
        diag = {
            'ts': ts,
            'symbol': symbol,
            'signal': signal,
            'close': close,
            'vwap': vwap,
            'rvol': rvol,
            'in_sip': in_sip,
            'warmup_ok': warmup_ok,
            'bars_held': pos['bars_held'],
            'decision': decision
        }

        # Decision trace for first 200
        if len(signals) < 200:
            diag['decision_trace'] = {
                'entry_condition': close < vwap and rvol >= rvol_min and in_sip and warmup_ok,
                'exit_condition_touch': close >= vwap,
                'exit_condition_timeout': pos['bars_held'] >= timeout_bars,
                'current_position': pos['entry_ts'] is not None
            }
        else:
            diag['decision_trace'] = None

        signals.append(diag)

    return pd.DataFrame(signals)