# L2 Signal Functions - Ready for Integration
# Generated from analysis of 135k L2 snapshots

import numpy as np
import pandas as pd


def obi_regime(obi_1: float) -> str:
    """Classify OBI into regime."""
    if obi_1 < -0.3:
        return "sell"
    elif obi_1 > 0.3:
        return "buy"
    return "neutral"


def detect_hidden_liquidity(obi_1: float, obi_5: float) -> str:
    """Detect hidden institutional liquidity."""
    if obi_1 < -0.3 and obi_5 > 0.2:
        return "hidden_buy"
    elif obi_1 > 0.3 and obi_5 < -0.2:
        return "hidden_sell"
    return "none"


def obi_extreme_signal(obi_1: float, d_obi_1_15s: float) -> str:
    """Detect extreme OBI with potential reversal."""
    if obi_1 < -0.6 and d_obi_1_15s > 0:
        return "long_reversal"
    elif obi_1 > 0.6 and d_obi_1_15s < 0:
        return "short_reversal"
    return "none"


def execution_window(obi_1: float, depth_bid_k: float, depth_ask_k: float) -> str:
    """Identify favorable execution windows."""
    if obi_1 < -0.3 and depth_ask_k > depth_bid_k * 1.5:
        return "favorable_buy"
    elif obi_1 > 0.3 and depth_bid_k > depth_ask_k * 1.5:
        return "favorable_sell"
    return "neutral"


def composite_entry_score(
    obi_1: float,
    obi_5: float,
    pressure_k: float,
    pressure_mean: float,
    pressure_std: float,
) -> float:
    """Calculate composite entry score (0-1, higher = more bullish)."""
    obi_score = (obi_1 + 1) / 2
    gradient_score = ((obi_5 - obi_1) + 1) / 2
    pressure_z = (pressure_k - pressure_mean) / pressure_std
    pressure_score = (np.clip(pressure_z, -2, 2) + 2) / 4
    return 0.4 * obi_score + 0.3 * gradient_score + 0.3 * pressure_score


def thin_book_warning(
    depth_bid_k: float, depth_ask_k: float, bid_threshold: float, ask_threshold: float
) -> bool:
    """Warn if book is thin (slippage risk)."""
    return depth_bid_k < bid_threshold or depth_ask_k < ask_threshold


# Thresholds by symbol (P10 values)
THIN_BOOK_THRESHOLDS = {
    "HAL": {"bid": 3200, "ask": 4200},
    "PFE": {"bid": 31100, "ask": 38500},
    "LUV": {"bid": 2100, "ask": 2100},
}

# Pressure stats by symbol (for z-score calculation)
PRESSURE_STATS = {
    "HAL": {"mean": -700, "std": 2000},
    "PFE": {"mean": -5500, "std": 20000},
    "LUV": {"mean": -300, "std": 1700},
}
