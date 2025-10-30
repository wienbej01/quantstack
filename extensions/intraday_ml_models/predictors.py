"""ML model inference utilities for intraday trading."""

from typing import Any, Dict, List, Optional, Union

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator

from .registry import MLModelRegistry
from .schemas import ModelMetadata, PredictionResult


class MLPredictor:
    """Predictor for ML models with feature validation and inference."""

    def __init__(self, registry: Optional[MLModelRegistry] = None):
        """Initialize predictor.

        Args:
            registry: Model registry instance (creates default if None)
        """
        self.registry = registry or MLModelRegistry()
        self._loaded_models: Dict[str, BaseEstimator] = {}

    def load_model(self, model_id: str, force_reload: bool = False) -> BaseEstimator:
        """Load model for inference with caching.

        Args:
            model_id: ID of model to load
            force_reload: Whether to force reload even if cached

        Returns:
            Loaded sklearn model
        """
        if force_reload or model_id not in self._loaded_models:
            self._loaded_models[model_id] = self.registry.load_model(model_id)

        return self._loaded_models[model_id]

    def predict(
        self,
        model_id: str,
        features: pd.DataFrame,
        timestamps: Optional[pd.Series] = None,
        symbols: Optional[pd.Series] = None,
        return_probabilities: bool = False,
    ) -> List[PredictionResult]:
        """Make predictions using loaded model.

        Args:
            model_id: ID of model to use
            features: DataFrame of features for prediction
            timestamps: Series of timestamps (uses index if None)
            symbols: Series of symbols (uses index if None)
            return_probabilities: Whether to return prediction probabilities

        Returns:
            List of prediction results
        """
        # Load model and metadata
        model = self.load_model(model_id)
        metadata = self.registry.get_metadata(model_id)

        # Validate features
        self._validate_features(features, metadata.features)

        # Prepare prediction data
        X = features[metadata.features].copy()

        # Apply scaling if model has scaler
        if hasattr(model, "scaler"):
            X = pd.DataFrame(
                model.scaler.transform(X), index=X.index, columns=X.columns
            )

        # Make predictions
        predictions = model.predict(X)

        # Get probabilities if requested and available
        probabilities = None
        if return_probabilities and hasattr(model, "predict_proba"):
            probabilities = model.predict_proba(X)
            # Use max probability as confidence
            probabilities = np.max(probabilities, axis=1)
        elif return_probabilities and hasattr(model, "decision_function"):
            # For SVMs, use decision function as confidence score
            probabilities = model.decision_function(X)
            if len(probabilities.shape) > 1:
                probabilities = np.max(probabilities, axis=1)

        # Prepare timestamps and symbols
        if timestamps is None:
            timestamps = pd.Series(X.index, index=X.index)
        if symbols is None:
            symbols = pd.Series(["UNKNOWN"] * len(X), index=X.index)

        # Create prediction results
        results = []
        for i, idx in enumerate(X.index):
            feature_values = {
                feature: float(X.iloc[i][feature]) for feature in metadata.features
            }

            result = PredictionResult(
                model_id=model_id,
                timestamp=int(timestamps.iloc[i]),
                symbol=str(symbols.iloc[i]),
                features_used=metadata.features.copy(),
                prediction=predictions[i],
                prediction_probability=(
                    float(probabilities[i]) if probabilities is not None else None
                ),
                feature_values=feature_values,
            )
            results.append(result)

        return results

    def predict_single(
        self,
        model_id: str,
        features: Dict[str, float],
        timestamp: int,
        symbol: str,
        return_probability: bool = False,
    ) -> PredictionResult:
        """Make prediction for a single observation.

        Args:
            model_id: ID of model to use
            features: Dictionary of feature values
            timestamp: Timestamp for prediction
            symbol: Symbol for prediction
            return_probability: Whether to return prediction probability

        Returns:
            Single prediction result
        """
        # Convert to DataFrame
        feature_df = pd.DataFrame([features])

        # Use batch prediction
        results = self.predict(
            model_id=model_id,
            features=feature_df,
            timestamps=pd.Series([timestamp]),
            symbols=pd.Series([symbol]),
            return_probabilities=return_probability,
        )

        return results[0]

    def _validate_features(
        self, features: pd.DataFrame, expected_features: List[str]
    ) -> None:
        """Validate that required features are present."""
        missing_features = [f for f in expected_features if f not in features.columns]
        if missing_features:
            raise ValueError(f"Missing required features: {missing_features}")

        # Check for NaN values
        feature_subset = features[expected_features]
        if feature_subset.isna().any().any():
            nan_cols = feature_subset.columns[feature_subset.isna().any()].tolist()
            raise ValueError(f"Features contain NaN values: {nan_cols}")

    def clear_cache(self) -> None:
        """Clear cached models."""
        self._loaded_models.clear()

    def get_loaded_models(self) -> List[str]:
        """Get list of currently loaded model IDs."""
        return list(self._loaded_models.keys())
