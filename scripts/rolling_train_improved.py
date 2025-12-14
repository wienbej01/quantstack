#!/usr/bin/env python3
"""Improved rolling training with fixes for model inconsistency.

Key improvements:
1. Time-of-day filtering (morning only)
2. Diversification constraints
3. Longer validation period (2 months)
4. Regime-aware features
5. Fixed position sizing
"""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from dateutil.relativedelta import relativedelta
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Improved parameters
THRESHOLD = 0.60
RISK_PER_TRADE = 200  # Fixed $200 risk (not percentage)
MAX_TRADES_PER_SYMBOL_PER_DAY = 3  # Diversification
MIN_SYMBOLS_PER_DAY = 3  # Require diversity
MAX_SYMBOL_EXPOSURE = 0.15  # Max 15% per symbol

# Time filtering - only profitable hours
PROFITABLE_HOURS = [9, 10, 11]  # Morning only

# Training parameters
TRAIN_MONTHS = 6
VALIDATION_MONTHS = 2  # Longer validation
OOS_MONTHS = 1


def train_models(train_df, val_df, feature_cols):
    """Train LONG and SHORT models with improved validation."""

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
        "min_data_in_leaf": 50,  # Prevent overfitting
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
    }

    # LONG model
    y_train_long, y_val_long = train_df["label_long"], val_df["label_long"]
    if y_train_long.sum() < 50 or y_val_long.sum() < 10:
        return None, None, 0, 0

    train_data = lgb.Dataset(X_train, label=y_train_long)
    val_data = lgb.Dataset(X_val, label=y_val_long, reference=train_data)

    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=300,  # Reduced to prevent overfitting
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
    )
    auc_long = roc_auc_score(y_val_long, model_long.predict(X_val))

    # SHORT model
    y_train_short, y_val_short = train_df["label_short"], val_df["label_short"]
    if y_train_short.sum() < 50 or y_val_short.sum() < 10:
        return model_long, None, auc_long, 0

    train_data = lgb.Dataset(X_train, label=y_train_short)
    val_data = lgb.Dataset(X_val, label=y_val_short, reference=train_data)

    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=300,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
    )
    auc_short = roc_auc_score(y_val_short, model_short.predict(X_val))

    return model_long, model_short, auc_long, auc_short


