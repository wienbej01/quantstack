#!/usr/bin/env python3
"""Enhanced training with XGBoost, Optuna tuning, and feature selection."""

import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import optuna
import pandas as pd
import polars as pl
import shap
import xgboost as xgb
from dateutil.relativedelta import relativedelta
from sklearn.feature_selection import SelectFromModel
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Parameters
THRESHOLD = 0.30
EQUITY = 10_000.0
RISK_FRACTION = 0.01
ATR_STOP_MULTIPLE = 1.5
R_TARGET = 2.0

# Enhanced training parameters
TRAIN_MONTHS = 3  # Shorter window
VAL_MONTHS = 1
OOS_MONTHS = 1
PURGE_BARS = 5  # Purging between splits


def get_feature_columns(df):
    """Get enhanced feature columns."""
    exclude = [
        "date",
        "symbol",
        "timestamp",
        "hour_et",
        "label_long_10",
        "label_short_10",
        "label_long_15",
        "label_short_15",
        "label_long_30",
        "label_short_30",
        "label_multiclass",
        "forward_return_10",
        "forward_return_15",
        "forward_return_30",
    ]

    feature_cols = [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in ["float64", "int64", "float32", "int32"]
    ]

    logging.info(f"Available features: {len(feature_cols)}")
    return feature_cols


def optimize_hyperparameters(X_train, y_train, X_val, y_val, n_trials=50):
    """Optimize XGBoost hyperparameters with Optuna."""

    def objective(trial):
        params = {
            "max_depth": trial.suggest_int("max_depth", 3, 10),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.1),
            "n_estimators": trial.suggest_int("n_estimators", 100, 500),
            "min_child_weight": trial.suggest_int("min_child_weight", 1, 10),
            "subsample": trial.suggest_float("subsample", 0.6, 1.0),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.6, 1.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 0, 1.0),
            "reg_lambda": trial.suggest_float("reg_lambda", 0, 1.0),
            "random_state": 42,
            "eval_metric": "auc",
            "early_stopping_rounds": 30,
            "verbose": False,
        }

        model = xgb.XGBClassifier(**params)
        model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        y_pred = model.predict_proba(X_val)[:, 1]
        return roc_auc_score(y_val, y_pred)

    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    return study.best_params


def select_features_shap(model, X_val, feature_cols, top_k=25):
    """Select top features using SHAP values."""
    try:
        explainer = shap.TreeExplainer(model)
        shap_values = explainer.shap_values(X_val.sample(min(1000, len(X_val))))

        importance = np.abs(shap_values).mean(axis=0)
        top_indices = np.argsort(importance)[-top_k:]
        selected_features = [feature_cols[i] for i in top_indices]

        logging.info(f"Selected {len(selected_features)} features using SHAP")
        return selected_features
    except Exception as e:
        logging.warning(f"SHAP selection failed: {e}, using all features")
        return feature_cols


def create_purged_splits(df, train_end_idx, val_end_idx, purge_bars=PURGE_BARS):
    """Create purged train/val/test splits."""
    train = df.iloc[: train_end_idx - purge_bars]
    val = df.iloc[train_end_idx + purge_bars : val_end_idx - purge_bars]
    test = df.iloc[val_end_idx + purge_bars :]

    return train, val, test


def train_enhanced_models(train_df, val_df, feature_cols, regime_filter=None):
    """Train enhanced XGBoost models with optimization."""

    # Apply regime filter if specified
    if regime_filter is not None:
        train_df = train_df[train_df["volatility_regime"] == regime_filter]
        val_df = val_df[val_df["volatility_regime"] == regime_filter]

    if len(train_df) < 1000 or len(val_df) < 100:
        logging.warning(f"Insufficient data: train={len(train_df)}, val={len(val_df)}")
        return None, None, 0, 0, []

    X_train = train_df[feature_cols].fillna(0)
    X_val = val_df[feature_cols].fillna(0)
    y_train_long = train_df["label_long_15"]  # Use 15-bar labels
    y_val_long = val_df["label_long_15"]
    y_train_short = train_df["label_short_15"]
    y_val_short = val_df["label_short_15"]

    # Train LONG model
    model_long = None
    auc_long = 0
    selected_features = feature_cols

    if y_train_long.sum() >= 50 and y_val_long.sum() >= 10:
        # Optimize hyperparameters
        best_params = optimize_hyperparameters(
            X_train, y_train_long, X_val, y_val_long, n_trials=30
        )

        # Train with best parameters
        model_long = xgb.XGBClassifier(**best_params)
        model_long.fit(
            X_train, y_train_long, eval_set=[(X_val, y_val_long)], verbose=False
        )

        # Feature selection
        selected_features = select_features_shap(
            model_long, X_val, feature_cols, top_k=25
        )

        # Retrain with selected features
        X_train_sel = X_train[selected_features]
        X_val_sel = X_val[selected_features]

        model_long = xgb.XGBClassifier(**best_params)
        model_long.fit(
            X_train_sel, y_train_long, eval_set=[(X_val_sel, y_val_long)], verbose=False
        )

        y_pred = model_long.predict_proba(X_val_sel)[:, 1]
        auc_long = roc_auc_score(y_val_long, y_pred)

    # Train SHORT model
    model_short = None
    auc_short = 0

    if y_train_short.sum() >= 50 and y_val_short.sum() >= 10:
        best_params = optimize_hyperparameters(
            X_train, y_train_short, X_val, y_val_short, n_trials=30
        )

        X_train_sel = X_train[selected_features]
        X_val_sel = X_val[selected_features]

        model_short = xgb.XGBClassifier(**best_params)
        model_short.fit(
            X_train_sel,
            y_train_short,
            eval_set=[(X_val_sel, y_val_short)],
            verbose=False,
        )

        y_pred = model_short.predict_proba(X_val_sel)[:, 1]
        auc_short = roc_auc_score(y_val_short, y_pred)

    logging.info(
        f"Models trained - Long AUC: {auc_long:.3f}, Short AUC: {auc_short:.3f}, Features: {len(selected_features)}"
    )
    return model_long, model_short, auc_long, auc_short, selected_features


