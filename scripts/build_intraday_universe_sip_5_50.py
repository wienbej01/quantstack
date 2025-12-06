"""Build a SIP-filtered intraday universe concentrated on the USD 5-50 price band."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yaml
from qx_data.gold_loader import load_bars

# Default file name used whenever --output points to a directory
DEFAULT_OUTPUT_FILENAME = "universe_intraday_sip_5_50.yaml"


@dataclass
class SymbolStats:
    symbol: str
    median_price: float
    avg_daily_dollar_volume: float
    days_sampled: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a USD 5-50 SIP universe based on real Gold bars.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Target YAML file for the new universe definition",
    )
    parser.add_argument(
        "--input-universe",
        type=Path,
        default=Path("configs/extensions/intraday_ml/universe_gold_full.yaml"),
        help="Baseline universe file with candidate symbols",
    )
    parser.add_argument(
        "--gold-root",
        type=Path,
        default=Path("/home/jacobw/gcs-mount/gold"),
        help="Path to the mounted Gold dataset",
    )
    parser.add_argument("--family", default="bars_1m", help="Gold family (e.g., bars_1m)")
    parser.add_argument(
        "--start-date",
        default="2023-10-02",
        help="Inclusive start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--end-date",
        default="2024-04-15",
        help="Inclusive end date (YYYY-MM-DD)",
    )
    parser.add_argument("--min-price", type=float, default=5.0, help="Minimum median price")
    parser.add_argument("--max-price", type=float, default=50.0, help="Maximum median price")
    parser.add_argument(
        "--min-dollar-vol",
        type=float,
        default=10_000_000,
        help="Minimum average daily dollar volume",
    )
    parser.add_argument(
        "--min-relative-volume",
        type=float,
        default=0.0,
        help="Minimum relative volume (for record keeping; not used in filtering)",
    )
    parser.add_argument(
        "--max-universe-size",
        type=int,
        default=600,
        help="`max_universe_size` to emit in the new config",
    )
    parser.add_argument(
        "--sip-symbols",
        type=Path,
        help="Optional newline-delimited file listing SIP symbols to intersect with",
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=5,
        help="Lookback window in days (copied to the universe config)",
    )
    parser.add_argument(
        "--volume-window",
        type=int,
        default=5,
        help="Volume smoothing window (copied to the universe config)",
    )
    return parser.parse_args()


def _business_days(start: str, end: str) -> list[str]:
    range_index = pd.date_range(start=start, end=end, freq="B")
    return [str(d.date()) for d in range_index]


def _load_candidate_symbols(universe_path: Path) -> list[str]:
    if not universe_path.exists():
        raise FileNotFoundError(f"Universe config not found at {universe_path}")
    with universe_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    raw_symbols = payload.get("symbols", [])
    raw_exclude = payload.get("exclude_symbols", []) or []
    normalized: list[str] = []
    for symbol in raw_symbols:
        if not isinstance(symbol, str):
            logging.warning(
                "Skipping non-string symbol entry %r in %s",
                symbol,
                universe_path,
            )
            continue
        normalized.append(symbol.strip().upper())
    excluded_set = {
        symbol.strip().upper()
        for symbol in raw_exclude
        if isinstance(symbol, str) and symbol.strip()
    }
    return [symbol for symbol in normalized if symbol not in excluded_set]


def _read_sip_symbols(path: Path | None) -> set[str]:
    if not path:
        return set()
    if not path.exists():
        logging.warning("SIP symbols file %s not found; ignoring SIP constraint", path)
        return set()
    with path.open("r", encoding="utf-8") as handle:
        lines = [line.strip().upper() for line in handle if line.strip()]
    return set(lines)


def _compute_symbol_stats(
    symbol: str,
    gold_root: str,
    family: str,
    dates: list[str],
) -> SymbolStats:
    df = load_bars(
        root=gold_root,
        family=family,
        symbols=[symbol],
        dates=dates,
        validate=True,
        sort=True,
    )
    if df.empty:
        raise ValueError(f"No bars for {symbol}")
    df = df.assign(
        close=pd.to_numeric(df["close"], errors="coerce"),
        volume=pd.to_numeric(df["volume"], errors="coerce"),
    ).dropna(subset=["close", "volume"])
    df = df[df["volume"] > 0]
    if df.empty:
        raise ValueError(f"No valid volume rows for {symbol}")
    ts = pd.to_datetime(df["ts"], unit="ns", utc=True, errors="coerce")
    df = df.assign(
        date=ts.dt.normalize(),
        dollar_volume=(df["close"] * df["volume"]).astype(float),
    )
    daily = df.groupby("date")["dollar_volume"].sum()
    if daily.empty:
        raise ValueError(f"No daily data for {symbol}")
    median_price = float(df["close"].median())
    avg_daily_dollar_volume = float(daily.mean())
    return SymbolStats(
        symbol=symbol,
        median_price=median_price,
        avg_daily_dollar_volume=avg_daily_dollar_volume,
        days_sampled=len(daily),
    )


def build_universe(config: argparse.Namespace) -> dict:
    candidates = _load_candidate_symbols(config.input_universe)
    if not candidates:
        raise RuntimeError("No candidate symbols found in the input universe")
    dates = _business_days(config.start_date, config.end_date)
    logging.info(
        "Processing %d candidate symbols over %d business days",
        len(candidates),
        len(dates),
    )
    stats: list[SymbolStats] = []
    for idx, symbol in enumerate(candidates, start=1):
        try:
            stats.append(_compute_symbol_stats(symbol, str(config.gold_root), config.family, dates))
        except Exception as exc:  # pylint: disable=broad-except
            logging.warning("Skipping %s: %s", symbol, exc)
        if idx % 25 == 0:
            logging.info(
                "Heartbeat: processed %d/%d symbols (%.1f%%)",
                idx,
                len(candidates),
                (idx / len(candidates)) * 100.0,
            )
    eligible = [
        stat
        for stat in stats
        if config.min_price <= stat.median_price <= config.max_price
        and stat.avg_daily_dollar_volume >= config.min_dollar_vol
    ]
    sip_symbols = _read_sip_symbols(config.sip_symbols)
    if sip_symbols:
        sip_filtered = [stat.symbol for stat in eligible if stat.symbol in sip_symbols]
        final_symbols = sip_filtered
    else:
        final_symbols = [stat.symbol for stat in eligible]
    logging.info("Eligible 5-50 USD symbols: %d", len(eligible))
    if sip_symbols:
        logging.info("SIP intersection yields %d symbols", len(final_symbols))
    else:
        logging.info("No SIP symbol list provided; using eligible set directly")
    final_symbols_sorted = sorted(dict.fromkeys(final_symbols))
    return {
        "dates": dates,
        "eligible_stats": eligible,
        "all_symbols": final_symbols_sorted,
    }


def _resolve_output_path(path: Path) -> Path:
    """Return a concrete file path even if the CLI argument is a directory."""

    if path.exists() and path.is_dir():
        return path / DEFAULT_OUTPUT_FILENAME

    # Treat paths without a suffix as directories unless they already end with .yaml
    if path.suffix == "":
        if path.name.endswith(".yaml") or path.name.endswith(".yml"):
            return path
        return path / DEFAULT_OUTPUT_FILENAME

    return path


def write_universe(
    output_path: Path,
    args: argparse.Namespace,
    symbols: Iterable[str],
) -> None:
    output_file = _resolve_output_path(output_path)
    payload = {
        "max_universe_size": args.max_universe_size,
        "min_price": args.min_price,
        "max_price": args.max_price,
        "min_avg_daily_volume": args.min_dollar_vol,
        "min_relative_volume": args.min_relative_volume,
        "lookback_days": args.lookback_days,
        "volume_window": args.volume_window,
        "exclude_symbols": [],
        "symbols": list(symbols),
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with output_file.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False)
    logging.info("Wrote universe file to %s (%d symbols)", output_file, len(payload["symbols"]))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    args = parse_args()
    universe_data = build_universe(args)
    write_universe(args.output, args, universe_data["all_symbols"])


if __name__ == "__main__":
    main()
