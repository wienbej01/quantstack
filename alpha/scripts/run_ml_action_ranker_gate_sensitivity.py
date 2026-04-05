#!/usr/bin/env python3
"""Run nearby weak-context gate variants on a fixed action-ranker config."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from scripts.run_ml_action_ranker_budget_backtest import RankedAction
from scripts.run_ml_action_ranker_budget_backtest import WeakContextGate
from scripts.run_ml_action_ranker_budget_backtest import _sort_results
from scripts.run_ml_action_ranker_budget_backtest import run_matrix

# Compatibility shim for scored-action caches pickled under __main__.
setattr(sys.modules["__main__"], "RankedAction", RankedAction)


def _parse_gate_specs(value: str) -> list[tuple[str, WeakContextGate]]:
    gates: list[tuple[str, WeakContextGate]] = []
    for chunk in value.split(","):
        label, pressure_k, spread, depth_imb_k = [
            part.strip() for part in chunk.split(":")
        ]
        gates.append(
            (
                label,
                WeakContextGate(
                    max_pressure_k=float(pressure_k),
                    max_spread=float(spread),
                    max_depth_imb_k=float(depth_imb_k),
                ),
            )
        )
    if not gates:
        raise ValueError("at least one gate spec is required")
    return gates


def _gate_output_dir(root: Path, label: str) -> Path:
    safe_label = "".join(
        char if char.isalnum() or char in ("-", "_") else "_" for char in label
    )
    return root / safe_label


def _load_gate_result(output_dir: Path) -> dict | None:
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        return None
    return json.loads(summary_path.read_text())


def _write_sensitivity_outputs(
    *,
    results: list[dict],
    artifact_path: str,
    top_k: int,
    max_longs_per_day: int,
    min_score: float,
    output_dir: Path,
) -> dict:
    sorted_results = _sort_results(results)
    pd.DataFrame(sorted_results).to_csv(
        output_dir / "gate_sensitivity_results.csv", index=False
    )
    summary = {
        "artifact_path": artifact_path,
        "top_k": top_k,
        "max_longs_per_day": max_longs_per_day,
        "min_score": min_score,
        "best_gate": sorted_results[0],
        "gates_tested": len(sorted_results),
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    lines = [
        "# Action Ranker Gate Sensitivity",
        "",
        f"- artifact: `{artifact_path}`",
        f"- fixed config: `top_k={top_k}, max_longs_per_day={max_longs_per_day}, min_score={min_score}`",
        f"- gates tested: `{len(sorted_results)}`",
        f"- best gate: `{sorted_results[0]}`",
    ]
    (output_dir / "report.md").write_text("\n".join(lines) + "\n")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run gate sensitivity on a fixed action-ranker config"
    )
    parser.add_argument(
        "--artifact-path", default="models/action_ranker_xgb_2026-03-19.pkl"
    )
    parser.add_argument(
        "--windows",
        default="w1:2026-03-06:2026-03-11,w2:2026-03-12:2026-03-13",
    )
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-longs-per-day", type=int, default=1)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument("--bar-source", choices=["gold", "polygon"], default="polygon")
    parser.add_argument(
        "--gate-specs",
        default="conservative:-100.0:0.02:-0.10,permissive:0.0:0.05:0.0",
        help="Comma-separated gate specs as label:max_pressure_k:max_spread:max_depth_imb_k",
    )
    parser.add_argument(
        "--output-dir",
        default="output/ml_action_ranker_xgb_gate_sensitivity_2026-03-20",
    )
    parser.add_argument(
        "--cache-dir",
        default="output/ml_action_ranker_xgb_gate_sensitivity_2026-03-20/shared_cache",
    )
    parser.add_argument(
        "--no-score-cache",
        action="store_true",
        help="Disable on-disk scored-action cache reuse.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Ignore any existing per-gate summaries.",
    )
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict] = []
    for label, gate in _parse_gate_specs(args.gate_specs):
        gate_dir = _gate_output_dir(output_dir, label)
        summary = None if args.no_resume else _load_gate_result(gate_dir)
        if summary is None:
            summary = run_matrix(
                artifact_path=args.artifact_path,
                windows=_parse_windows(args.windows),
                daily_top_ks=[args.top_k],
                max_longs_per_day_values=[args.max_longs_per_day],
                min_score=args.min_score,
                output_dir=gate_dir,
                bar_source=args.bar_source,
                resume=not args.no_resume,
                score_cache=not args.no_score_cache,
                weak_context_gate=gate,
                cache_dir=cache_dir,
            )
        row = dict(summary["best_config"])
        row["gate_label"] = label
        row["max_pressure_k"] = gate.max_pressure_k
        row["max_spread"] = gate.max_spread
        row["max_depth_imb_k"] = gate.max_depth_imb_k
        results.append(row)
        _write_sensitivity_outputs(
            results=results,
            artifact_path=args.artifact_path,
            top_k=args.top_k,
            max_longs_per_day=args.max_longs_per_day,
            min_score=args.min_score,
            output_dir=output_dir,
        )

    summary = _write_sensitivity_outputs(
        results=results,
        artifact_path=args.artifact_path,
        top_k=args.top_k,
        max_longs_per_day=args.max_longs_per_day,
        min_score=args.min_score,
        output_dir=output_dir,
    )
    print(json.dumps(summary, indent=2))


def _parse_windows(value: str):
    from scripts.run_ml_action_ranker_budget_backtest import (
        _parse_windows as parse_windows,
    )

    return parse_windows(value)


if __name__ == "__main__":
    main()
