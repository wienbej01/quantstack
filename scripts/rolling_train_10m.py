#!/usr/bin/env python3
"""Rolling training and backtest for 10m features."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import logging

import polars as pl

# Import the existing rolling training logic
from scripts.rolling_train_and_backtest import (
    FEATURE_COLS,
    backtest_oos,
    get_date_ranges,
    train_models,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("ROLLING TRAINING: 10M FEATURES")
    logging.info("=" * 80)

    # Load 10m features
    features_file = Path("run/intraday_features_10m/features.parquet")
    if not features_file.exists():
        logging.error(f"Features not found: {features_file}")
        return

    df = pl.read_parquet(features_file)
    logging.info(f"Loaded {len(df):,} feature rows")

    # Convert to pandas for sklearn/lightgbm
    df_pd = df.to_pandas()
    df_pd["date"] = df_pd["timestamp"].dt.date

    # Rolling training
    date_ranges = get_date_ranges()
    output_dir = Path("run/rolling_results_10m")
    output_dir.mkdir(parents=True, exist_ok=True)
    models_dir = output_dir / "models"
    models_dir.mkdir(exist_ok=True)

    all_trades = []
    all_metrics = []

    for i, r in enumerate(date_ranges, 1):
        logging.info("=" * 80)
        logging.info(f"ITERATION {i}/{len(date_ranges)}: OOS {r['oos_month']}")
        logging.info("=" * 80)
        logging.info(f"Train: {r['train_start']} to {r['train_end']}")
        logging.info(f"Val: {r['val_start']} to {r['val_end']}")
        logging.info(f"OOS: {r['oos_start']} to {r['oos_end']}")

        # Split data
        train_df = df_pd[
            (df_pd["date"] >= r["train_start"]) & (df_pd["date"] < r["train_end"])
        ]
        val_df = df_pd[
            (df_pd["date"] >= r["val_start"]) & (df_pd["date"] < r["val_end"])
        ]
        oos_df = df_pd[
            (df_pd["date"] >= r["oos_start"]) & (df_pd["date"] < r["oos_end"])
        ]

        logging.info(f"Train: {len(train_df):,} bars")
        logging.info(f"Val: {len(val_df):,} bars")
        logging.info(f"OOS: {len(oos_df):,} bars")

        if len(train_df) == 0 or len(val_df) == 0 or len(oos_df) == 0:
            logging.warning("Insufficient data, skipping")
            continue

        # Train models
        logging.info("Training models...")
        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, FEATURE_COLS
        )
        logging.info(f"LONG AUC: {auc_long:.4f}, SHORT AUC: {auc_short:.4f}")

        # Save models
        model_long.save_model(str(models_dir / f"{r['oos_month']}_long.txt"))
        model_short.save_model(str(models_dir / f"{r['oos_month']}_short.txt"))

        # Backtest
        logging.info("Backtesting...")
        trades, metrics = backtest_oos(
            oos_df, model_long, model_short, FEATURE_COLS, r["oos_month"]
        )

        logging.info(f"Signals: {metrics['signals']}")
        logging.info(f"Win Rate: {metrics['win_rate']:.2%}")
        logging.info(f"Total P&L: {metrics['total_pnl']:.2%}")
        logging.info(f"Exit reasons: {metrics['exit_reasons']}")
        logging.info("")

        all_trades.extend(trades)
        all_metrics.append(metrics)

    # Save results
    import pandas as pd

    trades_df = pd.DataFrame(all_trades)
    trades_df.to_csv(output_dir / "trades.csv", index=False)

    metrics_df = pd.DataFrame(all_metrics)
    metrics_df.to_csv(output_dir / "metrics.csv", index=False)

    logging.info("=" * 80)
    logging.info("ROLLING BACKTEST COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Results saved to: {output_dir}")
    logging.info(f"Final equity: ${metrics_df['final_equity'].iloc[-1]:,.2f}")
    logging.info("")
    logging.info("SUMMARY:")
    logging.info(f"Total iterations: {len(metrics_df)}")
    logging.info(f"Avg win rate: {metrics_df['win_rate'].mean():.2%}")
    logging.info(f"Total P&L: {(metrics_df['final_equity'].iloc[-1] / 10000 - 1):.2%}")
    logging.info(f"Total signals: {metrics_df['signals'].sum()}")


if __name__ == "__main__":
    main()
