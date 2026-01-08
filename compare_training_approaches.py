#!/usr/bin/env python3
"""Compare training approaches: 6 months vs 12/1 start date."""

import logging
import pickle
from pathlib import Path

import numpy as np
import pandas as pd
import polars as pl
from sklearn.ensemble import GradientBoostingClassifier
from sklearn.metrics import classification_report

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def detect_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime."""
    df = df.copy()
    df["mkt_ret_20"] = (
        df.groupby("date")["returns"].transform("mean").rolling(20, min_periods=1).sum()
    )
    df["mkt_vol_20"] = (
        df.groupby("date")["returns"].transform("std").rolling(20, min_periods=1).mean()
    )

    ret_high = df["mkt_ret_20"].quantile(0.67)
    ret_low = df["mkt_ret_20"].quantile(0.33)
    vol_high = df["mkt_vol_20"].quantile(0.67)

    df["trend"] = "sideways"
    df.loc[df["mkt_ret_20"] > ret_high, "trend"] = "bull"
    df.loc[df["mkt_ret_20"] < ret_low, "trend"] = "bear"
    df["high_vol"] = (df["mkt_vol_20"] > vol_high).astype(int)

    return df


def train_and_evaluate(train_start, train_end, val_start, val_end, label):
    """Train and evaluate model with given date ranges."""
    logging.info(f"=" * 80)
    logging.info(f"TRAINING APPROACH: {label}")
    logging.info(f"Training: {train_start} to {train_end}")
    logging.info(f"Validation: {val_start} to {val_end}")
    logging.info(f"=" * 80)

    # Load data
    df = pl.read_parquet("run/intraday_features_rolling/features.parquet")

    # Filter to SIP symbols
    sip = pl.read_parquet("run/sip_membership_rolling/sip_membership.parquet")
    sip_symbols = set(sip["symbol"].unique().to_list())

    df = df.filter(
        (pl.col("timestamp").dt.date() >= train_start)
        & (pl.col("timestamp").dt.date() <= val_end)
        & (pl.col("symbol").is_in(list(sip_symbols)))
    ).to_pandas()

    df["date"] = pd.to_datetime(df["timestamp"]).dt.date

    # Feature columns
    exclude_cols = [
        "timestamp",
        "symbol",
        "date",
        "forward_return",
        "label_long",
        "label_short",
        "entry_close",
        "entry_timestamp",
        "exit_close",
        "exit_timestamp",
    ]
    feature_cols = [
        c
        for c in df.columns
        if c not in exclude_cols
        and df[c].dtype in [np.float64, np.int64, np.int32, np.float32]
    ]

    # Create target
    df["target"] = (df["forward_return"] > 0).astype(int)

    # Detect regimes
    if "returns" not in df.columns:
        df["returns"] = df["close"].pct_change()
    df = detect_regime(df)

    # Split data
    train_mask = (df["date"] >= train_start) & (df["date"] <= train_end)
    val_mask = (df["date"] >= val_start) & (df["date"] <= val_end)

    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()

    logging.info(f"Training samples: {len(train_df):,}")
    logging.info(f"Validation samples: {len(val_df):,}")

    if len(train_df) == 0 or len(val_df) == 0:
        logging.error("Insufficient data!")
        return None

    # Train single model (bull regime for comparison)
    regime = "bull"
    regime_mask = train_df["trend"] == regime

    if regime_mask.sum() < 100:
        logging.warning(f"Insufficient {regime} data")
        return None

    X_train = (
        train_df.loc[regime_mask, feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
    )
    y_train = train_df.loc[regime_mask, "target"]
    valid = ~y_train.isna()

    model = GradientBoostingClassifier(
        n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
    )
    model.fit(X_train[valid], y_train[valid])

    # Validate
    val_regime_mask = val_df["trend"] == regime
    if val_regime_mask.sum() == 0:
        logging.warning("No validation data for regime")
        return None

    X_val = (
        val_df.loc[val_regime_mask, feature_cols]
        .fillna(0)
        .replace([np.inf, -np.inf], 0)
    )
    y_val = val_df.loc[val_regime_mask, "target"]
    val_returns = val_df.loc[val_regime_mask, "forward_return"].fillna(0)

    # Predictions
    proba = model.predict_proba(X_val)[:, 1]

    # Trading simulation
    long_signals = proba > 0.60
    short_signals = proba < 0.40

    long_trades = long_signals.sum()
    short_trades = short_signals.sum()

    if long_trades > 0:
        long_pnl = val_returns[long_signals].sum()
        long_win_rate = (val_returns[long_signals] > 0).mean()
    else:
        long_pnl = 0
        long_win_rate = 0

    if short_trades > 0:
        short_pnl = -val_returns[short_signals].sum()
        short_win_rate = (val_returns[short_signals] < 0).mean()
    else:
        short_pnl = 0
        short_win_rate = 0

    total_pnl = long_pnl + short_pnl

    # Feature importance
    top_features = sorted(
        zip(feature_cols, model.feature_importances_), key=lambda x: x[1], reverse=True
    )[:5]

    # Prediction stats
    pred_stats = {
        "mean": proba.mean(),
        "std": proba.std(),
        "min": proba.min(),
        "max": proba.max(),
        "long_pct": (proba > 0.60).mean() * 100,
        "short_pct": (proba < 0.40).mean() * 100,
    }

    results = {
        "label": label,
        "train_samples": len(train_df),
        "val_samples": len(val_df),
        "regime_train_samples": regime_mask.sum(),
        "regime_val_samples": val_regime_mask.sum(),
        "long_trades": long_trades,
        "short_trades": short_trades,
        "long_pnl": long_pnl,
        "short_pnl": short_pnl,
        "total_pnl": total_pnl,
        "long_win_rate": long_win_rate,
        "short_win_rate": short_win_rate,
        "top_features": top_features,
        "pred_stats": pred_stats,
    }

    return results


def main():
    # Approach 1: 6 months training, 1 month validation (recent data)
    results_6m = train_and_evaluate(
        train_start=pd.Timestamp("2025-06-01").date(),
        train_end=pd.Timestamp("2025-11-30").date(),
        val_start=pd.Timestamp("2025-12-01").date(),
        val_end=pd.Timestamp("2025-12-15").date(),
        label="6 Months Recent (Jun-Nov → Dec)",
    )

    # Approach 2: Original 12/1 start (11.5 months training, 1 month validation)
    results_12m = train_and_evaluate(
        train_start=pd.Timestamp("2024-12-01").date(),
        train_end=pd.Timestamp("2025-11-15").date(),
        val_start=pd.Timestamp("2025-11-16").date(),
        val_end=pd.Timestamp("2025-12-15").date(),
        label="11.5 Months (Dec'24-Nov'25 → Dec'25)",
    )

    # Approach 3: 6 months older data for comparison
    results_6m_old = train_and_evaluate(
        train_start=pd.Timestamp("2025-01-01").date(),
        train_end=pd.Timestamp("2025-06-30").date(),
        val_start=pd.Timestamp("2025-07-01").date(),
        val_end=pd.Timestamp("2025-07-31").date(),
        label="6 Months Older (Jan-Jun → Jul)",
    )

    # Compare results
    logging.info("\n" + "=" * 100)
    logging.info("COMPARISON RESULTS")
    logging.info("=" * 100)

    for results in [results_6m, results_12m, results_6m_old]:
        if results is None:
            continue

        logging.info(f"\n{results['label']}:")
        logging.info(
            f"  Training samples: {results['train_samples']:,} (regime: {results['regime_train_samples']:,})"
        )
        logging.info(
            f"  Validation samples: {results['val_samples']:,} (regime: {results['regime_val_samples']:,})"
        )
        logging.info(
            f"  Long trades: {results['long_trades']:,}, PnL: {results['long_pnl']:.2%}, Win rate: {results['long_win_rate']:.1%}"
        )
        logging.info(
            f"  Short trades: {results['short_trades']:,}, PnL: {results['short_pnl']:.2%}, Win rate: {results['short_win_rate']:.1%}"
        )
        logging.info(f"  Total PnL: {results['total_pnl']:.2%}")
        logging.info(
            f"  Prediction stats: mean={results['pred_stats']['mean']:.3f}, std={results['pred_stats']['std']:.3f}"
        )
        logging.info(
            f"  Signal distribution: {results['pred_stats']['long_pct']:.1f}% long, {results['pred_stats']['short_pct']:.1f}% short"
        )
        logging.info(f"  Top features: {[f[0] for f in results['top_features']]}")


if __name__ == "__main__":
    main()
