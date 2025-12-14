#!/usr/bin/env python3
"""Rolling training with time-stratified models and morning focus."""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from dateutil.relativedelta import relativedelta
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Parameters
THRESHOLD = 0.30
EQUITY = 10_000.0
RISK_FRACTION = 0.01
ATR_STOP_MULTIPLE = 1.5
R_TARGET = 2.0
MAX_HOLD_BARS = 390

# Time stratification
MORNING_HOURS = [9, 10, 11]  # 9:30-12:00 ET
AFTERNOON_HOURS = [12, 13, 14, 15]  # 12:00-16:00 ET


def get_feature_columns(df):
    """Get clean feature columns (no raw prices, metadata, or labels)."""
    exclude = [
        "date",
        "symbol",
        "timestamp",
        "label_long_atr",
        "label_short_atr",
        "forward_return",
        "atr_threshold",
        "hour_et",
    ]

    feature_cols = [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in ["float64", "int64", "float32", "int32"]
    ]

    logging.info(f"Using {len(feature_cols)} clean features")
    return feature_cols


def train_time_stratified_models(train_df, val_df, feature_cols, time_period="morning"):
    """Train models for specific time period."""

    if time_period == "morning":
        hours = MORNING_HOURS
    else:
        hours = AFTERNOON_HOURS

    # Filter to time period
    train_filtered = train_df[train_df["hour_et"].isin(hours)]
    val_filtered = val_df[val_df["hour_et"].isin(hours)]

    if len(train_filtered) < 1000 or len(val_filtered) < 100:
        logging.warning(
            f"Insufficient {time_period} data: train={len(train_filtered)}, val={len(val_filtered)}"
        )
        return None, None, 0, 0

    X_train = train_filtered[feature_cols].fillna(0)
    X_val = val_filtered[feature_cols].fillna(0)
    y_train_long = train_filtered["label_long_atr"]
    y_val_long = val_filtered["label_long_atr"]
    y_train_short = train_filtered["label_short_atr"]
    y_val_short = val_filtered["label_short_atr"]

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
        "min_data_in_leaf": 20,
        "lambda_l1": 0.1,
        "lambda_l2": 0.1,
    }

    # Train LONG model
    model_long = None
    auc_long = 0
    if y_train_long.sum() >= 50 and y_val_long.sum() >= 10:
        train_ds = lgb.Dataset(X_train, label=y_train_long)
        val_ds = lgb.Dataset(X_val, label=y_val_long, reference=train_ds)
        model_long = lgb.train(
            params,
            train_ds,
            num_boost_round=300,
            valid_sets=[val_ds],
            callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
        )
        auc_long = roc_auc_score(y_val_long, model_long.predict(X_val))

    # Train SHORT model
    model_short = None
    auc_short = 0
    if y_train_short.sum() >= 50 and y_val_short.sum() >= 10:
        train_ds = lgb.Dataset(X_train, label=y_train_short)
        val_ds = lgb.Dataset(X_val, label=y_val_short, reference=train_ds)
        model_short = lgb.train(
            params,
            train_ds,
            num_boost_round=300,
            valid_sets=[val_ds],
            callbacks=[lgb.early_stopping(30), lgb.log_evaluation(0)],
        )
        auc_short = roc_auc_score(y_val_short, model_short.predict(X_val))

    logging.info(
        f"{time_period.title()} models - Long AUC: {auc_long:.3f}, Short AUC: {auc_short:.3f}"
    )
    return model_long, model_short, auc_long, auc_short


