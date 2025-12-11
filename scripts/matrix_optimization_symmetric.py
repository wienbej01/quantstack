#!/usr/bin/env python3
"""Matrix optimization with SYMMETRIC model - single model predicts direction."""

import logging
from datetime import datetime
from itertools import product
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Optimization grid - thresholds are predicted return values now
HOLD_BARS = [5, 10, 15]
THRESHOLDS = [0.005, 0.010, 0.015]  # 0.5%, 1%, 1.5% predicted return
POSITION_PCTS = [0.10, 0.20]

# 6-month test period
TEST_START = datetime(2025, 4, 1)
TEST_END = datetime(2025, 10, 1)
TRAIN_END = datetime(2025, 3, 1)
TRAIN_START = datetime(2024, 9, 1)


def train_symmetric_model(train_df, val_df, feature_cols):
    """Train SINGLE symmetric model: regression on forward_return."""
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]
    y_train = train_df["forward_return"]
    y_val = val_df["forward_return"]

    params = {
        "objective": "regression",
        "metric": "rmse",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
    }

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    model = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    # Correlation as metric
    preds = model.predict(X_val)
    corr = pd.Series(preds).corr(pd.Series(y_val.values))
    return model, corr


def backtest_symmetric(
    model, test_df, feature_cols, threshold, position_pct, hold_bars
):
    """Backtest: predicted return > threshold = LONG, < -threshold = SHORT."""
    logging.info(
        f"    Backtest: hold={hold_bars}, thresh={threshold}, pos={position_pct}"
    )

    X_test = test_df[feature_cols]
    test_df = test_df.copy()

    # Predict forward return
    test_df["pred_return"] = model.predict(X_test)

    # Signals based on predicted return magnitude
    test_df["prediction"] = 0
    test_df.loc[test_df["pred_return"] >= threshold, "prediction"] = 1  # LONG
    test_df.loc[test_df["pred_return"] <= -threshold, "prediction"] = -1  # SHORT

    signals = test_df[test_df["prediction"] != 0].copy()
    logging.info(f"    Signals: {len(signals):,}")

    if len(signals) == 0:
        return {"trades": 0, "pnl": 0, "win_rate": 0, "long_pnl": 0, "short_pnl": 0}

    # Limit signals for speed
    if len(signals) > 5000:
        signals = signals.sample(5000, random_state=42)
        logging.info(f"    Sampled to 5000 signals")

    test_df_sorted = test_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)
    equity = 10_000.0
    trades = []

    for idx, (_, signal) in enumerate(signals.iterrows()):
        if idx % 1000 == 0 and idx > 0:
            logging.info(f"    Processing signal {idx}/{len(signals)}...")

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
        trades.append({"pnl": net_pnl, "side": "LONG" if direction == 1 else "SHORT"})

    if not trades:
        return {"trades": 0, "pnl": 0, "win_rate": 0, "long_pnl": 0, "short_pnl": 0}

    trades_df = pd.DataFrame(trades)
    long_pnl = (
        trades_df[trades_df["side"] == "LONG"]["pnl"].sum()
        if len(trades_df[trades_df["side"] == "LONG"]) > 0
        else 0
    )
    short_pnl = (
        trades_df[trades_df["side"] == "SHORT"]["pnl"].sum()
        if len(trades_df[trades_df["side"] == "SHORT"]) > 0
        else 0
    )

    return {
        "trades": len(trades),
        "pnl": sum(t["pnl"] for t in trades),
        "win_rate": sum(1 for t in trades if t["pnl"] > 0) / len(trades),
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
    }


def main():
    logging.info("=" * 70)
    logging.info("SYMMETRIC MODEL - MATRIX OPTIMIZATION")
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

    # Train single symmetric model
    logging.info("Training SYMMETRIC regression model...")
    model, corr = train_symmetric_model(train_df, val_df, feature_cols)
    logging.info(f"Symmetric model correlation: {corr:.4f}")

    # Run optimization grid
    results = []
    total = len(HOLD_BARS) * len(THRESHOLDS) * len(POSITION_PCTS)

    logging.info(f"Testing {total} combinations...")

    for i, (hold, thresh, pos) in enumerate(
        product(HOLD_BARS, THRESHOLDS, POSITION_PCTS), 1
    ):
        logging.info(f"[{i}/{total}] Testing hold={hold}, thresh={thresh}, pos={pos}")
        metrics = backtest_symmetric(model, test_df, feature_cols, thresh, pos, hold)
        logging.info(
            f"[{i}/{total}] Result: {metrics['trades']} trades, ${metrics['pnl']:,.0f} PnL"
        )
        results.append(
            {"hold_bars": hold, "threshold": thresh, "position_pct": pos, **metrics}
        )

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("pnl", ascending=False)
    results_df.to_csv("run/matrix_symmetric_results.csv", index=False)

    logging.info("\n" + "=" * 70)
    logging.info("SYMMETRIC MODEL - TOP CONFIGURATIONS")
    logging.info("=" * 70)
    print(results_df.to_string(index=False))

    logging.info("\n" + "=" * 70)
    logging.info("COMPARISON: SYMMETRIC vs SEPARATE MODELS")
    logging.info("=" * 70)

    # Load separate model results for comparison
    try:
        separate = pd.read_csv("run/matrix_optimization_results.csv")
        best_separate = separate.iloc[0]
        best_symmetric = results_df.iloc[0]

        print(
            f"\nSEPARATE MODELS (best): ${best_separate['pnl']:,.0f} | {best_separate['win_rate']*100:.1f}% win"
        )
        print(
            f"SYMMETRIC MODEL (best): ${best_symmetric['pnl']:,.0f} | {best_symmetric['win_rate']*100:.1f}% win"
        )
        print(f"  LONG PnL:  ${best_symmetric['long_pnl']:,.0f}")
        print(f"  SHORT PnL: ${best_symmetric['short_pnl']:,.0f}")
    except:
        pass


if __name__ == "__main__":
    main()
