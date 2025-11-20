from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

import numpy as np
import pandas as pd

PARQUET_PATH = Path(
    "artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions.parquet"
)

EXPECTED_COLUMNS = OrderedDict(
    prob_bigmove="prob_bigmove",
    prob_bigmove_long="prob_bigmove_long",
    prob_bigmove_short="prob_bigmove_short",
    expected_r_bigmove="expected_r_bigmove",
)

PROB_THRESHOLDS = [0.15, 0.25, 0.35, 0.45, 0.50, 0.60]
EXPECTED_R_THRESHOLDS = [1.0, 1.5, 2.0]
QUANTILES = [0.10, 0.25, 0.50, 0.75, 0.90, 0.99]
BASELINE_SCORE_FIELD = "score_margin"


def describe_numeric(series: pd.Series) -> dict[str, float | int | str]:
    numeric = pd.to_numeric(series, errors="coerce")
    nonnull = numeric.dropna()
    total = len(numeric)
    stats: dict[str, float | int | str] = {
        "count": total,
        "nonnull": int(nonnull.size),
        "null": total - int(nonnull.size),
    }
    if nonnull.size == 0:
        stats.update({"min": "<no data>", "max": "<no data>", "mean": "<no data>", "std": "<no data>"})
        for level in QUANTILES:
            stats[f"p{int(level * 100):02d}"] = "<no data>"
        return stats

    stats["min"] = float(nonnull.min())
    stats["max"] = float(nonnull.max())
    stats["mean"] = float(nonnull.mean())
    stats["std"] = float(nonnull.std(ddof=0))
    quantiles = nonnull.quantile(QUANTILES)
    for level, value in zip(QUANTILES, quantiles):
        stats[f"p{int(level * 100):02d}"] = float(value)
    return stats


def compute_threshold_fractions(series: pd.Series, thresholds: list[float]) -> dict[float, float]:
    numeric = pd.to_numeric(series, errors="coerce")
    total = len(numeric)
    if total == 0:
        return {thr: 0.0 for thr in thresholds}
    return {thr: float((numeric >= thr).sum()) / total for thr in thresholds}


def main() -> None:
    df = pd.read_parquet(PARQUET_PATH)
    columns = list(df.columns)
    print(f"Loaded parquet with {len(df)} rows and {len(columns)} columns.")

    print("\n--- Columns (first 40 listed) ---")
    for idx, col in enumerate(columns[:40], start=1):
        print(f"{idx:03d}. {col}")
    if len(columns) > 40:
        print(f"... {len(columns) - 40} more columns omitted ...")

    found_expected = [col for col in EXPECTED_COLUMNS.values() if col in df.columns]
    missing_expected = [col for col in EXPECTED_COLUMNS.values() if col not in df.columns]

    print("\n--- Expected big-move columns present ---")
    for col in found_expected:
        print(f"✔ {col}")
    if missing_expected:
        print("Missing:")
        for col in missing_expected:
            print(f"✖ {col}")

    suspicious_keywords = ("bigmove", "big_move", "big-move", "bm_")
    suspicious = [col for col in columns if any(keyword in col.lower() for keyword in suspicious_keywords)]
    print("\n--- Suspicious columns (matching bigmove keywords) ---")
    for col in suspicious:
        print(f"* {col}")

    if found_expected:
        print("\n--- Big-move column stats ---")
        for col in found_expected:
            print(f"\nColumn: {col}")
            stats = describe_numeric(df[col])
            for key in ("count", "nonnull", "null", "min", "max", "mean", "std"):
                print(f"  {key}: {stats[key]}")
            for quant_label in [f"p{int(level * 100):02d}" for level in QUANTILES]:
                print(f"  {quant_label}: {stats[quant_label]}")
            thresholds = PROB_THRESHOLDS if "prob" in col else EXPECTED_R_THRESHOLDS
            fractions = compute_threshold_fractions(df[col], thresholds)
            print("  fractions >= thresholds:")
            for thr in thresholds:
                print(f"    {thr:.2f}: {fractions[thr]:.4f}")

    if BASELINE_SCORE_FIELD in df.columns:
        print(f"\n--- Baseline field: {BASELINE_SCORE_FIELD} stats ---")
        stats = describe_numeric(df[BASELINE_SCORE_FIELD])
        for key in ("mean", "p50", "p90", "max"):
            if key in stats:
                print(f"  {key}: {stats[key]}")
        if "p90" not in stats:
            print("  (quantile info unavailable)")

    print("\n--- Non-null big-move counts ---")
    for col in EXPECTED_COLUMNS.values():
        if col in df.columns:
            nonnull = int(pd.to_numeric(df[col], errors="coerce").notna().sum())
            print(f"{col}: {nonnull} non-null / {len(df)} total")


if __name__ == "__main__":
    main()