def backtest_enhanced(models, test_df, selected_features, equity=EQUITY):
    """Enhanced backtest with regime awareness."""

    model_long, model_short = models

    if model_long is None and model_short is None:
        return [], equity

    test_df = test_df.copy()
    test_df["prob_long"] = 0.0
    test_df["prob_short"] = 0.0

    # Generate predictions
    if model_long is not None:
        X_test = test_df[selected_features].fillna(0)
        test_df["prob_long"] = model_long.predict_proba(X_test)[:, 1]

    if model_short is not None:
        X_test = test_df[selected_features].fillna(0)
        test_df["prob_short"] = model_short.predict_proba(X_test)[:, 1]

    # Apply threshold
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= THRESHOLD, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= THRESHOLD, "prediction"] = -1

    # Focus on morning trading (higher label rates)
    test_df = test_df[test_df["hour_et"].isin([9, 10, 11])]

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return [], equity

    # Execute trades
    trades = []
    current_equity = equity

    for _, signal in signals.iterrows():
        # Position sizing based on ATR
        atr_pct = signal["atr_pct"]
        stop_distance = atr_pct * ATR_STOP_MULTIPLE
        risk_amount = current_equity * RISK_FRACTION
        shares = int(risk_amount / (100 * stop_distance))  # Normalized pricing

        if shares <= 0:
            shares = 100

        # Trade execution
        side = "LONG" if signal["prediction"] == 1 else "SHORT"
        entry_price = 100.0  # Normalized

        # Use actual forward return for P&L
        forward_return = signal.get("forward_return_15", 0)
        exit_price = entry_price * (1 + forward_return)

        if side == "LONG":
            gross_pnl = (exit_price - entry_price) * shares
        else:
            gross_pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread

        current_equity += net_pnl

        trade = {
            "signal_timestamp": signal["timestamp"],
            "symbol": signal["symbol"],
            "side": side,
            "shares": shares,
            "entry_price": entry_price,
            "exit_price": exit_price,
            "gross_pnl": gross_pnl,
            "fee": fee,
            "spread": spread,
            "net_pnl": net_pnl,
            "r_multiple": net_pnl / (shares * entry_price * stop_distance),
            "hour_et": signal["hour_et"],
            "regime": signal.get("volatility_regime", 0),
            "prob_long": signal["prob_long"],
            "prob_short": signal["prob_short"],
        }
        trades.append(trade)

    return trades, current_equity


def main():
    logging.info("=" * 80)
    logging.info("ENHANCED TRAINING: XGBoost + Optuna + SHAP + Regime Detection")
    logging.info("=" * 80)

    # Load enhanced features
    features_path = Path("run/enhanced_features/features.parquet")
    if not features_path.exists():
        logging.error(
            "Enhanced features not found. Run build_enhanced_features.py first"
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
        oos_end = oos_start + relativedelta(months=OOS_MONTHS)
        val_start = oos_start - relativedelta(months=VAL_MONTHS)
        train_start = val_start - relativedelta(months=TRAIN_MONTHS)

        logging.info(
            f"\nOOS: {oos_start.strftime('%Y-%m')} | "
            f"Train: {train_start.strftime('%Y-%m')} to {val_start.strftime('%Y-%m')} | "
            f"Val: {val_start.strftime('%Y-%m')}"
        )

        # Split data with purging
        train_df = pdf[(pdf["date"] >= train_start) & (pdf["date"] < val_start)]
        val_df = pdf[(pdf["date"] >= val_start) & (pdf["date"] < oos_start)]
        test_df = pdf[(pdf["date"] >= oos_start) & (pdf["date"] < oos_end)]

        if len(test_df) == 0:
            current_date = oos_end
            continue

        # Train enhanced models
        model_long, model_short, auc_long, auc_short, selected_features = (
            train_enhanced_models(train_df, val_df, feature_cols)
        )

        models = (model_long, model_short)

        # Backtest
        trades, final_equity = backtest_enhanced(models, test_df, selected_features)

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
            "auc_long": auc_long,
            "auc_short": auc_short,
            "trades": len(trades),
            "win_rate": win_rate,
            "avg_pnl": avg_pnl,
            "total_pnl": total_pnl,
            "avg_r_multiple": avg_r,
            "final_equity": final_equity,
            "features_used": len(selected_features),
        }
        results.append(result)
        all_trades.extend(trades)

        logging.info(
            f"Trades: {len(trades)}, Win Rate: {win_rate:.1%}, "
            f"Total PnL: ${total_pnl:,.0f}, AUC L/S: {auc_long:.3f}/{auc_short:.3f}"
        )

        current_date = oos_end

    # Save results
    output_dir = Path("run/enhanced_results")
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
        logging.info("ENHANCED RESULTS")
        logging.info("=" * 80)
        logging.info(f"Total trades: {total_trades}")
        logging.info(f"Win rate: {overall_win_rate:.1%}")
        logging.info(f"Total PnL: ${total_pnl:,.0f}")
        logging.info(f"Average R-multiple: {avg_r:.2f}")
        logging.info(f"Average AUC Long: {results_df['auc_long'].mean():.3f}")
        logging.info(f"Average AUC Short: {results_df['auc_short'].mean():.3f}")
        logging.info(f"Results saved to: {output_dir}")


if __name__ == "__main__":
    main()
