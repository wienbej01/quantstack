#!/usr/bin/env python3
"""Calculate Sharpe ratio for all matrix configurations."""

import logging
from datetime import datetime
from itertools import product

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

HOLD_BARS = [3, 5, 7, 10, 15]
THRESHOLDS = [0.40, 0.50, 0.60]
POSITION_PCTS = [0.05, 0.10, 0.15, 0.20]

TEST_START = datetime(2025, 4, 1)
TEST_END = datetime(2025, 10, 1)
TRAIN_END = datetime(2025, 3, 1)
TRAIN_START = datetime(2024, 9, 1)


def train_models(train_df, val_df, feature_cols):
    X_train, X_val = train_df[feature_cols], val_df[feature_cols]
    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "verbose": -1,
    }

    train_data = lgb.Dataset(X_train, label=train_df["label_long"])
    val_data = lgb.Dataset(X_val, label=val_df["label_long"], reference=train_data)
    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

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


def backtest_with_trades(
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
        return []

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

        entry_bar, exit_bar = symbol_bars.iloc[0], symbol_bars.iloc[hold_bars]
        if entry_bar["timestamp"].date() != exit_bar["timestamp"].date():
            continue

        entry_price, exit_price = entry_bar["close"], exit_bar["close"]
        shares = int(equity * position_pct / entry_price)
        if shares <= 0:
            continue

        direction = signal["prediction"]
        gross_pnl = (exit_price - entry_price) * shares * direction
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread

        equity += net_pnl
        trades.append({"date": entry_bar["timestamp"].date(), "pnl": net_pnl})

    return trades


def calc_sharpe(trades):
    if not trades:
        return 0, 0, 0
    df = pd.DataFrame(trades)
    daily = df.groupby("date")["pnl"].sum()
    if len(daily) < 2 or daily.std() == 0:
        return 0, daily.sum(), len(trades)
    sharpe = (daily.mean() / daily.std()) * np.sqrt(252)
    return sharpe, daily.sum(), len(trades)


def main():
    logging.info("Loading data...")
    df = pl.read_parquet("run/intraday_features_rolling/features.parquet")

    exclude = [
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
    feature_cols = [c for c in df.columns if c not in exclude]

    train_df = df.filter(
        (pl.col("date") >= TRAIN_START.date()) & (pl.col("date") < TRAIN_END.date())
    ).to_pandas()
    val_df = df.filter(
        (pl.col("date") >= TRAIN_END.date()) & (pl.col("date") < TEST_START.date())
    ).to_pandas()
    test_df = df.filter(
        (pl.col("date") >= TEST_START.date()) & (pl.col("date") < TEST_END.date())
    ).to_pandas()

    logging.info("Training models...")
    model_long, model_short = train_models(train_df, val_df, feature_cols)

    results = []
    total = len(HOLD_BARS) * len(THRESHOLDS) * len(POSITION_PCTS)

    for i, (hold, thresh, pos) in enumerate(
        product(HOLD_BARS, THRESHOLDS, POSITION_PCTS), 1
    ):
        logging.info(f"[{i}/{total}] hold={hold}, thresh={thresh}, pos={pos}")
        trades = backtest_with_trades(
            model_long, model_short, test_df, feature_cols, thresh, pos, hold
        )
        sharpe, pnl, n_trades = calc_sharpe(trades)
        results.append(
            {
                "hold_bars": hold,
                "threshold": thresh,
                "position_pct": pos,
                "trades": n_trades,
                "pnl": pnl,
                "sharpe": sharpe,
            }
        )

    results_df = pd.DataFrame(results).sort_values("sharpe", ascending=False)
    results_df.to_csv("run/matrix_sharpe_results.csv", index=False)

    print("\nTOP 10 BY SHARPE:")
    print(results_df.head(10).to_string(index=False))
    print("\nBEST CONFIG:")
    best = results_df.iloc[0]
    print(
        f"  hold={int(best['hold_bars'])}, thresh={best['threshold']}, pos={best['position_pct']}"
    )
    print(
        f"  Sharpe: {best['sharpe']:.2f}, PnL: ${best['pnl']:,.0f}, Trades: {int(best['trades'])}"
    )


if __name__ == "__main__":
    main()
