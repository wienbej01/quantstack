#!/usr/bin/env python3
"""Triple-barrier labeling implementation following TRIPLE_BARRIER_APPROACH.md"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def create_trading_events(df, min_gap_minutes=30):
    """Create event start times - don't label every minute."""

    events = []
    df_sorted = df.sort_values(["symbol", "timestamp"])

    for symbol in df["symbol"].unique():
        symbol_data = df_sorted[df_sorted["symbol"] == symbol].copy()

        last_event_time = None

        for _, row in symbol_data.iterrows():
            # Event filters (strategy setup conditions)
            if (
                row["hour_et"] >= 9.5
                and row["hour_et"] <= 15.5  # Trading hours
                and row["atr_pct"] > 0.005  # Minimum volatility
                and row["volume_ratio_20"] > 1.2  # Above average volume
                and (
                    last_event_time is None
                    or (
                        pd.to_datetime(row["timestamp"]) - last_event_time
                    ).total_seconds()
                    >= min_gap_minutes * 60
                )
            ):
                events.append(
                    {
                        "event_id": len(events),
                        "symbol": row["symbol"],
                        "timestamp": row["timestamp"],
                        "entry_price": 100.0,  # Normalized price
                        "atr_pct": row["atr_pct"],
                        "hour_et": row["hour_et"],
                        "date": row["date"],
                    }
                )
                last_event_time = pd.to_datetime(row["timestamp"])

    return pd.DataFrame(events)


def apply_triple_barriers(
    events_df, price_data_df, pt_mult=2.0, sl_mult=1.5, horizon_minutes=390
):
    """Apply triple-barrier method to events."""

    results = []

    for i, event in events_df.iterrows():
        if i % 1000 == 0:
            logging.info(f"Processing barriers: {i:,}/{len(events_df):,}")

        symbol = event["symbol"]
        t0 = pd.to_datetime(event["timestamp"])
        p0 = event["entry_price"]
        vol = event["atr_pct"]

        # Clamp volatility for extremes
        vol = max(0.005, min(0.20, vol))

        # Calculate barrier distances
        pt_distance = pt_mult * vol
        sl_distance = sl_mult * vol

        # Time barrier (end of session or horizon)
        session_end = t0.replace(hour=16, minute=0, second=0)
        t1 = min(t0 + pd.Timedelta(minutes=horizon_minutes), session_end)

        # Get future price data for this symbol
        future_data = price_data_df[
            (price_data_df["symbol"] == symbol)
            & (pd.to_datetime(price_data_df["timestamp"]) > t0)
            & (pd.to_datetime(price_data_df["timestamp"]) <= t1)
            & (price_data_df["date"] == event["date"])
        ].sort_values("timestamp")

        if len(future_data) == 0:
            # No future data - time exit at entry price
            outcome = "time"
            exit_price = p0
            exit_time = t1
        else:
            # Check barriers for both long and short
            outcome_long, exit_price_long, exit_time_long = check_barriers_long(
                future_data, p0, pt_distance, sl_distance, t1
            )
            outcome_short, exit_price_short, exit_time_short = check_barriers_short(
                future_data, p0, pt_distance, sl_distance, t1
            )

            # Store both outcomes for meta-labeling
            results.append(
                {
                    "event_id": event["event_id"],
                    "symbol": symbol,
                    "entry_time": t0,
                    "entry_price": p0,
                    "vol_at_entry": vol,
                    "pt_distance": pt_distance,
                    "sl_distance": sl_distance,
                    # Long outcomes
                    "outcome_long": outcome_long,
                    "exit_price_long": exit_price_long,
                    "exit_time_long": exit_time_long,
                    "return_long": (exit_price_long - p0) / p0,
                    # Short outcomes
                    "outcome_short": outcome_short,
                    "exit_price_short": exit_price_short,
                    "exit_time_short": exit_time_short,
                    "return_short": (p0 - exit_price_short) / p0,
                    # Labels (3-class for long, meta-label for both)
                    "label_long_3class": (
                        1
                        if outcome_long == "pt"
                        else (-1 if outcome_long == "sl" else 0)
                    ),
                    "label_short_3class": (
                        1
                        if outcome_short == "pt"
                        else (-1 if outcome_short == "sl" else 0)
                    ),
                    "label_long_meta": 1 if outcome_long == "pt" else 0,
                    "label_short_meta": 1 if outcome_short == "pt" else 0,
                }
            )
            continue

        # Fallback for no future data
        results.append(
            {
                "event_id": event["event_id"],
                "symbol": symbol,
                "entry_time": t0,
                "entry_price": p0,
                "vol_at_entry": vol,
                "pt_distance": pt_distance,
                "sl_distance": sl_distance,
                "outcome_long": "time",
                "exit_price_long": p0,
                "exit_time_long": t1,
                "return_long": 0.0,
                "outcome_short": "time",
                "exit_price_short": p0,
                "exit_time_short": t1,
                "return_short": 0.0,
                "label_long_3class": 0,
                "label_short_3class": 0,
                "label_long_meta": 0,
                "label_short_meta": 0,
            }
        )

    return pd.DataFrame(results)


