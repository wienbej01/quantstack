"""Adapters that convert medium-move model outputs into policy-ready signals."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MediumMovePolicyAdapterConfig:
    """Configuration payload for :class:`MediumMovePolicyAdapter`."""

    mode: str = "probability"
    probability_threshold: float = 0.02
    quantile_threshold: float = 0.98
    prob_column: str = "prob_mediummove"
    quantile_column: str = "_mediummove_quantile"
    long_column: str = "prob_mediummove_long"
    short_column: str | None = "prob_mediummove_short"
    expected_r_column: str | None = "expected_r_mediummove"
    min_expected_r: float = 1.5

    @classmethod
    def from_dict(cls, raw: dict[str, Any] | None) -> "MediumMovePolicyAdapterConfig":
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


class MediumMovePolicyAdapter:
    """Translate medium-move stage outputs into policy-friendly columns."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = MediumMovePolicyAdapterConfig.from_dict(config)

    def transform(self, signals: pd.DataFrame) -> pd.DataFrame:
        """Return a DataFrame with unconditional probabilities and gating flags."""
        required_cols = {self.config.prob_column, self.config.long_column}
        missing = required_cols - set(signals.columns)
        if missing:
            missing_cols = ", ".join(sorted(missing))
            raise KeyError(
                f"Medium-move policy mode requires columns: {sorted(required_cols)} "
                f"(missing: {missing_cols})"
            )

        df = signals.copy()
        prob_mm = _to_numeric(df[self.config.prob_column]).clip(lower=0.0, upper=1.0)
        prob_cond_long = _to_numeric(df[self.config.long_column]).clip(lower=0.0, upper=1.0)
        if self.config.short_column and self.config.short_column in df.columns:
            prob_cond_short = _to_numeric(df[self.config.short_column]).clip(lower=0.0, upper=1.0)
        else:
            prob_cond_short = 1.0 - prob_cond_long

        conditional_sum = prob_cond_long + prob_cond_short
        overflow_mask = conditional_sum > 1.0
        if overflow_mask.any():
            prob_cond_long[overflow_mask] /= conditional_sum[overflow_mask]
            prob_cond_short[overflow_mask] /= conditional_sum[overflow_mask]

        prob_long = (prob_mm * prob_cond_long).clip(lower=0.0, upper=1.0)
        prob_short = (prob_mm * prob_cond_short).clip(lower=0.0, upper=1.0)
        prob_neutral = (1.0 - prob_long - prob_short).clip(lower=0.0, upper=1.0)

        df["prob_mediummove"] = prob_mm
        df["prob_long"] = prob_long
        df["prob_short"] = prob_short
        df["prob_neutral"] = prob_neutral

        mode = self.config.mode
        if mode == "probability":
            df["_mediummove_allowed"] = prob_mm >= self.config.probability_threshold
        elif mode == "quantile":
            raise ValueError(
                "Quantile mode for medium-move gating is disabled for OOS to preserve temporal integrity."
            )
        else:
            raise ValueError(f"Unsupported mediummove_policy.mode: {mode}")

        if self.config.expected_r_column and self.config.expected_r_column in df.columns:
            expected_r = _to_numeric(df[self.config.expected_r_column])
        else:
            expected_r = pd.Series(np.nan, index=df.index)

        min_r = float(self.config.min_expected_r)
        df["_mediummove_expected_r"] = expected_r.fillna(min_r).clip(lower=min_r)

        return df


def _to_numeric(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    return values.astype(float)


__all__ = ["MediumMovePolicyAdapter"]
