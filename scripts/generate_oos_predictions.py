#!/usr/bin/env python3
"""Generate OOS predictions using trained models."""

import json
import logging
from pathlib import Path

import joblib
import pandas as pd

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def main():
    output_root = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2")
    
    # Load OOS features
    oos_features_path = output_root / "oos_features.parquet"
    LOGGER.info("Loading OOS features from: %s", oos_features_path)
    oos_data = pd.read_parquet(oos_features_path)
    LOGGER.info("Loaded %d OOS samples", len(oos_data))
    
    # Load Stage 1 model
    stage1_model_path = output_root / "model.pkl"
    stage1_features_path = output_root / "features.json"
    
    LOGGER.info("Loading Stage 1 model...")
    stage1_model = joblib.load(stage1_model_path)
    with open(stage1_features_path) as f:
        stage1_features = json.load(f)
    
    # Prepare Stage 1 features
    X_stage1 = oos_data[stage1_features].fillna(0)
    
    # Stage 1 predictions
    LOGGER.info("Generating Stage 1 predictions...")
    prob_bigmove = stage1_model.predict_proba(X_stage1)[:, 1]
    
    # Load Stage 2 model
    stage2_model_path = output_root / "bigmove_stage2_dir" / "model.pkl"
    stage2_features_path = output_root / "bigmove_stage2_dir" / "features.json"
    
    LOGGER.info("Loading Stage 2 model...")
    stage2_model = joblib.load(stage2_model_path)
    with open(stage2_features_path) as f:
        stage2_features = json.load(f)
    
    # Prepare Stage 2 features
    X_stage2 = oos_data[stage2_features].fillna(0)
    
    # Stage 2 predictions
    LOGGER.info("Generating Stage 2 predictions...")
    prob_long_given_bigmove = stage2_model.predict_proba(X_stage2)[:, 1]
    
    # Combine predictions
    prob_long = prob_bigmove * prob_long_given_bigmove
    prob_short = prob_bigmove * (1 - prob_long_given_bigmove)
    prob_neutral = 1 - prob_bigmove
    
    # Create predictions dataframe
    predictions = pd.DataFrame({
        "symbol": oos_data["symbol"],
        "ts": oos_data["ts"],
        "prob_bigmove": prob_bigmove,
        "prob_long_given_bigmove": prob_long_given_bigmove,
        "prob_1": prob_long,
        "prob_-1": prob_short,
        "prob_0": prob_neutral,
    })
    
    # Save predictions
    output_path = output_root / "oos_predictions_bigmove.parquet"
    predictions.to_parquet(output_path, index=False)
    LOGGER.info("Saved predictions to: %s", output_path)
    
    # Print distribution
    predictions["predicted_class"] = predictions[["prob_1", "prob_-1", "prob_0"]].idxmax(axis=1)
    dist = predictions["predicted_class"].value_counts(normalize=True) * 100
    
    LOGGER.info("Prediction Distribution:")
    for cls, pct in dist.items():
        count = (predictions["predicted_class"] == cls).sum()
        LOGGER.info("  %s: %6d (%.2f%%)", cls, count, pct)


if __name__ == "__main__":
    main()