def check_barriers_long(future_data, p0, pt_distance, sl_distance, t1):
    """Check barriers for long position using OHLC logic."""

    pt_price = p0 * (1 + pt_distance)
    sl_price = p0 * (1 - sl_distance)

    for _, bar in future_data.iterrows():
        # Simulate OHLC within the bar (using forward_return as proxy)
        bar_return = bar.get("forward_return", 0)
        bar_high = p0 * (1 + max(0, bar_return))
        bar_low = p0 * (1 + min(0, bar_return))

        # Check PT first (conservative: assume adverse hit first if both)
        if bar_low <= sl_price:
            return "sl", sl_price, pd.to_datetime(bar["timestamp"])
        elif bar_high >= pt_price:
            return "pt", pt_price, pd.to_datetime(bar["timestamp"])

    # Time barrier hit
    last_price = p0 * (1 + future_data.iloc[-1].get("forward_return", 0))
    return "time", last_price, t1


def check_barriers_short(future_data, p0, pt_distance, sl_distance, t1):
    """Check barriers for short position using OHLC logic."""

    pt_price = p0 * (1 - pt_distance)  # Profit target below entry
    sl_price = p0 * (1 + sl_distance)  # Stop loss above entry

    for _, bar in future_data.iterrows():
        # Simulate OHLC within the bar
        bar_return = bar.get("forward_return", 0)
        bar_high = p0 * (1 + max(0, bar_return))
        bar_low = p0 * (1 + min(0, bar_return))

        # Check SL first (conservative)
        if bar_high >= sl_price:
            return "sl", sl_price, pd.to_datetime(bar["timestamp"])
        elif bar_low <= pt_price:
            return "pt", pt_price, pd.to_datetime(bar["timestamp"])

    # Time barrier hit
    last_price = p0 * (1 + future_data.iloc[-1].get("forward_return", 0))
    return "time", last_price, t1


def calculate_net_returns_with_costs(results_df):
    """Calculate net returns including realistic transaction costs."""

    fee_per_trade = 0.70  # $0.35 * 2 sides
    spread_bps = 5  # 5 basis points

    for side in ["long", "short"]:
        gross_returns = results_df[f"return_{side}"]

        # Calculate position sizes (simplified)
        position_values = 100.0 * 100  # $100 price * 100 shares

        # Calculate costs
        spread_costs = position_values * (spread_bps / 10000)
        total_costs = fee_per_trade + spread_costs
        cost_pct = total_costs / position_values

        # Net returns
        net_returns = gross_returns - cost_pct
        results_df[f"net_return_{side}"] = net_returns

        # Net labels (EV regression targets)
        results_df[f"label_{side}_ev"] = net_returns

        # Net meta labels (profitable after costs)
        results_df[f"label_{side}_net_meta"] = (net_returns > 0.002).astype(
            int
        )  # >0.2% net

    return results_df


def main():
    """Main triple-barrier labeling pipeline."""
    logging.info("=" * 80)
    logging.info("TRIPLE-BARRIER LABELING IMPLEMENTATION")
    logging.info("=" * 80)

    # Load base features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error("Base features not found")
        return False

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()

    logging.info(f"Loaded {len(pdf):,} rows")

    # Step 1: Create trading events (filtered)
    logging.info("Creating trading events...")
    events_df = create_trading_events(pdf)
    logging.info(f"Created {len(events_df):,} events from {len(pdf):,} bars")

    # Step 2: Apply triple barriers
    logging.info("Applying triple barriers...")
    results_df = apply_triple_barriers(events_df, pdf)
    logging.info(f"Processed {len(results_df):,} barrier outcomes")

    # Step 3: Calculate net returns with costs
    logging.info("Calculating net returns with costs...")
    results_df = calculate_net_returns_with_costs(results_df)

    # Validation
    logging.info("\n=== TRIPLE-BARRIER VALIDATION ===")
    logging.info(f"Events created: {len(events_df):,}")
    logging.info(f"Barrier outcomes: {len(results_df):,}")

    for side in ["long", "short"]:
        pt_rate = (results_df[f"outcome_{side}"] == "pt").mean() * 100
        sl_rate = (results_df[f"outcome_{side}"] == "sl").mean() * 100
        time_rate = (results_df[f"outcome_{side}"] == "time").mean() * 100
        net_meta_rate = results_df[f"label_{side}_net_meta"].mean() * 100
        avg_net_return = results_df[f"net_return_{side}"].mean() * 100

        logging.info(f"\n{side.upper()} outcomes:")
        logging.info(f"  PT hit: {pt_rate:.1f}%")
        logging.info(f"  SL hit: {sl_rate:.1f}%")
        logging.info(f"  Time exit: {time_rate:.1f}%")
        logging.info(f"  Net profitable: {net_meta_rate:.1f}%")
        logging.info(f"  Avg net return: {avg_net_return:.3f}%")

    # Save results
    output_dir = Path("run/triple_barrier_labels")
    output_dir.mkdir(exist_ok=True)

    # Save events and results
    events_df.to_parquet(output_dir / "events.parquet")
    results_df.to_parquet(output_dir / "barrier_outcomes.parquet")

    logging.info(f"✅ Saved triple-barrier results to {output_dir}")

    return True


if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)
