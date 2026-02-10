#!/usr/bin/env python3
"""
L2 Size Explorer - Interactive CLI Tool

Explore specific large order events and their outcomes.
"""

import argparse
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
L2_RAW_DIR = Path("/home/jacobw/quantstack/data/l2/l2_maximum/raw")


def load_data_for_symbol_date(symbol: str, date: str) -> pd.DataFrame:
    """Load L2 data for a specific symbol and date."""
    date_dir = L2_RAW_DIR / f"date={date}"
    symbol_dir = date_dir / f"symbol={symbol}"

    if not symbol_dir.exists():
        logger.error(f"No data found for {symbol} on {date}")
        return pd.DataFrame()

    all_data = []
    for pq_file in symbol_dir.glob("*.parquet"):
        try:
            df = pd.read_parquet(pq_file)
            all_data.append(df)
        except Exception as e:
            logger.warning(f"Error loading {pq_file}: {e}")

    if not all_data:
        return pd.DataFrame()

    df = pd.concat(all_data, ignore_index=True)
    df = df.sort_values("ts_epoch")
    return df


def find_large_order_events(
    df: pd.DataFrame, min_size: float
) -> pd.DataFrame:
    """Find all rows where any bid/ask level exceeds min_size."""
    df = df.copy()

    # Check each level
    large_mask = pd.Series(False, index=df.index)

    for level in range(1, 6):
        bid_col = f"bid_sz_{level}"
        ask_col = f"ask_sz_{level}"

        if bid_col in df.columns:
            large_mask = large_mask | (df[bid_col] >= min_size)
        if ask_col in df.columns:
            large_mask = large_mask | (df[ask_col] >= min_size)

    # Add context columns
    df["max_bid_sz"] = (
        df[[f"bid_sz_{i}" for i in range(1, 6) if f"bid_sz_{i}" in df.columns]].max(axis=1)
        if any(f"bid_sz_{i}" in df.columns for i in range(1, 6))
        else np.nan
    )
    df["max_ask_sz"] = (
        df[[f"ask_sz_{i}" for i in range(1, 6) if f"ask_sz_{i}" in df.columns]].max(axis=1)
        if any(f"ask_sz_{i}" in df.columns for i in range(1, 6))
        else np.nan
    )

    if "bid_px_1" in df.columns and "ask_px_1" in df.columns:
        df["mid"] = (df["bid_px_1"] + df["ask_px_1"]) / 2
        df["spread"] = df["ask_px_1"] - df["bid_px_1"]

    return df[large_mask].copy()


def compute_forward_returns_for_events(
    df: pd.DataFrame, events: pd.DataFrame, horizons: list[int]
) -> pd.DataFrame:
    """Compute forward returns for each event."""
    events = events.copy()

    for horizon in horizons:
        fwd_rets = []

        for _, event in events.iterrows():
            event_ts = event["ts_epoch"]
            event_mid = event.get("mid", np.nan)

            # Find future mid price
            future_df = df[df["ts_epoch"] > event_ts]
            if len(future_df) >= horizon:
                future_mid = (
                    future_df.iloc[horizon - 1].get("mid", np.nan)
                    if "mid" in df.columns
                    else np.nan
                )
                if not pd.isna(event_mid) and not pd.isna(future_mid):
                    fwd_ret = (future_mid / event_mid - 1) * 10000  # bps
                    fwd_rets.append(fwd_ret)
                else:
                    fwd_rets.append(np.nan)
            else:
                fwd_rets.append(np.nan)

        events[f"fwd_ret_{horizon}s"] = fwd_rets

    return events


def display_order_book(event: pd.Series, df: pd.DataFrame, context_rows: int = 2) -> str:
    """Display order book context around an event."""
    event_idx = df.index.get_indexer([event.name], method="nearest")[0]

    start_idx = max(0, event_idx - context_rows)
    end_idx = min(len(df), event_idx + context_rows + 1)

    context_df = df.iloc[start_idx:end_idx].copy()

    lines = []
    lines.append("\n" + "=" * 100)

    # Format timestamp
    ts = pd.to_datetime(event["ts_utc"])
    lines.append(f"TIMESTAMP: {ts} | Symbol: {event['symbol']}")
    lines.append(f"Mid: ${event.get('mid', 0):.2f} | Spread: ${event.get('spread', 0):.2f}")
    lines.append("=" * 100)
    lines.append("\nOrder Book Context:")

    for i, row in context_df.iterrows():
        marker = " >>> EVENT <<<" if i == event.name else ""
        lines.append(f"\n  [{ts.strftime('%H:%M:%S.%f')[:-3]}]{marker}")

        lines.append("  " + "-" * 60)
        lines.append("  Level    Bid Price    Bid Size    Ask Price    Ask Size")
        lines.append("  " + "-" * 60)

        for level in range(1, 6):
            bid_px = row.get(f"bid_px_{level}", np.nan)
            bid_sz = row.get(f"bid_sz_{level}", np.nan)
            ask_px = row.get(f"ask_px_{level}", np.nan)
            ask_sz = row.get(f"ask_sz_{level}", np.nan)

            bid_str = f"${bid_px:7.2f}" if not pd.isna(bid_px) else "        "
            sz_str = f"{int(bid_sz):6d}" if not pd.isna(bid_sz) else "      "
            ask_str = f"${ask_px:7.2f}" if not pd.isna(ask_px) else "        "
            ask_sz_str = f"{int(ask_sz):6d}" if not pd.isna(ask_sz) else "      "

            lines.append(f"  L{level}      {bid_str}     {sz_str}      {ask_str}     {ask_sz_str}")

    return "\n".join(lines)


