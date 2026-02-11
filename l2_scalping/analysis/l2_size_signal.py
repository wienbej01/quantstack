#!/usr/bin/env python3
"""
L2 Order Size Signal Analysis

Analyzes whether "large" order sizes predict subsequent price movements:
1. Define large order events using percentile-based thresholds
2. Compute forward returns at multiple horizons
3. Compare returns after large orders vs baseline
4. Calculate t-statistics for significance
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


def load_l2_raw_data() -> pd.DataFrame:
    """Load all raw L2 data from parquet files."""
    logger.info("Loading raw L2 data...")
    import sys
    import time

    all_data = []
    file_count = 0
    start_time = time.time()

    for date_dir in sorted(L2_RAW_DIR.glob("date=*")):
        date_str = date_dir.name.replace("date=", "")
        logger.info(f"  Processing {date_str}...")
        sys.stdout.flush()

        for symbol_dir in date_dir.glob("symbol=*"):
            symbol = symbol_dir.name.replace("symbol=", "")

            for pq_file in symbol_dir.glob("*.parquet"):
                try:
                    df = pd.read_parquet(pq_file)
                    df["symbol"] = symbol
                    df["date"] = date_str
                    all_data.append(df)
                    file_count += 1

                    # Heartbeat every 100 files
                    if file_count % 100 == 0:
                        elapsed = time.time() - start_time
                        logger.info(
                            f"    Loaded {file_count} files in {elapsed:.0f}s..."
                        )
                        sys.stdout.flush()
                except Exception as e:
                    pass  # Skip errors silently

    if not all_data:
        logger.error("No L2 data found!")
        return pd.DataFrame()

    df = pd.concat(all_data, ignore_index=True)
    logger.info(
        f"Loaded {len(df):,} L2 snapshots across {df['symbol'].nunique()} symbols"
    )
    return df


def compute_size_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute size-related features from raw L2 data."""
    logger.info("Computing size features...")

    df = df.copy()

    # Max sizes across levels
    bid_cols = [f"bid_sz_{i}" for i in range(1, 6) if f"bid_sz_{i}" in df.columns]
    ask_cols = [f"ask_sz_{i}" for i in range(1, 6) if f"ask_sz_{i}" in df.columns]

    if bid_cols:
        df["max_bid_sz"] = df[bid_cols].max(axis=1)
        df["total_bid_sz"] = df[bid_cols].sum(axis=1)

    if ask_cols:
        df["max_ask_sz"] = df[ask_cols].max(axis=1)
        df["total_ask_sz"] = df[ask_cols].sum(axis=1)

    # Size ratio (concentration of largest order)
    if "max_bid_sz" in df.columns and "total_bid_sz" in df.columns:
        df["bid_size_ratio"] = np.where(
            df["total_bid_sz"] > 0, df["max_bid_sz"] / df["total_bid_sz"], 0
        )

    if "max_ask_sz" in df.columns and "total_ask_sz" in df.columns:
        df["ask_size_ratio"] = np.where(
            df["total_ask_sz"] > 0, df["max_ask_sz"] / df["total_ask_sz"], 0
        )

    # Compute mid price
    if "bid_px_1" in df.columns and "ask_px_1" in df.columns:
        df["mid"] = (df["bid_px_1"] + df["ask_px_1"]) / 2

    return df


def compute_percentile_thresholds(
    df: pd.DataFrame, percentile: float = 95.0
) -> dict[str, float]:
    """Compute percentile-based thresholds per symbol."""
    logger.info(f"Computing {percentile}th percentile thresholds per symbol...")

    thresholds = {}

    for symbol in df["symbol"].unique():
        symbol_df = df[df["symbol"] == symbol]

        # Collect all bid and ask sizes
        all_sizes = []
        for level in range(1, 6):
            for col in [f"bid_sz_{level}", f"ask_sz_{level}"]:
                if col in symbol_df.columns:
                    all_sizes.extend(symbol_df[col].dropna().tolist())

        all_sizes = np.array(all_sizes)
        all_sizes = all_sizes[all_sizes > 0]

        if len(all_sizes) > 0:
            thresholds[symbol] = float(np.percentile(all_sizes, percentile))

    logger.info(f"Computed thresholds for {len(thresholds)} symbols")
    return thresholds


