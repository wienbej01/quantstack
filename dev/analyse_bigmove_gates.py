"""Quick analysis of big-move probability thresholds on OOS signals."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OOS_SIGNALS = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet")
THRESHOLDS = [0.0, 0.01, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.40, 0.50]


def main() -> None:
    df = pd.read_parquet(OOS_SIGNALS)
    if "prob_bigmove" not in df.columns:
        raise KeyError("prob_bigmove column missing from OOS predictions.")

    values = pd.to_numeric(df["prob_bigmove"], errors="coerce").fillna(0.0)
    total = len(values)
    zero_count = int((values == 0.0).sum())
    positive_count = int((values > 0.0).sum())

    print(f"Total rows: {total}")
    print(f"prob_bigmove == 0.0: {zero_count}")
    print(f"prob_bigmove > 0.0: {positive_count}")
    print()
    print("Counts with prob_bigmove >= threshold:")
    for threshold in THRESHOLDS:
        count = int((values >= threshold).sum())
        print(f"  >= {threshold:.2f}: {count}")

    stats = {
        "min": float(values.min()),
        "max": float(values.max()),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "p10": float(values.quantile(0.10)),
        "p25": float(values.quantile(0.25)),
        "p50": float(values.quantile(0.50)),
        "p75": float(values.quantile(0.75)),
        "p90": float(values.quantile(0.90)),
        "p99": float(values.quantile(0.99)),
    }
    print()
    print("prob_bigmove stats:")
    for key, value in stats.items():
        print(f"  {key}: {value:.6f}")


if __name__ == "__main__":
    main()
