"""Prediction loading and scoring helpers for Sprint 1 evaluator."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True, slots=True)
class ProbabilityColumnMap:
    """Names of model probability columns."""

    long: str
    short: str
    flat: str | None = None


_DEFAULT_COLUMN_CANDIDATES: tuple[ProbabilityColumnMap, ...] = (
    ProbabilityColumnMap(long="prob_long", short="prob_short", flat="prob_neutral"),
    ProbabilityColumnMap(long="prob_c2", short="prob_c0", flat="prob_c1"),
    ProbabilityColumnMap(long="p_long", short="p_short", flat="p_flat"),
)


def infer_probability_columns(
    df: pd.DataFrame,
    column_map: ProbabilityColumnMap | None = None,
) -> ProbabilityColumnMap:
    """Return a valid column mapping for class probabilities."""
    if column_map:
        missing = [col for col in (column_map.long, column_map.short) if col not in df.columns]
        if missing:
            raise ValueError(f"Prediction DataFrame missing required columns: {missing}")
        if column_map.flat and column_map.flat not in df.columns:
            raise ValueError(f"Prediction DataFrame missing flat column '{column_map.flat}'")
        return column_map

    for candidate in _DEFAULT_COLUMN_CANDIDATES:
        if candidate.long in df.columns and candidate.short in df.columns:
            if candidate.flat and candidate.flat not in df.columns:
                continue
            return candidate

    raise ValueError(
        "Unable to infer prediction probability columns. Provide column_map explicitly."
    )


def score_predictions(
    df: pd.DataFrame,
    column_map: ProbabilityColumnMap | None = None,
) -> pd.DataFrame:
    """Augment a prediction DataFrame with trade probability metrics."""
    if df.empty:
        return df.copy()

    mapping = infer_probability_columns(df, column_map)
    scored = df.copy()

    p_long = scored[mapping.long].astype(float).clip(0.0, 1.0).to_numpy()
    p_short = scored[mapping.short].astype(float).clip(0.0, 1.0).to_numpy()
    if mapping.flat:
        p_flat = scored[mapping.flat].astype(float).clip(0.0, 1.0).to_numpy()
    else:
        p_flat = np.zeros_like(p_long)

    trade_prob = np.maximum(p_long, p_short)
    trade_direction = np.where(p_long >= p_short, 1, -1)
    trade_direction = np.where(trade_prob <= 0, 0, trade_direction)

    edge_margin = trade_prob - p_flat
    trade_score = trade_prob * edge_margin

    scored["trade_prob"] = trade_prob
    scored["trade_direction"] = trade_direction
    scored["edge_margin"] = edge_margin
    scored["trade_score"] = trade_score

    return scored