def backtest_time_stratified(models, test_df, feature_cols, equity=EQUITY):
    """Backtest with time-stratified models."""

    morning_long, morning_short, afternoon_long, afternoon_short = models

    test_df = test_df.copy()
    test_df["prob_long"] = 0.0
    test_df["prob_short"] = 0.0

    # Apply morning models
    morning_mask = test_df["hour_et"].isin(MORNING_HOURS)
    if morning_long is not None and morning_mask.sum() > 0:
        morning_data = test_df[morning_mask]
        X_morning = morning_data[feature_cols].fillna(0)
        test_df.loc[morning_mask, "prob_long"] = morning_long.predict(X_morning)
    if morning_short is not None and morning_mask.sum() > 0:
        morning_data = test_df[morning_mask]
        X_morning = morning_data[feature_cols].fillna(0)
        test_df.loc[morning_mask, "prob_short"] = morning_short.predict(X_morning)

    # Apply afternoon models
    afternoon_mask = test_df["hour_et"].isin(AFTERNOON_HOURS)
    if afternoon_long is not None and afternoon_mask.sum() > 0:
        afternoon_data = test_df[afternoon_mask]
        X_afternoon = afternoon_data[feature_cols].fillna(0)
        test_df.loc[afternoon_mask, "prob_long"] = afternoon_long.predict(X_afternoon)
    if afternoon_short is not None and afternoon_mask.sum() > 0:
        afternoon_data = test_df[afternoon_mask]
        X_afternoon = afternoon_data[feature_cols].fillna(0)
        test_df.loc[afternoon_mask, "prob_short"] = afternoon_short.predict(X_afternoon)

    # Generate signals
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= THRESHOLD, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= THRESHOLD, "prediction"] = -1

    # Focus on morning trading (higher label rates)
    test_df = test_df[test_df["hour_et"].isin(MORNING_HOURS)]

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return [], equity

    # Execute trades
    trades = []
    current_equity = equity

    for _, signal in signals.iterrows():
        # Position sizing based on ATR (simplified)
        atr_pct = signal["atr_pct"]
        stop_distance = atr_pct * ATR_STOP_MULTIPLE
        risk_amount = current_equity * RISK_FRACTION
        # Use fixed position size since we don't have price
        shares = int(risk_amount / (100 * stop_distance))  # Assume $100 stock price

        if shares <= 0:
            shares = 100  # Minimum position

        # Trade execution
        side = "LONG" if signal["prediction"] == 1 else "SHORT"
        entry_price = 100.0  # Normalized price for P&L calculation

        if side == "LONG":
            stop_loss = entry_price * (1 - stop_distance)
            take_profit = entry_price * (1 + stop_distance * R_TARGET)
        else:
            stop_loss = entry_price * (1 + stop_distance)
            take_profit = entry_price * (1 - stop_distance * R_TARGET)

        # Simple exit at fixed bars (normalized P&L)
        # Simulate exit based on forward return
        forward_return = signal.get("forward_return", 0)
        exit_price = entry_price * (1 + forward_return)

        if side == "LONG":
            gross_pnl = (exit_price - entry_price) * shares
        else:
            gross_pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2  # Entry + exit
        spread = shares * entry_price * 0.0005  # 5 bps
        net_pnl = gross_pnl - fee - spread

        current_equity += net_pnl

        trade = {
            "signal_timestamp": signal["timestamp"],
            "entry_timestamp": signal["timestamp"],  # Same as signal for simplicity
            "exit_timestamp": signal["timestamp"],  # Same as signal for simplicity
            "symbol": signal["symbol"],
            "side": side,
            "shares": shares,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "exit_reason": "time_exit",
            "gross_pnl": gross_pnl,
            "fee": fee,
            "spread": spread,
            "net_pnl": net_pnl,
            "r_multiple": net_pnl / (shares * entry_price * stop_distance),
            "hour_et": signal["hour_et"],
        }
        trades.append(trade)

    return trades, current_equity


