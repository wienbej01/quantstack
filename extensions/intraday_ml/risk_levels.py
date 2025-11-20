"""Risk helper utilities for ATR-derived stop/target calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import math

import pandas as pd


@dataclass(frozen=True)
class RiskLevels:
    """Structured response for policy risk evaluation."""

    stop_pct: float
    take_profit_pct: float
    expected_r: float | None
    metadata: dict[str, Any]


def compute_risk_levels(
    *,
    row: pd.Series,
    side: str,
    config: dict[str, Any],
) -> RiskLevels | None:
    """Compute ATR-derived stops and targets for a policy signal."""
    if side not in {"long", "short"}:
        raise ValueError(f"Unsupported side '{side}' for risk level computation.")

    cfg = dict(config or {})
    price_column = cfg.get("price_column", "close")
    price = _get_numeric(row, price_column)
    if price is None or price <= 0:
        return None

    atr = _get_numeric(row, cfg.get("atr_feature", "f__vol__atr_6"))
    if atr is None or atr <= 0:
        return None

    stop_atr_multiple = float(cfg.get("stop_atr_multiple", cfg.get("max_atr_multiple", 1.0)))
    tp_r_multiple = float(cfg.get("tp_r_multiple", cfg.get("target_r_multiple", 1.5)))
    min_stop_pct = float(cfg.get("min_stop_pct", 0.0005))
    max_stop_pct = float(cfg.get("max_stop_pct", 0.05))

    stop_distance_abs = stop_atr_multiple * atr
    stop_distance_abs = max(stop_distance_abs, price * min_stop_pct)
    stop_distance_abs = min(stop_distance_abs, price * max_stop_pct)
    if stop_distance_abs <= 0:
        return None

    stop_pct = stop_distance_abs / price
    if side == "long":
        stop_price = price - stop_distance_abs
    else:
        stop_price = price + stop_distance_abs

    target_distance_abs = stop_distance_abs * max(tp_r_multiple, 1.0)
    take_profit_pct = target_distance_abs / price
    take_price = price + target_distance_abs if side == "long" else price - target_distance_abs

    expected_r_value = float(tp_r_multiple) if math.isfinite(tp_r_multiple) else None

    metadata = {
        "risk_stop_price": float(stop_price),
        "risk_take_profit_price": float(take_price),
        "risk_distance": float(stop_distance_abs),
        "risk_target_distance": float(target_distance_abs),
        "risk_reference_level": None,
        "risk_atr": float(atr),
        "risk_atr_multiple_stop": float(stop_distance_abs / atr) if atr > 0 else None,
        "expected_r": expected_r_value,
    }

    return RiskLevels(
        stop_pct=float(stop_pct),
        take_profit_pct=float(take_profit_pct),
        expected_r=expected_r_value,
        metadata=metadata,
    )


def _get_numeric(row: pd.Series, column: str | None) -> float | None:
    if not column or column not in row:
        return None
    value = row[column]
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(numeric):
        return None
    return numeric
