"""Policy calibration utilities for dynamic thresholding across symbols."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

from extensions.intraday_ml.risk_levels import compute_risk_levels


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


def _directional_bias(summary: dict[str, Any]) -> float | None:
    """Compute directional bias from probability summaries."""
    long_stats = summary.get("prob_long", {})
    short_stats = summary.get("prob_short", {})
    long_mean = long_stats.get("mean")
    short_mean = short_stats.get("mean")
    if long_mean is None or short_mean is None:
        return None
    if not np.isfinite(long_mean) or not np.isfinite(short_mean):
        return None
    return float(long_mean - short_mean)


def compute_policy_calibration_stats(
    model: Any,
    data: pd.DataFrame,
    feature_columns: list[str],
    calibration_config: dict[str, Any] | None = None,
    *,
    symbol_column: str = "symbol",
    risk_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute per-symbol probability / conviction summaries for policy calibration."""
    if data.empty:
        raise ValueError("Cannot compute calibration statistics on empty dataset.")

    calibration_config = calibration_config or {}
    quantiles = [float(q) for q in calibration_config.get("quantiles", [0.5, 0.75, 0.9])]
    extra_percentiles = [
        calibration_config.get("prob_long_percentile"),
        calibration_config.get("prob_short_percentile"),
        calibration_config.get("gap_percentile"),
        calibration_config.get("conviction_percentile"),
    ]
    quantiles = sorted(
        {round(float(q), 4) for q in quantiles + [p for p in extra_percentiles if p is not None]}
    )
    max_samples_per_symbol = calibration_config.get("max_samples_per_symbol")

    sample_df = data
    if max_samples_per_symbol:
        sample_df = data.groupby(symbol_column, group_keys=False).head(max_samples_per_symbol)

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

    expected_r_values: list[float | None] = [None] * len(sample_df)
    helper_cfg = dict(risk_config or {})
    if helper_cfg:
        helper_cfg.setdefault("price_column", "close")
        helper_cfg.setdefault("atr_feature", helper_cfg.get("atr_feature", "f__vol__atr_6"))
        helper_cfg.setdefault("support_feature_long", helper_cfg.get("support_feature_long", "low"))
        helper_cfg.setdefault(
            "resistance_feature_short", helper_cfg.get("resistance_feature_short", "high")
        )
        sample_reset = sample_df.reset_index(drop=True)
        for idx, row in sample_reset.iterrows():
            side = "long" if prob_long[idx] >= prob_short[idx] else "short"
            levels = compute_risk_levels(row=row, side=side, config=helper_cfg)
            expected_r_values[idx] = levels.expected_r if levels else None

    long_margin = prob_long - np.maximum(prob_short, prob_neutral)
    short_margin = prob_short - np.maximum(prob_long, prob_neutral)
    score_margin = np.maximum(long_margin, short_margin)

    stats_frame = pd.DataFrame(
        {
            "symbol": symbols,
            "prob_short": prob_short,
            "prob_neutral": prob_neutral,
            "prob_long": prob_long,
            "score_margin": score_margin,
        }
    )
    stats_frame["directional_gap"] = (stats_frame["prob_long"] - stats_frame["prob_short"]).abs()
    stats_frame["conviction"] = stats_frame["directional_gap"] * stats_frame[
        ["prob_long", "prob_short"]
    ].max(axis=1)
    stats_frame["prob_max"] = np.max(probabilities, axis=1)
    stats_frame["expected_r"] = expected_r_values

    symbols_stats: dict[str, Any] = {}
    for symbol, group in stats_frame.groupby("symbol"):
        summary = {
            "sample_count": int(len(group)),
            "prob_long": _metric_summary(group["prob_long"], quantiles),
            "prob_short": _metric_summary(group["prob_short"], quantiles),
            "directional_gap": _metric_summary(group["directional_gap"], quantiles),
            "conviction": _metric_summary(group["conviction"], quantiles),
            "prob_max": _metric_summary(group["prob_max"], quantiles),
            "expected_r": _metric_summary(group["expected_r"], quantiles),
            "score_margin": _metric_summary(group["score_margin"], quantiles),
        }
        summary["directional_bias"] = _directional_bias(summary)
        symbols_stats[symbol] = summary

    global_summary = {
        "sample_count": int(len(stats_frame)),
        "prob_long": _metric_summary(stats_frame["prob_long"], quantiles),
        "prob_short": _metric_summary(stats_frame["prob_short"], quantiles),
        "directional_gap": _metric_summary(stats_frame["directional_gap"], quantiles),
        "conviction": _metric_summary(stats_frame["conviction"], quantiles),
        "prob_max": _metric_summary(stats_frame["prob_max"], quantiles),
        "expected_r": _metric_summary(stats_frame["expected_r"], quantiles),
        "score_margin": _metric_summary(stats_frame["score_margin"], quantiles),
    }
    global_summary["directional_bias"] = _directional_bias(global_summary)

    return {
        "metadata": {
            "quantiles": quantiles,
            "classes": classes,
            "total_samples": int(len(stats_frame)),
            "directional_bias": global_summary.get("directional_bias"),
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
        self.expected_r_percentile = self.config.get("expected_r_percentile", 0.5)
        self.score_margin_percentile = self.config.get("score_margin_percentile", 0.75)
        self.prob_exit_offset = self.config.get("prob_exit_offset", 0.05)
        self.bias_config = self.config.get("bias_correction", {})
        self.bias_enabled = bool(self.bias_config.get("enabled", False))
        self._reported_symbols: set[str] = set()

        floors_cfg = self.config.get("floors", {})
        ceilings_cfg = self.config.get("ceilings", {})
        self.floors = {
            "prob_threshold_long": self._maybe_float(floors_cfg.get("prob_threshold_long")),
            "prob_threshold_short": self._maybe_float(floors_cfg.get("prob_threshold_short")),
            "exit_threshold_long": self._maybe_float(floors_cfg.get("exit_threshold_long")),
            "exit_threshold_short": self._maybe_float(floors_cfg.get("exit_threshold_short")),
            "min_directional_gap": self._maybe_float(floors_cfg.get("min_directional_gap")),
            "min_conviction_score": self._maybe_float(floors_cfg.get("min_conviction_score")),
            "min_expected_r": self._maybe_float(floors_cfg.get("min_expected_r")),
            "score_margin": self._maybe_float(floors_cfg.get("score_margin")),
        }
        self.ceilings = {
            "prob_threshold_long": self._maybe_float(
                ceilings_cfg.get("prob_threshold_long"), default=0.999
            ),
            "prob_threshold_short": self._maybe_float(
                ceilings_cfg.get("prob_threshold_short"), default=0.999
            ),
            "exit_threshold_long": self._maybe_float(ceilings_cfg.get("exit_threshold_long")),
            "exit_threshold_short": self._maybe_float(ceilings_cfg.get("exit_threshold_short")),
            "min_directional_gap": self._maybe_float(
                ceilings_cfg.get("min_directional_gap"), default=1.0
            ),
            "min_conviction_score": self._maybe_float(
                ceilings_cfg.get("min_conviction_score"), default=1.0
            ),
            "min_expected_r": self._maybe_float(ceilings_cfg.get("min_expected_r"), default=5.0),
            "score_margin": self._maybe_float(ceilings_cfg.get("score_margin"), default=1.0),
        }

        stats_path = self.config.get("stats_path")
        if not stats_path:
            self.symbol_stats = {}
            self.global_stats = {}
            return

        stats_data = json.loads(Path(stats_path).read_text())
        symbols_section = stats_data.get("symbols", {})
        self.symbol_stats = {symbol.upper(): data for symbol, data in symbols_section.items()}
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
        expected_r_value = self._select(stats, "expected_r", self.expected_r_percentile)
        score_margin_value = self._select(stats, "score_margin", self.score_margin_percentile)

        if prob_long is not None:
            thresholds["prob_threshold_long"] = self._bounded_threshold(
                "prob_threshold_long",
                prob_long,
                thresholds["prob_threshold_long"],
                default_ceiling=0.999,
            )
        else:
            thresholds["prob_threshold_long"] = float(thresholds["prob_threshold_long"])

        if prob_short is not None:
            thresholds["prob_threshold_short"] = self._bounded_threshold(
                "prob_threshold_short",
                prob_short,
                thresholds["prob_threshold_short"],
                default_ceiling=0.999,
            )
        else:
            thresholds["prob_threshold_short"] = float(thresholds["prob_threshold_short"])

        thresholds = self._apply_bias_correction(thresholds, stats)

        exit_long_candidate = thresholds["prob_threshold_long"] - self.prob_exit_offset
        thresholds["exit_threshold_long"] = self._bounded_threshold(
            "exit_threshold_long",
            exit_long_candidate,
            thresholds["exit_threshold_long"],
            default_ceiling=thresholds["prob_threshold_long"],
        )
        exit_short_candidate = thresholds["prob_threshold_short"] - self.prob_exit_offset
        thresholds["exit_threshold_short"] = self._bounded_threshold(
            "exit_threshold_short",
            exit_short_candidate,
            thresholds["exit_threshold_short"],
            default_ceiling=thresholds["prob_threshold_short"],
        )

        if gap_value is not None:
            thresholds["min_directional_gap"] = self._bounded_threshold(
                "min_directional_gap",
                gap_value,
                thresholds["min_directional_gap"],
                default_ceiling=1.0,
            )
        else:
            thresholds["min_directional_gap"] = float(thresholds["min_directional_gap"])

        if conviction_value is not None:
            thresholds["min_conviction_score"] = self._bounded_threshold(
                "min_conviction_score",
                conviction_value,
                thresholds["min_conviction_score"],
                default_ceiling=1.0,
            )
        else:
            thresholds["min_conviction_score"] = float(thresholds["min_conviction_score"])

        base_expected_r = thresholds.get(
            "min_expected_r", self.base_thresholds.get("min_expected_r", 1.5)
        )
        if expected_r_value is not None:
            thresholds["min_expected_r"] = self._bounded_threshold(
                "min_expected_r",
                expected_r_value,
                base_expected_r,
                default_ceiling=5.0,
            )
        else:
            thresholds["min_expected_r"] = float(base_expected_r)

        if score_margin_value is not None:
            thresholds["score_margin"] = self._bounded_threshold(
                "score_margin",
                score_margin_value,
                thresholds["score_margin"],
                default_ceiling=1.0,
            )
        else:
            thresholds["score_margin"] = float(thresholds["score_margin"])

        if symbol_key not in self._reported_symbols:
            print(
                f"   Calibrated policy thresholds for {symbol_key} using {source} statistics "
                f"(prob_long≥{thresholds['prob_threshold_long']:.3f}, "
                f"gap≥{thresholds['min_directional_gap']:.3f})"
            )
            self._reported_symbols.add(symbol_key)

        return thresholds

    def _select(self, stats: dict[str, Any], metric: str, percentile: float) -> float | None:
        metric_stats = stats.get(metric)
        if not metric_stats:
            return None

        quantiles = metric_stats.get("quantiles", {})
        key = _percentile_key(percentile)
        value = quantiles.get(key)
        if value is None:
            value = metric_stats.get("mean")
        return value if value is None else float(value)

    def _apply_bias_correction(
        self, thresholds: dict[str, float], stats: dict[str, Any] | None
    ) -> dict[str, float]:
        """Apply bias correction to directional thresholds when long/short probabilities diverge."""
        if not self.bias_enabled or not stats:
            return thresholds

        metric_key = self.bias_config.get("metric", "mean")
        scale = float(self.bias_config.get("scale", 0.5))
        max_adjustment = float(self.bias_config.get("max_adjustment", 0.05))
        apply_to_exit = bool(self.bias_config.get("apply_to_exit", True))

        prob_long_metric = self._metric_value(stats, "prob_long", metric_key)
        prob_short_metric = self._metric_value(stats, "prob_short", metric_key)

        if (
            prob_long_metric is None
            or prob_short_metric is None
            or not np.isfinite(prob_long_metric)
            or not np.isfinite(prob_short_metric)
        ):
            return thresholds

        bias_delta = float(prob_long_metric - prob_short_metric)
        if abs(bias_delta) < 1e-6:
            return thresholds

        adjustment = float(np.clip(-bias_delta * scale, -max_adjustment, max_adjustment))

        base_long = float(self.base_thresholds.get("prob_threshold_long", 0.0))
        base_short = float(self.base_thresholds.get("prob_threshold_short", 0.0))

        current_long = thresholds["prob_threshold_long"]
        current_short = thresholds["prob_threshold_short"]
        adjusted_long = current_long - adjustment
        adjusted_short = current_short + adjustment
        min_long = max(0.0, base_long - max_adjustment)
        min_short = max(0.0, base_short - max_adjustment)
        thresholds["prob_threshold_long"] = self._bounded_threshold(
            "prob_threshold_long",
            max(adjusted_long, min_long),
            current_long,
            default_ceiling=0.999,
        )
        thresholds["prob_threshold_short"] = self._bounded_threshold(
            "prob_threshold_short",
            max(adjusted_short, min_short),
            current_short,
            default_ceiling=0.999,
        )

        if apply_to_exit:
            exit_long = thresholds["exit_threshold_long"]
            exit_short = thresholds["exit_threshold_short"]
            thresholds["exit_threshold_long"] = self._bounded_threshold(
                "exit_threshold_long",
                exit_long - adjustment,
                exit_long,
                default_ceiling=thresholds["prob_threshold_long"],
            )
            thresholds["exit_threshold_short"] = self._bounded_threshold(
                "exit_threshold_short",
                exit_short + adjustment,
                exit_short,
                default_ceiling=thresholds["prob_threshold_short"],
            )

        return thresholds

    def _metric_value(self, stats: dict[str, Any], field: str, metric_key: str) -> float | None:
        """Fetch a metric/quantile value from calibration stats."""
        metric_stats = stats.get(field)
        if not metric_stats:
            return None

        if metric_key == "mean":
            return metric_stats.get("mean")
        if metric_key == "max":
            return metric_stats.get("max")
        if metric_key == "min":
            return metric_stats.get("min")

        if metric_key.startswith("p"):
            quantiles = metric_stats.get("quantiles", {})
            return quantiles.get(metric_key)

        return metric_stats.get("mean")

    @staticmethod
    def _maybe_float(value: Any, *, default: float | None = None) -> float | None:
        if value is None:
            return default
        return float(value)

    def _bounded_threshold(
        self,
        key: str,
        candidate: float | None,
        fallback: float,
        *,
        default_ceiling: float,
    ) -> float:
        """Clamp candidate threshold using configured floors/ceilings with fallback."""
        if candidate is None:
            return float(fallback)

        value = _sanitize(candidate, fallback)
        floor = self.floors.get(key)
        if floor is not None:
            value = max(value, float(floor))
        ceiling = self.ceilings.get(key)
        if ceiling is None:
            ceiling = default_ceiling
        value = min(value, float(ceiling))
        return value
