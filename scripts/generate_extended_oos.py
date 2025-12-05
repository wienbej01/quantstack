"""Generate predictions for validation + OOS period (April 16 - May 31)."""
import sys
from pathlib import Path
import pandas as pd
import joblib

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from extensions.intraday_ml.data_prep import load_split_data

def main():
    print("=== Generating Extended OOS Predictions ===\n")
    
    # Load models
    print("Loading models...")
    stage1_model = joblib.load("artefacts/extensions/intraday_ml/bigmove_stage1/model.pkl")
    stage2_model = joblib.load("artefacts/extensions/intraday_ml/bigmove_stage2_dir/model.pkl")
    
    # Load validation data
    print("Loading validation data...")
    val_data = load_split_data(
        "configs/extensions/intraday_ml/phaseA_sip_full.yaml",
        split="val"
    )
    
    # Load OOS data
    print("Loading OOS data...")
    oos_data = pd.read_parquet("artefacts/extensions/intraday_ml/phaseA_full_sip/oos_features.parquet")
    
    # Combine
    print(f"Val samples: {len(val_data):,}")
    print(f"OOS samples: {len(oos_data):,}")
    combined = pd.concat([val_data, oos_data], ignore_index=True)
    print(f"Combined samples: {len(combined):,}")
    
    # Get feature columns
    feature_cols = [c for c in combined.columns if c.startswith('f__')]
    X = combined[feature_cols]
    
    # Stage 1 predictions
    print("\nGenerating Stage 1 predictions...")
    prob_bigmove = stage1_model.predict_proba(X)[:, 1]
    
    # Stage 2 predictions
    print("Generating Stage 2 predictions...")
    prob_long = stage2_model.predict_proba(X)[:, 1]
    prob_short = 1 - prob_long
    
    # Create output dataframe
    output = pd.DataFrame({
        'ts': combined['ts'],
        'symbol': combined['symbol'],
        'prob_bigmove': prob_bigmove,
        'prob_bigmove_long': prob_long,
        'prob_bigmove_short': prob_short,
    })
    
    # Add features needed for policy
    for col in ['close', 'f__vol__atr_6']:
        if col in combined.columns:
            output[col] = combined[col]
    
    # Save
    output_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/extended_oos_predictions_bigmove.parquet")
    output.to_parquet(output_path, index=False)
    
    print(f"\n✅ Saved {len(output):,} predictions to {output_path}")
    print(f"Date range: {output['ts'].min()} to {output['ts'].max()}")
    print(f"Trading days: {pd.to_datetime(output['ts']).dt.date.nunique()}")

if __name__ == "__main__":
    main()
