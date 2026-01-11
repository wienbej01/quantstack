"""Manual implementation of LLM-selected patterns from 180m analysis."""

# Pattern 1: High ATR + Power Hour
# Rule: atr_14_bin == 4 AND is_power_hour_bin == True
# Lift: 5.86x, Support: 2.30%

# Pattern 2: Strong 60m momentum + Power Hour
# Rule: ret_60m_bin == 4.0 AND is_power_hour_bin == True
# Lift: 5.40x, Support: 2.59%

# Pattern 15: Elevated volume + Power Hour
# Rule: rvol_bin == 3 AND is_power_hour_bin == True
# Lift: 4.02x, Support: 3.76%


def evaluate_pattern_1(bar: dict) -> bool:
    """Pattern 1: High ATR + Power Hour.

    Entry: High volatility (ATR bin 4) during power hour (3-4 PM ET)
    Logic: Volatility expansion in final hour suggests continuation

    Args:
        bar: Bar data with features

    Returns:
        True if pattern matches
    """
    return bool(
        bar.get("atr_14_bin") == 4
        and bar.get("is_power_hour_bin")
        and bar.get("ret_60m_bin", 0) >= 3  # Add momentum filter
        and bar.get("rvol_bin", 0) >= 2  # Add volume filter
    )


def evaluate_pattern_2(bar: dict) -> bool:
    """Pattern 2: Strong 60m momentum + Power Hour.

    Entry: Strong 60-minute momentum (bin 4) during power hour
    Logic: Momentum continuation into close, institutional positioning

    Args:
        bar: Bar data with features

    Returns:
        True if pattern matches
    """
    return bool(
        bar.get("ret_60m_bin") == 4.0
        and bar.get("is_power_hour_bin")
        and bar.get("atr_14_bin", 0) >= 3  # Add volatility filter
        and bar.get("rvol_bin", 0) >= 2  # Add volume filter
    )


def evaluate_pattern_15(bar: dict) -> bool:
    """Pattern 15: Elevated volume + Power Hour.

    Entry: Above-average relative volume (bin 3) during power hour
    Logic: Increased participation suggests institutional interest

    Args:
        bar: Bar data with features

    Returns:
        True if pattern matches
    """
    return bool(bar.get("rvol_bin") == 3 and bar.get("is_power_hour_bin"))


# Pattern metadata for tracking
MANUAL_PATTERNS = {
    "pattern_1_high_atr_power": {
        "rule": "atr_14_bin == 4 AND is_power_hour_bin == True",
        "lift": 5.86,
        "support": 0.0230,
        "evaluator": evaluate_pattern_1,
        "description": "High ATR + Power Hour",
    },
    "pattern_2_momentum_power": {
        "rule": "ret_60m_bin == 4.0 AND is_power_hour_bin == True",
        "lift": 5.40,
        "support": 0.0259,
        "evaluator": evaluate_pattern_2,
        "description": "Strong 60m momentum + Power Hour",
    },
    "pattern_15_volume_power": {
        "rule": "rvol_bin == 3 AND is_power_hour_bin == True",
        "lift": 4.02,
        "support": 0.0376,
        "evaluator": evaluate_pattern_15,
        "description": "Elevated volume + Power Hour",
    },
}


def evaluate_all_manual_patterns(bar: dict) -> list:
    """Evaluate all manual patterns against a bar.

    Args:
        bar: Bar data with features

    Returns:
        List of pattern IDs that match
    """
    matches = []
    for pattern_id, pattern_data in MANUAL_PATTERNS.items():
        evaluator_func = pattern_data["evaluator"]
        if callable(evaluator_func) and evaluator_func(bar):
            matches.append(pattern_id)
    return matches
