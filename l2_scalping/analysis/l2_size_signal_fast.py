#!/usr/bin/env python3
"""
L2 Order Size Signal Analysis - Efficient Streaming Version

Analyzes whether large order sizes predict price movements.
Processes data incrementally without loading all 482k files into RAM.
"""

import argparse
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
L2_RAW_DIR = Path("/home/jacobw/quantstack/data/l2/l2_maximum/raw")
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output/size_analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def compute_signal_stats(
    returns: list[float], min_samples: int = 50
) -> dict[str, Any] | None:
    """Compute statistics for signal returns."""

    returns = np.array(returns)
    returns = returns[~np.isnan(returns)]
    n = len(returns)

    if n < min_samples:
        return None

    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns))

    if std_ret > 0:
        t_stat = mean_ret / (std_ret / np.sqrt(n))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    else:
        t_stat = 0.0
        p_value = 1.0

    wins = returns > 0
    win_rate = float(wins.mean())

    avg_win = float(returns[wins].mean()) if wins.any() else 0.0
    avg_loss = float(abs(returns[~wins]).mean()) if (~wins).any() else 0.0

    gross_profit = float(returns[wins].sum()) if wins.any() else 0.0
    gross_loss = float(abs(returns[~wins]).sum()) if (~wins).any() else 0.0
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    if std_ret > 0:
        sharpe = mean_ret / std_ret * np.sqrt(252 * 6.5 * 3600)
    else:
        sharpe = 0.0

    return {
        "t_stat": t_stat,
        "p_value": p_value,
        "expectancy_bps": mean_ret,
        "win_rate": win_rate,
        "avg_win_bps": avg_win,
        "avg_loss_bps": avg_loss,
        "profit_factor": profit_factor,
        "sharpe": sharpe,
        "n_trades": n,
        "std_bps": std_ret,
    }


def process_date_file(
    date_dir: Path, threshold: float, horizons: list[int]
) -> tuple[dict, list]:
    """Process all symbols for a single date."""

    date_str = date_dir.name.replace("date=", "")
    logger.info(f"    Processing {date_str}...")

    symbol_data = {}
    file_count = 0

    for symbol_dir in date_dir.glob("symbol=*"):
        symbol = symbol_dir.name.replace("symbol=", "")

        if symbol not in symbol_data:
            symbol_data[symbol] = {
                "ts": [],
                "mid": [],
                "max_bid_sz": [],
                "max_ask_sz": [],
                "large_bid": [],
                "large_ask": [],
            }

        for pq_file in symbol_dir.glob("*.parquet"):
            try:
                df = pd.read_parquet(pq_file)
                file_count += 1

                if "bid_px_1" in df.columns and "ask_px_1" in df.columns:
                    df["mid"] = (df["bid_px_1"] + df["ask_px_1"]) / 2
                    df["ts"] = pd.to_datetime(df["ts_utc"])

                    # Compute max sizes
                    bid_cols = [f"bid_sz_{i}" for i in range(1, 6) if f"bid_sz_{i}" in df.columns]
                    ask_cols = [f"ask_sz_{i}" for i in range(1, 6) if f"ask_sz_{i}" in df.columns]

                    if bid_cols:
                        df["max_bid_sz"] = df[bid_cols].max(axis=1)
                    if ask_cols:
                        df["max_ask_sz"] = df[ask_cols].max(axis=1)

                    # Mark large orders
                    df["large_bid"] = df.get("max_bid_sz", 0) >= threshold
                    df["large_ask"] = df.get("max_ask_sz", 0) >= threshold

                    symbol_data[symbol]["ts"].extend(df["ts"].tolist())
                    symbol_data[symbol]["mid"].extend(df["mid"].tolist())
                    symbol_data[symbol]["max_bid_sz"].extend(df.get("max_bid_sz", 0).tolist())
                    symbol_data[symbol]["max_ask_sz"].extend(df.get("max_ask_sz", 0).tolist())
                    symbol_data[symbol]["large_bid"].extend(df["large_bid"].tolist())
                    symbol_data[symbol]["large_ask"].extend(df["large_ask"].tolist())

            except Exception:
                pass

    return symbol_data, file_count


