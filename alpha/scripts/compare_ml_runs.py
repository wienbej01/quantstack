#!/usr/bin/env python
"""Compare two ML training report JSON files and write a markdown summary."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_report(path: str) -> dict:
    return json.loads(Path(path).read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two cached ML training runs")
    parser.add_argument(
        "--baseline", required=True, help="Baseline training_metrics.json path"
    )
    parser.add_argument(
        "--candidate", required=True, help="Candidate training_metrics.json path"
    )
    parser.add_argument(
        "--output-path",
        default="reports/ml_run_comparison.md",
        help="Markdown output path",
    )
    args = parser.parse_args()

    baseline = _load_report(args.baseline)
    candidate = _load_report(args.candidate)

    def metric(report: dict, key: str) -> float | None:
        value = report.get(key)
        return float(value) if value is not None else None

    lines = [
        "# ML Run Comparison",
        "",
        f"- baseline: `{args.baseline}`",
        f"- candidate: `{args.candidate}`",
        "",
        "## Metrics",
        "",
    ]
    for key in ("mean_val_accuracy", "train_val_gap", "test_accuracy"):
        base = metric(baseline, key)
        cand = metric(candidate, key)
        if base is None or cand is None:
            lines.append(f"- {key}: unavailable")
            continue
        delta = cand - base
        lines.append(
            f"- {key}: baseline={base:.3f}, candidate={cand:.3f}, delta={delta:+.3f}"
        )

    output_path = Path(args.output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
