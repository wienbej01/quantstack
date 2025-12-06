#!/usr/bin/env python3
"""Train v4 models with EXPANDED feature set."""

import logging
from pathlib import Path

import lightgbm as lgb
import pandas as pd
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def engineer_features_expanded(df):
    """Create expanded feature set."""
    df = df.sort_values(['symbol', 'ts']).copy()
    
    # Price features
    df['returns'] = df.groupby('symbol')['close'].pct_change()
    df['returns_5'] = df.groupby('symbol')['close'].pct_change(5)
    df['returns_10'] = df.groupby('symbol')['close'].pct_change(10)
    df['returns_20'] = df.groupby('symbol')['close'].pct_change(20)
    
    # Range features
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['body_pct'] = abs(df['close'] - df['open']) / df['close']
    df['upper_wick'] = (df['high'] - df[['open', 'close']].max(axis=1)) / df['close']
    df['lower_wick'] = (df[['open', 'close']].min(axis=1) - df['low']) / df['close']
    
    # Volume features
    df['volume_ma5'] = df.groupby('symbol')['volume'].transform(lambda x: x.rolling(5, min_periods=1).mean())
    df['volume_ma20'] = df.groupby('symbol')['volume'].transform(lambda x: x.rolling(20, min_periods=1).mean())
    df['volume_ratio'] = df['volume'] / df['volume_ma5']
    df['volume_ratio_20'] = df['volume'] / df['volume_ma20']
    
    # Momentum features
    df['rsi_5'] = df.groupby('symbol')['returns'].transform(
        lambda x: x.rolling(5, min_periods=1).apply(lambda y: 100 - 100/(1 + (y[y>0].sum() / abs(y[y<0].sum()) if y[y<0].sum() != 0 else 1)))
    )
    
    # Volatility features
    df['volatility_5'] = df.groupby('symbol')['returns'].transform(lambda x: x.rolling(5, min_periods=1).std())
    df['volatility_20'] = df.groupby('symbol')['returns'].transform(lambda x: x.rolling(20, min_periods=1).std())
    
    # Time-of-day features
    df['hour'] = df['ts'].dt.hour
    df['minute'] = df['ts'].dt.minute
    df['time_since_open'] = (df['hour'] - 9) * 60 + (df['minute'] - 30)  # Minutes since 9:30
    df['time_to_close'] = (16 - df['hour']) * 60 - df['minute']  # Minutes to 16:00
    
    # Price position features
    df['high_5'] = df.groupby('symbol')['high'].transform(lambda x: x.rolling(5, min_periods=1).max())
    df['low_5'] = df.groupby('symbol')['low'].transform(lambda x: x.rolling(5, min_periods=1).min())
    df['price_position'] = (df['close'] - df['low_5']) / (df['high_5'] - df['low_5'])
    
    return df.fillna(0)


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Training v4 Models - EXPANDED FEATURES")
    LOGGER.info("=" * 80)
    
    # Load data
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")
    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")
    
    LOGGER.info(f"Train: {len(train_df):,} rows")
    LOGGER.info(f"Val: {len(val_df):,} rows")
    
    # Engineer features
    LOGGER.info("Engineering expanded features...")
    train_df = engineer_features_expanded(train_df)
    val_df = engineer_features_expanded(val_df)
    
    feature_cols = [
        'returns', 'returns_5', 'returns_10', 'returns_20',
        'range_pct', 'body_pct', 'upper_wick', 'lower_wick',
        'volume_ratio', 'volume_ratio_20',
        'rsi_5', 'volatility_5', 'volatility_20',
        'time_since_open', 'time_to_close',
        'price_position'
    ]
    
    LOGGER.info(f"Features: {len(feature_cols)}")
    
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]
    
    # Train LONG model
    LOGGER.info("")
    LOGGER.info("Training LONG model...")
    y_train_long = (train_df['label'] == 1).astype(int)
    y_val_long = (val_df['label'] == 1).astype(int)
    
    model_long = lgb.LGBMClassifier(
        n_estimators=300,
        max_depth=7,
        learning_rate=0.03,
        num_leaves=64,
        min_child_samples=100,
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
        n_estimators=300,
        max_depth=7,
        learning_rate=0.03,
        num_leaves=64,
        min_child_samples=100,
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
    
    model_long.booster_.save_model(str(output_dir / "v4_6months_expanded_long.txt"))
    model_short.booster_.save_model(str(output_dir / "v4_6months_expanded_short.txt"))
    
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Training Complete!")
    LOGGER.info("=" * 80)
    LOGGER.info(f"LONG: Train {train_auc_long:.4f}, Val {val_auc_long:.4f}")
    LOGGER.info(f"SHORT: Train {train_auc_short:.4f}, Val {val_auc_short:.4f}")
    LOGGER.info("Models saved to models/v4_6months_expanded_*.txt")


if __name__ == "__main__":
    main()