def explore_large_orders(
    symbol: str, date: str, min_size: float, max_events: int = 10, horizons: list[int] = [60, 300]
):
    """Explore large order events for a symbol/date."""

    logger.info(f"Exploring {symbol} on {date} for orders >= {min_size} shares")

    # Load data
    df = load_data_for_symbol_date(symbol, date)
    if df.empty:
        logger.error("No data found!")
        return

    logger.info(f"Loaded {len(df):,} snapshots")

    # Find large order events
    events = find_large_order_events(df, min_size)
    logger.info(f"Found {len(events)} events with order size >= {min_size}")

    if len(events) == 0:
        logger.info("No large orders found at this threshold")
        return

    # Compute forward returns
    events = compute_forward_returns_for_events(df, events, horizons)

    # Sort by max size and limit
    events["max_size"] = events[["max_bid_sz", "max_ask_sz"]].max(axis=1)
    events = events.sort_values("max_size", ascending=False).head(max_events)

    # Display summary
    print("\n" + "=" * 100)
    print(f"LARGE ORDER EVENTS: {symbol} on {date} (size >= {min_size})")
    print("=" * 100)
    print(f"\nTop {len(events)} largest orders:\n")

    summary_cols = ["ts_utc", "max_bid_sz", "max_ask_sz"] + [f"fwd_ret_{h}s" for h in horizons]
    print(events[summary_cols].to_string(index=False))

    # Display forward return statistics
    print("\n" + "-" * 100)
    print("FORWARD RETURN STATISTICS")
    print("-" * 100)

    for horizon in horizons:
        col = f"fwd_ret_{horizon}s"
        returns = events[col].dropna()
        if len(returns) > 0:
            print(f"\n{horizon}s forward returns:")
            print(f"  Mean: {returns.mean():.2f} bps")
            print(f"  Std:  {returns.std():.2f} bps")
            print(f"  Min:  {returns.min():.2f} bps")
            print(f"  Max:  {returns.max():.2f} bps")
            print(f"  Win rate: {(returns > 0).mean():.1%}")

    # Check if running in interactive mode
    import sys
    is_interactive = sys.stdin.isatty()

    if is_interactive:
        # Interactive prompt for detailed view
        print("\n" + "=" * 100)
        print("Enter event number (1-{}) to view order book, or 'q' to quit: ".format(len(events)))

        while True:
            try:
                user_input = input(">>> ").strip()
                if user_input.lower() == "q":
                    break

                event_num = int(user_input)
                if 1 <= event_num <= len(events):
                    event = events.iloc[event_num - 1]
                    print(display_order_book(event, df, context_rows=3))
                else:
                    print(f"Enter a number between 1 and {len(events)}")
            except (ValueError, KeyboardInterrupt):
                break
    else:
        print("\n" + "=" * 100)
        print("(Non-interactive mode - use --show-events N to display order book for specific event)")


def list_available_dates() -> list[str]:
    """List available dates in the L2 data."""
    dates = []
    for date_dir in sorted(L2_RAW_DIR.glob("date=*")):
        dates.append(date_dir.name.replace("date=", ""))
    return dates


def list_available_symbols(date: str) -> list[str]:
    """List available symbols for a given date."""
    date_dir = L2_RAW_DIR / f"date={date}"
    if not date_dir.exists():
        return []

    symbols = []
    for symbol_dir in date_dir.glob("symbol=*"):
        symbols.append(symbol_dir.name.replace("symbol=", ""))
    return sorted(symbols)


def main():
    """Main entry point for interactive explorer."""

    parser = argparse.ArgumentParser(description="Explore L2 large order events")
    parser.add_argument("--symbol", type=str, help="Symbol to explore")
    parser.add_argument("--date", type=str, help="Date (YYYY-MM-DD)")
    parser.add_argument(
        "--min-size", type=float, default=1000, help="Minimum order size (default: 1000)"
    )
    parser.add_argument(
        "--max-events", type=int, default=10, help="Maximum events to display (default: 10)"
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[60, 300],
        help="Forward return horizons in seconds (default: 60 300)",
    )
    parser.add_argument("--list-dates", action="store_true", help="List available dates")
    parser.add_argument(
        "--list-symbols",
        type=str,
        metavar="DATE",
        help="List available symbols for DATE",
    )

    args = parser.parse_args()

    # Handle listing modes
    if args.list_dates:
        print("Available dates:")
        for date in list_available_dates():
            print(f"  {date}")
        return

    if args.list_symbols:
        symbols = list_available_symbols(args.list_symbols)
        if symbols:
            print(f"Available symbols for {args.list_symbols}:")
            for symbol in symbols:
                print(f"  {symbol}")
        else:
            print(f"No symbols found for {args.list_symbols}")
        return

    # Validate required args
    if not args.symbol or not args.date:
        parser.error("--symbol and --date are required for exploration")

    # Run exploration
    explore_large_orders(
        symbol=args.symbol,
        date=args.date,
        min_size=args.min_size,
        max_events=args.max_events,
        horizons=args.horizons,
    )


if __name__ == "__main__":
    main()
