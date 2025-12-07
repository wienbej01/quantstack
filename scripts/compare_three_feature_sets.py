#!/usr/bin/env python3
"""Compare 15 optimal vs 30 ICT vs 30 VPA feature sets."""

import logging
import warnings
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Define feature sets
OPTIMAL_15 = [
    "is_last_30min",
    "sma_200",
    "time_to_close",
    "obv_ema_10",
    "liquidity_grab_high",
    "volatility_30",
    "liquidity_grab_low",
    "range_pct",
    "volatility_5",
    "volume_momentum_50",
    "bb_width_10",
    "bb_width_20",
    "volume_std_50",
    "atr_7",
]

ICT_30 = [
    "returns",
    "returns_5",
    "returns_10",
    "returns_20",
    "range_pct",
    "body_pct",
    "upper_wick",
    "lower_wick",
    "volume_ratio",
    "volume_ratio_20",
    "volatility_5",
    "volatility_20",
    "time_since_open",
    "time_to_close",
    "price_position",
    "fvg_up",
    "fvg_down",
    "fvg_size_pct",
    "displacement_up",
    "displacement_down",
    "order_block_bull",
    "order_block_bear",
    "liquidity_grab_high",
    "liquidity_grab_low",
    "bos_up",
    "bos_down",
    "pressure_ratio",
    "distance_from_vwap",
    "volume_momentum",
    "pv_divergence",
]

VPA_30 = [
    # Volume features (10)
    "volume_ma_5",
    "volume_ma_10",
    "volume_ma_20",
    "volume_ma_30",
    "volume_ma_50",
    "volume_ratio_5",
    "volume_ratio_10",
    "volume_ratio_20",
    "volume_ratio_30",
    "volume_ratio_50",
    # Volume momentum (5)
    "volume_momentum_5",
    "volume_momentum_10",
    "volume_momentum_20",
    "volume_momentum_30",
    "volume_momentum_50",
    # Volume-price analysis (5)
    "buying_pressure",
    "selling_pressure",
    "pressure_ratio",
    "volume_price_ratio",
    "pv_divergence",
    # VWAP (3)
    "vwap_10",
    "vwap_20",
    "distance_from_vwap_20",
    # OBV (2)
    "obv",
    "obv_ema_10",
    # Volume std (3)
    "volume_std_20",
    "volume_std_30",
    "volume_std_50",
    # MFI (1)
    "mfi_14",
    # Range-volume (1)
    "range_volume_ratio",
]


