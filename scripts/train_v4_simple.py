#!/usr/bin/env python3
"""Train v4 models with simple feature engineering."""

import logging
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import train_test_split

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def engineer_features(df):
    """Create simple features from OHLCV."""
    df = df.sort_values(['symbol', 'ts']).copy()
    
    # Price features
    df['returns'] = df.groupby('symbol')['close'].pct_change()
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    
    # Volume features
    df['volume_ma5'] = df.groupby('symbol')['volume'].transform(lambda x: x.rolling(5, min_periods=1).mean())
    df['volume_ratio'] = df['volume'] / df['volume_ma5']
    
    # Momentum features
    df['returns_5'] = df.groupby('symbol')['close'].pct_change(5)
    df['returns_10'] = df.groupby('symbol')['close'].pct_change(10)
    
    # Fill NaN
    df = df.fillna(0)
    
    return df


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models - Simple Features")
    LOGGER.info("=" * 80)
    
    # Load data
    data_path = Path("artefacts/extensions/intraday_ml/v4_sip_smb/training_data.parquet")
    df = pd.read_parquet(data_path)
    LOGGER.info(f"Loaded {len(df):,} rows, {df['symbol'].nunique()} symbols")
    
    # Engineer features
    LOGGER.info("Engineering features...")
    df = engineer_features(df)
    
    # Feature columns
    feature_cols = ['returns', 'range_pct', 'volume_ratio', 'returns_5', 'returns_10']
    
    # Train LONG model (predict label==1 vs others)
    LOGGER.info("")
    LOGGER.info("Training LONG model...")
    X = df[feature_cols]
    y_long = (df['label'] == 1).astype(int)
    
    X_train, X_val, y_train, y_val = train_test_split(
        X, y_long, test_size=0.2, random_state=42, stratify=y_long
    )
    
    model_long = lgb.LGBMClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        verbose=-1
    )
    model_long.fit(X_train, y_train)
    
    y_pred = model_long.predict_proba(X_val)[:, 1]
    auc_long = roc_auc_score(y_val, y_pred)
    LOGGER.info(f"LONG ROC AUC: {auc_long:.4f}")
    
    # Train SHORT model (predict label==-1 vs others)
    LOGGER.info("")
    LOGGER.info("Training SHORT model...")
    y_short = (df['label'] == -1).astype(int)
    
    X_train, X_val, y_train, y_val = train_test_split(
        X, y_short, test_size=0.2, random_state=42, stratify=y_short
    )
    
    model_short = lgb.LGBMClassifier(
        n_estimators=100,
        max_depth=5,
        learning_rate=0.1,
        random_state=42,
        verbose=-1
    )
    model_short.fit(X_train, y_train)
    
    y_pred = model_short.predict_proba(X_val)[:, 1]
    auc_short = roc_auc_score(y_val, y_pred)
    LOGGER.info(f"SHORT ROC AUC: {auc_short:.4f}")
    
    # Save models
    output_dir = Path("models")
    output_dir.mkdir(exist_ok=True)
    
    model_long.booster_.save_model(str(output_dir / "v4_sip_smb_long.txt"))
    model_short.booster_.save_model(str(output_dir / "v4_sip_smb_short.txt"))
    
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Training Complete!")
    LOGGER.info(f"LONG model: models/v4_sip_smb_long.txt (AUC: {auc_long:.4f})")
    LOGGER.info(f"SHORT model: models/v4_sip_smb_short.txt (AUC: {auc_short:.4f})")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
