#!/usr/bin/env python3
"""Matrix optimization: test combinations of hold_bars, threshold, position_pct."""

import logging
from datetime import datetime
from itertools import product
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Optimization grid
HOLD_BARS = [3, 5, 7, 10, 15]
THRESHOLDS = [0.40, 0.50, 0.60]
POSITION_PCTS = [0.05, 0.10, 0.15, 0.20]

# 6-month test period
TEST_START = datetime(2025, 4, 1)
TEST_END = datetime(2025, 10, 1)
TRAIN_END = datetime(2025, 3, 1)
TRAIN_START = datetime(2024, 9, 1)  # 6 months training


def train_models(train_df, val_df, feature_cols):
    X_train, X_val = train_df[feature_cols], val_df[feature_cols]
    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    }

    # LONG
    train_data = lgb.Dataset(X_train, label=train_df["label_long"])
    val_data = lgb.Dataset(X_val, label=val_df["label_long"], reference=train_data)
    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    # SHORT
    train_data = lgb.Dataset(X_train, label=train_df["label_short"])
    val_data = lgb.Dataset(X_val, label=val_df["label_short"], reference=train_data)
    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    return model_long, model_short


def backtest(
    model_long, model_short, test_df, feature_cols, threshold, position_pct, hold_bars
):
    X_test = test_df[feature_cols]
    test_df = test_df.copy()
    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)

    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return {"trades": 0, "pnl": 0, "win_rate": 0}

    test_df_sorted = test_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    equity = 10_000.0
    trades = []

    for _, signal in signals.iterrows():
        symbol_bars = test_df_sorted[
            (test_df_sorted["symbol"] == signal["symbol"])
            & (test_df_sorted["timestamp"] > signal["timestamp"])
        ]

        if len(symbol_bars) < hold_bars + 1:
            continue

        entry_bar = symbol_bars.iloc[0]
        exit_bar = symbol_bars.iloc[hold_bars]

        if entry_bar["timestamp"].date() != exit_bar["timestamp"].date():
            continue

        entry_price = entry_bar["close"]
        exit_price = exit_bar["close"]
        shares = int(equity * position_pct / entry_price)

        if shares <= 0:
            continue

        direction = signal["prediction"]
        gross_pnl = (exit_price - entry_price) * shares * direction
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread

        equity += net_pnl
        trades.append(net_pnl)

    if not trades:
        return {"trades": 0, "pnl": 0, "win_rate": 0}

    return {
        "trades": len(trades),
        "pnl": sum(trades),
        "win_rate": sum(1 for t in trades if t > 0) / len(trades),
    }


def main():
    logging.info("=" * 70)
    logging.info("MATRIX OPTIMIZATION - 6 MONTH TEST PERIOD")
    logging.info("=" * 70)

    features_path = Path("run/intraday_features_rolling/features.parquet")
    df = pl.read_parquet(features_path)

    exclude_cols = [
        "timestamp",
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "entry_close",
        "entry_timestamp",
        "exit_close",
        "exit_timestamp",
        "forward_return",
        "label_long",
        "label_short",
        "atr",
        "tr",
        "prev_close",
        "candle_top",
        "candle_bottom",
        "prev_high",
        "prev_low",
        "next_low",
        "next_high",
        "prev_bearish",
        "prev_bullish",
        "prev_high_5",
        "prev_low_5",
        "up_volume",
        "down_volume",
        "typical_price",
        "vwap_num",
        "vwap_den",
    ]
    feature_cols = [c for c in df.columns if c not in exclude_cols]

    # Split data
    train_df = df.filter(
        (pl.col("date") >= TRAIN_START.date()) & (pl.col("date") < TRAIN_END.date())
    ).to_pandas()

    val_df = df.filter(
        (pl.col("date") >= TRAIN_END.date()) & (pl.col("date") < TEST_START.date())
    ).to_pandas()

    test_df = df.filter(
        (pl.col("date") >= TEST_START.date()) & (pl.col("date") < TEST_END.date())
    ).to_pandas()

    logging.info(
        f"Train: {len(train_df):,} | Val: {len(val_df):,} | Test: {len(test_df):,}"
    )
    logging.info(f"Test period: {TEST_START.date()} to {TEST_END.date()}")

    # Train models once
    logging.info("Training models...")
    model_long, model_short = train_models(train_df, val_df, feature_cols)

    # Run optimization grid
    results = []
    total = len(HOLD_BARS) * len(THRESHOLDS) * len(POSITION_PCTS)

    logging.info(f"Testing {total} combinations...")

    for i, (hold, thresh, pos) in enumerate(
        product(HOLD_BARS, THRESHOLDS, POSITION_PCTS), 1
    ):
        metrics = backtest(
            model_long, model_short, test_df, feature_cols, thresh, pos, hold
        )
        results.append(
            {"hold_bars": hold, "threshold": thresh, "position_pct": pos, **metrics}
        )
        if i % 10 == 0:
            logging.info(f"  {i}/{total} complete")

    # Save and display results
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("pnl", ascending=False)
    results_df.to_csv("run/matrix_optimization_results.csv", index=False)

    logging.info("\n" + "=" * 70)
    logging.info("TOP 10 CONFIGURATIONS")
    logging.info("=" * 70)
    print(results_df.head(10).to_string(index=False))

    logging.info("\n" + "=" * 70)
    logging.info("BOTTOM 5 CONFIGURATIONS")
    logging.info("=" * 70)
    print(results_df.tail(5).to_string(index=False))

    # Best by metric
    logging.info("\n" + "=" * 70)
    logging.info("BEST BY METRIC")
    logging.info("=" * 70)
    best_pnl = results_df.iloc[0]
    best_wr = results_df.loc[results_df["win_rate"].idxmax()]
    best_trades = results_df.loc[results_df["trades"].idxmax()]

    print(
        f"Best PnL:      hold={best_pnl['hold_bars']}, thresh={best_pnl['threshold']}, pos={best_pnl['position_pct']} → ${best_pnl['pnl']:,.0f}"
    )
    print(
        f"Best Win Rate: hold={best_wr['hold_bars']}, thresh={best_wr['threshold']}, pos={best_wr['position_pct']} → {best_wr['win_rate']:.1%}"
    )
    print(
        f"Most Trades:   hold={best_trades['hold_bars']}, thresh={best_trades['threshold']}, pos={best_trades['position_pct']} → {best_trades['trades']}"
    )


if __name__ == "__main__":
    main()