def backtest_improved(model_long, model_short, test_df, feature_cols, equity=10_000.0):
    """Improved backtest with time filtering and diversification."""

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

    # TIME FILTERING - Only trade profitable hours
    test_df["hour"] = pd.to_datetime(test_df["timestamp"]).dt.hour
    test_df = test_df[test_df["hour"].isin(PROFITABLE_HOURS)]

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return None, equity

    # DIVERSIFICATION - Group by date and apply constraints
    signals["date"] = pd.to_datetime(signals["timestamp"]).dt.date

    filtered_signals = []
    for date, day_signals in signals.groupby("date"):
        # Limit trades per symbol per day
        symbol_counts = {}
        day_filtered = []

        for _, signal in day_signals.iterrows():
            symbol = signal["symbol"]
            if symbol_counts.get(symbol, 0) < MAX_TRADES_PER_SYMBOL_PER_DAY:
                day_filtered.append(signal)
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1

        # Check minimum symbol diversity
        if len(set(s["symbol"] for s in day_filtered)) >= MIN_SYMBOLS_PER_DAY:
            filtered_signals.extend(day_filtered)

    if not filtered_signals:
        return None, equity

    signals = pd.DataFrame(filtered_signals)

    # Execute trades with fixed position sizing
    trades = []
    symbol_exposure = {}  # Track exposure per symbol

    for _, signal in signals.iterrows():
        symbol = signal["symbol"]
        direction = signal["prediction"]

        # Check symbol exposure limit
        current_exposure = symbol_exposure.get(symbol, 0)
        if current_exposure >= MAX_SYMBOL_EXPOSURE * equity:
            continue

        # Fixed position sizing
        entry_price = signal["entry_close"]
        if pd.isna(entry_price) or entry_price <= 0:
            continue

        # Use ATR for position sizing (fixed risk)
        atr_pct = signal.get("atr_pct", 0.02)  # Default 2% if missing
        if atr_pct <= 0:
            atr_pct = 0.02

        shares = int(RISK_PER_TRADE / (entry_price * atr_pct))
        if shares <= 0:
            continue

        position_value = shares * entry_price

        # Update symbol exposure
        symbol_exposure[symbol] = symbol_exposure.get(symbol, 0) + position_value

        # Calculate P&L (simple 5-bar hold)
        exit_price = signal["exit_close"]
        if pd.isna(exit_price) or exit_price <= 0:
            continue

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
                "entry_timestamp": signal["entry_timestamp"],
                "exit_timestamp": signal["exit_timestamp"],
                "symbol": symbol,
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
    logging.info("=" * 80)
    logging.info("IMPROVED ROLLING TRAINING - Fixing Model Inconsistency")
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_improved/features.parquet")
    if not features_path.exists():
        logging.error(
            "Improved features not found. Run build_intraday_features_improved.py first"
        )
        return

    output_dir = Path("run/rolling_results_improved")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load features
    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)

    # Feature columns (exclude raw prices and metadata)
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
        "atr_threshold",
        # Remove any remaining raw price features
        "open",
        "high",
        "low",
        "close",
        "vwap_session",
        "prev_session_close",
        "first_open",
        "prev_close",
        "atr",
        "tr",
        "volume",
        "cum_volume",
        "cum_dollar_vol",
    ]
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    logging.info(f"Features: {len(feature_cols)}")

    # Rolling training with improved parameters
    all_trades = []
    all_metrics = []
    equity = 10_000.0

    current = datetime(2024, 1, 1)  # Start later for more stable period
    end_date = datetime(2025, 10, 1)
    iteration = 0

    while current < end_date:
        iteration += 1
        oos_start = current
        oos_end = oos_start + relativedelta(months=OOS_MONTHS)
        val_start = oos_start - relativedelta(months=VALIDATION_MONTHS)
        train_end = val_start
        train_start = train_end - relativedelta(months=TRAIN_MONTHS)

        logging.info(f"\n{'='*60}")
        logging.info(f"ITERATION {iteration}: OOS {oos_start.strftime('%Y-%m')}")
        logging.info(
            f"Train: {train_start.strftime('%Y-%m')} to {train_end.strftime('%Y-%m')}"
        )
        logging.info(
            f"Val: {val_start.strftime('%Y-%m')} to {oos_start.strftime('%Y-%m')}"
        )

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
            f"Data: Train {len(train_df):,} | Val {len(val_df):,} | OOS {len(test_df):,}"
        )

        if len(train_df) < 1000 or len(val_df) < 500 or len(test_df) < 100:
            logging.warning("Insufficient data, skipping")
            current = oos_end
            continue

        # Train models
        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, feature_cols
        )
        logging.info(f"AUC - Long: {auc_long:.4f} | Short: {auc_short:.4f}")

        # Backtest
        trades_df, equity = backtest_improved(
            model_long, model_short, test_df, feature_cols, equity
        )

        if trades_df is not None and len(trades_df) > 0:
            n_trades = len(trades_df)
            win_rate = (trades_df["net_pnl"] > 0).mean() * 100
            total_pnl = trades_df["net_pnl"].sum()
            unique_symbols = trades_df["symbol"].nunique()

            logging.info(
                f"Results: {n_trades} trades | {unique_symbols} symbols | {win_rate:.1f}% win | ${total_pnl:,.0f} PnL"
            )
            logging.info(f"Equity: ${equity:,.0f}")

            trades_df["oos_month"] = oos_start.strftime("%Y-%m")
            all_trades.append(trades_df)

            all_metrics.append(
                {
                    "oos_month": oos_start.strftime("%Y-%m"),
                    "trades": n_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "equity": equity,
                    "unique_symbols": unique_symbols,
                    "auc_long": auc_long,
                    "auc_short": auc_short,
                }
            )
        else:
            logging.info("No trades generated")

        current = oos_end

    # Save results
    if all_trades:
        trades_all = pd.concat(all_trades, ignore_index=True)
        trades_all.to_csv(output_dir / "trades.csv", index=False)

        metrics_df = pd.DataFrame(all_metrics)
        metrics_df.to_csv(output_dir / "metrics.csv", index=False)

        # Summary
        logging.info("\n" + "=" * 80)
        logging.info("IMPROVED SYSTEM RESULTS")
        logging.info("=" * 80)
        logging.info(f"Total trades: {len(trades_all)}")
        logging.info(f"Win rate: {(trades_all['net_pnl'] > 0).mean()*100:.1f}%")
        logging.info(f"Total PnL: ${trades_all['net_pnl'].sum():,.0f}")
        logging.info(f"Final equity: ${equity:,.0f}")
        logging.info(f"Return: {(equity - 10000) / 10000 * 100:.1f}%")

        # Monthly consistency
        profitable_months = (metrics_df["total_pnl"] > 0).sum()
        total_months = len(metrics_df)
        logging.info(
            f"Profitable months: {profitable_months}/{total_months} ({profitable_months/total_months*100:.0f}%)"
        )

        # Diversification check
        symbol_counts = trades_all["symbol"].value_counts()
        logging.info(f"Unique symbols: {len(symbol_counts)}")
        logging.info(f"Max trades per symbol: {symbol_counts.max()}")
        logging.info(
            f"Top symbol: {symbol_counts.index[0]} ({symbol_counts.iloc[0]} trades)"
        )

        # Time distribution
        hour_pnl = trades_all.groupby("hour")["net_pnl"].sum()
        logging.info(f"\nPnL by hour: {hour_pnl.to_dict()}")

        logging.info(f"\nResults saved to: {output_dir}")
    else:
        logging.warning("No trades generated across all periods")


if __name__ == "__main__":
    main()