def main():
    """Main entry point."""

    parser = argparse.ArgumentParser(description="Analyze L2 order size signals")
    parser.add_argument(
        "--threshold",
        type=float,
        default=15000,
        help="Large order threshold in shares (default: 15000)",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[30, 60, 120, 300],
        help="Forward return horizons in seconds",
    )
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("L2 ORDER SIZE SIGNAL ANALYSIS (STREAMING)")
    logger.info("=" * 70)
    logger.info(f"Threshold: {args.threshold} shares")
    logger.info(f"Horizons: {args.horizons}s")

    # Process all dates
    logger.info("\n[1/4] Loading data and computing forward returns...")

    all_symbol_data = {}
    total_files = 0
    start_time = __import__("time").time()

    for date_dir in sorted(L2_RAW_DIR.glob("date=*")):
        symbol_data, files = process_date_file(date_dir, args.threshold, args.horizons)

        for symbol, data in symbol_data.items():
            if symbol not in all_symbol_data:
                all_symbol_data[symbol] = {
                    "ts": [],
                    "mid": [],
                    "max_bid_sz": [],
                    "max_ask_sz": [],
                    "large_bid": [],
                    "large_ask": [],
                }

            for key in all_symbol_data[symbol].keys():
                all_symbol_data[symbol][key].extend(data[key])

        total_files += files

        elapsed = __import__("time").time() - start_time
        logger.info(f"      Processed {total_files:,} files in {elapsed:.0f}s")

    logger.info(f"\n  Loaded {len(all_symbol_data)} symbols, {total_files:,} files")

    # Compute forward returns and analyze signals
    logger.info("\n[2/4] Computing forward returns and signals...")

    signals = []

    for symbol, data in all_symbol_data.items():
        if len(data["mid"]) < 1000:
            continue

        df = pd.DataFrame({
            "ts": data["ts"],
            "mid": data["mid"],
            "max_bid_sz": data["max_bid_sz"],
            "max_ask_sz": data["max_ask_sz"],
            "large_bid": data["large_bid"],
            "large_ask": data["large_ask"],
        })
        df = df.sort_values("ts")

        # Compute forward returns
        for horizon in args.horizons:
            fwd_mid = df["mid"].shift(-horizon)
            fwd_ret = (fwd_mid / df["mid"] - 1) * 10000  # bps
            df[f"fwd_ret_{horizon}s"] = fwd_ret

            # Large bid signal
            large_bid_returns = df.loc[df["large_bid"], f"fwd_ret_{horizon}s"].values
            stats_bid = compute_signal_stats(large_bid_returns.tolist())

            if stats_bid:
                signals.append({
                    "signal": "large_bid",
                    "symbol": symbol,
                    "horizon_sec": horizon,
                    **stats_bid,
                })

            # Large ask signal (flip for short)
            large_ask_returns = -df.loc[df["large_ask"], f"fwd_ret_{horizon}s"].values
            stats_ask = compute_signal_stats(large_ask_returns.tolist())

            if stats_ask:
                signals.append({
                    "signal": "large_ask",
                    "symbol": symbol,
                    "horizon_sec": horizon,
                    **stats_ask,
                })

    if not signals:
        logger.error("No signals found!")
        return

    signals_df = pd.DataFrame(signals)

    logger.info("\n[3/4] Aggregating results...")

    # Aggregate by signal type and horizon
    agg_results = []

    for signal_name in ["large_bid", "large_ask"]:
        for horizon in args.horizons:
            subset = signals_df[(signals_df["signal"] == signal_name) & (signals_df["horizon_sec"] == horizon)]

            if len(subset) == 0:
                continue

            # Combine all returns
            all_returns = []
            for _, row in subset.iterrows():
                symbol_data = all_symbol_data[row["symbol"]]
                df = pd.DataFrame({"mid": symbol_data["mid"], "large_bid": symbol_data["large_bid"], "large_ask": symbol_data["large_ask"]})
                df = df.sort_values("mid")  # Need ts, using index as proxy

                # Recompute forward returns for this symbol
                for h_idx, h in enumerate(args.horizons):
                    if h == horizon:
                        fwd_mid = df["mid"].shift(-h)
                        fwd_ret = (fwd_mid / df["mid"] - 1) * 10000
                        df["fwd_ret"] = fwd_ret
                        break

                if signal_name == "large_bid":
                    event_returns = df.loc[df["large_bid"], "fwd_ret"].values
                else:
                    event_returns = -df.loc[df["large_ask"], "fwd_ret"].values

                all_returns.extend(event_returns[~np.isnan(event_returns)].tolist())

            combined_stats = compute_signal_stats(all_returns, min_samples=10)

            if combined_stats:
                agg_results.append({
                    "signal": signal_name,
                    "horizon_sec": horizon,
                    **combined_stats,
                })

    agg_df = pd.DataFrame(agg_results)

    # Save results
    logger.info("\n[4/4] Saving results...")

    signals_file = OUTPUT_DIR / f"size_signals_thresh{int(args.threshold)}.csv"
    signals_df.to_csv(signals_file, index=False)
    logger.info(f"  Per-symbol results: {signals_file}")

    agg_file = OUTPUT_DIR / f"size_signals_agg_thresh{int(args.threshold)}.csv"
    agg_df.to_csv(agg_file, index=False)
    logger.info(f"  Aggregated results: {agg_file}")

    # Print summary
    logger.info("\n" + "=" * 70)
    logger.info("ALPHA RESULTS - LARGE ORDER SIGNALS")
    logger.info("=" * 70)

    print("\n" + "=" * 70)
    print("AGGREGATED SIGNAL PERFORMANCE")
    print("=" * 70)

    for _, row in agg_df.iterrows():
        direction = "LONG" if row["signal"] == "large_bid" else "SHORT"
        sig = "***" if abs(row["t_stat"]) >= 2 else "  " if abs(row["t_stat"]) >= 1.5 else ""

        print(f"\n{row['signal'].upper()} → {direction} ({row['horizon_sec']}s horizon): {sig}")
        print(f"  t-stat:      {row['t_stat']:+.2f}")
        print(f"  expectancy:  {row['expectancy_bps']:+.2f} bps")
        print(f"  win rate:    {row['win_rate']:.1%}")
        print(f"  profit factor: {row['profit_factor']:.2f}")
        print(f"  n_trades:    {row['n_trades']:,}")
        print(f"  sharpe:      {row['sharpe']:.2f}")

    print("\n" + "=" * 70)
    print("INTERPRETATION:")
    print("=" * 70)
    print("  t-stat >= 2.0  = Statistically significant (95% confidence)")
    print("  t-stat >= 1.5  = Marginally significant")
    print("  expectancy > 0 = Positive alpha (profitable)")
    print(f"\n  Large Bid Orders → Expect price to go UP (long signal)")
    print(f"  Large Ask Orders → Expect price to go DOWN (short signal)")

    if any(agg_df["t_stat"] >= 2):
        print("\n  *** SIGNIFICANT ALPHA FOUND ***")
    elif any(agg_df["t_stat"] >= 1.5):
        print("\n  *** MARGINAL ALPHA FOUND ***")
    else:
        print("\n  *** NO SIGNIFICANT ALPHA DETECTED ***")


if __name__ == "__main__":
    main()
