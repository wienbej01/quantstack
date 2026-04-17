#!/usr/bin/env python3
"""Run the alpha ML action-ranker paper/shadow trading service."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.paper_trading.action_ranker_paper import (  # noqa: E402
    ALPHA_ROOT,
    PaperRunConfig,
    current_et_date,
    is_market_window,
    run_paper_loop,
    run_paper_once,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s"
)
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Alpha ML action-ranker paper/shadow runner"
    )
    parser.add_argument("--date", default=current_et_date())
    parser.add_argument(
        "--artifact-path",
        default=str(ALPHA_ROOT / "models" / "action_ranker_xgb_2026-03-19.pkl"),
    )
    parser.add_argument(
        "--sip-root",
        default="/home/jacobw/quantstack-v2/data/daily_sip",
        help="Daily SIP root with date=YYYY-MM-DD/sip_universe.json partitions.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ALPHA_ROOT / "output" / "paper_trading" / "action_ranker"),
    )
    parser.add_argument(
        "--polygon-cache-dir",
        default=str(ALPHA_ROOT / "output" / "polygon_ohlcv_cache"),
    )
    parser.add_argument("--bar-source", choices=["polygon", "gold"], default="polygon")
    parser.add_argument("--max-symbols", type=int, default=3)
    parser.add_argument("--daily-top-k", type=int, default=4)
    parser.add_argument("--max-longs-per-day", type=int, default=2)
    parser.add_argument("--min-score", type=float, default=0.5)
    parser.add_argument(
        "--execution-mode",
        choices=["shadow", "ibkr_paper"],
        default="shadow",
        help="shadow writes intents only; ibkr_paper submits fresh selected intents to IBKR paper.",
    )
    parser.add_argument(
        "--exit-mode",
        choices=["time_only"],
        default="time_only",
        help="Exit selected actions at their model-selected hold time.",
    )
    parser.add_argument("--execution-quantity", type=int, default=10)
    parser.add_argument(
        "--execution-stop-bps",
        type=float,
        default=50.0,
        help="Protective emergency stop; model exit remains time_only.",
    )
    parser.add_argument(
        "--execution-target-bps",
        type=float,
        default=5000.0,
        help="Wide emergency target; model exit remains time_only.",
    )
    parser.add_argument("--execution-max-action-age-seconds", type=int, default=180)
    parser.add_argument("--ibkr-host", default="127.0.0.1")
    parser.add_argument("--ibkr-port", type=int, default=7494)
    parser.add_argument("--ibkr-client-id", type=int, default=410)
    parser.add_argument("--ibkr-account-id", default=None)
    parser.add_argument("--order-ref-prefix", default="ALPHA_ML")
    parser.add_argument(
        "--cutoff-et",
        default=None,
        help="Optional HH:MM[:SS] ET cutoff for deterministic one-shot runs.",
    )
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--session-start", default="09:31:00")
    parser.add_argument("--session-end", default="16:00:00")
    parser.add_argument(
        "--allow-outside-hours",
        action="store_true",
        help="Allow running outside the weekday ET market paper window.",
    )
    args = parser.parse_args()

    if not args.allow_outside_hours and not is_market_window(
        start_time=args.session_start,
        end_time=args.session_end,
    ):
        logger.info("Outside alpha paper trading window - exiting")
        return 0

    run_config = PaperRunConfig(
        date=args.date,
        artifact_path=Path(args.artifact_path),
        sip_root=Path(args.sip_root),
        output_dir=Path(args.output_dir),
        polygon_cache_dir=Path(args.polygon_cache_dir),
        bar_source=args.bar_source,
        max_symbols=args.max_symbols,
        daily_top_k=args.daily_top_k,
        max_longs_per_day=args.max_longs_per_day,
        min_score=args.min_score,
        cutoff_et=args.cutoff_et,
        execution_mode=args.execution_mode,
        exit_mode=args.exit_mode,
        execution_quantity=args.execution_quantity,
        execution_stop_bps=args.execution_stop_bps,
        execution_target_bps=args.execution_target_bps,
        execution_max_action_age_seconds=args.execution_max_action_age_seconds,
        ibkr_host=args.ibkr_host,
        ibkr_port=args.ibkr_port,
        ibkr_client_id=args.ibkr_client_id,
        ibkr_account_id=args.ibkr_account_id or None,
        order_ref_prefix=args.order_ref_prefix,
    )
    if args.loop:
        run_paper_loop(
            run_config,
            interval_seconds=args.interval_seconds,
            session_end=args.session_end,
        )
        return 0

    status = run_paper_once(run_config)
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
