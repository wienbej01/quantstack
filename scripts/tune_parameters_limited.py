#!/usr/bin/env python3
"""Parameter tuning on limited period to avoid overfitting."""

import logging
from itertools import product

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Limited period for tuning (last 2 months)
TUNE_START = "2025-07-01"
TUNE_END = "2025-09-30"


def tune_parameters():
    """Tune parameters on limited recent period."""

    logging.info("PARAMETER TUNING - LIMITED PERIOD")
    logging.info(f"Period: {TUNE_START} to {TUNE_END}")

    # Load improved features
    df = pl.read_parquet("run/intraday_features_improved/features.parquet")

    # Filter to tuning period
    df = df.filter(
        (pl.col("date") >= pl.lit(TUNE_START).str.strptime(pl.Date))
        & (pl.col("date") <= pl.lit(TUNE_END).str.strptime(pl.Date))
    )

    logging.info(f"Tuning data: {len(df):,} rows")

    if len(df) < 10000:
        logging.error("Insufficient data for tuning")
        return

    pdf = df.to_pandas()

    # Split chronologically
    split_idx = int(len(pdf) * 0.7)
    train_df = pdf.iloc[:split_idx]
    test_df = pdf.iloc[split_idx:]

    # Feature columns
    exclude_cols = [
        "timestamp",
        "date",
        "symbol",
        "session_id",
        "bar_index",
        "entry_timestamp",
        "exit_timestamp",
        "entry_close",
        "exit_close",
        "forward_return",
        "label_long",
        "label_short",
        "label_long_atr",
        "label_short_atr",
        "atr_threshold",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "atr",
        "tr",
        "prev_close",
        "vwap_session",
        "first_open",
        "prev_session_close",
        "cum_dollar_vol",
        "cum_volume",
    ]
    feature_cols = [c for c in pdf.columns if c not in exclude_cols]

    # Parameter grid
    thresholds = [0.30, 0.35, 0.40, 0.45]
    atr_multipliers = [1.0, 1.2, 1.5]
    hour_filters = [
        [9, 10, 11],  # Morning only
        [9, 10, 11, 12],  # Morning + lunch
        [13, 14, 15],  # Afternoon only
        [9, 10, 11, 12, 13, 14, 15],  # All hours
    ]

    results = []

    for thresh, atr_mult, hours in product(thresholds, atr_multipliers, hour_filters):
        try:
            result = test_config(
                train_df, test_df, feature_cols, thresh, atr_mult, hours
            )
            if result:
                results.append(result)
                logging.info(
                    f"Config: thresh={thresh}, atr={atr_mult}, hours={len(hours)} → "
                    f"{result['trades']} trades, {result['win_rate']:.1f}% win, ${result['pnl']:,.0f}"
                )
        except Exception as e:
            logging.warning(f"Error testing config: {e}")

    if not results:
        logging.error("No valid results")
        return

    # Save and analyze results
    results_df = pd.DataFrame(results)
    results_df.to_csv("run/parameter_tuning_results.csv", index=False)

    # Sort by different metrics
    logging.info("\n" + "=" * 80)
    logging.info("TOP CONFIGS BY WIN RATE")
    logging.info("=" * 80)
    top_win = results_df.nlargest(5, "win_rate")
    print(
        top_win[
            [
                "threshold",
                "atr_mult",
                "hour_count",
                "trades",
                "win_rate",
                "pnl",
                "symbols",
            ]
        ].to_string(index=False)
    )

    logging.info("\n" + "=" * 80)
    logging.info("TOP CONFIGS BY PNL")
    logging.info("=" * 80)
    top_pnl = results_df.nlargest(5, "pnl")
    print(
        top_pnl[
            [
                "threshold",
                "atr_mult",
                "hour_count",
                "trades",
                "win_rate",
                "pnl",
                "symbols",
            ]
        ].to_string(index=False)
    )

    # Best overall (balance of win rate and PnL)
    results_df["score"] = (
        results_df["win_rate"] * np.log(results_df["trades"].clip(lower=1))
        + results_df["pnl"] / 1000
    )
    best = results_df.loc[results_df["score"].idxmax()]

    logging.info("\n" + "=" * 80)
    logging.info("RECOMMENDED CONFIG")
    logging.info("=" * 80)
    logging.info(f"Threshold: {best['threshold']}")
    logging.info(f"ATR multiplier: {best['atr_mult']}")
    logging.info(f"Hours: {best['hours']}")
    logging.info(
        f"Performance: {best['trades']} trades, {best['win_rate']:.1f}% win, ${best['pnl']:,.0f}"
    )


