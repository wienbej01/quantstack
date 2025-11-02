"""Policy calibration utilities for dynamic thresholding across symbols."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


def _percentile_key(percentile: float) -> str:
    """Convert percentile value (0-1) to dict key."""
    return f"p{int(round(percentile * 100))}"


def _sanitize(value: float | None, fallback: float) -> float:
    """Ensure numeric outputs are finite floats."""
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return float(fallback)
    return float(value)


def _metric_summary(values: pd.Series, quantiles: Iterable[float]) -> dict[str, Any]:
    """Create summary statistics for a numeric series."""
    cleaned = values.astype(float).replace([np.inf, -np.inf], np.nan).dropna()
    if cleaned.empty:
        return {
            "mean": None,
            "std": None,
            "min": None,
            "max": None,
            "quantiles": {},
        }

    summary = {
        "mean": float(cleaned.mean()),
        "std": float(cleaned.std(ddof=0)),
        "min": float(cleaned.min()),
        "max": float(cleaned.max()),
        "quantiles": {},
    }
    for q in quantiles:
        key = _percentile_key(q)
        summary["quantiles"][key] = float(np.quantile(cleaned, q))

    return summary


def compute_policy_calibration_stats(
    model: Any,
    data: pd.DataFrame,
    feature_columns: list[str],
    calibration_config: dict[str, Any] | None = None,
    *,
    symbol_column: str = "symbol",
) -> dict[str, Any]:
    """Compute per-symbol probability / conviction summaries for policy calibration."""
    if data.empty:
        raise ValueError("Cannot compute calibration statistics on empty dataset.")

    calibration_config = calibration_config or {}
    quantiles = [
        float(q) for q in calibration_config.get("quantiles", [0.5, 0.75, 0.9])
    ]
    extra_percentiles = [
        calibration_config.get("prob_long_percentile"),
        calibration_config.get("prob_short_percentile"),
        calibration_config.get("gap_percentile"),
        calibration_config.get("conviction_percentile"),
    ]
    quantiles = sorted(
        {
            round(float(q), 4)
            for q in quantiles + [p for p in extra_percentiles if p is not None]
        }
    )
    max_samples_per_symbol = calibration_config.get("max_samples_per_symbol")

    sample_df = data
    if max_samples_per_symbol:
        sample_df = data.groupby(symbol_column, group_keys=False).head(
            max_samples_per_symbol
        )

    symbols = sample_df[symbol_column].astype(str).str.upper().reset_index(drop=True)
    feature_matrix = sample_df[feature_columns].fillna(0.0)

    probabilities = model.predict_proba(feature_matrix)
    classes = [int(cls) for cls in model.classes_]
    class_positions = {int(cls): idx for idx, cls in enumerate(classes)}

    try:
        prob_short = probabilities[:, class_positions[-1]]
        prob_neutral = probabilities[:, class_positions[0]]
        prob_long = probabilities[:, class_positions[1]]
    except KeyError as exc:
        raise ValueError(
            f"Model classes must include -1, 0, 1 for triclass outputs (found {classes})."
        ) from exc

    stats_frame = pd.DataFrame(
        {
            "symbol": symbols,
            "prob_short": prob_short,
            "prob_neutral": prob_neutral,
            "prob_long": prob_long,
        }
    )
    stats_frame["directional_gap"] = (
        stats_frame["prob_long"] - stats_frame["prob_short"]
    ).abs()
    stats_frame["conviction"] = stats_frame["directional_gap"] * stats_frame[
        ["prob_long", "prob_short"]
    ].max(axis=1)
    stats_frame["prob_max"] = np.max(probabilities, axis=1)

    symbols_stats: dict[str, Any] = {}
    for symbol, group in stats_frame.groupby("symbol"):
        summary = {
            "sample_count": int(len(group)),
            "prob_long": _metric_summary(group["prob_long"], quantiles),
            "prob_short": _metric_summary(group["prob_short"], quantiles),
            "directional_gap": _metric_summary(group["directional_gap"], quantiles),
            "conviction": _metric_summary(group["conviction"], quantiles),
            "prob_max": _metric_summary(group["prob_max"], quantiles),
        }
        symbols_stats[symbol] = summary

    global_summary = {
        "sample_count": int(len(stats_frame)),
        "prob_long": _metric_summary(stats_frame["prob_long"], quantiles),
        "prob_short": _metric_summary(stats_frame["prob_short"], quantiles),
        "directional_gap": _metric_summary(stats_frame["directional_gap"], quantiles),
        "conviction": _metric_summary(stats_frame["conviction"], quantiles),
        "prob_max": _metric_summary(stats_frame["prob_max"], quantiles),
    }

    return {
        "metadata": {
            "quantiles": quantiles,
            "classes": classes,
            "total_samples": int(len(stats_frame)),
        },
        "symbols": symbols_stats,
        "global": global_summary,
    }


class SymbolThresholdCalibrator:
    """Load calibration stats and derive per-symbol policy thresholds."""

    def __init__(
        self,
        calibration_config: dict[str, Any] | None,
        base_thresholds: dict[str, float],
    ):
        self.base_thresholds = dict(base_thresholds)
        self.enabled = False
        self.config = calibration_config or {}
        self.min_samples = self.config.get("min_samples", 0)
        self.prob_long_percentile = self.config.get("prob_long_percentile", 0.75)
        self.prob_short_percentile = self.config.get("prob_short_percentile", 0.75)
        self.gap_percentile = self.config.get("gap_percentile", 0.75)
        self.conviction_percentile = self.config.get("conviction_percentile", 0.75)
        self.prob_exit_offset = self.config.get("prob_exit_offset", 0.05)
        self._reported_symbols: set[str] = set()

        stats_path = self.config.get("stats_path")
        if not stats_path:
            self.symbol_stats = {}
            self.global_stats = {}
            return

        stats_data = json.loads(Path(stats_path).read_text())
        symbols_section = stats_data.get("symbols", {})
        self.symbol_stats = {
            symbol.upper(): data for symbol, data in symbols_section.items()
        }
        self.global_stats = stats_data.get("global", {})
        self.enabled = bool(self.symbol_stats or self.global_stats)

    def get_thresholds(self, symbol: str) -> dict[str, float]:
        """Return thresholds for the provided symbol, falling back to global/base values."""
        thresholds = dict(self.base_thresholds)
        if not self.enabled:
            return thresholds

        symbol_key = symbol.upper()
        stats = self.symbol_stats.get(symbol_key)

        source = "symbol"
        if not stats or stats.get("sample_count", 0) < self.min_samples:
            stats = self.global_stats
            source = "global"

        if not stats:
            return thresholds

        prob_long = self._select(stats, "prob_long", self.prob_long_percentile)
        prob_short = self._select(stats, "prob_short", self.prob_short_percentile)
        gap_value = self._select(stats, "directional_gap", self.gap_percentile)
        conviction_value = self._select(stats, "conviction", self.conviction_percentile)

        if prob_long is not None:
            raw_long = max(prob_long, thresholds["prob_threshold_long"])
            thresholds["prob_threshold_long"] = min(
                _sanitize(raw_long, thresholds["prob_threshold_long"]), 0.999
            )
        else:
            thresholds["prob_threshold_long"] = float(thresholds["prob_threshold_long"])

        if prob_short is not None:
            raw_short = max(prob_short, thresholds["prob_threshold_short"])
            thresholds["prob_threshold_short"] = min(
                _sanitize(raw_short, thresholds["prob_threshold_short"]), 0.999
            )
        else:
            thresholds["prob_threshold_short"] = float(
                thresholds["prob_threshold_short"]
            )

        thresholds["exit_threshold_long"] = min(
            _sanitize(
                max(
                    thresholds["exit_threshold_long"],
                    thresholds["prob_threshold_long"] - self.prob_exit_offset,
                ),
                thresholds["exit_threshold_long"],
            ),
            0.999,
        )
        thresholds["exit_threshold_short"] = min(
            _sanitize(
                max(
                    thresholds["exit_threshold_short"],
                    thresholds["prob_threshold_short"] - self.prob_exit_offset,
                ),
                thresholds["exit_threshold_short"],
            ),
            0.999,
        )

        if gap_value is not None:
            raw_gap = max(gap_value, thresholds["min_directional_gap"])
            thresholds["min_directional_gap"] = min(
                _sanitize(raw_gap, thresholds["min_directional_gap"]), 0.999
            )
        else:
            thresholds["min_directional_gap"] = float(thresholds["min_directional_gap"])

        if conviction_value is not None:
            raw_conviction = max(conviction_value, thresholds["min_conviction_score"])
            thresholds["min_conviction_score"] = min(
                _sanitize(raw_conviction, thresholds["min_conviction_score"]), 0.999
            )
        else:
            thresholds["min_conviction_score"] = float(
                thresholds["min_conviction_score"]
            )

        if symbol_key not in self._reported_symbols:
            print(
                f"   Calibrated policy thresholds for {symbol_key} using {source} statistics "
                f"(prob_long≥{thresholds['prob_threshold_long']:.3f}, "
                f"gap≥{thresholds['min_directional_gap']:.3f})"
            )
            self._reported_symbols.add(symbol_key)

        return thresholds

    def _select(
        self, stats: dict[str, Any], metric: str, percentile: float
    ) -> float | None:
        metric_stats = stats.get(metric)
        if not metric_stats:
            return None

        quantiles = metric_stats.get("quantiles", {})
        key = _percentile_key(percentile)
        value = quantiles.get(key)
        if value is None:
            value = metric_stats.get("mean")
        return value if value is None else float(value)
