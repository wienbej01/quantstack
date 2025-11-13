#!/usr/bin/env python3
"""CLI helper to run walk-forward policy optimization."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from extensions.intraday_ml_policies.wfo_optimizer import WalkForwardPolicyOptimizer


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run walk-forward policy optimizer")
    parser.add_argument("predictions", help="Path to parquet/CSV with probabilities and labels")
    parser.add_argument(
        "--config",
        help="JSON file with optimizer configuration",
    )
    parser.add_argument(
        "--output",
        help="Optional path to save optimizer report (JSON)",
    )
    return parser.parse_args()


def load_predictions(path: str) -> pd.DataFrame:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(path)
    if file_path.suffix.lower() == ".parquet":
        return pd.read_parquet(file_path)
    return pd.read_csv(file_path)


def main() -> int:
    args = parse_args()
    config = {}
    if args.config:
        with open(args.config) as f:
            config = json.load(f)

    df = load_predictions(args.predictions)
    optimizer = WalkForwardPolicyOptimizer(config)
    result = optimizer.run(df)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(result, f, indent=2)
    else:
        print(json.dumps(result, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
