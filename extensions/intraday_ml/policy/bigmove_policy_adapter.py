"""Adapters that convert big-move model outputs into policy-ready signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class BigMovePolicyAdapterConfig:
    """Configuration payload for :class:`BigMovePolicyAdapter`."""

    mode: str = "probability"
    probability_threshold: float = 0.45
    quantile_threshold: float = 0.999
    prob_column: str = "prob_bigmove"
    quantile_column: str = "_bigmove_quantile"
    long_column: str = "prob_bigmove_long"
    short_column: str | None = "prob_bigmove_short"
    expected_r_column: str | None = "expected_r_bigmove"
    min_expected_r: float = 1.0

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "BigMovePolicyAdapterConfig":
        data = raw or {}
        return cls(
            mode=str(data.get("mode", cls.mode)).lower(),
            probability_threshold=float(data.get("probability_threshold", cls.probability_threshold)),
            quantile_threshold=float(data.get("quantile_threshold", cls.quantile_threshold)),
            prob_column=str(data.get("prob_column", cls.prob_column)),
            quantile_column=str(data.get("quantile_column", cls.quantile_column)),
            long_column=str(data.get("long_prob_column", cls.long_column)),
            short_column=data.get("short_prob_column", cls.short_column),
            expected_r_column=data.get("expected_r_column", cls.expected_r_column),
            min_expected_r=float(data.get("min_expected_r", cls.min_expected_r)),
        )


class BigMovePolicyAdapter:
    """Translate Stage 1/2 big-move outputs into policy-friendly columns."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = BigMovePolicyAdapterConfig.from_dict(config)

    def transform(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with unconditional probabilities and gating flags."""
        required_cols = {self.config.prob_column, self.config.long_column}
        missing = required_cols - set(signals.columns)
        if missing:
            missing_cols = ", ".join(sorted(missing))
            raise KeyError(
                f"Big-move policy mode requires columns: {sorted(required_cols)} "
                f"(missing: {missing_cols})"
            )

        df = signals.copy()
        prob_bigmove = _to_numeric(df[self.config.prob_column])
        prob_cond_long = _to_numeric(df[self.config.long_column])
        if self.config.short_column and self.config.short_column in df.columns:
            prob_cond_short = _to_numeric(df[self.config.short_column])
        else:
            prob_cond_short = 1.0 - prob_cond_long

        prob_bigmove = prob_bigmove.clip(lower=0.0, upper=1.0)
        prob_cond_long = prob_cond_long.clip(lower=0.0, upper=1.0)
        prob_cond_short = prob_cond_short.clip(lower=0.0, upper=1.0)

        conditional_sum = prob_cond_long + prob_cond_short
        overflow_mask = conditional_sum > 1.0
        if overflow_mask.any():
            prob_cond_long[overflow_mask] /= conditional_sum[overflow_mask]
            prob_cond_short[overflow_mask] /= conditional_sum[overflow_mask]

        prob_long = (prob_bigmove * prob_cond_long).clip(lower=0.0, upper=1.0)
        prob_short = (prob_bigmove * prob_cond_short).clip(lower=0.0, upper=1.0)
        prob_neutral = (1.0 - prob_long - prob_short).clip(lower=0.0, upper=1.0)

        df["prob_bigmove"] = prob_bigmove
        df["prob_long"] = prob_long
        df["prob_short"] = prob_short
        df["prob_neutral"] = prob_neutral
        mode = self.config.mode
        if mode == "probability":
            df["_bigmove_allowed"] = prob_bigmove >= self.config.probability_threshold
        elif mode == "quantile":
            raise ValueError(
                "Quantile mode for big-move gating is disabled for OOS to preserve temporal integrity."
            )
        else:
            raise ValueError(f"Unsupported bigmove_policy.mode: {mode}")

        if self.config.expected_r_column and self.config.expected_r_column in df.columns:
            expected_r = _to_numeric(df[self.config.expected_r_column])
        else:
            expected_r = pd.Series(np.nan, index=df.index)

        min_r = float(self.config.min_expected_r)
        df["_bigmove_expected_r"] = expected_r.fillna(min_r).clip(lower=min_r)

        return df


def _to_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.astype(float)


__all__ = ["BigMovePolicyAdapter"]
