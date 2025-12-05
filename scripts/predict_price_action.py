#!/usr/bin/env python3
"""Generate predictions using price action models."""

import json
import logging
from pathlib import Path

import joblib
import pandas as pd

from extensions.intraday_ml.price_action_features import add_all_price_action_features

logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)


def main():
    output_root = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v3")
    
    # Load OOS features
    oos_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip_v2/oos_features.parquet")
    LOGGER.info("Loading OOS features...")
    oos_data = pd.read_parquet(oos_path)
    LOGGER.info("Loaded %d OOS samples", len(oos_data))
    
    # Add price action features
    LOGGER.info("Adding price action features...")
    oos_data = add_all_price_action_features(oos_data)
    
    # Load models
    LOGGER.info("Loading LONG model...")
    long_model = joblib.load(output_root / "model_long" / "model.pkl")
    with open(output_root / "model_long" / "features.json") as f:
        long_features = json.load(f)
    
    LOGGER.info("Loading SHORT model...")
    short_model = joblib.load(output_root / "model_short" / "model.pkl")
    with open(output_root / "model_short" / "features.json") as f:
        short_features = json.load(f)
    
    # Generate predictions
    LOGGER.info("Generating predictions...")
    X_long = oos_data[long_features].fillna(0)
    X_short = oos_data[short_features].fillna(0)
    
    prob_long = long_model.predict_proba(X_long)[:, 1]
    prob_short = short_model.predict_proba(X_short)[:, 1]
    prob_neutral = 1 - prob_long - prob_short
    prob_neutral = prob_neutral.clip(0, 1)
    
    # Normalize
    total = prob_long + prob_short + prob_neutral
    prob_long = prob_long / total
    prob_short = prob_short / total
    prob_neutral = prob_neutral / total
    
    predictions = pd.DataFrame({
        "symbol": oos_data["symbol"],
        "ts": oos_data["ts"],
        "prob_long": prob_long,
        "prob_short": prob_short,
        "prob_neutral": prob_neutral,
    })
    
    # Save
    pred_path = output_root / "oos_predictions.parquet"
    predictions.to_parquet(pred_path, index=False)
    LOGGER.info("Saved predictions to: %s", pred_path)
    
    # Analyze distribution
    LOGGER.info("\nPrediction Distribution:")
    LOGGER.info("  Mean prob_long:    %.4f", prob_long.mean())
    LOGGER.info("  Mean prob_short:   %.4f", prob_short.mean())
    LOGGER.info("  Mean prob_neutral: %.4f", prob_neutral.mean())
    
    # Test thresholds
    for thresh in [0.30, 0.35, 0.40, 0.45, 0.50]:
        n_long = (prob_long > thresh).sum()
        n_short = (prob_short > thresh).sum()
        n_neutral = len(predictions) - n_long - n_short
        
        LOGGER.info(f"\nThreshold {thresh:.2f}:")
        LOGGER.info(f"  LONG:    {n_long:5d} ({100*n_long/len(predictions):5.1f}%)")
        LOGGER.info(f"  SHORT:   {n_short:5d} ({100*n_short/len(predictions):5.1f}%)")
        LOGGER.info(f"  NEUTRAL: {n_neutral:5d} ({100*n_neutral/len(predictions):5.1f}%)")


if __name__ == "__main__":
    main()
