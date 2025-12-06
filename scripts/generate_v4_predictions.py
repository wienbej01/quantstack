#!/usr/bin/env python3
"""Generate v4 predictions with high selectivity (prob ≥ 0.75)."""

import logging
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd

from extensions.intraday_ml_models.bigmove_training_utils import (
    prepare_feature_matrix,
    select_feature_columns,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
LOGGER = logging.getLogger(__name__)


def load_model(model_path: Path) -> lgb.Booster:
    """Load LightGBM model."""
    if not model_path.exists():
        raise FileNotFoundError(f"Model not found: {model_path}")
    return lgb.Booster(model_file=str(model_path))


def generate_predictions(
    dataset: pd.DataFrame,
    model_long: lgb.Booster,
    model_short: lgb.Booster,
    feature_columns: list[str],
    prob_threshold: float = 0.75,
    volume_momentum_threshold: float = 0.15,
) -> pd.DataFrame:
    """Generate predictions with high selectivity."""

    # Prepare features
    features = prepare_feature_matrix(dataset, feature_columns)

    # Get predictions
    prob_long = model_long.predict(features)
    prob_short = model_short.predict(features)

    # Initialize as NEUTRAL
    predictions = np.zeros(len(dataset), dtype=int)

    # Check volume momentum if available
    has_volume_momentum = "volume_momentum" in dataset.columns
    if has_volume_momentum:
        volume_momentum = dataset["volume_momentum"].values
    else:
        LOGGER.warning("volume_momentum not found, skipping volume filter")
        volume_momentum = np.ones(len(dataset))  # Pass all

    # LONG: prob_long ≥ threshold AND volume_momentum ≥ threshold
    long_mask = (prob_long >= prob_threshold) & (
        volume_momentum >= volume_momentum_threshold
    )
    predictions[long_mask] = 1

    # SHORT: prob_short ≥ threshold AND volume_momentum ≥ threshold
    short_mask = (prob_short >= prob_threshold) & (
        volume_momentum >= volume_momentum_threshold
    )
    predictions[short_mask] = -1

    # If both LONG and SHORT, take higher probability
    both_mask = long_mask & short_mask
    if both_mask.any():
        LOGGER.info("Resolving %d conflicts (both LONG and SHORT)", both_mask.sum())
        predictions[both_mask] = np.where(
            prob_long[both_mask] > prob_short[both_mask], 1, -1
        )

    # Create output DataFrame
    result = dataset[["symbol", "ts"]].copy()
    result["prediction"] = predictions
    result["prob_long"] = prob_long
    result["prob_short"] = prob_short
    result["prob_max"] = np.maximum(prob_long, prob_short)

    if has_volume_momentum:
        result["volume_momentum"] = volume_momentum

    return result


def main():
    # Paths
    training_data_path = Path(
        "artefacts/extensions/intraday_ml/phaseA_full_sip_v2/training_data.parquet"
    )
    model_dir = Path("artefacts/extensions/intraday_ml/v4_smb")
    output_path = Path("artefacts/extensions/intraday_ml/v4_smb/predictions.parquet")

    # Selectivity parameters
    prob_threshold = 0.75
    volume_momentum_threshold = 0.15

    LOGGER.info("=" * 80)
    LOGGER.info("Generating v4 SMB Predictions")
    LOGGER.info("=" * 80)
    LOGGER.info("Probability threshold: %.2f", prob_threshold)
    LOGGER.info("Volume momentum threshold: %.2f", volume_momentum_threshold)
    LOGGER.info("")

    # Load models
    LOGGER.info("Loading models...")
    model_long_path = model_dir / "model_long" / "model.txt"
    model_short_path = model_dir / "model_short" / "model.txt"

    model_long = load_model(model_long_path)
    model_short = load_model(model_short_path)
    LOGGER.info("Models loaded successfully")

    # Load training data (for OOS prediction)
    LOGGER.info("Loading data from: %s", training_data_path)
    dataset = pd.read_parquet(training_data_path)
    LOGGER.info("Loaded %d rows", len(dataset))

    # Get feature columns
    feature_columns = select_feature_columns(dataset)
    LOGGER.info("Using %d features", len(feature_columns))

    # Generate predictions
    LOGGER.info("Generating predictions...")
    predictions = generate_predictions(
        dataset=dataset,
        model_long=model_long,
        model_short=model_short,
        feature_columns=feature_columns,
        prob_threshold=prob_threshold,
        volume_momentum_threshold=volume_momentum_threshold,
    )

    # Statistics
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Prediction Distribution")
    LOGGER.info("=" * 80)

    pred_counts = predictions["prediction"].value_counts().sort_index()
    total = len(predictions)

    for pred, count in pred_counts.items():
        pct = 100 * count / total
        label = {-1: "SHORT", 0: "NEUTRAL", 1: "LONG"}.get(pred, "UNKNOWN")
        LOGGER.info("%8s: %7d (%.2f%%)", label, count, pct)

    LOGGER.info("")
    LOGGER.info(
        "Selectivity: %.2f%% (LONG + SHORT)",
        100 * (pred_counts.get(1, 0) + pred_counts.get(-1, 0)) / total,
    )

    # Save predictions
    output_path.parent.mkdir(parents=True, exist_ok=True)
    predictions.to_parquet(output_path, index=False)
    LOGGER.info("")
    LOGGER.info("Predictions saved to: %s", output_path)
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
