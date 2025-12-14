#!/usr/bin/env python3
"""Improved training with relaxed parameters to generate trades."""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Relaxed parameters to generate more trades
THRESHOLD = 0.40  # Lower threshold
RISK_PER_TRADE = 200
MAX_TRADES_PER_SYMBOL_PER_DAY = 5  # More trades allowed
PROFITABLE_HOURS = [9, 10, 11, 12, 13, 14, 15]  # All trading hours


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

    # LONG model
    y_train_long, y_val_long = train_df["label_long_atr"], val_df["label_long_atr"]
    if y_train_long.sum() < 50:
        return None, None, 0, 0

    model_long = lgb.train(params, lgb.Dataset(X_train, y_train_long), 100)
    auc_long = roc_auc_score(y_val_long, model_long.predict(X_val))

    # SHORT model
    y_train_short, y_val_short = train_df["label_short_atr"], val_df["label_short_atr"]
    if y_train_short.sum() < 50:
        return model_long, None, auc_long, 0

    model_short = lgb.train(params, lgb.Dataset(X_train, y_train_short), 100)
    auc_short = roc_auc_score(y_val_short, model_short.predict(X_val))

    return model_long, model_short, auc_long, auc_short


def backtest_relaxed(model_long, model_short, test_df, feature_cols, equity=10_000.0):
    if model_long is None and model_short is None:
        return None, equity

    test_df = test_df.copy()

    # Generate predictions
    if model_long is not None:
        test_df["prob_long"] = model_long.predict(test_df[feature_cols])
    else:
        test_df["prob_long"] = 0

    if model_short is not None:
        test_df["prob_short"] = model_short.predict(test_df[feature_cols])
    else:
        test_df["prob_short"] = 0

    # Apply threshold
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= THRESHOLD, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= THRESHOLD, "prediction"] = -1

    # Time filtering - all trading hours
    test_df["hour"] = pd.to_datetime(test_df["timestamp"]).dt.hour
    test_df = test_df[test_df["hour"].isin(PROFITABLE_HOURS)]

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return None, equity

    # Simple diversification
    signals["date"] = pd.to_datetime(signals["timestamp"]).dt.date
    filtered_signals = []

    for date, day_signals in signals.groupby("date"):
        symbol_counts = {}
        for _, signal in day_signals.iterrows():
            symbol = signal["symbol"]
            if symbol_counts.get(symbol, 0) < MAX_TRADES_PER_SYMBOL_PER_DAY:
                filtered_signals.append(signal)
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

    if not filtered_signals:
        return None, equity

    signals = pd.DataFrame(filtered_signals)

    # Execute trades
    trades = []

    for _, signal in signals.iterrows():
        direction = signal["prediction"]

        # Use available price data
        entry_price = signal.get("entry_close", signal["close"])
        exit_price = signal.get("exit_close", signal["close"])

        if pd.isna(entry_price) or pd.isna(exit_price):
            continue

        # Fixed position sizing
        atr_pct = signal.get("atr_pct", 0.02)
        if atr_pct <= 0:
            atr_pct = 0.02

        shares = int(RISK_PER_TRADE / (entry_price * atr_pct))
        if shares <= 0:
            continue

        # Calculate P&L
        if direction == 1:  # LONG
            gross_pnl = (exit_price - entry_price) * shares
        else:  # SHORT
            gross_pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread

        equity += net_pnl

        trades.append(
            {
                "signal_timestamp": signal["timestamp"],
                "entry_timestamp": signal.get("entry_timestamp", signal["timestamp"]),
                "exit_timestamp": signal.get("exit_timestamp", signal["timestamp"]),
                "symbol": signal["symbol"],
                "side": "LONG" if direction == 1 else "SHORT",
                "shares": shares,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "gross_pnl": gross_pnl,
                "fee": fee,
                "spread": spread,
                "net_pnl": net_pnl,
                "hour": signal["hour"],
            }
        )

    return pd.DataFrame(trades) if trades else None, equity


def main():
    logging.info("RELAXED IMPROVED TRAINING - Generate More Trades")

    features_path = Path("run/intraday_features_improved/features.parquet")
    output_dir = Path("run/rolling_results_relaxed")
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pl.read_parquet(features_path)

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
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    logging.info(f"Features: {len(feature_cols)}")

    # Test on recent period only (faster)
    start_date = datetime(2025, 6, 1)
    end_date = datetime(2025, 10, 1)

    # Single test period
    train_start = datetime(2025, 1, 1)
    train_end = datetime(2025, 6, 1)
    test_start = datetime(2025, 6, 1)
    test_end = datetime(2025, 10, 1)

    logging.info(f"Train: {train_start} to {train_end}")
    logging.info(f"Test: {test_start} to {test_end}")

    train_df = df.filter(
        (pl.col("date") >= train_start.date()) & (pl.col("date") < train_end.date())
    ).to_pandas()
    test_df = df.filter(
        (pl.col("date") >= test_start.date()) & (pl.col("date") < test_end.date())
    ).to_pandas()

    logging.info(f"Data: Train {len(train_df):,} | Test {len(test_df):,}")

    if len(train_df) < 1000 or len(test_df) < 100:
        logging.error("Insufficient data")
        return

    # Use train data for both training and validation (simplified)
    val_df = train_df.sample(frac=0.3, random_state=42)

    # Train models
    model_long, model_short, auc_long, auc_short = train_models(
        train_df, val_df, feature_cols
    )
    logging.info(f"AUC - Long: {auc_long:.4f} | Short: {auc_short:.4f}")

    # Backtest
    trades_df, final_equity = backtest_relaxed(
        model_long, model_short, test_df, feature_cols
    )

    if trades_df is not None and len(trades_df) > 0:
        trades_df.to_csv(output_dir / "trades.csv", index=False)

        logging.info("=" * 60)
        logging.info("RELAXED IMPROVED RESULTS")
        logging.info("=" * 60)
        logging.info(f"Total trades: {len(trades_df)}")
        logging.info(f"Win rate: {(trades_df['net_pnl'] > 0).mean()*100:.1f}%")
        logging.info(f"Total PnL: ${trades_df['net_pnl'].sum():,.0f}")
        logging.info(f"Final equity: ${final_equity:,.0f}")

        # Diversification
        symbol_counts = trades_df["symbol"].value_counts()
        logging.info(f"Unique symbols: {len(symbol_counts)}")
        logging.info(f"Max trades per symbol: {symbol_counts.max()}")

        # Time distribution
        hour_pnl = trades_df.groupby("hour")["net_pnl"].agg(["count", "sum"])
        logging.info("\nBy hour:")
        for hour, row in hour_pnl.iterrows():
            logging.info(
                f"  {hour:2d}: {row['count']:3.0f} trades, ${row['sum']:>8,.0f} PnL"
            )

        # Direction
        for side in ["LONG", "SHORT"]:
            side_trades = trades_df[trades_df["side"] == side]
            if len(side_trades) > 0:
                logging.info(
                    f"{side}: {len(side_trades)} trades, ${side_trades['net_pnl'].sum():,.0f} PnL"
                )
    else:
        logging.info("No trades generated")


if __name__ == "__main__":
    main()
