#!/usr/bin/env python3
"""Analyze triple-barrier labeling results."""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def analyze_barrier_outcomes():
    """Analyze the triple-barrier results."""

    # Load results
    events_path = Path("run/triple_barrier_labels/events.parquet")
    outcomes_path = Path("run/triple_barrier_labels/barrier_outcomes.parquet")

    if not events_path.exists() or not outcomes_path.exists():
        logging.error("Triple-barrier results not found")
        return False

    events_df = pd.read_parquet(events_path)
    outcomes_df = pd.read_parquet(outcomes_path)

    logging.info("=" * 80)
    logging.info("TRIPLE-BARRIER RESULTS ANALYSIS")
    logging.info("=" * 80)

    # Basic statistics
    logging.info(f"Total events created: {len(events_df):,}")
    logging.info(f"Total outcomes processed: {len(outcomes_df):,}")
    logging.info(f"Symbols covered: {events_df['symbol'].nunique()}")
    logging.info(f"Date range: {events_df['date'].min()} to {events_df['date'].max()}")

    # Event distribution by hour
    logging.info("\n=== EVENT DISTRIBUTION BY HOUR ===")
    hour_dist = events_df["hour_et"].value_counts().sort_index()
    for hour, count in hour_dist.items():
        pct = count / len(events_df) * 100
        logging.info(f"Hour {hour}: {count:,} events ({pct:.1f}%)")

    # Barrier outcome analysis
    logging.info("\n=== BARRIER OUTCOME ANALYSIS ===")

    for side in ["long", "short"]:
        logging.info(f"\n{side.upper()} SIDE:")

        # Outcome distribution
        outcome_dist = outcomes_df[f"outcome_{side}"].value_counts()
        total = len(outcomes_df)

        for outcome, count in outcome_dist.items():
            pct = count / total * 100
            logging.info(f"  {outcome}: {count:,} ({pct:.1f}%)")

        # Return statistics
        gross_returns = outcomes_df[f"return_{side}"]
        net_returns = outcomes_df[f"net_return_{side}"]

        logging.info(
            f"  Gross return: {gross_returns.mean()*100:.3f}% ± {gross_returns.std()*100:.3f}%"
        )
        logging.info(
            f"  Net return: {net_returns.mean()*100:.3f}% ± {net_returns.std()*100:.3f}%"
        )
        logging.info(f"  Win rate (net): {(net_returns > 0).mean()*100:.1f}%")
        logging.info(f"  Profitable (>0.2%): {(net_returns > 0.002).mean()*100:.1f}%")

        # Outcome-specific returns
        for outcome in ["pt", "sl", "time"]:
            mask = outcomes_df[f"outcome_{side}"] == outcome
            if mask.sum() > 0:
                avg_return = net_returns[mask].mean() * 100
                logging.info(f"  Avg net return ({outcome}): {avg_return:.3f}%")

    # Label distribution
    logging.info("\n=== LABEL DISTRIBUTION ===")

    for side in ["long", "short"]:
        # 3-class labels
        class_dist = outcomes_df[f"label_{side}_3class"].value_counts().sort_index()
        logging.info(f"\n{side.upper()} 3-class labels:")
        for label, count in class_dist.items():
            pct = count / len(outcomes_df) * 100
            label_name = {1: "PT", -1: "SL", 0: "Time"}[label]
            logging.info(f"  {label_name} ({label}): {count:,} ({pct:.1f}%)")

        # Meta labels
        meta_rate = outcomes_df[f"label_{side}_meta"].mean() * 100
        net_meta_rate = outcomes_df[f"label_{side}_net_meta"].mean() * 100
        logging.info(f"  Meta label rate: {meta_rate:.1f}%")
        logging.info(f"  Net meta label rate: {net_meta_rate:.1f}%")

    # Economic analysis
    logging.info("\n=== ECONOMIC ANALYSIS ===")

    # Expected values by label
    for side in ["long", "short"]:
        net_returns = outcomes_df[f"net_return_{side}"]
        meta_labels = outcomes_df[f"label_{side}_net_meta"]

        ev_positive = net_returns[meta_labels == 1].mean() * 100
        ev_negative = net_returns[meta_labels == 0].mean() * 100

        logging.info(f"\n{side.upper()} Expected Values:")
        logging.info(f"  EV when label=1: {ev_positive:.3f}%")
        logging.info(f"  EV when label=0: {ev_negative:.3f}%")
        logging.info(f"  Edge (difference): {ev_positive - ev_negative:.3f}%")

    # Volatility regime analysis
    logging.info("\n=== VOLATILITY REGIME ANALYSIS ===")

    # Create volatility quintiles
    outcomes_df["vol_quintile"] = pd.qcut(
        outcomes_df["vol_at_entry"], q=5, labels=False
    )

    for quintile in range(5):
        mask = outcomes_df["vol_quintile"] == quintile
        vol_data = outcomes_df[mask]

        if len(vol_data) > 0:
            avg_vol = vol_data["vol_at_entry"].mean() * 100
            long_ev = vol_data["net_return_long"].mean() * 100
            short_ev = vol_data["net_return_short"].mean() * 100

            logging.info(
                f"  Quintile {quintile+1} (vol={avg_vol:.2f}%): Long EV={long_ev:.3f}%, Short EV={short_ev:.3f}%"
            )

    # Time-of-day analysis
    logging.info("\n=== TIME-OF-DAY ANALYSIS ===")

    outcomes_df["hour"] = pd.to_datetime(outcomes_df["entry_time"]).dt.hour

    for hour in sorted(outcomes_df["hour"].unique()):
        mask = outcomes_df["hour"] == hour
        hour_data = outcomes_df[mask]

        if len(hour_data) > 0:
            long_ev = hour_data["net_return_long"].mean() * 100
            short_ev = hour_data["net_return_short"].mean() * 100
            count = len(hour_data)

            logging.info(
                f"  Hour {hour}: {count:,} events, Long EV={long_ev:.3f}%, Short EV={short_ev:.3f}%"
            )

    # Summary recommendations
    logging.info("\n=== SUMMARY & RECOMMENDATIONS ===")

    # Overall expected values
    overall_long_ev = outcomes_df["net_return_long"].mean() * 100
    overall_short_ev = outcomes_df["net_return_short"].mean() * 100

    logging.info(f"Overall Long EV: {overall_long_ev:.3f}%")
    logging.info(f"Overall Short EV: {overall_short_ev:.3f}%")

    # Best performing conditions
    best_long_hour = outcomes_df.groupby("hour")["net_return_long"].mean().idxmax()
    best_short_hour = outcomes_df.groupby("hour")["net_return_short"].mean().idxmax()

    logging.info(f"Best Long hour: {best_long_hour}")
    logging.info(f"Best Short hour: {best_short_hour}")

    # Profitability assessment
    if overall_long_ev > 0 or overall_short_ev > 0:
        logging.info("✅ POSITIVE EDGE DETECTED")
        if overall_long_ev > overall_short_ev:
            logging.info("   Long bias recommended")
        else:
            logging.info("   Short bias recommended")
    else:
        logging.info("❌ NO POSITIVE EDGE - FURTHER OPTIMIZATION NEEDED")

    return True


if __name__ == "__main__":
    success = analyze_barrier_outcomes()
    exit(0 if success else 1)
