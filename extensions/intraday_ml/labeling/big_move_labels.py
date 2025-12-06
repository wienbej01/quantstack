"""
ATR-based big-move label utilities used in Sprint 3.

The helpers in this module operate on already engineered bar datasets where
each row contains a symbol, timestamp, price column, and the ATR feature that
will be used as the volatility yardstick. Labels are expressed as:

* ``y_bigmove`` – binary flag indicating whether the forward return exceeded
  the ATR-based magnitude requirement.
* ``y_bigmove_direction`` – ternary {-1, 0, +1} label describing the direction
  of the qualified move.

The code avoids any forward-looking leakage by relying exclusively on in-row
information plus a pure forward shift when computing returns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BigMoveLabelConfig:
    """Parsed configuration for big-move labels."""

    label_name: str = "y_bigmove"
    direction_label_name: str = "y_bigmove_direction"
    forward_return_column: str = "fwd_return_bigmove"
    price_column: str = "close"
    atr_column: str = "f__vol__atr_6"
    bar_minutes: int = 10
    forward_minutes: int = 60
    atr_multiple: float = 1.5
    min_return_floor_pct: float = 0.0075
    atr_is_return_pct: bool = True

    @classmethod
    def from_targets_config(cls, targets_cfg: dict[str, Any]) -> BigMoveLabelConfig:
        """Build config from the shared targets YAML dictionary."""
        cfg = (targets_cfg or {}).get("big_move", {}) or {}
        return cls(
            label_name=str(cfg.get("label_name", cls.label_name)),
            direction_label_name=str(cfg.get("direction_label_name", cls.direction_label_name)),
            forward_return_column=str(cfg.get("forward_return_column", cls.forward_return_column)),
            price_column=str(cfg.get("price_column", cls.price_column)),
            atr_column=str(cfg.get("atr_column", cls.atr_column)),
            bar_minutes=int(cfg.get("bar_minutes", cls.bar_minutes)),
            forward_minutes=int(cfg.get("forward_minutes", cls.forward_minutes)),
            atr_multiple=float(cfg.get("atr_multiple", cls.atr_multiple)),
            min_return_floor_pct=float(cfg.get("min_return_floor_pct", cls.min_return_floor_pct)),
            atr_is_return_pct=bool(cfg.get("atr_is_return_pct", cls.atr_is_return_pct)),
        )

    @property
    def forward_bars(self) -> int:
        """Number of bars corresponding to the forward horizon."""
        if self.bar_minutes <= 0:
            raise ValueError("bar_minutes must be positive.")
        if self.forward_minutes <= 0:
            raise ValueError("forward_minutes must be positive.")
        bars = max(int(round(self.forward_minutes / self.bar_minutes)), 1)
        return bars


@dataclass(frozen=True)
class BigMoveLabelResult:
    """Structured response produced by ``compute_big_move_labels``."""

    labels: pd.Series
    directions: pd.Series
    forward_returns: pd.Series
    thresholds: pd.Series
    metadata: dict[str, Any]


def compute_big_move_labels(
    bars: pd.DataFrame,
    targets_cfg: dict[str, Any],
) -> BigMoveLabelResult:
    """
    Compute ATR-based big-move labels for a set of bars.

    Args:
        bars: Multi-symbol bar DataFrame containing at least the columns
            ``['symbol', 'ts', price_column, atr_column]``. Data must be sorted
            by symbol and timestamp or at least sortable without duplicates.
        targets_cfg: Targets configuration dictionary (parsed from YAML).

    Returns:
        ``BigMoveLabelResult`` with the binary big-move labels, the
        direction-specific label, forward returns, and helpful metadata.
    """
    config = BigMoveLabelConfig.from_targets_config(targets_cfg)
    _validate_input_columns(bars, config)

    sorted_bars = bars.sort_values(["symbol", "ts"]).reset_index(drop=True).copy()
    forward_bars = config.forward_bars

    price = sorted_bars[config.price_column].astype(float)
    sorted_bars[config.price_column] = price
    if config.atr_is_return_pct:
        atr_return = sorted_bars[config.atr_column].astype(float)
    else:
        atr_absolute = sorted_bars[config.atr_column].astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            atr_return = atr_absolute / price.replace(0.0, np.nan)

    forward_price = sorted_bars.groupby("symbol")[config.price_column].shift(-forward_bars)
    forward_return = (forward_price / price) - 1.0
    threshold = np.maximum(
        config.atr_multiple * atr_return,
        config.min_return_floor_pct,
    )

    valid_mask = forward_return.notna() & atr_return.notna()
    big_move_mask = valid_mask & (forward_return.abs() >= threshold)
    directions = np.sign(forward_return).where(big_move_mask, 0.0)

    labels = big_move_mask.astype(int)
    directions = directions.astype(int)

    result_df = sorted_bars[["symbol", "ts"]].copy()
    result_df[config.forward_return_column] = forward_return
    result_df[config.label_name] = labels
    result_df[config.direction_label_name] = directions
    result_df["big_move_threshold"] = threshold

    metadata = {
        "forward_minutes": config.forward_minutes,
        "forward_bars": forward_bars,
        "atr_multiple": config.atr_multiple,
        "min_return_floor_pct": config.min_return_floor_pct,
        "label_name": config.label_name,
        "direction_label_name": config.direction_label_name,
        "label_counts": labels.value_counts().to_dict(),
        "direction_counts": directions.value_counts().to_dict(),
    }

    return BigMoveLabelResult(
        labels=result_df[config.label_name],
        directions=result_df[config.direction_label_name],
        forward_returns=result_df[config.forward_return_column],
        thresholds=result_df["big_move_threshold"],
        metadata=metadata,
    )


def _validate_input_columns(bars: pd.DataFrame, config: BigMoveLabelConfig) -> None:
    required_cols = {"symbol", "ts", config.price_column, config.atr_column}
    missing = required_cols.difference(bars.columns)
    if missing:
        raise KeyError(
            f"Missing columns required for big-move labels: {sorted(missing)}. "
            f"Expected at least {sorted(required_cols)}."
        )
