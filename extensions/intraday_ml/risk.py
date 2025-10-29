"""Intraday ML risk management extension (Sprint 5).

This module wraps existing qx-risk functionality while providing
Sprint 5 interface for position sizing and risk management.
"""

import pandas as pd
from typing import Any, Dict, List

from qx_risk.atr_stop import size_order, set_stops
from qx_core.hashers import hash_dataframe


def intraday_ml_size_orders(
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    config: Dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Size orders using existing qx-risk functionality.

    Args:
        signals: DataFrame with trading signals
        bars: DataFrame with OHLCV data for risk calculations
        config: Risk management configuration

    Returns:
        DataFrame with sized orders
    """
    if config is None:
        config = {}

    # Default risk parameters
    max_risk_frac = config.get("max_risk_frac", 0.02)  # 2% of portfolio
    atr_mult = config.get("atr_mult", 1.0)
    atr_window = config.get("atr_window", 14)
    equity = config.get("equity", 1000000.0)  # $1M default

    # Create sized orders
    sized_orders = []

    for _, signal in signals.iterrows():
        # Get ATR for stop distance calculation
        symbol_data = bars[bars["symbol"] == signal["symbol"]]
        if symbol_data.empty or len(symbol_data) < atr_window:
            continue

        # Calculate ATR
        high = symbol_data["high"]
        low = symbol_data["low"]
        close = symbol_data["close"]
        atr = (high.rolling(atr_window).max() - low.rolling(atr_window).min()).iloc[-1]

        if atr > 0:
            # Convert signal to dict for existing function
            signal_dict = {
                "entry_hint": signal.get("close", signal.get("entry")),
                "stop_hint": signal.get("stop_hint"),
                "side": signal["side"],
            }

            risk_params = {
                "max_risk_frac": max_risk_frac,
                "atr_mult": atr_mult,
            }

            # Use existing qx-risk sizing function
            qty = size_order(signal_dict, equity, atr, risk_params)

            if qty is not None:
                order = {
                    "ts": signal["ts"],
                    "symbol": signal["symbol"],
                    "side": signal["side"],
                    "qty": qty,
                    "atr": atr,
                    "risk_frac": max_risk_frac,
                }
                sized_orders.append(order)

    return pd.DataFrame(sized_orders)


def intraday_ml_get_risk_hash(
    signals: pd.DataFrame,
    bars: pd.DataFrame,
    config: Dict[str, Any] | None = None,
) -> str:
    """Get deterministic hash of risk management parameters.

    Args:
        signals: Input signals DataFrame
        bars: Input bars DataFrame
        config: Risk management configuration

    Returns:
        Deterministic hash string
    """
    if config is None:
        config = {}

    # Create hash from inputs and risk parameters
    signals_hash = hash_dataframe(signals)
    bars_hash = hash_dataframe(bars)
    risk_params = {
        "config": config,
    }
    config_hash = hash_dataframe(pd.DataFrame([risk_params]))

    # Combine hashes
    return f"{signals_hash}_{bars_hash}_{config_hash}"