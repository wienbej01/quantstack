"""CLI wrapper for trading performance evaluation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd
import yaml

from extensions.intraday_ml.eval import SelectionPolicy, evaluate_trading_performance


def _load_frame(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix in {".csv", ".tsv"}:
        sep = "," if path.suffix == ".csv" else "\t"
        return pd.read_csv(path, sep=sep)
    raise ValueError(f"Unsupported file type for {path}")


def _load_policies(path: Path | None) -> list[SelectionPolicy]:
    if not path:
        return [
            SelectionPolicy(
                name="threshold_55",
                kind="threshold",
                prob_threshold=0.55,
                min_edge=0.02,
                min_score=0.01,
            ),
            SelectionPolicy(
                name="topk_3",
                kind="topk",
                prob_threshold=0.5,
                top_k=3,
                score_column="trade_score",
            ),
        ]
    with open(path) as handle:
        data = yaml.safe_load(handle)
    policies: list[SelectionPolicy] = []
    for cfg in data.get("policies", []):
        policies.append(
            SelectionPolicy(
                name=cfg["name"],
                kind=cfg["kind"],
                prob_threshold=cfg.get("prob_threshold"),
                min_edge=cfg.get("min_edge", 0.0),
                min_score=cfg.get("min_score", 0.0),
                top_k=cfg.get("top_k"),
                score_column=cfg.get("score_column", "trade_score"),
            )
        )
    if not policies:
        raise ValueError("Policy config did not define any policies.")
    return policies


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate trading performance using precomputed bars/predictions.",
    )
    parser.add_argument("--bars", required=True, help="Path to bars parquet/csv.")
    parser.add_argument("--predictions", required=True, help="Path to predictions parquet/csv.")
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for evaluation artifacts (default: alongside bars file).",
    )
    parser.add_argument(
        "--horizon-minutes",
        type=int,
        default=30,
        help="Forward return horizon in minutes.",
    )
    parser.add_argument(
        "--transaction-cost-bps",
        type=float,
        default=10.0,
        help="Round-trip transaction cost in basis points.",
    )
    parser.add_argument(
        "--policy-config",
        default=None,
        help="Optional YAML with policy definitions.",
    )

    args = parser.parse_args()
    bars_path = Path(args.bars)
    preds_path = Path(args.predictions)
    output_dir = Path(args.output_dir) if args.output_dir else bars_path.parent / "eval"

    bars = _load_frame(bars_path)
    predictions = _load_frame(preds_path)
    policies = _load_policies(Path(args.policy_config) if args.policy_config else None)

    results = evaluate_trading_performance(
        bars=bars,
        predictions=predictions,
        policies=policies,
        horizon_minutes=args.horizon_minutes,
        transaction_cost_bps=args.transaction_cost_bps,
        output_dir=output_dir,
    )

    summary = {policy_name: result.metrics for policy_name, result in results.items()}
    summary_path = output_dir / "summary_metrics.json"
    output_dir.mkdir(parents=True, exist_ok=True)
    with open(summary_path, "w") as handle:
        json.dump(summary, handle, indent=2)

    for name, metrics in summary.items():
        print(f"[eval] {name}: trades={metrics['total_trades']} Sharpe={metrics['sharpe']:.3f}")

    print(f"[eval] Summary written to {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