def compute_forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Compute forward mid-price returns at given horizons (in seconds)."""

    # Convert ts_utc to datetime and sort
    df = df.copy()
    df["ts"] = pd.to_datetime(df["ts_utc"])
    df = df.sort_values(["symbol", "ts"])

    result = df.copy()

    for symbol in df["symbol"].unique():
        symbol_df = result[result["symbol"] == symbol].copy()

        for horizon in horizons:
            # Forward mid price
            fwd_mid = symbol_df["mid"].shift(-horizon)
            # Return in basis points
            fwd_ret = (fwd_mid / symbol_df["mid"] - 1) * 10000
            result.loc[symbol_df.index, f"fwd_ret_{horizon}s"] = fwd_ret.values

    return result


def compute_signal_stats(
    returns: pd.Series, min_samples: int = 50
) -> dict[str, Any] | None:
    """Compute statistics for signal returns."""

    returns = returns.dropna()
    n = len(returns)

    if n < min_samples:
        return None

    mean_ret = returns.mean()
    std_ret = returns.std()

    # t-statistic
    if std_ret > 0:
        t_stat = mean_ret / (std_ret / np.sqrt(n))
        p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1))
    else:
        t_stat = 0.0
        p_value = 1.0

    # Win rate
    wins = returns > 0
    win_rate = wins.mean()

    # Avg win / avg loss
    avg_win = returns[wins].mean() if wins.any() else 0.0
    avg_loss = abs(returns[~wins].mean()) if (~wins).any() else 0.0

    # Profit factor
    gross_profit = returns[wins].sum() if wins.any() else 0.0
    gross_loss = abs(returns[~wins].sum()) if (~wins).any() else 0.001
    profit_factor = gross_profit / gross_loss

    # Sharpe (annualized, assuming ~1 obs/second)
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


def analyze_size_signals(
    df: pd.DataFrame,
    horizons: list[int],
    percentile: float = 95.0,
) -> pd.DataFrame:
    """Analyze size-based signals across multiple horizons."""

    logger.info(f"\n=== ANALYZING SIZE SIGNALS (p{percentile} THRESHOLD) ===")

    # Compute thresholds
    thresholds = compute_percentile_thresholds(df, percentile)

    # Create large order flags
    df = df.copy()
    df["large_bid"] = False
    df["large_ask"] = False

    for symbol, threshold in thresholds.items():
        mask = df["symbol"] == symbol
        if "max_bid_sz" in df.columns:
            df.loc[mask, "large_bid"] = df.loc[mask, "max_bid_sz"] > threshold
        if "max_ask_sz" in df.columns:
            df.loc[mask, "large_ask"] = df.loc[mask, "max_ask_sz"] > threshold

    # Analyze each signal type
    signals = []

    signal_definitions = [
        # Large bid orders
        ("large_bid", "Large bid order (max_bid_sz > p95)", df["large_bid"], "LONG"),
        # Large ask orders
        ("large_ask", "Large ask order (max_ask_sz > p95)", df["large_ask"], "SHORT"),
        # Large bid + concentrated
        (
            "large_bid_concentrated",
            "Large bid + high concentration",
            df["large_bid"] & (df.get("bid_size_ratio", 0) > 0.5),
            "LONG",
        ),
        # Large ask + concentrated
        (
            "large_ask_concentrated",
            "Large ask + high concentration",
            df["large_ask"] & (df.get("ask_size_ratio", 0) > 0.5),
            "SHORT",
        ),
    ]

    for signal_name, description, mask, direction in signal_definitions:
        if not isinstance(mask, pd.Series):
            continue

        n_events = mask.sum()
        logger.info(f"\nSignal: {description}")
        logger.info(f"  Events: {n_events:,}")

        for horizon in horizons:
            return_col = f"fwd_ret_{horizon}s"
            if return_col not in df.columns:
                continue

            # Get returns for this signal
            signal_returns = df.loc[mask, return_col]

            # For SHORT signals, flip returns
            if direction == "SHORT":
                signal_returns = -signal_returns

            stats = compute_signal_stats(signal_returns)

            if stats:
                logger.info(
                    f"  {horizon}s: t={stats['t_stat']:.2f}, "
                    f"exp={stats['expectancy_bps']:.2f}bps, "
                    f"wr={stats['win_rate']:.1%}, n={stats['n_trades']}"
                )

                signals.append(
                    {
                        "signal": signal_name,
                        "description": description,
                        "direction": direction,
                        "horizon_sec": horizon,
                        **stats,
                    }
                )

    if signals:
        return pd.DataFrame(signals)
    return pd.DataFrame()


def compare_vs_baseline(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Compare size signals vs baseline (all periods)."""

    logger.info(f"\n=== BASELINE COMPARISON ===")

    comparisons = []

    for horizon in horizons:
        return_col = f"fwd_ret_{horizon}s"
        if return_col not in df.columns:
            continue

        # Baseline stats
        baseline_returns = df[return_col].dropna()
        baseline_stats = compute_signal_stats(baseline_returns)

        if baseline_stats:
            logger.info(f"\n{horizon}s Baseline:")
            logger.info(
                f"  exp={baseline_stats['expectancy_bps']:.2f}bps, "
                f"std={baseline_stats['std_bps']:.2f}bps"
            )

        # Large bid vs baseline
        if "large_bid" in df.columns:
            large_bid_returns = df.loc[df["large_bid"], return_col]
            large_bid_stats = compute_signal_stats(large_bid_returns)

            if large_bid_stats and baseline_stats:
                improvement = (
                    large_bid_stats["expectancy_bps"] - baseline_stats["expectancy_bps"]
                )
                logger.info(
                    f"  After large bid: exp={large_bid_stats['expectancy_bps']:.2f}bps "
                    f"({improvement:+.2f}bps vs baseline)"
                )

                comparisons.append(
                    {
                        "horizon_sec": horizon,
                        "scenario": "large_bid_vs_baseline",
                        "signal_expectancy_bps": large_bid_stats["expectancy_bps"],
                        "baseline_expectancy_bps": baseline_stats["expectancy_bps"],
                        "diff_bps": improvement,
                        "signal_n": large_bid_stats["n_trades"],
                        "baseline_n": baseline_stats["n_trades"],
                    }
                )

        # Large ask vs baseline (flip for comparison)
        if "large_ask" in df.columns:
            large_ask_returns = -df.loc[df["large_ask"], return_col]
            large_ask_stats = compute_signal_stats(large_ask_returns)

            if large_ask_stats and baseline_stats:
                improvement = (
                    large_ask_stats["expectancy_bps"] - baseline_stats["expectancy_bps"]
                )
                logger.info(
                    f"  After large ask: exp={large_ask_stats['expectancy_bps']:.2f}bps "
                    f"({improvement:+.2f}bps vs baseline)"
                )

                comparisons.append(
                    {
                        "horizon_sec": horizon,
                        "scenario": "large_ask_vs_baseline",
                        "signal_expectancy_bps": large_ask_stats["expectancy_bps"],
                        "baseline_expectancy_bps": baseline_stats["expectancy_bps"],
                        "diff_bps": improvement,
                        "signal_n": large_ask_stats["n_trades"],
                        "baseline_n": baseline_stats["n_trades"],
                    }
                )

    if comparisons:
        return pd.DataFrame(comparisons)
    return pd.DataFrame()


