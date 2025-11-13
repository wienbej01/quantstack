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
    """Compute ATR/support-derived stops and targets for a policy signal."""
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

    max_atr_multiple = float(cfg.get("max_atr_multiple", 1.25))
    buffer_mult = float(cfg.get("support_buffer_atr", 0.1))
    allow_missing_support = bool(cfg.get("allow_missing_support", True))
    min_stop_pct = float(cfg.get("min_stop_pct", 0.0005))
    max_stop_pct = float(cfg.get("max_stop_pct", 0.05))
    target_r_multiple = float(cfg.get("target_r_multiple", 1.5))

    stop_distance_abs: float | None = None
    reference_level: float | None = None
    atr_cap = atr * max(max_atr_multiple, 1e-6)
    buffer_abs = buffer_mult * atr

    if side == "long":
        level = _get_numeric(row, cfg.get("support_feature_long", "low"))
        if level is not None:
            reference_level = level
            stop_price_candidate = level - buffer_abs
            if stop_price_candidate >= price:
                return None
            candidate_distance = price - stop_price_candidate
            if candidate_distance <= 0 or candidate_distance > atr_cap + 1e-9:
                return None
            stop_distance_abs = candidate_distance
        elif not allow_missing_support:
            return None
    else:
        level = _get_numeric(row, cfg.get("resistance_feature_short", "high"))
        if level is not None:
            reference_level = level
            stop_price_candidate = level + buffer_abs
            if stop_price_candidate <= price:
                return None
            candidate_distance = stop_price_candidate - price
            if candidate_distance <= 0 or candidate_distance > atr_cap + 1e-9:
                return None
            stop_distance_abs = candidate_distance
        elif not allow_missing_support:
            return None

    if stop_distance_abs is None:
        stop_distance_abs = atr_cap

    stop_distance_abs = max(stop_distance_abs, price * min_stop_pct)
    stop_distance_abs = min(stop_distance_abs, price * max_stop_pct)
    stop_distance_abs = min(stop_distance_abs, atr_cap)
    if stop_distance_abs <= 0:
        return None

    stop_pct = stop_distance_abs / price
    if side == "long":
        stop_price = price - stop_distance_abs
    else:
        stop_price = price + stop_distance_abs

    target_distance_abs = stop_distance_abs * max(target_r_multiple, 1.0)
    take_profit_pct = target_distance_abs / price
    take_price = price + target_distance_abs if side == "long" else price - target_distance_abs

    expected_r = take_profit_pct / stop_pct if stop_pct > 0 else math.nan
    expected_r_value = float(expected_r) if math.isfinite(expected_r) else None

    metadata = {
        "risk_stop_price": float(stop_price),
        "risk_take_profit_price": float(take_price),
        "risk_distance": float(stop_distance_abs),
        "risk_target_distance": float(target_distance_abs),
        "risk_reference_level": float(reference_level) if reference_level is not None else None,
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