def train_and_evaluate(X_train, y_train, X_val, y_val, X_oos, y_oos, feature_set_name):
    """Train model and evaluate on val and OOS."""
    logging.info(f"Training {feature_set_name}...")

    # Train LONG model
    train_long = X_train[y_train != -1].copy()
    y_train_long = (y_train[y_train != -1] == 1).astype(int)

    val_long = X_val[y_val != -1].copy()
    y_val_long = (y_val[y_val != -1] == 1).astype(int)

    train_data_long = lgb.Dataset(train_long, label=y_train_long)
    val_data_long = lgb.Dataset(val_long, label=y_val_long, reference=train_data_long)

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
        "seed": 42,
    }

    model_long = lgb.train(
        params,
        train_data_long,
        num_boost_round=500,
        valid_sets=[val_data_long],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    # Train SHORT model
    train_short = X_train[y_train != 1].copy()
    y_train_short = (y_train[y_train != 1] == -1).astype(int)

    val_short = X_val[y_val != 1].copy()
    y_val_short = (y_val[y_val != 1] == -1).astype(int)

    train_data_short = lgb.Dataset(train_short, label=y_train_short)
    val_data_short = lgb.Dataset(
        val_short, label=y_val_short, reference=train_data_short
    )

    model_short = lgb.train(
        params,
        train_data_short,
        num_boost_round=500,
        valid_sets=[val_data_short],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    # Evaluate
    auc_long = roc_auc_score(y_val_long, model_long.predict(val_long))
    auc_short = roc_auc_score(y_val_short, model_short.predict(val_short))

    logging.info(f"  Val AUC - LONG: {auc_long:.4f}, SHORT: {auc_short:.4f}")

    return model_long, model_short, auc_long, auc_short


def backtest_model(
    model_long, model_short, X_oos, y_oos, forward_returns_series, threshold=0.30
):
    """Backtest model on OOS data."""
    # Predict
    prob_long = model_long.predict(X_oos)
    prob_short = model_short.predict(X_oos)

    # Generate signals
    predictions = pd.Series("NEUTRAL", index=X_oos.index)
    predictions[prob_long >= threshold] = "LONG"
    predictions[prob_short >= threshold] = "SHORT"

    # Calculate P&L
    signals = predictions[predictions != "NEUTRAL"]

    pnl = pd.Series(0.0, index=signals.index)
    pnl[signals == "LONG"] = (
        forward_returns_series.loc[signals[signals == "LONG"].index] * 100
    )
    pnl[signals == "SHORT"] = (
        -forward_returns_series.loc[signals[signals == "SHORT"].index] * 100
    )

    # Metrics
    total_trades = len(signals)
    wins = (pnl > 0).sum()
    losses = (pnl <= 0).sum()
    win_rate = wins / total_trades * 100 if total_trades > 0 else 0
    avg_pnl = pnl.mean()
    total_pnl = pnl.sum()
    sharpe = pnl.mean() / (pnl.std() + 1e-8) * (252**0.5)

    # Per-direction
    long_signals = signals[signals == "LONG"]
    short_signals = signals[signals == "SHORT"]

    long_pnl = pnl[signals == "LONG"]
    short_pnl = pnl[signals == "SHORT"]

    long_win_rate = (
        (long_pnl > 0).sum() / len(long_pnl) * 100 if len(long_pnl) > 0 else 0
    )
    short_win_rate = (
        (short_pnl > 0).sum() / len(short_pnl) * 100 if len(short_pnl) > 0 else 0
    )

    long_avg_pnl = long_pnl.mean() if len(long_pnl) > 0 else 0
    short_avg_pnl = short_pnl.mean() if len(short_pnl) > 0 else 0

    return {
        "total_trades": total_trades,
        "wins": wins,
        "losses": losses,
        "win_rate": win_rate,
        "avg_pnl": avg_pnl,
        "total_pnl": total_pnl,
        "sharpe": sharpe,
        "long_trades": len(long_signals),
        "long_win_rate": long_win_rate,
        "long_avg_pnl": long_avg_pnl,
        "short_trades": len(short_signals),
        "short_win_rate": short_win_rate,
        "short_avg_pnl": short_avg_pnl,
    }


def main():
    logging.info("Loading data...")
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")

    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")
    oos_df = pd.read_parquet(data_dir / "oos.parquet")

    # Engineer features
    logging.info("Engineering features...")
    from train_v4_6months_comprehensive_features import engineer_comprehensive_features

    train_df = engineer_comprehensive_features(train_df)
    val_df = engineer_comprehensive_features(val_df)
    oos_df = engineer_comprehensive_features(oos_df)

    # Calculate forward returns for OOS
    oos_df = oos_df.sort_values(["symbol", "ts"])
    oos_df["forward_return"] = (
        oos_df.groupby("symbol")["close"].shift(-10) / oos_df["close"] - 1
    )

    # Drop nulls
    train_df = train_df.dropna()
    val_df = val_df.dropna()
    oos_df = oos_df.dropna()

    logging.info(
        f"Data: Train={len(train_df):,}, Val={len(val_df):,}, OOS={len(oos_df):,}"
    )

    # Prepare labels
    y_train = train_df["label"].values
    y_val = val_df["label"].values
    y_oos = oos_df["label"].values
    forward_returns = oos_df["forward_return"].values

    results = {}

    # === TEST 1: 15 OPTIMAL FEATURES ===
    logging.info("\n=== Testing 15 Optimal Features ===")
    X_train_opt = train_df[OPTIMAL_15]
    X_val_opt = val_df[OPTIMAL_15]
    X_oos_opt = oos_df[OPTIMAL_15]

    model_long_opt, model_short_opt, auc_long_opt, auc_short_opt = train_and_evaluate(
        X_train_opt, y_train, X_val_opt, y_val, X_oos_opt, y_oos, "15 Optimal"
    )

    results["15_optimal"] = backtest_model(
        model_long_opt, model_short_opt, X_oos_opt, y_oos, oos_df["forward_return"]
    )
    results["15_optimal"]["auc_long"] = auc_long_opt
    results["15_optimal"]["auc_short"] = auc_short_opt

    # === TEST 2: 30 ICT FEATURES ===
    logging.info("\n=== Testing 30 ICT Features ===")
    # Use existing ICT model
    from train_v4_6months_ict_features import engineer_features_ict

    train_ict = engineer_features_ict(pd.read_parquet(data_dir / "train.parquet"))
    val_ict = engineer_features_ict(pd.read_parquet(data_dir / "val.parquet"))
    oos_ict = engineer_features_ict(pd.read_parquet(data_dir / "oos.parquet"))

    train_ict = train_ict.dropna()
    val_ict = val_ict.dropna()
    oos_ict = oos_ict.dropna()

    # Calculate forward returns
    oos_ict = oos_ict.sort_values(["symbol", "ts"])
    oos_ict["forward_return"] = (
        oos_ict.groupby("symbol")["close"].shift(-10) / oos_ict["close"] - 1
    )
    oos_ict = oos_ict.dropna()

    X_train_ict = train_ict[ICT_30]
    X_val_ict = val_ict[ICT_30]
    X_oos_ict = oos_ict[ICT_30]

    y_train_ict = train_ict["label"].values
    y_val_ict = val_ict["label"].values
    y_oos_ict = oos_ict["label"].values

    model_long_ict, model_short_ict, auc_long_ict, auc_short_ict = train_and_evaluate(
        X_train_ict, y_train_ict, X_val_ict, y_val_ict, X_oos_ict, y_oos_ict, "30 ICT"
    )

    results["30_ict"] = backtest_model(
        model_long_ict, model_short_ict, X_oos_ict, y_oos_ict, oos_ict["forward_return"]
    )
    results["30_ict"]["auc_long"] = auc_long_ict
    results["30_ict"]["auc_short"] = auc_short_ict

    # === TEST 3: 30 VPA FEATURES ===
    logging.info("\n=== Testing 30 VPA Features ===")
    X_train_vpa = train_df[VPA_30]
    X_val_vpa = val_df[VPA_30]
    X_oos_vpa = oos_df[VPA_30]

    model_long_vpa, model_short_vpa, auc_long_vpa, auc_short_vpa = train_and_evaluate(
        X_train_vpa, y_train, X_val_vpa, y_val, X_oos_vpa, y_oos, "30 VPA"
    )

    results["30_vpa"] = backtest_model(
        model_long_vpa, model_short_vpa, X_oos_vpa, y_oos, oos_df["forward_return"]
    )
    results["30_vpa"]["auc_long"] = auc_long_vpa
    results["30_vpa"]["auc_short"] = auc_short_vpa

    # === PRINT COMPARISON ===
    print("\n" + "=" * 100)
    print("THREE-WAY FEATURE SET COMPARISON")
    print("=" * 100)

    print("\n--- VALIDATION METRICS ---")
    print(f"{'Model':<20} {'LONG AUC':>12} {'SHORT AUC':>12}")
    print("-" * 100)
    for name, res in results.items():
        print(f"{name:<20} {res['auc_long']:>12.4f} {res['auc_short']:>12.4f}")

    print("\n--- OOS PERFORMANCE (Threshold=0.30) ---")
    print(
        f"{'Model':<20} {'Trades':>8} {'Win Rate':>10} {'Avg P&L':>10} {'Total P&L':>12} {'Sharpe':>10}"
    )
    print("-" * 100)
    for name, res in results.items():
        print(
            f"{name:<20} {res['total_trades']:>8} {res['win_rate']:>9.1f}% {res['avg_pnl']:>9.2f}% {res['total_pnl']:>11.2f}% {res['sharpe']:>10.2f}"
        )

    print("\n--- DIRECTION-SPECIFIC PERFORMANCE ---")
    print(
        f"{'Model':<20} {'LONG Trades':>12} {'LONG Win%':>10} {'LONG Avg':>10} {'SHORT Trades':>14} {'SHORT Win%':>11} {'SHORT Avg':>11}"
    )
    print("-" * 100)
    for name, res in results.items():
        print(
            f"{name:<20} {res['long_trades']:>12} {res['long_win_rate']:>9.1f}% {res['long_avg_pnl']:>9.2f}% {res['short_trades']:>14} {res['short_win_rate']:>10.1f}% {res['short_avg_pnl']:>10.2f}%"
        )

    # Determine winner
    print("\n--- WINNER DETERMINATION ---")
    scores = {}
    for name, res in results.items():
        score = (
            res["win_rate"] * 0.4  # 40% weight on win rate
            + (res["total_pnl"] / 100) * 0.3  # 30% weight on total P&L
            + res["sharpe"] * 10 * 0.2  # 20% weight on Sharpe
            + (res["total_trades"] / 100) * 0.1  # 10% weight on trade volume
        )
        scores[name] = score

    winner = max(scores, key=scores.get)

    print(f"{'Model':<20} {'Score':>10} {'Rank':>8}")
    print("-" * 100)
    for i, (name, score) in enumerate(
        sorted(scores.items(), key=lambda x: x[1], reverse=True), 1
    ):
        marker = " ⭐ WINNER" if name == winner else ""
        print(f"{name:<20} {score:>10.2f} {i:>8}{marker}")

    # Save results
    output_dir = Path("run")
    results_df = pd.DataFrame(results).T
    results_df.to_csv(output_dir / "three_way_comparison.csv")

    logging.info(f"\nResults saved to {output_dir}/three_way_comparison.csv")

    print("\n" + "=" * 100)
    print(f"WINNER: {winner.upper()}")
    print("=" * 100)


if __name__ == "__main__":
    main()
