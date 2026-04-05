#!/usr/bin/env python
"""Build compact ML feature cache with event-aware sampling."""

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.data.ml_compact_cache import CompactCacheConfig, save_compact_cache
from src.data.ml_label_artifacts import LabelArtifactConfig

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build compact ML cache from symbol-day L2 data"
    )
    parser.add_argument(
        "--output-dir", default="output/ml_compact_cache", help="Cache directory"
    )
    parser.add_argument(
        "--horizons", default="60,180,300", help="Comma-separated horizons in seconds"
    )
    parser.add_argument("--threshold-method", default="fixed", help="fixed or quantile")
    parser.add_argument(
        "--fixed-bps",
        type=float,
        default=10.0,
        help="Mid-return threshold in basis points",
    )
    parser.add_argument(
        "--bucket-seconds", type=int, default=1, help="Compact feature bucket size"
    )
    parser.add_argument(
        "--sample-rows-per-symbol-day",
        type=int,
        default=4000,
        help="Event-aware sample size per symbol-day",
    )
    parser.add_argument(
        "--event-threshold", type=float, default=1.0, help="Event score threshold"
    )
    parser.add_argument(
        "--label-mode",
        choices=["mid_return", "barrier", "both"],
        default="mid_return",
        help="Which label family to attach to compact rows",
    )
    parser.add_argument(
        "--stop-bps", type=float, default=10.0, help="Barrier stop distance in bps"
    )
    parser.add_argument(
        "--take-profit-bps", type=float, default=10.0, help="Barrier TP distance in bps"
    )
    args = parser.parse_args()

    label_config = LabelArtifactConfig(
        horizons_seconds=tuple(
            int(value) for value in args.horizons.split(",") if value
        ),
        threshold_method=args.threshold_method,
        fixed_bps=args.fixed_bps,
        label_mode=args.label_mode,
        stop_bps=args.stop_bps,
        take_profit_bps=args.take_profit_bps,
    )
    compact_config = CompactCacheConfig(
        bucket_seconds=args.bucket_seconds,
        event_threshold=args.event_threshold,
    )
    save_compact_cache(
        output_dir=args.output_dir,
        label_config=label_config,
        compact_config=compact_config,
        sample_rows_per_symbol_day=args.sample_rows_per_symbol_day,
    )


if __name__ == "__main__":
    main()
