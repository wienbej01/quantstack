"""
Command-Line Interface for pre-computing and storing SIP membership.

This tool uses the existing `HMMSIPUniverseSelector` to determine the daily
Stock-In-Play (SIP) universe over a specified date range and for a given
symbol universe. The results are saved to a partitioned Parquet dataset
for efficient downstream consumption by the ML pipeline.

This approach avoids re-computing SIP membership repeatedly during training
and backtesting, ensuring consistency and performance.

Example usage (to be run from the terminal):
  python -m extensions.intraday_ml.cli_build_sip_membership \
      --start-date 2023-01-01 \
      --end-date 2023-12-31 \
      --universe-config configs/extensions/intraday_ml/universe_sp500.yaml \
      --gold-root /path/to/your/gold_data \
      --top-k 40
"""
from __future__ import annotations

import argparse
import logging
from datetime import timedelta

import pandas as pd
import yaml
from qx_data.gold_loader import load_bars

from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector
from extensions.intraday_ml.sip_membership import save_sip_membership

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def build_sip_for_range(
    start_date: str,
    end_date: str,
    universe_config_path: str,
    gold_root: str,
    top_k: int,
    score_floor: float,
    mode: str,
):
    """
    Computes and saves SIP membership for a given date range and universe.
    """
    # Load symbol universe from the YAML config
    with open(universe_config_path) as f:
        universe_config = yaml.safe_load(f)
    candidate_symbols = universe_config.get("symbols")
    if not candidate_symbols:
        raise ValueError(
            f"No 'symbols' found in universe config: {universe_config_path}"
        )
    logger.info(
        f"Loaded {len(candidate_symbols)} symbols from {universe_config_path}"
    )

    # Configure the HMM SIP selector to use the legacy mode
    sip_config = HMMSIPConfig(
        top_k=top_k,
        score_floor=score_floor,
        mode=mode,
        enable_gold_fallback=True,  # Ensure it can run without external files
    )
    selector = HMMSIPUniverseSelector(cfg=sip_config)

    # Iterate over each date in the specified range
    current_date = pd.to_datetime(start_date)
    end_date_dt = pd.to_datetime(end_date)

    while current_date <= end_date_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        logger.info(f"Processing SIP for {date_str}...")

        try:
            # For the selector's fallback mechanism to work, we need to provide bar data.
            # We load data for the target date plus a lookback for context (e.g., previous close).
            load_start = (current_date - timedelta(days=5)).strftime("%Y-%m-%d")
            
            # The load_bars function expects a list of dates.
            # We'll create a date range string list.
            date_range = [d.strftime("%Y-%m-%d") for d in pd.date_range(load_start, date_str)]

            bars_utc = load_bars(
                root=gold_root,
                family="equities",
                symbols=candidate_symbols,
                dates=date_range,
                validate=True,
                sort=True,
            )

            if bars_utc.empty:
                logger.warning(f"No bar data found for {date_str}. Skipping.")
                current_date += timedelta(days=1)
                continue

            # The selector returns a map of {timestamp: {symbols...}}.
            # We need to get the union of all selected symbols for the day.
            ref = {"target_date": date_str}
            sip_map = selector.select(bars_utc=bars_utc, ref=ref)

            sip_symbols_for_day = set()
            if sip_map:
                for symbols in sip_map.values():
                    sip_symbols_for_day.update(symbols)

            logger.info(
                f"Found {len(sip_symbols_for_day)} SIP symbols for {date_str}"
            )

            # Create the membership DataFrame for the day
            membership_records = []
            for symbol in candidate_symbols:
                membership_records.append(
                    {
                        "trade_date": date_str,
                        "symbol": symbol,
                        "is_sip": symbol in sip_symbols_for_day,
                        "sip_score": None,  # Score is not exposed by legacy selector
                        "sip_reason": "legacy_hmm_sip_fallback",
                    }
                )

            membership_df = pd.DataFrame(membership_records)

            # Save the membership data for the day
            save_sip_membership(df=membership_df, gold_root=gold_root)
            logger.info(f"Successfully saved SIP membership for {date_str}.")

        except Exception as e:
            logger.error(f"Failed to process SIP for {date_str}: {e}", exc_info=True)

        current_date += timedelta(days=1)


def main():
    """Main entry point for the CLI tool."""
    parser = argparse.ArgumentParser(
        description="Pre-compute and store SIP membership for the intraday ML pipeline.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--start-date",
        type=str,
        required=True,
        help="Start date for SIP computation (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--end-date",
        type=str,
        required=True,
        help="End date for SIP computation (YYYY-MM-DD).",
    )
    parser.add_argument(
        "--universe-config",
        type=str,
        required=True,
        help="Path to the YAML universe configuration file.",
    )
    parser.add_argument(
        "--gold-root",
        type=str,
        required=True,
        help="Path to the root of the 'gold' data layer.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=40,
        help="Number of top symbols to select (default: 40).",
    )
    parser.add_argument(
        "--score-floor",
        type=float,
        default=0.0,
        help="Minimum score for a symbol to be included (default: 0.0).",
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["legacy"],
        default="legacy",
        help="SIP selector mode. Currently only 'legacy' is supported.",
    )

    args = parser.parse_args()

    logger.info("Starting SIP membership pre-computation job.")
    build_sip_for_range(
        start_date=args.start_date,
        end_date=args.end_date,
        universe_config_path=args.universe_config,
        gold_root=args.gold_root,
        top_k=args.top_k,
        score_floor=args.score_floor,
        mode=args.mode,
    )
    logger.info("SIP membership pre-computation job finished.")


if __name__ == "__main__":
    main()
