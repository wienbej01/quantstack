#!/usr/bin/env python3
"""Train regime-aware models with custom date ranges for live trading."""
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

warnings.filterwarnings("ignore")

# Daily features (available in daily dataset)
DAILY_FEATURES = [
    "gap_pct", "atr14", "adv20", "prior_close"
]

def detect_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime using daily data."""
    # Simple regime detection based on gap and volatility
    df["gap_abs"] = df["gap_pct"].abs()
    df["vol_regime"] = df["atr14"] / df["close"]
    
    gap_high = df["gap_abs"].quantile(0.67)
    gap_low = df["gap_abs"].quantile(0.33)
    vol_high = df["vol_regime"].quantile(0.67)
    
    df["trend"] = "sideways"
    df.loc[df["gap_pct"] > gap_high, "trend"] = "bull"
    df.loc[df["gap_pct"] < -gap_high, "trend"] = "bear"
    df["high_vol"] = (df["vol_regime"] > vol_high).astype(int)
    
    # Create simple return target (next day gap)
    df["return_30min"] = df.groupby("symbol")["gap_pct"].shift(-1)
    
    return df

def train_and_save_models():
    """Train regime-aware models with custom date ranges."""
    
    # Load data - use daily features which have complete coverage
    data_path = Path(__file__).parent.parent / "run" / "daily_features_rolling" / "features.parquet"
    
    if not data_path.exists():
        print(f"❌ Data file not found: {data_path}")
        return False
    
    print("📊 Loading daily features data...")
    df = pd.read_parquet(data_path)
    # Daily features use 'date' column directly
    df["date"] = pd.to_datetime(df["date"]).dt.date
    
    # Custom date ranges
    train_start = pd.Timestamp("2024-12-01").date()
    train_end = pd.Timestamp("2025-11-15").date()
    val_start = pd.Timestamp("2025-11-16").date()
    val_end = pd.Timestamp("2025-12-15").date()
    
    print(f"🎯 Training period: {train_start} to {train_end}")
    print(f"🎯 Validation period: {val_start} to {val_end}")
    
    # Filter data
    train_mask = (df["date"] >= train_start) & (df["date"] <= train_end)
    val_mask = (df["date"] >= val_start) & (df["date"] <= val_end)
    
    train_df = df[train_mask].copy()
    val_df = df[val_mask].copy()
    
    if len(train_df) == 0:
        print("❌ No training data found for specified period")
        return False
    
    if len(val_df) == 0:
        print("❌ No validation data found for specified period")
        return False
    
    print(f"✅ Training samples: {len(train_df)}")
    print(f"✅ Validation samples: {len(val_df)}")
    
    print("🔍 Detecting regimes...")
    train_df = detect_regime(train_df)
    val_df = detect_regime(val_df)
    
    # Prepare features and target
    features = [f for f in DAILY_FEATURES if f in train_df.columns]
    train_y = (train_df["return_30min"] > 0).astype(int)
    val_y = (val_df["return_30min"] > 0).astype(int)
    
    print(f"✅ Features available: {len(features)}")
    
    # Train models for each regime
    models = {}
    model_dir = Path("models/regime_aware")
    model_dir.mkdir(parents=True, exist_ok=True)
    
    for regime in ["bull", "bear", "sideways"]:
        regime_mask = train_df["trend"] == regime
        regime_samples = regime_mask.sum()
        
        print(f"\n🎯 Training {regime} model ({regime_samples} samples)...")
        
        if regime_samples < 100:
            print(f"⚠️  Insufficient data for {regime} regime, skipping")
            continue
        
        # Prepare regime-specific data
        X_regime = train_df.loc[regime_mask, features].fillna(0).replace([np.inf, -np.inf], 0)
        y_regime = train_y[regime_mask]
        valid = ~y_regime.isna()
        
        if valid.sum() < 50:
            print(f"⚠️  Insufficient valid samples for {regime} regime")
            continue
        
        # Train model
        model = GradientBoostingClassifier(
            n_estimators=100, max_depth=4, learning_rate=0.1, random_state=42
        )
        
        model.fit(X_regime[valid], y_regime[valid])
        
        # Save model
        model_path = model_dir / f"{regime}_model.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)
        
        models[regime] = model
        
        print(f"✅ {regime} model saved: {model_path}")
        
        # Show feature importance
        importance = dict(zip(features, model.feature_importances_, strict=False))
        top_features = sorted(importance.items(), key=lambda x: x[1], reverse=True)[:3]
        print(f"   Top features: {dict(top_features)}")
    
    print(f"\n🎉 Training complete! Saved {len(models)} regime models")
    
    # Validation backtest
    print("\n📈 Running validation backtest...")
    
    if len(val_df) > 0:
        # Generate predictions
        predictions = np.full(len(val_df), 0.5)
        X_val = val_df[features].fillna(0).replace([np.inf, -np.inf], 0)
        
        for regime, model in models.items():
            regime_mask = val_df["trend"] == regime
            if regime_mask.sum() > 0:
                predictions[regime_mask] = model.predict_proba(X_val[regime_mask])[:, 1]
        
        # Calculate performance
        val_returns = val_df["return_30min"].fillna(0)
        long_signals = predictions > 0.65
        short_signals = predictions < 0.35
        
        long_pnl = val_returns[long_signals].sum() if long_signals.sum() > 0 else 0
        short_pnl = -val_returns[short_signals].sum() if short_signals.sum() > 0 else 0
        total_pnl = long_pnl + short_pnl
        
        long_trades = long_signals.sum()
        short_trades = short_signals.sum()
        total_trades = long_trades + short_trades
        
        if total_trades > 0:
            win_rate = ((val_returns[long_signals] > 0).sum() + (val_returns[short_signals] < 0).sum()) / total_trades
        else:
            win_rate = 0
        
        print("✅ Validation Results (2025-11-16 to 2025-12-15):")
        print(f"   Long trades: {long_trades}, PnL: {long_pnl:.2f}%")
        print(f"   Short trades: {short_trades}, PnL: {short_pnl:.2f}%")
        print(f"   Total trades: {total_trades}")
        print(f"   Total PnL: {total_pnl:.2f}%")
        print(f"   Win rate: {win_rate:.1%}")
        
        # Save validation results
        val_results = val_df.copy()
        val_results["prediction"] = predictions
        val_results["signal"] = "hold"
        val_results.loc[long_signals, "signal"] = "long"
        val_results.loc[short_signals, "signal"] = "short"
        
        results_path = Path("run") / "validation_results_custom.csv"
        val_results.to_csv(results_path, index=False)
        print(f"   Validation results saved: {results_path}")
    
    return True

if __name__ == "__main__":
    success = train_and_save_models()
    if success:
        print("\n🚀 Models ready for live trading!")
    else:
        print("\n❌ Training failed!")
        exit(1)
