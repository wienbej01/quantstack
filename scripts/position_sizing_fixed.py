#!/usr/bin/env python3
"""Fixed position sizing functions."""


def calculate_position_size_fixed(
    atr_pct, current_equity, entry_price, risk_fraction=0.01, atr_multiplier=1.5
):
    """
    Calculate position size with proper risk management.

    Args:
        atr_pct: ATR as percentage (e.g., 0.02 for 2%)
        current_equity: Current account equity
        entry_price: Entry price per share
        risk_fraction: Fraction of equity to risk (default 1%)
        atr_multiplier: ATR multiplier for stop distance

    Returns:
        shares: Number of shares to trade
    """
    # Calculate stop distance in percentage terms
    stop_distance_pct = atr_pct * atr_multiplier

    # Risk amount in dollars
    risk_amount = current_equity * risk_fraction

    # Risk per share in dollars
    risk_per_share = entry_price * stop_distance_pct

    # Calculate shares
    if risk_per_share <= 0:
        return 100  # Minimum position

    shares = int(risk_amount / risk_per_share)

    # Apply reasonable limits
    max_shares = int(current_equity * 0.1 / entry_price)  # Max 10% of equity
    min_shares = 100  # Minimum position

    shares = max(min_shares, min(shares, max_shares))

    return shares


def validate_position_size(
    shares, entry_price, current_equity, atr_pct, atr_multiplier=1.5
):
    """Validate that position size is reasonable."""
    position_value = shares * entry_price
    position_pct = position_value / current_equity

    # Calculate actual risk
    stop_distance_pct = atr_pct * atr_multiplier
    risk_amount = shares * entry_price * stop_distance_pct
    risk_pct = risk_amount / current_equity

    # Validation checks
    checks = {
        "position_under_50pct": position_pct < 0.5,
        "risk_under_5pct": risk_pct < 0.05,
        "shares_reasonable": 100 <= shares <= 10000,
        "position_value_reasonable": 1000 <= position_value <= current_equity * 0.5,
    }

    return (
        all(checks.values()),
        checks,
        {
            "position_value": position_value,
            "position_pct": position_pct,
            "risk_amount": risk_amount,
            "risk_pct": risk_pct,
        },
    )
