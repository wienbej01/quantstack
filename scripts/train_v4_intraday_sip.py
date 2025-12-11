#!/usr/bin/env python3
"""Train v4 models on intraday SIP features."""

import logging
from pathlib import Path

import lightgbm as lgb
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("TRAINING V4 MODELS - INTRADAY SIP")
    logging.info("=" * 80)

    # Load intraday features
    features_path = Path("run/intraday_features_sip_6months/features.parquet")
    logging.info(f"Loading features: {features_path}")
    df = pl.read_parquet(features_path)

    logging.info(
        f"Loaded {len(df):,} bars, {df['symbol'].n_unique()} symbols, {df['date'].n_unique()} dates"
    )

    # Drop nulls
    df = df.drop_nulls()
    logging.info(f"After dropping nulls: {len(df):,} bars")

    # Feature columns
    feature_cols = [
        "returns",
        "returns_5",
        "returns_10",
        "returns_20",
        "range_pct",
        "body_pct",
        "volume_ratio",
        "volume_ratio_20",
        "volatility_5",
        "volatility_20",
        "time_since_open",
        "time_to_close",
        "price_position",
    ]

    # Convert to pandas
    df_pd = df.to_pandas()

    # Split: first 80% train, last 20% validation (time-based)
    split_idx = int(len(df_pd) * 0.8)
    train = df_pd.iloc[:split_idx]
    val = df_pd.iloc[split_idx:]

    logging.info(f"Train: {len(train):,} bars ({train['symbol'].nunique()} symbols)")
    logging.info(f"Val: {len(val):,} bars ({val['symbol'].nunique()} symbols)")

    # Train LONG model
    logging.info("\n" + "=" * 80)
    logging.info("TRAINING LONG MODEL")
    logging.info("=" * 80)

    X_train = train[feature_cols]
    y_train = train["label_long"]
    X_val = val[feature_cols]
    y_val = val["label_long"]

    logging.info(f"Positive rate (train): {y_train.mean():.2%}")
    logging.info(f"Positive rate (val): {y_val.mean():.2%}")

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

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

    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Evaluate
    y_pred = model_long.predict(X_val)
    auc = roc_auc_score(y_val, y_pred)
    logging.info(f"\nLONG Model AUC: {auc:.4f}")

    # Feature importance
    importance = model_long.feature_importance(importance_type="gain")
    feature_importance = sorted(
        zip(feature_cols, importance, strict=False), key=lambda x: x[1], reverse=True
    )
    logging.info("\nTop Features (LONG):")
    for feat, imp in feature_importance:
        logging.info(f"  {feat}: {imp:.1f}")

    # Save
    model_path = Path("models/v4_intraday_sip_long.txt")
    model_path.parent.mkdir(exist_ok=True)
    model_long.save_model(str(model_path))
    logging.info(f"\nSaved: {model_path}")

    # Train SHORT model
    logging.info("\n" + "=" * 80)
    logging.info("TRAINING SHORT MODEL")
    logging.info("=" * 80)

    y_train = train["label_short"]
    y_val = val["label_short"]

    logging.info(f"Positive rate (train): {y_train.mean():.2%}")
    logging.info(f"Positive rate (val): {y_val.mean():.2%}")

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Evaluate
    y_pred = model_short.predict(X_val)
    auc = roc_auc_score(y_val, y_pred)
    logging.info(f"\nSHORT Model AUC: {auc:.4f}")

    # Feature importance
    importance = model_short.feature_importance(importance_type="gain")
    feature_importance = sorted(
        zip(feature_cols, importance, strict=False), key=lambda x: x[1], reverse=True
    )
    logging.info("\nTop Features (SHORT):")
    for feat, imp in feature_importance:
        logging.info(f"  {feat}: {imp:.1f}")

    # Save
    model_path = Path("models/v4_intraday_sip_short.txt")
    model_short.save_model(str(model_path))
    logging.info(f"\nSaved: {model_path}")

    logging.info("\n" + "=" * 80)
    logging.info("TRAINING COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
