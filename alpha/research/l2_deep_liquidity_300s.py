"""CLI entrypoint for deep L2 liquidity impact experiment."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from research.l2_impact.pipeline import run_experiment

DEFAULT_RUN_ID = "2026-01-23_l2_impact_105017"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Deep L2 liquidity impact experiment (300s horizon)",
    )
    parser.add_argument(
        "--l2-root",
        type=Path,
        required=True,
        help="Root path for L2 data (recursive scan)",
    )
    parser.add_argument(
        "--ohlcv",
        type=str,
        default="polygon",
        help="OHLCV source (polygon)",
    )
    parser.add_argument(
        "--tz",
        type=str,
        default="America/New_York",
        help="Timezone for alignment",
    )
    parser.add_argument(
        "--run-id",
        type=str,
        default=DEFAULT_RUN_ID,
        help="Run identifier for output folder",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("reports"),
        help="Root output directory",
    )
    parser.add_argument(
        "--placebo",
        action="store_true",
        help="Run placebo analysis",
    )
    parser.add_argument(
        "--falsification",
        type=str,
        default=None,
        help="Run falsification analysis (e.g., shift_30m)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        default=None,
        help="End date YYYY-MM-DD",
    )
    parser.add_argument(
        "--symbols",
        type=str,
        default=None,
        help="Comma-separated symbols to include",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("research/l2_impact/config.yaml"),
        help="Path to config.yaml",
    )
    return parser


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = build_parser()
    args = parser.parse_args()

    if args.placebo and args.falsification:
        raise ValueError("Choose either --placebo or --falsification, not both")

    symbols = args.symbols.split(",") if args.symbols else None
    output_dir = args.output_root / args.run_id

    run_experiment(
        l2_root=args.l2_root,
        ohlcv_source=args.ohlcv,
        tz=args.tz,
        run_id=args.run_id,
        output_dir=output_dir,
        placebo=args.placebo,
        falsification=args.falsification,
        start_date=args.start_date,
        end_date=args.end_date,
        symbols=symbols,
        config_path=args.config,
    )


if __name__ == "__main__":
    main()
