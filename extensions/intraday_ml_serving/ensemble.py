"""Ensemble model methods for improved prediction accuracy."""

import logging
import time
from typing import Dict, Any, List, Optional, Union, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import numpy as np
import pandas as pd

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


@dataclass
class EnsembleConfig:
    """Configuration for ensemble methods."""
    method: str = "voting"  # "voting", "stacking", "blending", "bagging"
    weights: Optional[List[float]] = None
    voting_strategy: str = "soft"  # "soft", "hard"
    stacking_model: Optional[str] = None  # model_id for meta-learner
    blending_ratio: float = 0.8  # train/validation split for blending
    cross_validation_folds: int = 5
    timeout_seconds: int = 30


@dataclass
class EnsemblePrediction:
    """Ensemble prediction result."""
    prediction: float
    confidence: float
    individual_predictions: List[float]
    individual_confidences: List[float]
    ensemble_method: str
    model_ids: List[str]
    prediction_time_ms: float
    consensus_score: Optional[float] = None
    variance: Optional[float] = None


class EnsembleModel:
    """Ensemble model for combining multiple ML models."""

    def __init__(
        self,
        model_ids: List[str],
        registry: Optional[MLModelRegistry] = None,
        config: Optional[EnsembleConfig] = None
    ):
        """
        Initialize ensemble model.

        Args:
            model_ids: List of model IDs to ensemble
            registry: Model registry instance
            config: Ensemble configuration
        """
        self.model_ids = model_ids
        self.registry = registry or MLModelRegistry()
        self.config = config or EnsembleConfig()
        self.predictors = {}
        self.logger = logging.getLogger(__name__)
        self._lock = threading.Lock()

        # Load predictors
        self._load_predictors()

    def _load_predictors(self):
        """Load all model predictors."""
        with self._lock:
            for model_id in self.model_ids:
                try:
                    predictor = MLPredictor(model_id, self.registry)
                    self.predictors[model_id] = predictor
                    self.logger.info(f"Loaded predictor for model: {model_id}")
                except Exception as e:
                    self.logger.error(f"Failed to load predictor for {model_id}: {e}")

    def predict(self, features: Dict[str, float]) -> EnsemblePrediction:
        """
        Make ensemble prediction.

        Args:
            features: Feature dictionary

        Returns:
            Ensemble prediction result
        """
        start_time = time.time()

        # Get individual predictions
        individual_results = self._get_individual_predictions(features)

        # Combine predictions using configured method
        if self.config.method == "voting":
            ensemble_result = self._voting_ensemble(individual_results)
        elif self.config.method == "stacking":
            ensemble_result = self._stacking_ensemble(features, individual_results)
        elif self.config.method == "blending":
            ensemble_result = self._blending_ensemble(features, individual_results)
        elif self.config.method == "bagging":
            ensemble_result = self._bagging_ensemble(individual_results)
        else:
            raise ValueError(f"Unknown ensemble method: {self.config.method}")

        prediction_time_ms = (time.time() - start_time) * 1000

        return EnsemblePrediction(
            prediction=ensemble_result["prediction"],
            confidence=ensemble_result["confidence"],
            individual_predictions=[r["prediction"] for r in individual_results],
            individual_confidences=[r["confidence"] for r in individual_results],
            ensemble_method=self.config.method,
            model_ids=list(individual_results.keys()),
            prediction_time_ms=prediction_time_ms,
            consensus_score=ensemble_result.get("consensus_score"),
            variance=ensemble_result.get("variance")
        )

    def _get_individual_predictions(self, features: Dict[str, float]) -> Dict[str, Dict[str, float]]:
        """Get predictions from all models."""
        results = {}

        with ThreadPoolExecutor(max_workers=len(self.predictors)) as executor:
            future_to_model = {
                executor.submit(self._predict_single, model_id, predictor, features): model_id
                for model_id, predictor in self.predictors.items()
            }

            for future in as_completed(future_to_model, timeout=self.config.timeout_seconds):
                model_id = future_to_model[future]
                try:
                    result = future.result()
                    results[model_id] = result
                except Exception as e:
                    self.logger.error(f"Prediction failed for model {model_id}: {e}")
                    # Use neutral values for failed predictions
                    results[model_id] = {"prediction": 0.0, "confidence": 0.0}

        return results

    def _predict_single(self, model_id: str, predictor: MLPredictor, features: Dict[str, float]) -> Dict[str, float]:
        """Get prediction from single model."""
        try:
            result = predictor.predict(features)
            return {
                "prediction": float(result.prediction),
                "confidence": float(result.prediction_probability) if hasattr(result, 'prediction_probability') else 0.5
            }
        except Exception as e:
            self.logger.error(f"Single prediction failed for {model_id}: {e}")
            raise

    def _voting_ensemble(self, individual_results: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Voting ensemble method."""
        predictions = [r["prediction"] for r in individual_results.values()]
        confidences = [r["confidence"] for r in individual_results.values()]

        if self.config.voting_strategy == "soft":
            # Weighted voting by confidence
            weights = self.config.weights or confidences
            weighted_prediction = np.average(predictions, weights=weights)
            avg_confidence = np.mean(confidences)
        else:
            # Hard voting (majority)
            positive_votes = sum(1 for p in predictions if p > 0)
            weighted_prediction = 1.0 if positive_votes > len(predictions) / 2 else -1.0
            avg_confidence = positive_votes / len(predictions)

        # Calculate consensus score
        consensus_score = 1.0 - np.std(predictions) / (np.mean(np.abs(predictions)) + 1e-8)
        variance = np.var(predictions)

        return {
            "prediction": weighted_prediction,
            "confidence": avg_confidence,
            "consensus_score": consensus_score,
            "variance": variance
        }

    def _stacking_ensemble(self, features: Dict[str, float], individual_results: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Stacking ensemble method."""
        if not self.config.stacking_model:
            # Fallback to voting if no stacking model specified
            return self._voting_ensemble(individual_results)

        try:
            # Create meta-features from individual predictions
            meta_features = {
                "original_" + k: v for k, v in features.items()
            }

            # Add individual predictions as features
            for model_id, result in individual_results.items():
                meta_features[f"pred_{model_id}"] = result["prediction"]
                meta_features[f"conf_{model_id}"] = result["confidence"]

            # Use stacking model for final prediction
            stacking_predictor = self.predictors.get(self.config.stacking_model)
            if stacking_predictor:
                stacking_result = stacking_predictor.predict(meta_features)
                return {
                    "prediction": float(stacking_result.prediction),
                    "confidence": float(stacking_result.prediction_probability) if hasattr(stacking_result, 'prediction_probability') else 0.5
                }
            else:
                self.logger.warning(f"Stacking model {self.config.stacking_model} not found, using voting")
                return self._voting_ensemble(individual_results)

        except Exception as e:
            self.logger.error(f"Stacking ensemble failed: {e}")
            return self._voting_ensemble(individual_results)

    def _blending_ensemble(self, features: Dict[str, float], individual_results: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Blending ensemble method."""
        predictions = [r["prediction"] for r in individual_results.values()]
        confidences = [r["confidence"] for r in individual_results.values()]

        # Simple weighted average with confidence weights
        weights = self.config.weights or confidences
        blended_prediction = np.average(predictions, weights=weights)
        blended_confidence = np.mean(confidences)

        return {
            "prediction": blended_prediction,
            "confidence": blended_confidence,
            "variance": np.var(predictions)
        }

    def _bagging_ensemble(self, individual_results: Dict[str, Dict[str, float]]) -> Dict[str, float]:
        """Bagging ensemble method (bootstrap aggregation)."""
        predictions = [r["prediction"] for r in individual_results.values()]
        confidences = [r["confidence"] for r in individual_results.values()]

        # Bootstrap sampling with replacement
        n_samples = len(predictions)
        bootstrapped_predictions = []

        for _ in range(100):  # 100 bootstrap samples
            sample_indices = np.random.choice(n_samples, n_samples, replace=True)
            sample_predictions = [predictions[i] for i in sample_indices]
            bootstrapped_predictions.append(np.mean(sample_predictions))

        bagged_prediction = np.mean(bootstrapped_predictions)
        bagged_confidence = 1.0 - np.std(bootstrapped_predictions) / (np.abs(bagged_prediction) + 1e-8)

        return {
            "prediction": bagged_prediction,
            "confidence": min(max(bagged_confidence, 0.0), 1.0),  # Clamp to [0,1]
            "variance": np.var(bootstrapped_predictions)
        }

    def evaluate_ensemble(self, test_features: List[Dict[str, float]], test_targets: List[float]) -> Dict[str, float]:
        """
        Evaluate ensemble performance.

        Args:
            test_features: List of test feature dictionaries
            test_targets: List of test target values

        Returns:
            Evaluation metrics
        """
        predictions = []
        confidences = []

        for features in test_features:
            result = self.predict(features)
            predictions.append(result.prediction)
            confidences.append(result.confidence)

        # Calculate metrics
        predictions = np.array(predictions)
        targets = np.array(test_targets)
        confidences = np.array(confidences)

        mse = np.mean((predictions - targets) ** 2)
        mae = np.mean(np.abs(predictions - targets))
        rmse = np.sqrt(mse)

        # Correlation
        correlation = np.corrcoef(predictions, targets)[0, 1] if len(predictions) > 1 else 0.0

        # Confidence calibration
        confidence_error = np.mean(np.abs(confidences - np.abs(predictions - targets)))

        return {
            "mse": float(mse),
            "mae": float(mae),
            "rmse": float(rmse),
            "correlation": float(correlation) if not np.isnan(correlation) else 0.0,
            "confidence_error": float(confidence_error),
            "avg_prediction_time_ms": np.mean([r.prediction_time_ms for r in [self.predict(f) for f in test_features[:10]]])
        }

    def update_config(self, new_config: EnsembleConfig):
        """Update ensemble configuration."""
        self.config = new_config
        self.logger.info(f"Updated ensemble config: method={new_config.method}")

    def add_model(self, model_id: str):
        """Add new model to ensemble."""
        if model_id not in self.model_ids:
            self.model_ids.append(model_id)
            try:
                predictor = MLPredictor(model_id, self.registry)
                self.predictors[model_id] = predictor
                self.logger.info(f"Added model to ensemble: {model_id}")
            except Exception as e:
                self.logger.error(f"Failed to add model {model_id}: {e}")
                self.model_ids.remove(model_id)

    def remove_model(self, model_id: str):
        """Remove model from ensemble."""
        if model_id in self.model_ids:
            self.model_ids.remove(model_id)
            self.predictors.pop(model_id, None)
            self.logger.info(f"Removed model from ensemble: {model_id}")

    def get_model_weights(self) -> Dict[str, float]:
        """Get current model weights."""
        if self.config.weights:
            return dict(zip(self.model_ids, self.config.weights))
        else:
            # Equal weights if not specified
            equal_weight = 1.0 / len(self.model_ids)
            return {model_id: equal_weight for model_id in self.model_ids}