def main():
    """Main entry point for size signal analysis."""

    parser = argparse.ArgumentParser(description="Analyze L2 order size signals")
    parser.add_argument(
        "--percentile",
        type=float,
        default=95.0,
        help="Percentile threshold for large orders (default: 95)",
    )
    parser.add_argument(
        "--horizons",
        type=int,
        nargs="+",
        default=[30, 60, 120, 300],
        help="Forward return horizons in seconds (default: 30 60 120 300)",
    )
    args = parser.parse_args()

    logger.info("=" * 70)
    logger.info("L2 ORDER SIZE SIGNAL ANALYSIS")
    logger.info("=" * 70)
    logger.info(f"Percentile threshold: p{args.percentile}")
    logger.info(f"Horizons: {args.horizons}s")

    # Load data
    logger.info("\n[1/5] Loading raw L2 data...")
    df = load_l2_raw_data()

    if df.empty:
        logger.error("No data loaded!")
        return

    # Compute features
    logger.info("\n[2/5] Computing size features...")
    df = compute_size_features(df)

    # Compute forward returns
    logger.info("\n[3/5] Computing forward returns...")
    df = compute_forward_returns(df, args.horizons)

    # Analyze signals
    logger.info("\n[4/5] Analyzing size signals...")
    signals_df = analyze_size_signals(df, args.horizons, args.percentile)

    if not signals_df.empty:
        # Save signals
        signals_file = OUTPUT_DIR / f"size_signals_p{int(args.percentile)}.csv"
        signals_df.to_csv(signals_file, index=False)
        logger.info(f"\nSaved signal results to {signals_file}")

        # Print summary
        logger.info("\n" + "=" * 70)
        logger.info("TOP SIGNALS BY T-STATISTIC")
        logger.info("=" * 70)

        top_signals = signals_df.sort_values("t_stat", ascending=False).head(10)
        cols = [
            "signal",
            "direction",
            "horizon_sec",
            "t_stat",
            "expectancy_bps",
            "win_rate",
            "n_trades",
        ]
        print(top_signals[cols].to_string(index=False))

    # Baseline comparison
    logger.info("\n[5/5] Comparing vs baseline...")
    baseline_df = compare_vs_baseline(df, args.horizons)

    if not baseline_df.empty:
        baseline_file = OUTPUT_DIR / f"baseline_comparison_p{int(args.percentile)}.csv"
        baseline_df.to_csv(baseline_file, index=False)
        logger.info(f"\nSaved baseline comparison to {baseline_file}")

    logger.info("\n" + "=" * 70)
    logger.info("COMPLETE")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()
