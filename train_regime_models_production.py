#!/usr/bin/env python3
"""Train regime-aware models with EXACT date ranges specified:
- Training: 2024-12-01 to 2025-11-15
- Validation: 2025-11-16 to 2025-12-15
- Uses SIP-filtered tickers only
- Uses full intraday feature set
"""

import pickle
import logging
from pathlib import Path
import numpy as np
import pandas as pd
import polars as pl
from sklearn.ensemble import GradientBoostingClassifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Date ranges
TRAIN_START = pd.Timestamp("2024-12-01").date()
TRAIN_END = pd.Timestamp("2025-11-15").date()
VAL_START = pd.Timestamp("2025-11-16").date()
VAL_END = pd.Timestamp("2025-12-15").date()

def detect_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime."""
    df = df.copy()
    df["mkt_ret_20"] = df.groupby("date")["returns"].transform("mean").rolling(20, min_periods=1).sum()
    df["mkt_vol_20"] = df.groupby("date")["returns"].transform("std").rolling(20, min_periods=1).mean()
    
    ret_high = df["mkt_ret_20"].quantile(0.67)
    ret_low = df["mkt_ret_20"].quantile(0.33)
    vol_high = df["mkt_vol_20"].quantile(0.67)
    
    df["trend"] = "sideways"
    df.loc[df["mkt_ret_20"] > ret_high, "trend"] = "bull"
    df.loc[df["mkt_ret_20"] < ret_low, "trend"] = "bear"
    df["high_vol"] = (df["mkt_vol_20"] > vol_high).astype(int)
    
    return df

def main():
    logging.info("=" * 80)
    logging.info("TRAINING REGIME-AWARE MODELS")
    logging.info(f"Training: {TRAIN_START} to {TRAIN_END}")
    logging.info(f"Validation: {VAL_START} to {VAL_END}")
    logging.info("=" * 80)
    
    # Step 1: Load SIP-filtered tickers for the period
    logging.info("Step 1: Loading SIP membership...")
    sip = pl.read_parquet("run/sip_membership_rolling/sip_membership.parquet")
    sip = sip.filter(
        (pl.col("date") >= pl.date(2024, 12, 1)) &
        (pl.col("date") <= pl.date(2025, 12, 15))
    )
    sip_symbols = set(sip["symbol"].unique().to_list())
    logging.info(f"  SIP symbols: {len(sip_symbols)}")
    logging.info(f"  SIP date range: {sip['date'].min()} to {sip['date'].max()}")
    
    # Step 2: Load full intraday features
    logging.info("Step 2: Loading intraday features...")
    features_path = Path("run/intraday_features_rolling/features.parquet")
    df = pl.read_parquet(features_path)
    logging.info(f"  Total rows: {len(df):,}")
    logging.info(f"  Total columns: {len(df.columns)}")
    
    # Filter to date range and SIP symbols
    df = df.filter(
        (pl.col("timestamp").dt.date() >= pl.date(2024, 12, 1)) &
        (pl.col("timestamp").dt.date() <= pl.date(2025, 12, 15)) &
        (pl.col("symbol").is_in(list(sip_symbols)))
    )
    logging.info(f"  After SIP filter: {len(df):,} rows")
    
    # Convert to pandas for sklearn
    df = df.to_pandas()
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    
    # Step 3: Identify feature columns
    logging.info("Step 3: Identifying features...")
    exclude_cols = ["timestamp", "symbol", "date", "forward_return", "label_long", "label_short",
                    "entry_close", "entry_timestamp", "exit_close", "exit_timestamp"]
    feature_cols = [c for c in df.columns if c not in exclude_cols and df[c].dtype in [np.float64, np.int64, np.int32, np.float32]]
    logging.info(f"  Feature columns: {len(feature_cols)}")
    
    # Step 4: Create target variable
    logging.info("Step 4: Creating target variable...")
    if "forward_return" in df.columns:
        df["target"] = (df["forward_return"] > 0).astype(int)
    elif "returns" in df.columns:
        df["target"] = (df["returns"].shift(-30) > 0).astype(int)
    else:
        logging.error("No return column found!")
        return
    
    # Step 5: Detect regimes
    logging.info("Step 5: Detecting regimes...")
    if "returns" not in df.columns:
        df["returns"] = df["close"].pct_change()
    df = detect_regime(df)
    
    # Step 6: Split train/validation
    logging.info("Step 6: Splitting train/validation...")
    train_mask = (df["date"] >= TRAIN_START) & (df["date"] <= TRAIN_END)
    val_mask = (df["date"] >= VAL_START) & (df["date"] <= VAL_END)
    
    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    
    logging.info(f"  Training samples: {len(train_df):,}")
    logging.info(f"  Validation samples: {len(val_df):,}")
    
    if len(train_df) == 0:
        logging.error("No training data!")
        return
    if len(val_df) == 0:
        logging.error("No validation data!")
        return
    
    # Step 7: Train regime-specific models
    logging.info("Step 7: Training regime models...")
    models = {}
    model_dir = Path("models/regime_aware")
    model_dir.mkdir(parents=True, exist_ok=True)
    
    for regime in ["bull", "bear", "sideways"]:
        regime_mask = train_df["trend"] == regime
        regime_samples = regime_mask.sum()
        
        logging.info(f"  Training {regime} model ({regime_samples:,} samples)...")
        
        if regime_samples < 100:
            logging.warning(f"  Insufficient data for {regime}, skipping")
            continue
        
        X_train = train_df.loc[regime_mask, feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
        y_train = train_df.loc[regime_mask, "target"]
        valid = ~y_train.isna()
        
        if valid.sum() < 50:
            logging.warning(f"  Insufficient valid samples for {regime}")
            continue
        
        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
        model.fit(X_train[valid], y_train[valid])
        
        # Save model
        model_path = model_dir / f"{regime}_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        
        models[regime] = model
        logging.info(f"  ✅ {regime} model saved: {model_path}")
    
    # Step 8: Validate on holdout period
    logging.info("Step 8: Running validation (2025-11-16 to 2025-12-15)...")
    
    predictions = np.full(len(val_df), 0.5)
    X_val = val_df[feature_cols].fillna(0).replace([np.inf, -np.inf], 0)
    
    for regime, model in models.items():
        regime_mask = val_df["trend"] == regime
        if regime_mask.sum() > 0:
            predictions[regime_mask] = model.predict_proba(X_val[regime_mask])[:, 1]
    
    # Calculate validation metrics
    val_returns = val_df["forward_return"].fillna(0) if "forward_return" in val_df.columns else val_df["returns"].shift(-30).fillna(0)
    
    long_signals = predictions > 0.60
    short_signals = predictions < 0.40
    
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
    
    logging.info("=" * 80)
    logging.info("VALIDATION RESULTS (2025-11-16 to 2025-12-15)")
    logging.info("=" * 80)
    logging.info(f"Long trades: {long_trades:,}, PnL: {long_pnl:.2%}, Win rate: {long_win_rate:.1%}")
    logging.info(f"Short trades: {short_trades:,}, PnL: {short_pnl:.2%}, Win rate: {short_win_rate:.1%}")
    logging.info(f"Total PnL: {total_pnl:.2%}")
    logging.info("=" * 80)
    logging.info("🎉 Models trained and validated! Ready for live trading.")

if __name__ == "__main__":
    main()