def test_config(train_df, test_df, feature_cols, threshold, atr_mult, hours):
    """Test single parameter configuration."""

    # Retrain labels with new ATR multiplier
    train_df = train_df.copy()
    test_df = test_df.copy()

    # Recalculate ATR labels
    train_df["atr_threshold_new"] = train_df["atr"] / train_df["close"] * atr_mult
    train_df["label_long_new"] = (
        train_df["forward_return"] > train_df["atr_threshold_new"]
    ).astype(int)
    train_df["label_short_new"] = (
        train_df["forward_return"] < -train_df["atr_threshold_new"]
    ).astype(int)

    test_df["atr_threshold_new"] = test_df["atr"] / test_df["close"] * atr_mult
    test_df["label_long_new"] = (
        test_df["forward_return"] > test_df["atr_threshold_new"]
    ).astype(int)
    test_df["label_short_new"] = (
        test_df["forward_return"] < -test_df["atr_threshold_new"]
    ).astype(int)

    # Train models
    X_train, X_test = train_df[feature_cols], test_df[feature_cols]

    params = {
        "objective": "binary",
        "metric": "auc",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "verbose": -1,
    }

    # LONG model
    if train_df["label_long_new"].sum() < 50:
        return None

    model_long = lgb.train(
        params, lgb.Dataset(X_train, train_df["label_long_new"]), 100
    )
    pred_long = model_long.predict(X_test)

    # SHORT model
    if train_df["label_short_new"].sum() < 50:
        model_short = None
        pred_short = np.zeros(len(X_test))
    else:
        model_short = lgb.train(
            params, lgb.Dataset(X_train, train_df["label_short_new"]), 100
        )
        pred_short = model_short.predict(X_test)

    # Generate signals
    test_df["prob_long"] = pred_long
    test_df["prob_short"] = pred_short
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1

    # Hour filtering
    test_df["hour"] = pd.to_datetime(test_df["timestamp"]).dt.hour
    test_df = test_df[test_df["hour"].isin(hours)]

    signals = test_df[test_df["prediction"] != 0]

    if len(signals) < 10:
        return None

    # Simple backtest
    trades = []
    for _, signal in signals.iterrows():
        direction = signal["prediction"]
        entry_price = signal.get("entry_close", signal["close"])
        exit_price = signal.get("exit_close", signal["close"])

        if pd.isna(entry_price) or pd.isna(exit_price):
            continue

        # Fixed $200 risk
        atr_pct = signal.get("atr_pct", 0.02)
        if atr_pct <= 0 or pd.isna(atr_pct):
            atr_pct = 0.02

        shares = int(200 / (entry_price * atr_pct))

        if shares <= 0:
            continue

        # P&L
        if direction == 1:
            pnl = (exit_price - entry_price) * shares
        else:
            pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = pnl - fee - spread

        trades.append(
            {
                "symbol": signal["symbol"],
                "side": "LONG" if direction == 1 else "SHORT",
                "net_pnl": net_pnl,
                "hour": signal["hour"],
            }
        )

    if len(trades) < 5:
        return None

    trades_df = pd.DataFrame(trades)

    return {
        "threshold": threshold,
        "atr_mult": atr_mult,
        "hours": hours,
        "hour_count": len(hours),
        "trades": len(trades_df),
        "win_rate": (trades_df["net_pnl"] > 0).mean() * 100,
        "pnl": trades_df["net_pnl"].sum(),
        "symbols": trades_df["symbol"].nunique(),
        "long_trades": (trades_df["side"] == "LONG").sum(),
        "short_trades": (trades_df["side"] == "SHORT").sum(),
    }


if __name__ == "__main__":
    tune_parameters()
