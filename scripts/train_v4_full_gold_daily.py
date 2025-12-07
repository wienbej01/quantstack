#!/usr/bin/env python3
"""Train v4 models on full gold universe using daily features."""

import logging
from pathlib import Path

import lightgbm as lgb
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_data():
    """Load feature store and SIP membership."""
    features_path = Path("run/daily_features_full_gold_6months/features.parquet")
    sip_path = Path("run/sip_membership_full_gold_6months/sip_membership.parquet")
    
    logging.info(f"Loading features: {features_path}")
    features = pl.read_parquet(features_path)
    
    logging.info(f"Loading SIP: {sip_path}")
    sip = pl.read_parquet(sip_path)
    
    # Join to filter only SIP symbols
    df = features.join(
        sip.select(["date", "symbol"]),
        on=["date", "symbol"],
        how="inner"
    )
    
    logging.info(f"After SIP filter: {len(df):,} rows, {df['symbol'].n_unique()} symbols")
    return df


def engineer_features(df):
    """Create features from daily data."""
    df = df.sort(["symbol", "date"])
    
    # Price momentum
    df = df.with_columns([
        ((pl.col("close") - pl.col("prior_close")) / pl.col("prior_close")).alias("daily_return"),
        (pl.col("close").pct_change(5).over("symbol")).alias("returns_5d"),
        (pl.col("close").pct_change(10).over("symbol")).alias("returns_10d"),
    ])
    
    # Volatility
    df = df.with_columns([
        (pl.col("daily_return").rolling_std(5).over("symbol")).alias("volatility_5d"),
        (pl.col("daily_return").rolling_std(10).over("symbol")).alias("volatility_10d"),
    ])
    
    # Volume
    df = df.with_columns([
        (pl.col("volume") / pl.col("adv20")).alias("volume_ratio"),
    ])
    
    # ATR-based
    df = df.with_columns([
        (pl.col("atr14") / pl.col("close")).alias("atr_pct"),
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("range_pct"),
        (((pl.col("high") - pl.col("low")) / pl.col("close")) / (pl.col("atr14") / pl.col("close") + 1e-8)).alias("range_atr_ratio"),
    ])
    
    # Gap characteristics
    df = df.with_columns([
        pl.col("gap_pct").abs().alias("abs_gap"),
        (pl.col("gap_pct") > 0).cast(pl.Int8).alias("gap_up"),
        (pl.col("gap_pct") < 0).cast(pl.Int8).alias("gap_down"),
    ])
    
    # Price position
    df = df.with_columns([
        ((pl.col("close") - pl.col("low")) / (pl.col("high") - pl.col("low") + 1e-8)).alias("close_position"),
    ])
    
    return df


def create_labels(df, forward_days=1, profit_threshold=0.02):
    """Create LONG/SHORT labels based on next-day returns."""
    df = df.sort(["symbol", "date"])
    
    # Forward returns
    df = df.with_columns([
        pl.col("close").shift(-forward_days).over("symbol").alias("future_close"),
    ])
    df = df.with_columns([
        ((pl.col("future_close") - pl.col("close")) / pl.col("close")).alias("forward_return"),
    ])
    
    # Labels
    df = df.with_columns([
        pl.when(pl.col("forward_return") > profit_threshold)
        .then(1)
        .otherwise(0)
        .alias("label_long"),
        
        pl.when(pl.col("forward_return") < -profit_threshold)
        .then(1)
        .otherwise(0)
        .alias("label_short"),
    ])
    
    return df


def main():
    logging.info("=" * 80)
    logging.info("TRAINING V4 MODELS - FULL GOLD UNIVERSE (DAILY)")
    logging.info("=" * 80)
    
    # Load data
    df = load_data()
    
    # Engineer features
    logging.info("Engineering features...")
    df = engineer_features(df)
    
    # Create labels
    logging.info("Creating labels...")
    df = create_labels(df)
    
    # Drop nulls
    df = df.drop_nulls()
    logging.info(f"After dropping nulls: {len(df):,} rows")
    
    # Feature columns
    feature_cols = [
        "gap_pct", "abs_gap", "gap_up", "gap_down",
        "daily_return", "returns_5d", "returns_10d",
        "volatility_5d", "volatility_10d",
        "volume_ratio",
        "atr_pct", "range_pct", "range_atr_ratio",
        "close_position",
        "atr14", "adv20",
    ]
    
    # Convert to pandas for LightGBM
    df_pd = df.to_pandas()
    
    # Split: first 80% train, last 20% validation
    split_idx = int(len(df_pd) * 0.8)
    train = df_pd.iloc[:split_idx]
    val = df_pd.iloc[split_idx:]
    
    logging.info(f"Train: {len(train):,} rows ({train['symbol'].nunique()} symbols)")
    logging.info(f"Val: {len(val):,} rows ({val['symbol'].nunique()} symbols)")
    
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
    importance = model_long.feature_importance(importance_type='gain')
    feature_importance = sorted(zip(feature_cols, importance), key=lambda x: x[1], reverse=True)
    logging.info("\nTop 10 Features (LONG):")
    for feat, imp in feature_importance[:10]:
        logging.info(f"  {feat}: {imp:.1f}")
    
    # Save
    model_path = Path("models/v4_full_gold_daily_long.txt")
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
    importance = model_short.feature_importance(importance_type='gain')
    feature_importance = sorted(zip(feature_cols, importance), key=lambda x: x[1], reverse=True)
    logging.info("\nTop 10 Features (SHORT):")
    for feat, imp in feature_importance[:10]:
        logging.info(f"  {feat}: {imp:.1f}")
    
    # Save
    model_path = Path("models/v4_full_gold_daily_short.txt")
    model_short.save_model(str(model_path))
    logging.info(f"\nSaved: {model_path}")
    
    logging.info("\n" + "=" * 80)
    logging.info("TRAINING COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