def main():
    logging.info("=" * 80)
    logging.info("ROLLING TRAINING: Time-stratified models with morning focus")
    logging.info("=" * 80)

    # Load fixed features
    features_path = Path("run/intraday_features_fixed/features.parquet")
    if not features_path.exists():
        logging.error(
            "Fixed features not found. Run build_intraday_features_fixed.py first"
        )
        return

    df = pl.read_parquet(features_path)
    pdf = df.to_pandas()
    pdf["date"] = pd.to_datetime(pdf["date"])
    pdf["hour_et"] = pd.to_datetime(pdf["timestamp"]).dt.hour

    feature_cols = get_feature_columns(pdf)

    # Rolling training setup
    start_date = datetime(2023, 8, 1)
    end_date = datetime(2025, 9, 30)

    results = []
    all_trades = []

    current_date = start_date
    while current_date <= end_date:
        oos_start = current_date
        oos_end = oos_start + relativedelta(months=1)
        val_start = oos_start - relativedelta(months=1)
        train_start = val_start - relativedelta(months=6)

        logging.info(
            f"\nOOS: {oos_start.strftime('%Y-%m')} | "
            f"Train: {train_start.strftime('%Y-%m')} to {val_start.strftime('%Y-%m')} | "
            f"Val: {val_start.strftime('%Y-%m')}"
        )

        # Split data
        train_df = pdf[(pdf["date"] >= train_start) & (pdf["date"] < val_start)]
        val_df = pdf[(pdf["date"] >= val_start) & (pdf["date"] < oos_start)]
        test_df = pdf[(pdf["date"] >= oos_start) & (pdf["date"] < oos_end)]

        if len(test_df) == 0:
            current_date = oos_end
            continue

        # Train time-stratified models
        morning_long, morning_short, morning_auc_l, morning_auc_s = (
            train_time_stratified_models(train_df, val_df, feature_cols, "morning")
        )
        afternoon_long, afternoon_short, afternoon_auc_l, afternoon_auc_s = (
            train_time_stratified_models(train_df, val_df, feature_cols, "afternoon")
        )

        models = (morning_long, morning_short, afternoon_long, afternoon_short)

        # Backtest
        trades, final_equity = backtest_time_stratified(models, test_df, feature_cols)

        # Results
        if trades:
            trades_df = pd.DataFrame(trades)
            win_rate = (trades_df["net_pnl"] > 0).mean()
            avg_pnl = trades_df["net_pnl"].mean()
            total_pnl = trades_df["net_pnl"].sum()
            avg_r = trades_df["r_multiple"].mean()
        else:
            win_rate = avg_pnl = total_pnl = avg_r = 0

        result = {
            "oos_month": oos_start.strftime("%Y-%m"),
            "morning_auc_long": morning_auc_l,
            "morning_auc_short": morning_auc_s,
            "afternoon_auc_long": afternoon_auc_l,
            "afternoon_auc_short": afternoon_auc_s,
            "trades": len(trades),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_pnl": total_pnl,
            "avg_r_multiple": avg_r,
            "final_equity": final_equity,
        }
        results.append(result)
        all_trades.extend(trades)

        logging.info(
            f"Trades: {len(trades)}, Win Rate: {win_rate:.1%}, "
            f"Total PnL: ${total_pnl:,.0f}, Avg R: {avg_r:.2f}"
        )

        current_date = oos_end

    # Save results
    output_dir = Path("run/rolling_results_fixed")
    output_dir.mkdir(parents=True, exist_ok=True)

    results_df = pd.DataFrame(results)
    results_df.to_csv(output_dir / "metrics.csv", index=False)

    if all_trades:
        trades_df = pd.DataFrame(all_trades)
        trades_df.to_csv(output_dir / "trades.csv", index=False)

        # Summary
        total_trades = len(trades_df)
        overall_win_rate = (trades_df["net_pnl"] > 0).mean()
        total_pnl = trades_df["net_pnl"].sum()
        avg_r = trades_df["r_multiple"].mean()

        logging.info("=" * 80)
        logging.info("FINAL RESULTS")
        logging.info("=" * 80)
        logging.info(f"Total trades: {total_trades}")
        logging.info(f"Win rate: {overall_win_rate:.1%}")
        logging.info(f"Total PnL: ${total_pnl:,.0f}")
        logging.info(f"Average R-multiple: {avg_r:.2f}")
        logging.info(f"Morning trades: {(trades_df['hour_et'] < 12).sum()}")
        logging.info(f"Results saved to: {output_dir}")


if __name__ == "__main__":
    main()
