#!/usr/bin/env python
"""Build full-resolution label artifacts for all available L2 symbol-days."""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.ml_label_artifacts import LabelArtifactConfig, save_label_artifacts

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build full-resolution ML label artifacts"
    )
    parser.add_argument(
        "--output-dir", default="output/ml_label_artifacts", help="Artifact directory"
    )
    parser.add_argument(
        "--horizons", default="60,180,300", help="Comma-separated horizons in seconds"
    )
    parser.add_argument("--threshold-method", default="fixed", help="fixed or quantile")
    parser.add_argument(
        "--fixed-bps",
        type=float,
        default=10.0,
        help="Fallback threshold in basis points",
    )
    parser.add_argument(
        "--label-mode",
        choices=["mid_return", "barrier", "both"],
        default="mid_return",
        help="Which label family to generate",
    )
    parser.add_argument(
        "--stop-bps", type=float, default=10.0, help="Barrier stop distance in bps"
    )
    parser.add_argument(
        "--take-profit-bps", type=float, default=10.0, help="Barrier TP distance in bps"
    )
    parser.add_argument(
        "--direction", choices=["long", "short"], default="long", help="Trade direction"
    )
    parser.add_argument(
        "--tie-break-policy",
        choices=["worst_case", "best_case", "neutral"],
        default="worst_case",
        help="Policy when TP and SL are hit at the same observed step",
    )
    args = parser.parse_args()

    config = LabelArtifactConfig(
        horizons_seconds=tuple(
            int(value) for value in args.horizons.split(",") if value
        ),
        threshold_method=args.threshold_method,
        fixed_bps=args.fixed_bps,
        label_mode=args.label_mode,
        stop_bps=args.stop_bps,
        take_profit_bps=args.take_profit_bps,
        direction=args.direction,
        tie_break_policy=args.tie_break_policy,
    )
    save_label_artifacts(args.output_dir, config=config)


if __name__ == "__main__":
    main()
