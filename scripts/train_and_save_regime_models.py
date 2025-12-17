#!/usr/bin/env python3
"""Train and save regime-aware models for live trading."""
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

warnings.filterwarnings("ignore")

# Cross-sectional features (best performers)
CROSS_SECTIONAL_FEATURES = [
    "cross_rank_ret",
    "cross_rank_vol",
    "sector_momentum",
    "cross_dispersion",
    "market_breadth",
    "up_down_ratio",
    "rel_strength_5",
    "rel_strength_10",
    "rel_strength_20",
    "market_ret_5",
    "market_ret_10",
]


def detect_regime(df: pd.DataFrame) -> pd.DataFrame:
    """Detect market regime (trend + volatility)."""
    market_ret = df.groupby("timestamp")["returns"].transform("mean")
    market_vol = df.groupby("timestamp")["returns"].transform("std")

    df["mkt_ret_20"] = market_ret.rolling(20, min_periods=1).sum()
    df["mkt_vol_20"] = market_vol.rolling(20, min_periods=1).mean()

    ret_high = df["mkt_ret_20"].quantile(0.67)
    ret_low = df["mkt_ret_20"].quantile(0.33)
    vol_high = df["mkt_vol_20"].quantile(0.67)

    df["trend"] = "sideways"
    df.loc[df["mkt_ret_20"] > ret_high, "trend"] = "bull"
    df.loc[df["mkt_ret_20"] < ret_low, "trend"] = "bear"
    df["high_vol"] = (df["mkt_vol_20"] > vol_high).astype(int)

    return df


def train_and_save_models():
    """Train regime-aware models and save them."""

    # Load data
    data_path = (
        Path(__file__).parent.parent
        / "run"
        / "cross_sectional_features"
        / "features.parquet"
    )

    if not data_path.exists():
        print(f"❌ Data file not found: {data_path}")
        return False

    print("📊 Loading training data...")
    df = pd.read_parquet(data_path)
    df["date"] = pd.to_datetime(df["timestamp"]).dt.date
    df = df[df["date"] < pd.Timestamp("2025-01-01").date()]

    print("🔍 Detecting regimes...")
    df = detect_regime(df)

    # Prepare features and target
    features = [f for f in CROSS_SECTIONAL_FEATURES if f in df.columns]
    y = (df["return_30min"] > 0).astype(int)

    print(f"✅ Features available: {len(features)}")
    print(f"✅ Data points: {len(df)}")

    # Use most recent data for training (last 6 months)
    recent_date = df["date"].max()
    train_start = recent_date - pd.Timedelta(days=180)
    train_mask = df["date"] >= train_start

    train_df = df[train_mask]
    train_y = y[train_mask]

    print(f"✅ Training period: {train_start} to {recent_date}")
    print(f"✅ Training samples: {len(train_df)}")

    # Train models for each regime
    models = {}
    model_dir = Path("models/regime_aware")
    model_dir.mkdir(parents=True, exist_ok=True)

    for regime in ["bull", "bear", "sideways"]:
        regime_mask = train_df["trend"] == regime
        regime_samples = regime_mask.sum()

        print(f"\n🎯 Training {regime} model ({regime_samples} samples)...")

        if regime_samples < 500:
            print(f"⚠️  Insufficient data for {regime} regime, skipping")
            continue

        # Prepare regime-specific data
        X_regime = (
            train_df.loc[regime_mask, features].fillna(0).replace([np.inf, -np.inf], 0)
        )
        y_regime = train_y[regime_mask]
        valid = ~y_regime.isna()

        if valid.sum() < 300:
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

        # Validate model can be loaded
        with open(model_path, "rb") as f:
            loaded_model = pickle.load(f)

        print(f"✅ {regime} model saved and validated: {model_path}")
        print(
            f"   Feature importance (top 3): {dict(list(zip(features, model.feature_importances_, strict=False))[:3])}"
        )

    print(f"\n🎉 Training complete! Saved {len(models)} regime models")

    # Quick validation backtest
    print("\n📈 Running validation backtest...")

    # Use last month for validation
    val_start = recent_date - pd.Timedelta(days=30)
    val_mask = (df["date"] >= val_start) & (df["date"] <= recent_date)
    val_df = df[val_mask]

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

        print("✅ Validation (last 30 days):")
        print(f"   Long trades: {long_signals.sum()}, PnL: {long_pnl:.1f}%")
        print(f"   Short trades: {short_signals.sum()}, PnL: {short_pnl:.1f}%")
        print(f"   Total PnL: {total_pnl:.1f}%")

    return True


if __name__ == "__main__":
    success = train_and_save_models()
    if success:
        print("\n🚀 Models ready for live trading!")
    else:
        print("\n❌ Training failed!")
        exit(1)
