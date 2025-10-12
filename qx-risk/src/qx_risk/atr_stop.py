"""ATR-based stop and sizing."""

from typing import Dict, Optional, Tuple

import pandas as pd


def size_order(signal: Dict, equity: float, atr: float, params: Dict) -> Optional[int]:
    """Size order based on ATR risk.

    Args:
        signal: Signal dict
        equity: Current equity
        atr: ATR value
        params: Risk params with max_risk_frac, atr_mult

    Returns:
        Quantity or None if rejected
    """
    max_risk_frac = params.get('max_risk_frac', 0.02)  # 2%
    atr_mult = params.get('atr_mult', 1.0)

    if atr <= 0:
        return None  # Reject tiny ATR

    entry_px = signal.get('entry_hint')
    if not entry_px:
        return None

    # Risk per share = ATR * atr_mult
    risk_per_share = atr * atr_mult

    # Max risk amount = max_risk_frac * equity
    max_risk = max_risk_frac * equity

    # Qty = max_risk / risk_per_share
    qty = int(max_risk / risk_per_share)

    # Check notional
    notional = qty * entry_px
    if notional > equity * 0.1:  # Arbitrary cap at 10% equity
        return None

    return max(qty, 1)  # At least 1


def set_stops(signal: Dict, qty: int, atr: float, params: Dict) -> Tuple[Optional[float], Optional[float]]:
    """Set stop and target prices.

    Args:
        signal: Signal dict
        qty: Quantity
        atr: ATR
        params: Risk params

    Returns:
        (stop_price, target_price)
    """
    entry_px = signal.get('entry_hint')
    stop_hint = signal.get('stop_hint')
    atr_mult = params.get('atr_mult', 1.0)

    if not entry_px:
        return None, None

    # Stop at stop_hint or entry - ATR * mult
    stop_price = stop_hint if stop_hint else entry_px - atr * atr_mult

    # Target at entry + ATR * mult (for profit taking)
    target_price = entry_px + atr * atr_mult

    return stop_price, target_price