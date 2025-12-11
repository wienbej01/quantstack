#!/usr/bin/env python3
"""Rolling train and backtest with SIMPLE 5-bar hold (no stops/targets).

Key difference from complex version:
- Entry on bar AFTER signal (no leakage)
- Hold for exactly 5 bars
- Exit at close of 5th bar
- No stop loss or take profit monitoring
"""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/rolling_simple_hold.log"),
        logging.StreamHandler(),
    ],
)


def train_models(train_df, val_df, feature_cols):
    """Train LONG and SHORT models."""
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]

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

    # LONG model
    y_train_long = train_df["label_long"]
    y_val_long = val_df["label_long"]

    train_data = lgb.Dataset(X_train, label=y_train_long)
    val_data = lgb.Dataset(X_val, label=y_val_long, reference=train_data)

    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    auc_long = roc_auc_score(y_val_long, model_long.predict(X_val))

    # SHORT model
    y_train_short = train_df["label_short"]
    y_val_short = val_df["label_short"]

    train_data = lgb.Dataset(X_train, label=y_train_short)
    val_data = lgb.Dataset(X_val, label=y_val_short, reference=train_data)

    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    auc_short = roc_auc_score(y_val_short, model_short.predict(X_val))

    return model_long, model_short, auc_long, auc_short


def backtest_simple_hold(
    model_long,
    model_short,
    test_df,
    feature_cols,
    threshold=0.50,
    equity=10_000.0,
    position_pct=0.10,  # 10% of equity per trade
    hold_bars=5,
):
    """Simple backtest: entry on bar after signal, hold for N bars, exit at close."""
    X_test = test_df[feature_cols]

    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)

    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0].copy()
    signals = signals.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if len(signals) == 0:
        return None

    trades = []
    test_df_sorted = test_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    for idx, signal in signals.iterrows():
        signal_ts = signal["timestamp"]
        symbol = signal["symbol"]
        direction = signal["prediction"]

        # Get bars after signal for this symbol
        symbol_bars = test_df_sorted[
            (test_df_sorted["symbol"] == symbol)
            & (test_df_sorted["timestamp"] > signal_ts)
        ]

        if len(symbol_bars) < hold_bars + 1:
            continue

        # Entry on NEXT bar after signal (bar 0 = entry bar)
        entry_bar = symbol_bars.iloc[0]
        entry_price = entry_bar["close"]
        entry_ts = entry_bar["timestamp"]

        # Exit on bar N after entry (hold_bars bars later)
        exit_bar = symbol_bars.iloc[hold_bars]
        exit_price = exit_bar["close"]
        exit_ts = exit_bar["timestamp"]

        # Same-day check
        if entry_ts.date() != exit_ts.date():
            continue

        # Position sizing: fixed % of equity
        position_value = equity * position_pct
        shares = int(position_value / entry_price)

        if shares <= 0:
            continue

        # Calculate P&L
        if direction == 1:  # LONG
            gross_pnl = (exit_price - entry_price) * shares
        else:  # SHORT
            gross_pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2  # Entry + exit
        spread = shares * entry_price * 0.0005  # 5 bps
        net_pnl = gross_pnl - fee - spread

        # Update equity
        equity += net_pnl

        trades.append(
            {
                "signal_timestamp": signal_ts,
                "entry_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "symbol": symbol,
                "side": "LONG" if direction == 1 else "SHORT",
                "shares": shares,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "hold_bars": hold_bars,
                "gross_pnl": gross_pnl,
                "fee": fee,
                "spread": spread,
                "net_pnl": net_pnl,
            }
        )

    if not trades:
        return None

    return pd.DataFrame(trades)


