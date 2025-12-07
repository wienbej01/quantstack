#!/usr/bin/env python3
"""Train v4 models on 3-month data with validation."""

import logging
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def engineer_features(df):
    """Create features from OHLCV."""
    df = df.sort_values(['symbol', 'ts']).copy()
    
    df['returns'] = df.groupby('symbol')['close'].pct_change()
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['volume_ma5'] = df.groupby('symbol')['volume'].transform(lambda x: x.rolling(5, min_periods=1).mean())
    df['volume_ratio'] = df['volume'] / df['volume_ma5']
    df['returns_5'] = df.groupby('symbol')['close'].pct_change(5)
    df['returns_10'] = df.groupby('symbol')['close'].pct_change(10)
    
    df = df.fillna(0)
    return df


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models - 3 MONTHS")
    LOGGER.info("=" * 80)
    
    # Load data
    data_dir = Path("artefacts/extensions/intraday_ml/v4_3months")
    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")
    
    LOGGER.info(f"Train: {len(train_df):,} rows")
    LOGGER.info(f"Val: {len(val_df):,} rows")
    
    # Engineer features
    LOGGER.info("Engineering features...")
    train_df = engineer_features(train_df)
    val_df = engineer_features(val_df)
    
    feature_cols = ['returns', 'range_pct', 'volume_ratio', 'returns_5', 'returns_10']
    
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]
    
    # Train LONG model
    LOGGER.info("")
    LOGGER.info("Training LONG model...")
    y_train_long = (train_df['label'] == 1).astype(int)
    y_val_long = (val_df['label'] == 1).astype(int)
    
    model_long = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        random_state=42,
        verbose=-1
    )
    model_long.fit(X_train, y_train_long)
    
    train_auc_long = roc_auc_score(y_train_long, model_long.predict_proba(X_train)[:, 1])
    val_auc_long = roc_auc_score(y_val_long, model_long.predict_proba(X_val)[:, 1])
    
    LOGGER.info(f"LONG - Train AUC: {train_auc_long:.4f}, Val AUC: {val_auc_long:.4f}")
    
    # Train SHORT model
    LOGGER.info("")
    LOGGER.info("Training SHORT model...")
    y_train_short = (train_df['label'] == -1).astype(int)
    y_val_short = (val_df['label'] == -1).astype(int)
    
    model_short = lgb.LGBMClassifier(
        n_estimators=200,
        max_depth=6,
        learning_rate=0.05,
        random_state=42,
        verbose=-1
    )
    model_short.fit(X_train, y_train_short)
    
    train_auc_short = roc_auc_score(y_train_short, model_short.predict_proba(X_train)[:, 1])
    val_auc_short = roc_auc_score(y_val_short, model_short.predict_proba(X_val)[:, 1])
    
    LOGGER.info(f"SHORT - Train AUC: {train_auc_short:.4f}, Val AUC: {val_auc_short:.4f}")
    
    # Save models
    output_dir = Path("models")
    output_dir.mkdir(exist_ok=True)
    
    model_long.booster_.save_model(str(output_dir / "v4_3months_long.txt"))
    model_short.booster_.save_model(str(output_dir / "v4_3months_short.txt"))
    
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Training Complete!")
    LOGGER.info("=" * 80)
    LOGGER.info("LONG model: models/v4_3months_long.txt")
    LOGGER.info(f"  Train AUC: {train_auc_long:.4f}")
    LOGGER.info(f"  Val AUC: {val_auc_long:.4f}")
    LOGGER.info("SHORT model: models/v4_3months_short.txt")
    LOGGER.info(f"  Train AUC: {train_auc_short:.4f}")
    LOGGER.info(f"  Val AUC: {val_auc_short:.4f}")
    
    # Check for overfitting
    if train_auc_long - val_auc_long > 0.05:
        LOGGER.warning("⚠️ LONG model may be overfitting (train-val gap > 0.05)")
    if train_auc_short - val_auc_short > 0.05:
        LOGGER.warning("⚠️ SHORT model may be overfitting (train-val gap > 0.05)")


if __name__ == "__main__":
    main()
