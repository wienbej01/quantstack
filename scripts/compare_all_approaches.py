#!/usr/bin/env python3
"""Compare all labeling approaches: Mean Reversion vs Momentum strategies."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_all_results():
    """Load all labeling results."""

    results = {}

    # Mean reversion approaches
    paths = {
        "Mean Reversion - Triple Barrier": "run/triple_barrier_labels/barrier_outcomes.parquet",
        "Mean Reversion - Fixed Time": "run/fixed_time_labels/labels.parquet",
        "Momentum - Fixed Time": "run/momentum_breakout_labels/labels.parquet",
        "Momentum - Triple Barrier": "run/momentum_triple_barrier_labels/labels.parquet",
    }

    for name, path in paths.items():
        if Path(path).exists():
            results[name] = pd.read_parquet(path)
            logging.info(f"Loaded {name}: {len(results[name]):,} events")
        else:
            logging.warning(f"Missing: {name}")

    return results


def analyze_approach(name, df):
    """Analyze a single approach."""

    if len(df) == 0:
        return None

    # Determine return column
    if "net_return" in df.columns:
        returns = df["net_return"]
    elif "net_return_long" in df.columns:
        returns = df["net_return_long"]  # Use long side for triple barrier
    else:
        return None

    # Basic metrics
    total_events = len(df)
    avg_return = returns.mean() * 100
    return_std = returns.std() * 100
    sharpe = avg_return / return_std if return_std > 0 else 0
    win_rate = (returns > 0).mean() * 100
    profitable_rate = (returns > 0.002).mean() * 100  # >0.2% threshold

    # Risk metrics
    max_loss = returns.min() * 100
    max_gain = returns.max() * 100

    # Edge analysis
    winners = returns[returns > 0.002]
    losers = returns[returns < -0.002]

    avg_winner = winners.mean() * 100 if len(winners) > 0 else 0
    avg_loser = losers.mean() * 100 if len(losers) > 0 else 0
    edge_ratio = abs(avg_winner / avg_loser) if avg_loser != 0 else 0

    return {
        "name": name,
        "total_events": total_events,
        "avg_return": avg_return,
        "return_std": return_std,
        "sharpe": sharpe,
        "win_rate": win_rate,
        "profitable_rate": profitable_rate,
        "max_loss": max_loss,
        "max_gain": max_gain,
        "avg_winner": avg_winner,
        "avg_loser": avg_loser,
        "edge_ratio": edge_ratio,
    }


def compare_all_approaches():
    """Compare all labeling approaches."""

    logging.info("=" * 80)
    logging.info("COMPREHENSIVE APPROACH COMPARISON")
    logging.info("=" * 80)

    # Load all results
    all_results = load_all_results()

    if len(all_results) == 0:
        logging.error("No results found to compare")
        return False

    # Analyze each approach
    analyses = []
    for name, df in all_results.items():
        analysis = analyze_approach(name, df)
        if analysis:
            analyses.append(analysis)

    if len(analyses) == 0:
        logging.error("No valid analyses generated")
        return False

    # Create comparison table
    logging.info("\n=== PERFORMANCE COMPARISON TABLE ===")

    # Header
    header = f"{'Strategy':<30} {'Events':<8} {'Avg Ret':<8} {'Sharpe':<7} {'Win%':<6} {'Prof%':<6} {'Edge':<6}"
    logging.info(header)
    logging.info("-" * len(header))

    # Sort by Sharpe ratio
    analyses.sort(key=lambda x: x["sharpe"], reverse=True)

    for analysis in analyses:
        row = (
            f"{analysis['name']:<30} "
            f"{analysis['total_events']:<8,} "
            f"{analysis['avg_return']:<+7.3f}% "
            f"{analysis['sharpe']:<+6.3f} "
            f"{analysis['win_rate']:<5.1f}% "
            f"{analysis['profitable_rate']:<5.1f}% "
            f"{analysis['edge_ratio']:<5.2f}"
        )
        logging.info(row)

    # Detailed analysis
    logging.info("\n=== DETAILED ANALYSIS ===")

    best_approach = analyses[0]
    logging.info(f"\n🏆 BEST PERFORMER: {best_approach['name']}")
    logging.info(f"   Sharpe Ratio: {best_approach['sharpe']:.3f}")
    logging.info(f"   Expected Value: {best_approach['avg_return']:.3f}%")
    logging.info(f"   Sample Size: {best_approach['total_events']:,} events")

    # Strategy comparison
    logging.info("\n=== STRATEGY COMPARISON ===")

    # Group by strategy type
    mean_reversion = [a for a in analyses if "Mean Reversion" in a["name"]]
    momentum = [a for a in analyses if "Momentum" in a["name"]]

    if mean_reversion:
        mr_best = max(mean_reversion, key=lambda x: x["sharpe"])
        logging.info(f"\nBest Mean Reversion: {mr_best['name']}")
        logging.info(
            f"   Sharpe: {mr_best['sharpe']:.3f}, EV: {mr_best['avg_return']:.3f}%"
        )

    if momentum:
        mom_best = max(momentum, key=lambda x: x["sharpe"])
        logging.info(f"\nBest Momentum: {mom_best['name']}")
        logging.info(
            f"   Sharpe: {mom_best['sharpe']:.3f}, EV: {mom_best['avg_return']:.3f}%"
        )

    # Exit method comparison
    logging.info("\n=== EXIT METHOD COMPARISON ===")

    fixed_time = [a for a in analyses if "Fixed Time" in a["name"]]
    triple_barrier = [a for a in analyses if "Triple Barrier" in a["name"]]

    if fixed_time:
        ft_avg_sharpe = np.mean([a["sharpe"] for a in fixed_time])
        ft_avg_events = np.mean([a["total_events"] for a in fixed_time])
        logging.info(f"\nFixed Time Average:")
        logging.info(f"   Avg Sharpe: {ft_avg_sharpe:.3f}")
        logging.info(f"   Avg Events: {ft_avg_events:,.0f}")

    if triple_barrier:
        tb_avg_sharpe = np.mean([a["sharpe"] for a in triple_barrier])
        tb_avg_events = np.mean([a["total_events"] for a in triple_barrier])
        logging.info(f"\nTriple Barrier Average:")
        logging.info(f"   Avg Sharpe: {tb_avg_sharpe:.3f}")
        logging.info(f"   Avg Events: {tb_avg_events:,.0f}")

    # Risk analysis
    logging.info("\n=== RISK ANALYSIS ===")

    for analysis in analyses:
        logging.info(f"\n{analysis['name']}:")
        logging.info(f"   Max Loss: {analysis['max_loss']:.2f}%")
        logging.info(f"   Max Gain: {analysis['max_gain']:.2f}%")
        logging.info(f"   Avg Winner: {analysis['avg_winner']:.3f}%")
        logging.info(f"   Avg Loser: {analysis['avg_loser']:.3f}%")
        logging.info(f"   Risk/Reward: {analysis['edge_ratio']:.2f}")

    # Final recommendations
    logging.info("\n=== FINAL RECOMMENDATIONS ===")

    # Check if any approach is profitable
    profitable_approaches = [a for a in analyses if a["avg_return"] > 0]

    if profitable_approaches:
        best_profitable = max(profitable_approaches, key=lambda x: x["sharpe"])
        logging.info(f"✅ PROFITABLE STRATEGY FOUND: {best_profitable['name']}")
        logging.info(f"   Expected Value: +{best_profitable['avg_return']:.3f}%")
        logging.info(f"   Sharpe Ratio: {best_profitable['sharpe']:.3f}")
        logging.info(f"   Recommended for model training")
    else:
        logging.info("❌ NO PROFITABLE STRATEGIES FOUND")
        logging.info("   All approaches show negative expected value")
        logging.info("   Recommendations:")
        logging.info("   1. Tighten entry filters further")
        logging.info("   2. Add market regime detection")
        logging.info("   3. Consider different time horizons")
        logging.info("   4. Implement dynamic position sizing")

    # Implementation guidance
    if best_approach["sharpe"] > -0.1:  # Close to breakeven
        logging.info(f"\n🔧 OPTIMIZATION POTENTIAL:")
        logging.info(
            f"   Best approach ({best_approach['name']}) is close to profitability"
        )
        logging.info(f"   Small improvements could turn it positive:")
        logging.info(f"   - Reduce transaction costs")
        logging.info(f"   - Improve entry timing")
        logging.info(f"   - Add market filters")

    # Data quality assessment
    total_events = sum(a["total_events"] for a in analyses)
    logging.info(f"\n📊 DATA QUALITY:")
    logging.info(f"   Total events across all approaches: {total_events:,}")
    logging.info(
        f"   Largest dataset: {max(a['total_events'] for a in analyses):,} events"
    )
    logging.info(
        f"   Sufficient for ML training: {'✅' if max(a['total_events'] for a in analyses) > 1000 else '❌'}"
    )

    return True


if __name__ == "__main__":
    success = compare_all_approaches()
    exit(0 if success else 1)
