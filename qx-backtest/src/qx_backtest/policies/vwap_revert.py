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

        # Get position state from START of bar
        pos_before_decision = position_tracker.get(symbol, {'entry_ts': None, 'bars_held': 0})

        # Decision logic
        decision = 'hold'
        if pos_before_decision['entry_ts'] is not None:
            # In position
            new_bars_held = pos_before_decision['bars_held'] + 1
            if close >= vwap or new_bars_held >= timeout_bars:
                decision = 'exit'
                position_tracker[symbol] = {'entry_ts': None, 'bars_held': 0}
            else:
                position_tracker[symbol]['bars_held'] = new_bars_held
        else:
            # Flat
            if close < vwap and rvol >= rvol_min and in_sip and warmup_ok:
                decision = 'enter'
                position_tracker[symbol] = {'entry_ts': ts, 'bars_held': 1}

        # Get position state AFTER decision for the current bar
        pos_after_decision = position_tracker.get(symbol, {'entry_ts': None, 'bars_held': 0})
        
        # Generate signal based on the state AFTER the decision
        signal = 1 if pos_after_decision['entry_ts'] is not None else 0

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
            'bars_held': pos_after_decision['bars_held'],
            'decision': decision
        }
        signals.append(diag)

    return pd.DataFrame(signals)