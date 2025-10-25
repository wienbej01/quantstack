"""ATR-based stop and sizing with regime-aware risk controls."""

from typing import Any, Dict

# Try to import regime types
try:
    from qx_core.schemas import RegimeType

    REGIME_AWARE = True
except ImportError:
    REGIME_AWARE = False
    RegimeType = None


def size_order(
    signal: dict,
    equity: float,
    atr: float,
    params: dict,
    current_regime: RegimeType | None = None,
) -> int | None:
    """Size order based on ATR risk with regime-aware adjustments.

    Args:
        signal: Signal dict
        equity: Current equity
        atr: ATR value
        params: Risk params with max_risk_frac, atr_mult
        current_regime: Current market regime for risk adjustment

    Returns:
        Quantity or None if rejected
    """
    max_risk_frac = params.get("max_risk_frac", 0.02)  # 2%
    atr_mult = params.get("atr_mult", 1.0)

    # Apply regime-based risk adjustments
    if REGIME_AWARE and current_regime:
        max_risk_frac, atr_mult = _apply_regime_risk_adjustments(
            max_risk_frac, atr_mult, current_regime, params
        )

    if atr <= 0:
        return None  # Reject tiny ATR

    entry_px = signal.get("entry_hint")
    if not entry_px:
        return None

    # Risk per share = ATR * atr_mult
    risk_per_share = atr * atr_mult

    # Max risk amount = max_risk_frac * equity
    max_risk = max_risk_frac * equity

    # Qty = max_risk / risk_per_share
    qty = int(max_risk / risk_per_share)

    # Cap position size to available equity (no leverage) while allowing at least 1 share
    max_qty_by_equity = int(equity / entry_px)
    if max_qty_by_equity <= 0:
        return None

    qty = min(qty, max_qty_by_equity)

    return max(qty, 1)  # At least 1


def set_stops(
    signal: dict, qty: int, atr: float, params: dict
) -> tuple[float | None, float | None]:
    """Set stop and target prices.

    Args:
        signal: Signal dict
        qty: Quantity
        atr: ATR
        params: Risk params

    Returns:
        (stop_price, target_price)
    """
    entry_px = signal.get("entry_hint")
    stop_hint = signal.get("stop_hint")
    atr_mult = params.get("atr_mult", 1.0)

    if not entry_px:
        return None, None

    # Stop at stop_hint or entry - ATR * mult
    stop_price = stop_hint if stop_hint else entry_px - atr * atr_mult

    # Target at entry + ATR * mult (for profit taking)
    target_price = entry_px + atr * atr_mult

    return stop_price, target_price


def _apply_regime_risk_adjustments(
    max_risk_frac: float,
    atr_mult: float,
    current_regime: RegimeType,
    params: Dict[str, Any],
) -> tuple[float, float]:
    """Apply regime-based risk adjustments.

    Args:
        max_risk_frac: Base maximum risk fraction
        atr_mult: Base ATR multiplier
        current_regime: Current market regime
        params: Risk parameters

    Returns:
        Tuple of (adjusted_max_risk_frac, adjusted_atr_mult)
    """
    if not REGIME_AWARE:
        return max_risk_frac, atr_mult

    # Default regime adjustments
    regime_adjustments = params.get(
        "regime_adjustments",
        {
            "BULL": {"risk_multiplier": 1.0, "atr_multiplier": 1.0},
            "BEAR": {
                "risk_multiplier": 0.8,
                "atr_multiplier": 1.2,
            },  # More conservative in bear
            "SIDEWAYS": {
                "risk_multiplier": 0.9,
                "atr_multiplier": 1.1,
            },  # Slightly conservative
            "STRESS": {
                "risk_multiplier": 0.3,
                "atr_multiplier": 1.5,
            },  # Very conservative in stress
            "OFF": {"risk_multiplier": 1.0, "atr_multiplier": 1.0},
        },
    )

    # Get adjustments for current regime
    adjustments = regime_adjustments.get(
        current_regime.value,
        regime_adjustments.get("OFF", {"risk_multiplier": 1.0, "atr_multiplier": 1.0}),
    )

    # Apply adjustments
    adjusted_risk_frac = max_risk_frac * adjustments["risk_multiplier"]
    adjusted_atr_mult = atr_mult * adjustments["atr_multiplier"]

    # Ensure reasonable bounds
    adjusted_risk_frac = max(0.001, min(adjusted_risk_frac, 0.1))  # 0.1% to 10%
    adjusted_atr_mult = max(0.5, min(adjusted_atr_mult, 3.0))  # 0.5x to 3x ATR

    return adjusted_risk_frac, adjusted_atr_mult


def reject_order_for_regime(signal: dict, current_regime: RegimeType | None) -> bool:
    """Check if order should be rejected based on regime.

    Args:
        signal: Trading signal
        current_regime: Current market regime

    Returns:
        True if order should be rejected
    """
    if not REGIME_AWARE or current_regime is None:
        return False

    # Reject all new orders in stress regime
    if current_regime == RegimeType.STRESS:
        return True

    # Additional regime-specific rejections can be added here
    # For example, reject trend-following in sideways regime
    # if current_regime == RegimeType.SIDEWAYS and signal.get('strategy') == 'trend_following':
    #     return True

    return False


def get_regime_risk_context(current_regime: RegimeType | None) -> Dict[str, Any]:
    """Get risk context information for current regime.

    Args:
        current_regime: Current market regime

    Returns:
        Dictionary with regime risk context
    """
    if not REGIME_AWARE or current_regime is None:
        return {"regime_aware": False}

    context = {
        "regime_aware": True,
        "current_regime": current_regime.value,
        "risk_mode": "normal",
    }

    if current_regime == RegimeType.STRESS:
        context.update(
            {
                "risk_mode": "stress",
                "risk_reduction": 0.7,  # 70% risk reduction
                "recommended_actions": [
                    "reduce_positions",
                    "tighten_stops",
                    "avoid_new_entries",
                ],
            }
        )
    elif current_regime == RegimeType.BEAR:
        context.update(
            {
                "risk_mode": "conservative",
                "risk_reduction": 0.2,  # 20% risk reduction
                "recommended_actions": ["tighten_stops", "reduce_size"],
            }
        )
    elif current_regime == RegimeType.SIDEWAYS:
        context.update(
            {
                "risk_mode": "neutral",
                "risk_reduction": 0.1,  # 10% risk reduction
                "recommended_actions": ["wider_stops", "mean_reversion_focus"],
            }
        )
    elif current_regime == RegimeType.BULL:
        context.update(
            {
                "risk_mode": "normal",
                "risk_reduction": 0.0,
                "recommended_actions": ["standard_risk"],
            }
        )

    return context
