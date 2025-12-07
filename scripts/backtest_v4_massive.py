#!/usr/bin/env python3
"""Backtest massive feature model on OOS data."""

import logging
import sys
from pathlib import Path

import lightgbm as lgb
import polars as pl

# Import feature engineering from training script
sys.path.insert(0, str(Path(__file__).parent))
from train_v4_6months_massive_features import engineer_massive_features

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def main():
    threshold = 0.30

    logging.info(f"Backtesting massive feature model (threshold={threshold:.2f})")

    # Load data
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    train_df = (
        pl.read_parquet(data_dir / "train.parquet")
        .rename({"ts": "timestamp"})
        .with_columns(pl.lit("train").alias("dataset"))
    )
    val_df = (
        pl.read_parquet(data_dir / "val.parquet")
        .rename({"ts": "timestamp"})
        .with_columns(pl.lit("val").alias("dataset"))
    )
    oos_df = (
        pl.read_parquet(data_dir / "oos.parquet")
        .rename({"ts": "timestamp"})
        .with_columns(pl.lit("oos").alias("dataset"))
    )

    df = pl.concat([train_df, val_df, oos_df])

    # Calculate forward returns for evaluation
    df = df.sort(["symbol", "timestamp"])
    df = df.with_columns(
        [
            (pl.col("close").shift(-10).over("symbol") / pl.col("close") - 1).alias(
                "forward_return"
            )
        ]
    )

    # Engineer features
    logging.info(f"Engineering features for {len(df):,} rows...")
    df = engineer_massive_features(df)
    df = df.drop_nulls()

    # Filter OOS only
    oos = df.filter(pl.col("dataset") == "oos")
    logging.info(f"OOS data: {len(oos):,} rows")

    # Load models
    models_dir = Path("models")
    model_long = lgb.Booster(model_file=str(models_dir / "v4_6months_massive_long.txt"))
    model_short = lgb.Booster(
        model_file=str(models_dir / "v4_6months_massive_short.txt")
    )

    # Get feature columns
    exclude_cols = {
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "label",
        "dataset",
        "forward_return",
        "hour",
        "minute",
    }
    feature_cols = [c for c in df.columns if c not in exclude_cols]

    X_oos = oos.select(feature_cols).to_pandas()

    # Predict
    logging.info("Predicting...")
    prob_long = model_long.predict(X_oos)
    prob_short = model_short.predict(X_oos)

    # Add predictions to dataframe
    oos = oos.with_columns(
        [
            pl.lit(prob_long).alias("prob_long"),
            pl.lit(prob_short).alias("prob_short"),
        ]
    )

    # Generate signals
    oos = oos.with_columns(
        [
            pl.when(pl.col("prob_long") >= threshold)
            .then(pl.lit("LONG"))
            .when(pl.col("prob_short") >= threshold)
            .then(pl.lit("SHORT"))
            .otherwise(pl.lit("NEUTRAL"))
            .alias("prediction")
        ]
    )

    # Filter tradeable signals
    signals = oos.filter(pl.col("prediction") != "NEUTRAL")

    logging.info(
        f"Signals: {len(signals)} (LONG: {len(signals.filter(pl.col('prediction') == 'LONG'))}, SHORT: {len(signals.filter(pl.col('prediction') == 'SHORT'))})"
    )

    # Calculate P&L
    signals = signals.with_columns(
        [
            pl.when(pl.col("prediction") == "LONG")
            .then(pl.col("forward_return") * 100)
            .when(pl.col("prediction") == "SHORT")
            .then(-pl.col("forward_return") * 100)
            .otherwise(0.0)
            .alias("pnl")
        ]
    )

    # Calculate metrics
    total_trades = len(signals)
    wins = len(signals.filter(pl.col("pnl") > 0))
    losses = len(signals.filter(pl.col("pnl") <= 0))
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl = signals["pnl"].mean()
    total_pnl = signals["pnl"].sum()
    sharpe = signals["pnl"].mean() / (signals["pnl"].std() + 1e-8) * (252**0.5)

    # Per-direction metrics
    long_signals = signals.filter(pl.col("prediction") == "LONG")
    short_signals = signals.filter(pl.col("prediction") == "SHORT")

    long_win_rate = (
        len(long_signals.filter(pl.col("pnl") > 0)) / len(long_signals) * 100
        if len(long_signals) > 0
        else 0
    )
    short_win_rate = (
        len(short_signals.filter(pl.col("pnl") > 0)) / len(short_signals) * 100
        if len(short_signals) > 0
        else 0
    )

    long_avg_pnl = long_signals["pnl"].mean() if len(long_signals) > 0 else 0
    short_avg_pnl = short_signals["pnl"].mean() if len(short_signals) > 0 else 0

    # Calculate signals per day
    unique_dates = oos.with_columns(pl.col("timestamp").dt.date().alias("date"))[
        "date"
    ].n_unique()
    signals_per_day = total_trades / unique_dates if unique_dates > 0 else 0

    # Print results
    print("=" * 80)
    print(f"Tradeable signals: {total_trades}")
    print(f"Win rate: {win_rate:.1f}% ({wins} wins, {losses} losses)")
    print(f"Avg P&L: {avg_pnl:.2f}%")
    print(f"Total P&L: {total_pnl:.2f}%")
    print(f"Sharpe: {sharpe:.2f}")
    print(f"Signals/day: {signals_per_day:.1f}")
    print(
        f"LONG: {len(long_signals)} trades, {long_win_rate:.1f}% win, {long_avg_pnl:.2f}% avg"
    )
    print(
        f"SHORT: {len(short_signals)} trades, {short_win_rate:.1f}% win, {short_avg_pnl:.2f}% avg"
    )
    print("Results saved")

    # Save results
    output_dir = Path("run")
    signals.write_parquet(output_dir / "backtest_v4_massive_results.parquet")


if __name__ == "__main__":
    main()
