#!/usr/bin/env python3
"""Compare triple-barrier vs fixed-time labeling approaches."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_results():
    """Load both labeling results."""

    # Triple-barrier results
    tb_path = Path("run/triple_barrier_labels/barrier_outcomes.parquet")
    ft_path = Path("run/fixed_time_labels/labels.parquet")

    if not tb_path.exists():
        logging.error("Triple-barrier results not found")
        return None, None

    if not ft_path.exists():
        logging.error("Fixed-time results not found")
        return None, None

    tb_df = pd.read_parquet(tb_path)
    ft_df = pd.read_parquet(ft_path)

    return tb_df, ft_df


def compare_approaches():
    """Compare the two labeling approaches."""

    tb_df, ft_df = load_results()
    if tb_df is None or ft_df is None:
        return False

    logging.info("=" * 80)
    logging.info("LABELING APPROACH COMPARISON")
    logging.info("=" * 80)

    # Basic statistics
    logging.info("=== DATASET COMPARISON ===")
    logging.info(f"Triple-Barrier events: {len(tb_df):,}")
    logging.info(f"Fixed-Time events: {len(ft_df):,}")
    logging.info(f"Data ratio (FT/TB): {len(ft_df)/len(tb_df):.1f}x")

    # Performance comparison
    logging.info("\n=== PERFORMANCE COMPARISON ===")

    # Triple-barrier metrics (using long side)
    tb_overall_ev = tb_df["net_return_long"].mean() * 100
    tb_win_rate = (tb_df["net_return_long"] > 0).mean() * 100
    tb_profitable_rate = (tb_df["net_return_long"] > 0.002).mean() * 100
    tb_return_std = tb_df["net_return_long"].std() * 100
    tb_sharpe = tb_overall_ev / tb_return_std if tb_return_std > 0 else 0

    # Fixed-time metrics
    ft_overall_ev = ft_df["net_return"].mean() * 100
    ft_win_rate = (ft_df["net_return"] > 0).mean() * 100
    ft_profitable_rate = ft_df["label_profitable"].mean() * 100
    ft_return_std = ft_df["net_return"].std() * 100
    ft_sharpe = ft_overall_ev / ft_return_std if ft_return_std > 0 else 0

    logging.info("TRIPLE-BARRIER:")
    logging.info(f"  Expected Value: {tb_overall_ev:.3f}%")
    logging.info(f"  Win Rate: {tb_win_rate:.1f}%")
    logging.info(f"  Profitable Rate (>0.2%): {tb_profitable_rate:.1f}%")
    logging.info(f"  Return Volatility: {tb_return_std:.3f}%")
    logging.info(f"  Sharpe Ratio: {tb_sharpe:.3f}")

    logging.info("\nFIXED-TIME (30min):")
    logging.info(f"  Expected Value: {ft_overall_ev:.3f}%")
    logging.info(f"  Win Rate: {ft_win_rate:.1f}%")
    logging.info(f"  Profitable Rate (>0.2%): {ft_profitable_rate:.1f}%")
    logging.info(f"  Return Volatility: {ft_return_std:.3f}%")
    logging.info(f"  Sharpe Ratio: {ft_sharpe:.3f}")

    # Label distribution comparison
    logging.info("\n=== LABEL DISTRIBUTION COMPARISON ===")

    # Triple-barrier label rates
    tb_pt_rate = (tb_df["outcome_long"] == "pt").mean() * 100
    tb_sl_rate = (tb_df["outcome_long"] == "sl").mean() * 100
    tb_time_rate = (tb_df["outcome_long"] == "time").mean() * 100

    logging.info("TRIPLE-BARRIER OUTCOMES:")
    logging.info(f"  Profit Target: {tb_pt_rate:.1f}%")
    logging.info(f"  Stop Loss: {tb_sl_rate:.1f}%")
    logging.info(f"  Time Exit: {tb_time_rate:.1f}%")

    logging.info("FIXED-TIME LABELS:")
    logging.info(f"  Profitable: {ft_profitable_rate:.1f}%")
    logging.info(f"  Unprofitable: {100-ft_profitable_rate:.1f}%")

    # Predictability analysis
    logging.info("\n=== PREDICTABILITY ANALYSIS ===")

    # Triple-barrier: edge when correct
    tb_pt_returns = tb_df[tb_df["outcome_long"] == "pt"]["net_return_long"]
    tb_sl_returns = tb_df[tb_df["outcome_long"] == "sl"]["net_return_long"]

    if len(tb_pt_returns) > 0 and len(tb_sl_returns) > 0:
        tb_edge_when_right = tb_pt_returns.mean() * 100
        tb_edge_when_wrong = tb_sl_returns.mean() * 100
        tb_edge_spread = tb_edge_when_right - tb_edge_when_wrong

        logging.info("TRIPLE-BARRIER EDGE:")
        logging.info(f"  When PT hit: {tb_edge_when_right:.3f}%")
        logging.info(f"  When SL hit: {tb_edge_when_wrong:.3f}%")
        logging.info(f"  Edge spread: {tb_edge_spread:.3f}%")

    # Fixed-time: edge when correct
    ft_profitable_returns = ft_df[ft_df["label_profitable"] == 1]["net_return"]
    ft_unprofitable_returns = ft_df[ft_df["label_profitable"] == 0]["net_return"]

    ft_edge_when_right = ft_profitable_returns.mean() * 100
    ft_edge_when_wrong = ft_unprofitable_returns.mean() * 100
    ft_edge_spread = ft_edge_when_right - ft_edge_when_wrong

    logging.info("\nFIXED-TIME EDGE:")
    logging.info(f"  When profitable: {ft_edge_when_right:.3f}%")
    logging.info(f"  When unprofitable: {ft_edge_when_wrong:.3f}%")
    logging.info(f"  Edge spread: {ft_edge_spread:.3f}%")

    # Time-of-day comparison
    logging.info("\n=== TIME-OF-DAY COMPARISON ===")

    # Triple-barrier by hour
    tb_df["hour"] = pd.to_datetime(tb_df["entry_time"]).dt.hour
    tb_hourly = tb_df.groupby("hour")["net_return_long"].mean() * 100

    # Fixed-time by hour
    ft_hourly = ft_df.groupby("hour_et")["net_return"].mean() * 100

    logging.info("HOURLY EXPECTED VALUES:")
    for hour in sorted(set(tb_hourly.index) | set(ft_hourly.index)):
        tb_ev = tb_hourly.get(hour, 0)
        ft_ev = ft_hourly.get(hour, 0)
        logging.info(f"  Hour {hour}: TB={tb_ev:.3f}%, FT={ft_ev:.3f}%")

    # Training suitability analysis
    logging.info("\n=== TRAINING SUITABILITY ANALYSIS ===")

    # Label balance
    tb_label_balance = (
        min(tb_profitable_rate, 100 - tb_profitable_rate) / 50
    )  # 0-1 scale
    ft_label_balance = min(ft_profitable_rate, 100 - ft_profitable_rate) / 50

    # Sample size
    tb_sample_score = min(len(tb_df) / 10000, 1.0)  # 0-1 scale, 10k+ is good
    ft_sample_score = min(len(ft_df) / 10000, 1.0)

    # Consistency (lower volatility is better for training)
    tb_consistency = max(0, 1 - tb_return_std / 2.0)  # 0-1 scale
    ft_consistency = max(0, 1 - ft_return_std / 2.0)

    # Overall training score
    tb_training_score = (tb_label_balance + tb_sample_score + tb_consistency) / 3
    ft_training_score = (ft_label_balance + ft_sample_score + ft_consistency) / 3

    logging.info("TRAINING SUITABILITY SCORES (0-1):")
    logging.info(f"  Triple-Barrier: {tb_training_score:.3f}")
    logging.info(f"    Label balance: {tb_label_balance:.3f}")
    logging.info(f"    Sample size: {tb_sample_score:.3f}")
    logging.info(f"    Consistency: {tb_consistency:.3f}")

    logging.info(f"  Fixed-Time: {ft_training_score:.3f}")
    logging.info(f"    Label balance: {ft_label_balance:.3f}")
    logging.info(f"    Sample size: {ft_sample_score:.3f}")
    logging.info(f"    Consistency: {ft_consistency:.3f}")

    # Final recommendation
    logging.info("\n=== FINAL RECOMMENDATION ===")

    if ft_training_score > tb_training_score:
        winner = "FIXED-TIME"
        winner_score = ft_training_score
        winner_ev = ft_overall_ev
    else:
        winner = "TRIPLE-BARRIER"
        winner_score = tb_training_score
        winner_ev = tb_overall_ev

    logging.info(f"RECOMMENDED APPROACH: {winner}")
    logging.info(f"  Training Score: {winner_score:.3f}")
    logging.info(f"  Expected Value: {winner_ev:.3f}%")

    # Specific advantages
    if winner == "FIXED-TIME":
        logging.info("  ADVANTAGES:")
        logging.info(f"    - More training samples: {len(ft_df):,} vs {len(tb_df):,}")
        logging.info(
            f"    - Better label balance: {ft_label_balance:.3f} vs {tb_label_balance:.3f}"
        )
        logging.info("    - Simpler execution logic")
        logging.info("    - More predictable exit timing")
    else:
        logging.info("  ADVANTAGES:")
        logging.info(
            f"    - Better edge spread: {tb_edge_spread:.3f}% vs {ft_edge_spread:.3f}%"
        )
        logging.info("    - Risk-managed exits")
        logging.info("    - Captures strong moves early")

    # Implementation guidance
    if winner_ev > 0:
        logging.info("\n✅ POSITIVE EDGE DETECTED - Proceed with model training")
    else:
        logging.info("\n⚠️ NEGATIVE EDGE - Need further optimization before training")
        logging.info("  Consider:")
        logging.info("    - Tighter entry filters")
        logging.info("    - Different time periods")
        logging.info("    - Market regime filtering")

    return True


if __name__ == "__main__":
    success = compare_approaches()
    exit(0 if success else 1)
