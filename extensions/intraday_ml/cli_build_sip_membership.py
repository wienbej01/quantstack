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
import re
from collections.abc import Sequence
from datetime import timedelta
from pathlib import Path

import pandas as pd
import yaml
from qx_data.gold_loader import list_available_symbols, load_bars
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector

from extensions.intraday_ml.sip_membership import save_sip_membership
from extensions.intraday_ml.utils import MonthlyBarsCache

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def _normalize_timestamp_units(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ensure timestamps are in nanoseconds (Gold data can be microseconds).
    """
    if df.empty or "ts" not in df.columns:
        return df

    ts = df["ts"].astype("int64")
    max_ts = int(ts.max()) if not ts.empty else 0

    # Gold bars often arrive in microseconds (<1e17). Convert once to ns.
    if 0 < max_ts < 10**17:
        ts = ts * 1000

    df = df.copy()
    df["ts"] = ts
    return df


_SYMBOL_TOKEN = re.compile(r"^[A-Z0-9]{1,5}$")


def _load_symbols_from_config(path: str) -> list[str]:
    with open(path) as f:
        config = yaml.safe_load(f)

    symbols = config.get("symbols")
    if not symbols:
        raise ValueError(f"No 'symbols' found in universe config: {path}")

    normalized = []
    for symbol in symbols:
        token = str(symbol).strip()
        if not token:
            continue
        normalized.append(token.upper())

    unique = sorted(dict.fromkeys(normalized))
    if not unique:
        raise ValueError(f"No valid symbols found in universe config: {path}")
    return unique


def _load_symbols_from_list_file(path: str) -> list[str]:
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Universe list file not found: {path}")

    tokens: list[str] = []
    for raw_line in file_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        cleaned = line.replace("├──", " ").replace("└──", " ").replace("│", " ").replace("─", " ")
        for token in cleaned.replace(",", " ").split():
            candidate = token.strip()
            if not candidate:
                continue
            if candidate.upper() != candidate:
                continue
            if _SYMBOL_TOKEN.match(candidate):
                tokens.append(candidate)

    unique = list(dict.fromkeys(tokens))
    if not unique:
        raise ValueError(f"No symbols could be parsed from {path}.")
    return unique


def _resolve_candidate_symbols(
    *,
    gold_root: str,
    universe_config_path: str | None,
    universe_list_file: str | None,
    use_gold_universe: bool,
) -> list[str]:
    selections = [
        bool(universe_config_path),
        bool(universe_list_file),
        bool(use_gold_universe),
    ]
    if sum(selections) == 0:
        raise ValueError(
            "Specify one of --universe-config, --universe-list-file, or "
            "--use-gold-universe to define the candidate symbols."
        )
    if sum(selections) > 1:
        raise ValueError("Please choose only one universe source: config, list file, or full Gold.")

    if universe_config_path:
        return _load_symbols_from_config(universe_config_path)
    if universe_list_file:
        return _load_symbols_from_list_file(universe_list_file)

    symbols = sorted(list_available_symbols(gold_root, "bars_1m"))
    if not symbols:
        raise ValueError(
            f"No symbols discovered under Gold root '{gold_root}'. "
            "Verify the path or specify a universe config."
        )
    return symbols


def build_sip_for_range(
    start_date: str,
    end_date: str,
    candidate_symbols: Sequence[str],
    gold_root: str,
    top_k: int,
    score_floor: float,
    mode: str,
    external_premarket_root: str,
    output_root: str | None,
):
    """
    Computes and saves SIP membership for a given date range and universe.
    """
    if not candidate_symbols:
        raise ValueError("candidate_symbols cannot be empty.")
    candidate_symbols = sorted({str(symbol).upper() for symbol in candidate_symbols})
    logger.info("Using %d candidate symbols for SIP generation.", len(candidate_symbols))

    # Configure the HMM SIP selector to use the legacy mode
    sip_config = HMMSIPConfig(
        top_k=top_k,
        score_floor=score_floor,
        mode=mode,
        enable_gold_fallback=True,  # Ensure it can run without external files
        external_premarket_root=external_premarket_root,
    )
    selector = HMMSIPUniverseSelector(cfg=sip_config)

    start_dt = pd.to_datetime(start_date)
    end_dt = pd.to_datetime(end_date)
    if end_dt < start_dt:
        raise ValueError("end_date must be on or after start_date.")

    lookback_days = 5
    cache_start = start_dt - timedelta(days=lookback_days)
    cache = MonthlyBarsCache(
        root=gold_root,
        family="bars_1m",
        symbols=candidate_symbols,
        start_date=cache_start,
        end_date=end_dt,
    )

    if cache.is_empty():
        raise RuntimeError(
            "Failed to preload Gold bars. Ensure the gold root and symbols are correct."
        )

    # Iterate over each date in the specified range
    current_date = start_dt
    end_date_dt = end_dt

    while current_date <= end_date_dt:
        date_str = current_date.strftime("%Y-%m-%d")
        logger.info(f"Processing SIP for {date_str}...")

        if current_date.weekday() >= 5:
            logger.info("Skipping %s (non-trading day).", date_str)
            current_date += timedelta(days=1)
            continue

        try:
            window_start = current_date - timedelta(days=lookback_days)
            window_end = current_date + timedelta(days=1) - timedelta(microseconds=1)
            bars_utc = cache.get_window(
                start_date=window_start,
                end_date=window_end,
                symbols=candidate_symbols,
            )

            if bars_utc.empty:
                logger.info(
                    "Cache empty for %s (window start %s). Loading Gold directly.",
                    date_str,
                    window_start.strftime("%Y-%m-%d"),
                )
                fallback_dates = pd.bdate_range(window_start, current_date)
                fallback_str_dates = [d.strftime("%Y-%m-%d") for d in fallback_dates]
                if fallback_str_dates:
                    try:
                        bars_utc = load_bars(
                            root=gold_root,
                            family="bars_1m",
                            symbols=candidate_symbols,
                            dates=fallback_str_dates,
                            validate=True,
                            sort=True,
                        )
                    except RuntimeError:
                        bars_utc = pd.DataFrame()

            if bars_utc.empty:
                logger.info(
                    "No Gold data available for %s. Likely market holiday. Skipping.",
                    date_str,
                )
                current_date += timedelta(days=1)
                continue
            bars_utc = _normalize_timestamp_units(bars_utc)

            # The selector returns a map of {timestamp: {symbols...}}.
            # We need to get the union of all selected symbols for the day.
            ref = {"target_date": date_str}
            sip_map = selector.select(bars_utc=bars_utc, ref=ref)

            sip_symbols_for_day = set()
            if sip_map:
                for symbols in sip_map.values():
                    sip_symbols_for_day.update(symbols)

            logger.info(f"Found {len(sip_symbols_for_day)} SIP symbols for {date_str}")

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
            save_sip_membership(
                df=membership_df,
                gold_root=gold_root,
                output_root=output_root,
            )
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
        help="Path to the YAML universe configuration file.",
    )
    parser.add_argument(
        "--universe-list-file",
        type=str,
        help=(
            "Path to a text file containing symbols (one per line or tree output). "
            "Mutually exclusive with --universe-config and --use-gold-universe."
        ),
    )
    parser.add_argument(
        "--use-gold-universe",
        action="store_true",
        help="Automatically use every symbol found under the Gold root.",
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
    parser.add_argument(
        "--external-premarket-root",
        type=str,
        help=(
            "Directory containing daily pre-market shortlists. "
            "Defaults to <gold_root>/intraday_ml/sip_universe_pre, which is expected to host "
            "the Russell 2000 USD 5-50 universe shortlists."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=str,
        help=(
            "Optional directory to store the generated sip_membership dataset. "
            "Defaults to <gold_root>/intraday_ml/sip_membership."
        ),
    )

    args = parser.parse_args()

    logger.info("Starting SIP membership pre-computation job.")
    candidate_symbols = _resolve_candidate_symbols(
        gold_root=args.gold_root,
        universe_config_path=args.universe_config,
        universe_list_file=args.universe_list_file,
        use_gold_universe=args.use_gold_universe,
    )
    external_premarket_root = args.external_premarket_root
    if not external_premarket_root:
        external_premarket_root = str(Path(args.gold_root) / "intraday_ml" / "sip_universe_pre")

    output_root = args.output_root
    if output_root:
        output_root = str(Path(output_root).expanduser())

    build_sip_for_range(
        start_date=args.start_date,
        end_date=args.end_date,
        candidate_symbols=candidate_symbols,
        gold_root=args.gold_root,
        top_k=args.top_k,
        score_floor=args.score_floor,
        mode=args.mode,
        external_premarket_root=external_premarket_root,
        output_root=output_root,
    )
    logger.info("SIP membership pre-computation job finished.")


if __name__ == "__main__":
    main()
