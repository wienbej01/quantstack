#!/usr/bin/env python3
"""Roll-forward backtest with cross-sectional features."""
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier

warnings.filterwarnings("ignore")


def load_features():
    """Load features and data."""
    feat_path = Path(__file__).parent.parent / "run" / "features_500" / "all_features.parquet"
    data_path = Path(__file__).parent.parent / "run" / "predictions_v4_simple.parquet"
    
    features = pd.read_parquet(feat_path)
    data = pd.read_parquet(data_path)
    if "ts" in data.columns:
        data = data.rename(columns={"ts": "timestamp"})
    
    return data, features


def run_roll_forward(train_days=10, test_days=2):
    """Run roll-forward backtest."""
    data, features = load_features()
    
    # Create target (30min forward return > 0)
    data["target"] = (data.groupby("symbol")["close"].shift(-6) / data["close"] - 1 > 0).astype(int)
    
    # Get dates
    data["date"] = pd.to_datetime(data["timestamp"]).dt.date
    dates = sorted(data["date"].unique())
    
    # Feature columns (drop non-numeric and problematic)
    feat_cols = [c for c in features.columns if features[c].dtype in [np.float64, np.int64, np.float32, np.int32]]
    
    # Fill NaN
    X = features[feat_cols].fillna(0).replace([np.inf, -np.inf], 0)
    y = data["target"]
    
    results = []
    equity = 10000
    
    print("=" * 70)
    print("ROLL-FORWARD BACKTEST (Daily Windows)")
    print("=" * 70)
    print(f"Train window: {train_days} days, Test window: {test_days} days")
    print(f"Features: {len(feat_cols)}")
    print(f"Date range: {dates[0]} to {dates[-1]} ({len(dates)} days)")
    print("-" * 70)
    
    # Roll forward by days
    for i in range(train_days, len(dates) - test_days, test_days):
        train_start = dates[i - train_days]
        train_end = dates[i]
        test_start = dates[i]
        test_end = dates[min(i + test_days, len(dates) - 1)]
        
        # Get indices
        train_mask = (data["date"] >= train_start) & (data["date"] < train_end)
        test_mask = (data["date"] >= test_start) & (data["date"] < test_end)
        
        if train_mask.sum() < 100 or test_mask.sum() < 50:
            continue
        
        X_train, y_train = X[train_mask], y[train_mask]
        X_test, y_test = X[test_mask], y[test_mask]
        
        # Remove NaN targets
        valid_train = ~y_train.isna()
        valid_test = ~y_test.isna()
        X_train, y_train = X_train[valid_train], y_train[valid_train]
        X_test, y_test = X_test[valid_test], y_test[valid_test]
        
        if len(X_train) < 100 or len(X_test) < 50:
            continue
        
        # Train model (fast)
        from sklearn.linear_model import LogisticRegression
        model = LogisticRegression(max_iter=100, random_state=42)
        model.fit(X_train, y_train)
        
        # Predict
        proba = model.predict_proba(X_test)[:, 1]
        
        # Simple strategy: go long when prob > 0.55
        signals = proba > 0.55
        
        # Calculate returns
        test_data = data[test_mask][valid_test].copy()
        test_data["signal"] = signals
        test_data["forward_ret"] = test_data.groupby("symbol")["close"].shift(-6) / test_data["close"] - 1
        
        # Only trade on signals
        trades = test_data[test_data["signal"] == True]
        if len(trades) > 0:
            avg_ret = trades["forward_ret"].mean()
            win_rate = (trades["forward_ret"] > 0).mean()
            n_trades = len(trades)
            
            # Update equity (simplified)
            period_ret = avg_ret * min(n_trades, 100) * 0.01  # 1% per trade
            equity *= (1 + period_ret)
            
            results.append({
                "period": f"{test_start} to {test_end}",
                "n_trades": n_trades,
                "avg_ret": avg_ret,
                "win_rate": win_rate,
                "equity": equity,
            })
            
            print(f"{test_start} → {test_end}: {n_trades:4d} trades, {win_rate:.1%} win, {avg_ret:+.2%} avg, ${equity:,.0f}")
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    
    if results:
        results_df = pd.DataFrame(results)
        total_ret = (equity / 10000 - 1) * 100
        avg_win_rate = results_df["win_rate"].mean()
        
        print(f"Starting equity: $10,000")
        print(f"Final equity: ${equity:,.0f}")
        print(f"Total return: {total_ret:+.1f}%")
        print(f"Average win rate: {avg_win_rate:.1%}")
        print(f"Periods tested: {len(results)}")
        
        # Save results
        out_path = Path(__file__).parent.parent / "run" / "roll_forward_results.csv"
        results_df.to_csv(out_path, index=False)
        print(f"\n✅ Results saved to {out_path}")
    else:
        print("No valid test periods found")


if __name__ == "__main__":
    run_roll_forward()