def main():
    logging.info("=" * 80)
    logging.info("ROLLING TRAINING - SIMPLE 5-BAR HOLD (NO STOPS)")
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_rolling/features.parquet")
    output_dir = Path("run/rolling_results_simple")
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)

    # Feature columns
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
    logging.info(f"Features: {len(feature_cols)}")

    # Rolling schedule
    start_date = datetime(2023, 1, 1)
    end_date = datetime(2025, 10, 1)
    train_months = 6
    val_months = 1

    all_trades = []
    all_metrics = []

    current = datetime(2023, 8, 1)  # First OOS month
    iteration = 0

    while current < end_date:
        iteration += 1
        oos_start = current
        from dateutil.relativedelta import relativedelta

        oos_end = oos_start + relativedelta(months=1)

        # Calculate val and train periods
        val_start = oos_start - relativedelta(months=1)
        train_end = val_start
        train_start = train_end - relativedelta(months=train_months)

        logging.info("=" * 80)
        logging.info(f"ITERATION {iteration}: OOS {oos_start.strftime('%Y-%m')}")
        logging.info("=" * 80)

        # Filter data
        train_df = df.filter(
            (pl.col("date") >= train_start.date()) & (pl.col("date") < train_end.date())
        ).to_pandas()

        val_df = df.filter(
            (pl.col("date") >= val_start.date()) & (pl.col("date") < oos_start.date())
        ).to_pandas()

        test_df = df.filter(
            (pl.col("date") >= oos_start.date()) & (pl.col("date") < oos_end.date())
        ).to_pandas()

        logging.info(
            f"Train: {len(train_df):,} | Val: {len(val_df):,} | OOS: {len(test_df):,}"
        )

        if len(train_df) < 1000 or len(val_df) < 100 or len(test_df) < 100:
            logging.warning("Insufficient data, skipping")
            current = oos_end
            continue

        # Train
        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, feature_cols
        )
        logging.info(f"AUC - Long: {auc_long:.4f}, Short: {auc_short:.4f}")

        # Backtest with best Sharpe parameters
        trades_df = backtest_simple_hold(
            model_long,
            model_short,
            test_df,
            feature_cols,
            threshold=0.60,
            equity=10_000.0,
            position_pct=0.20,
            hold_bars=10,
        )

        if trades_df is not None and len(trades_df) > 0:
            trades_df["oos_month"] = oos_start.strftime("%Y-%m")
            all_trades.append(trades_df)

            win_rate = (trades_df["net_pnl"] > 0).mean()
            total_pnl = trades_df["net_pnl"].sum()
            n_trades = len(trades_df)

            logging.info(
                f"Trades: {n_trades}, Win: {win_rate:.1%}, PnL: ${total_pnl:,.0f}"
            )

            all_metrics.append(
                {
                    "oos_month": oos_start.strftime("%Y-%m"),
                    "n_trades": n_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "auc_long": auc_long,
                    "auc_short": auc_short,
                }
            )

        current = oos_end

    # Save results
    if all_trades:
        trades_combined = pd.concat(all_trades, ignore_index=True)
        trades_combined.to_csv(output_dir / "trades.csv", index=False)
        logging.info(f"Saved {len(trades_combined):,} trades")

        metrics_df = pd.DataFrame(all_metrics)
        metrics_df.to_csv(output_dir / "metrics.csv", index=False)

        # Summary
        logging.info("=" * 80)
        logging.info("FINAL RESULTS - SIMPLE 5-BAR HOLD")
        logging.info("=" * 80)
        logging.info(f"Total trades: {len(trades_combined):,}")
        logging.info(f"Win rate: {(trades_combined['net_pnl'] > 0).mean():.1%}")
        logging.info(f"Total PnL: ${trades_combined['net_pnl'].sum():,.0f}")
        logging.info(f"Avg PnL/trade: ${trades_combined['net_pnl'].mean():.2f}")

        by_side = trades_combined.groupby("side").agg(
            {"net_pnl": ["count", "sum", lambda x: (x > 0).mean()]}
        )
        logging.info(f"\nBy Side:\n{by_side}")


if __name__ == "__main__":
    main()
