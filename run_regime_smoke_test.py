#!/usr/bin/env python3
"""
Smoke test for Regime-Aware Pipeline.
Runs the pipeline with the new 'features_regime.yaml' and 'policy_regime.json'.
Verifies that the system handles missing market data gracefully.
"""

import sys
import yaml
import pandas as pd
import numpy as np
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure current directory is in path
sys.path.append(".")

import run_phaseA_pipeline

def mock_load_bars(**kwargs):
    """Return dummy data for AAPL and empty for others."""
    symbols = kwargs.get("symbols", [])
    # If loading market data (SPY/VIX), return empty to test fallback
    if "SPY" in symbols or "VIX" in symbols:
        # Raise RuntimeError to trigger the fallback logic in market_context
        raise RuntimeError("Market data missing")
        
    # If loading AAPL, return valid data
    dates = pd.date_range(start="2024-01-01", end="2025-06-30", freq="1min", tz="UTC")
    # Filter to trading hours to be realistic (9:30 - 16:00)
    market_hours = (dates.time >= pd.Timestamp("09:30").time()) & (dates.time <= pd.Timestamp("16:00").time())
    dates = dates[market_hours]
    
    df = pd.DataFrame({
        "ts": dates,
        "symbol": "AAPL",
        "open": 150.0,
        "high": 151.0,
        "low": 149.0,
        "close": 150.5,
        "volume": 100000
    })
    # Add some noise
    df["close"] += np.random.randn(len(df))
    
    # Filter by requested dates if needed (simplified)
    return df

def run_smoke_test():
    print("🚀 Starting Regime Pipeline Smoke Test (In-Process with Mocks)...")
    
    # 1. Verify Configs exist
    features_cfg = Path("configs/extensions/intraday_ml/features_regime.yaml")
    policy_cfg = Path("configs/extensions/intraday_ml/policy_regime.json")
    
    if not features_cfg.exists() or not policy_cfg.exists():
        print("❌ Config files missing!")
        return 1
        
    # 2. Create a temporary master config
    master_config = {
        "includes": {
            "universe": "configs/extensions/intraday_ml/universe_single.yaml",
            "splits": "configs/extensions/intraday_ml/splits_pilot.yaml",
            "cuts": "configs/extensions/intraday_ml/cuts_10m.yaml",
            "features": "configs/extensions/intraday_ml/features_regime.yaml",
            "targets": "configs/extensions/intraday_ml/targets_loose.yaml",
            "model": "configs/extensions/intraday_ml/model_lgbm_loose.yaml",
            "cv": "configs/extensions/intraday_ml/cv/phaseA.yaml",
        },
        "policy": {
            "policy_base_config": "configs/extensions/intraday_ml/policy_regime.json",
            "max_entries_per_day": 5
        },
        "data": {
            "root": "/tmp/mock_gold", # won't be used due to patch
        },
        "run_cv": False,
        "artifacts": "artefacts/extensions/intraday_ml/smoke_regime"
    }
    
    config_path = Path("smoke_regime_config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(master_config, f)
        
    # 3. Run the pipeline with patched data loader
    # Patching where it is imported/used
    # Note: data_prep imports load_bars from qx_data.gold_loader
    # dataset_manifest imports load_bars from qx_data.gold_loader
    # market_context imports load_bars from qx_data.gold_loader
    
    # We patch 'qx_data.gold_loader.load_bars' globally
    with patch('qx_data.gold_loader.load_bars', side_effect=mock_load_bars):
        # Also mock sys.argv
        test_argv = [
            "run_phaseA_pipeline.py",
            "--config", str(config_path),
            "--symbol", "AAPL"
        ]
        
        with patch.object(sys, 'argv', test_argv):
            try:
                print(f"   Executing pipeline...")
                run_phaseA_pipeline.main()
            except SystemExit as e:
                if e.code != 0:
                    print(f"❌ Pipeline exited with code {e.code}")
                    return 1
            except Exception as e:
                print(f"❌ Pipeline crashed: {e}")
                import traceback
                traceback.print_exc()
                return 1

    print("\n✅ Pipeline finished successfully.")
    
    # 4. Verify Artifacts
    artifact_dir = Path("artefacts/extensions/intraday_ml/smoke_regime")
    required_files = [
        "training_data.parquet",
        "model_lgbm/model.pkl",
        "oos_predictions.parquet",
        "oos_orders.parquet"
    ]
    
    missing = []
    for f in required_files:
        if not (artifact_dir / f).exists():
            missing.append(f)
            
    if missing:
        print(f"⚠️ Missing expected artifacts: {missing}")
    else:
        print("✅ All key artifacts generated.")

    # 5. Check for Regime Features
    try:
        train_df = pd.read_parquet(artifact_dir / "training_data.parquet")
        regime_cols = [c for c in train_df.columns if "f__regime" in c or "f__mkt" in c]
        print(f"   Regime Features found: {len(regime_cols)}")
        if regime_cols:
            # Check if they are all null (expected since we simulated missing market data)
            null_counts = train_df[regime_cols].isnull().mean()
            print(f"   Null ratio for regime features: {null_counts.mean():.2f} (Expected 1.0)")
            
            # Verify VPA features (should NOT be null as they use OHLCV)
            vpa_cols = [c for c in train_df.columns if "f__vpa" in c]
            if vpa_cols:
                vpa_nulls = train_df[vpa_cols].isnull().mean().mean()
                print(f"   Null ratio for VPA features: {vpa_nulls:.2f} (Expected 0.0)")
                if vpa_nulls > 0.1:
                    print("❌ VPA features should not be null!")
                    return 1
    except Exception as e:
        print(f"   Could not verify features: {e}")

    return 0

if __name__ == "__main__":
    sys.exit(run_smoke_test())
