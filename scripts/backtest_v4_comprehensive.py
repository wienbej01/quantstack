#!/usr/bin/env python3
"""Backtest comprehensive feature model on OOS data."""

import logging
import sys
import warnings
from pathlib import Path

import lightgbm as lgb
import pandas as pd

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None

sys.path.insert(0, str(Path(__file__).parent))
from train_v4_6months_comprehensive_features import engineer_comprehensive_features

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    threshold = 0.30

    logging.info(f"Backtesting comprehensive model (threshold={threshold:.2f})")

    # Load OOS data
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    oos_df = pd.read_parquet(data_dir / "oos.parquet")

    logging.info(f"Engineering features for {len(oos_df):,} rows...")
    oos_df = engineer_comprehensive_features(oos_df)
    oos_df = oos_df.dropna()

    logging.info(f"OOS data: {len(oos_df):,} rows")

    # Calculate forward returns
    oos_df = oos_df.sort_values(["symbol", "ts"])
    oos_df["forward_return"] = (
        oos_df.groupby("symbol")["close"].shift(-10) / oos_df["close"] - 1
    )

    # Load models
    models_dir = Path("models")
    model_long = lgb.Booster(
        model_file=str(models_dir / "v4_6months_comprehensive_long.txt")
    )
    model_short = lgb.Booster(
        model_file=str(models_dir / "v4_6months_comprehensive_short.txt")
    )

    # Get feature columns
    exclude_cols = {
        "symbol",
        "ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "label",
        "hour",
        "minute",
        "tr",
        "forward_return",
    }
    feature_cols = [c for c in oos_df.columns if c not in exclude_cols]

    X_oos = oos_df[feature_cols]

    # Predict
    logging.info("Predicting...")
    prob_long = model_long.predict(X_oos)
    prob_short = model_short.predict(X_oos)

    oos_df["prob_long"] = prob_long
    oos_df["prob_short"] = prob_short

    # Generate signals
    oos_df["prediction"] = "NEUTRAL"
    oos_df.loc[oos_df["prob_long"] >= threshold, "prediction"] = "LONG"
    oos_df.loc[oos_df["prob_short"] >= threshold, "prediction"] = "SHORT"

    # Filter tradeable signals
    signals = oos_df[oos_df["prediction"] != "NEUTRAL"].copy()

    logging.info(
        f"Signals: {len(signals)} (LONG: {len(signals[signals['prediction'] == 'LONG'])}, SHORT: {len(signals[signals['prediction'] == 'SHORT'])})"
    )

    # Calculate P&L
    signals["pnl"] = 0.0
    signals.loc[signals["prediction"] == "LONG", "pnl"] = (
        signals.loc[signals["prediction"] == "LONG", "forward_return"] * 100
    )
    signals.loc[signals["prediction"] == "SHORT", "pnl"] = (
        -signals.loc[signals["prediction"] == "SHORT", "forward_return"] * 100
    )

    # Calculate metrics
    total_trades = len(signals)
    wins = len(signals[signals["pnl"] > 0])
    losses = len(signals[signals["pnl"] <= 0])
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl = signals["pnl"].mean()
    total_pnl = signals["pnl"].sum()
    sharpe = signals["pnl"].mean() / (signals["pnl"].std() + 1e-8) * (252**0.5)

    # Per-direction metrics
    long_signals = signals[signals["prediction"] == "LONG"]
    short_signals = signals[signals["prediction"] == "SHORT"]

    long_win_rate = (
        len(long_signals[long_signals["pnl"] > 0]) / len(long_signals) * 100
        if len(long_signals) > 0
        else 0
    )
    short_win_rate = (
        len(short_signals[short_signals["pnl"] > 0]) / len(short_signals) * 100
        if len(short_signals) > 0
        else 0
    )

    long_avg_pnl = long_signals["pnl"].mean() if len(long_signals) > 0 else 0
    short_avg_pnl = short_signals["pnl"].mean() if len(short_signals) > 0 else 0

    # Calculate signals per day
    unique_dates = oos_df["ts"].dt.date.nunique()
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
    print("=" * 80)

    # Save results
    output_dir = Path("run")
    signals.to_parquet(output_dir / "backtest_v4_comprehensive_results.parquet")
    logging.info("Results saved")


if __name__ == "__main__":
    main()
