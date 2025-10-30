"""Ensemble ML policy combining multiple models.

This module provides an ensemble trading policy that combines predictions
from multiple ML models using various ensemble methods.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from statistics import mean, median
from typing import Any, Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd

from .base import (
    BaseMLPolicy,
    PolicyAction,
    PolicyDecision,
    PolicyMetrics,
    PolicySignal,
)


class EnsembleMethod(Enum):
    """Ensemble combination methods."""

    VOTING = "voting"
    WEIGHTED_AVERAGE = "weighted_average"
    STACKING = "stacking"
    DYNAMIC = "dynamic"
    PERFORMANCE_BASED = "performance_based"


@dataclass
class ModelConfig:
    """Configuration for individual models in ensemble."""

    model_id: str
    weight: float = 1.0
    enabled: bool = True
    min_confidence: float = 0.5
    performance_weight: float = 1.0
    specialty_tags: List[str] = field(default_factory=list)
    last_updated: Optional[datetime] = None


@dataclass
class EnsemblePrediction:
    """Prediction from ensemble of models."""

    final_prediction: float
    confidence: float
    individual_predictions: Dict[str, float]
    individual_confidences: Dict[str, float]
    ensemble_method: EnsembleMethod
    voting_breakdown: Dict[str, int] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)


class EnsemblePolicy(BaseMLPolicy):
    """Ensemble ML trading policy combining multiple models.

    Combines predictions from multiple ML models using various ensemble methods
    and dynamically adjusts model weights based on performance.
    """

    def __init__(
        self,
        model_ids: List[str],
        registry=None,
        feature_pipeline=None,
        config: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize ensemble ML policy.

        Args:
            model_ids: List of model IDs to include in ensemble
            registry: Optional model registry
            feature_pipeline: Optional feature pipeline
            config: Policy configuration parameters
        """
        # Initialize with first model as primary
        primary_model_id = model_ids[0] if model_ids else "default"
        super().__init__(primary_model_id, registry, feature_pipeline, config)

        # Ensemble configuration
        self.model_ids = model_ids
        self.ensemble_method = EnsembleMethod(
            self.config.get("ensemble_method", "weighted_average")
        )
        self.consensus_threshold = self.config.get("consensus_threshold", 0.6)
        self.diversification_bonus = self.config.get("diversification_bonus", 0.1)

        # Model configurations
        self.model_configs: Dict[str, ModelConfig] = {}
        for model_id in model_ids:
            self.model_configs[model_id] = ModelConfig(
                model_id=model_id,
                weight=1.0 / len(model_ids),  # Equal weights initially
            )

        # Individual model predictors
        self.predictors: Dict[str, Any] = {}
        for model_id in model_ids:
            try:
                self.predictors[model_id] = type(self.predictor)(self.registry)
            except Exception as e:
                self.logger.warning(
                    f"Failed to initialize predictor for {model_id}: {e}"
                )

        # Performance tracking for individual models
        self.model_performance: Dict[str, Dict[str, float]] = defaultdict(
            lambda: {
                "accuracy": 0.5,
                "confidence": 0.5,
                "prediction_count": 0,
                "success_count": 0,
                "last_updated": None,
            }
        )

        # Ensemble performance tracking
        self.ensemble_metrics = {
            "total_predictions": 0,
            "successful_predictions": 0,
            "accuracy": 0.0,
            "avg_confidence": 0.0,
            "diversity_score": 0.0,
            "consensus_rate": 0.0,
        }

        # Dynamic adaptation parameters
        self.performance_window = self.config.get("performance_window", 100)
        self.weight_learning_rate = self.config.get("weight_learning_rate", 0.01)
        self.enable_dynamic_weights = self.config.get("enable_dynamic_weights", True)

        self.logger = logging.getLogger(__name__)

    def generate_signal(
        self,
        features: Dict[str, float],
        current_position: float,
        market_data: pd.DataFrame,
    ) -> PolicySignal:
        """
        Generate ensemble trading signal from multiple models.

        Args:
            features: Feature dictionary
            current_position: Current position size
            market_data: Market data DataFrame

        Returns:
            Ensemble trading signal
        """
        try:
            # Get predictions from all models
            ensemble_prediction = self.get_ensemble_prediction(features)

            if not ensemble_prediction:
                return PolicySignal.NEUTRAL

            # Convert ensemble prediction to signal
            signal = self._prediction_to_signal(ensemble_prediction.final_prediction)

            # Update ensemble metrics
            self._update_ensemble_metrics(ensemble_prediction)

            return signal

        except Exception as e:
            self.logger.error(f"Error generating ensemble signal: {e}")
            return PolicySignal.NEUTRAL

    def calculate_position_size(
        self,
        signal: PolicySignal,
        confidence: float,
        volatility: float,
        account_value: float,
    ) -> float:
        """
        Calculate position size with ensemble confidence adjustments.

        Args:
            signal: Trading signal
            confidence: Signal confidence
            volatility: Market volatility
            account_value: Total account value

        Returns:
            Ensemble-adjusted position size
        """
        # Get base position size
        base_position_size = super().calculate_position_size(
            signal, confidence, volatility, account_value
        )

        # Adjust based on ensemble consensus
        consensus_multiplier = 1.0
        if self.ensemble_metrics["consensus_rate"] < self.consensus_threshold:
            consensus_multiplier = 0.7  # Reduce size when models disagree

        # Adjust based on model diversity
        diversity_multiplier = (
            1.0 + self.diversification_bonus * self.ensemble_metrics["diversity_score"]
        )

        # Adjust based on ensemble accuracy
        accuracy_multiplier = 0.5 + 0.5 * self.ensemble_metrics["accuracy"]

        return (
            base_position_size
            * consensus_multiplier
            * diversity_multiplier
            * accuracy_multiplier
        )

    def get_ensemble_prediction(
        self, features: Dict[str, float]
    ) -> Optional[EnsemblePrediction]:
        """
        Get ensemble prediction from all models.

        Args:
            features: Feature dictionary

        Returns:
            Ensemble prediction or None if no models available
        """
        if not self.predictors:
            return None

        individual_predictions = {}
        individual_confidences = {}

        # Get predictions from all enabled models
        for model_id, predictor in self.predictors.items():
            model_config = self.model_configs.get(model_id)
            if not model_config or not model_config.enabled:
                continue

            try:
                # Get prediction from model
                features_df = pd.DataFrame([features])
                results = predictor.predict(
                    model_id, features_df, return_probabilities=True
                )

                if results and len(results) > 0:
                    result = results[0]
                    prediction = (
                        float(result.prediction[0]) if result.prediction else 0.0
                    )
                    confidence = (
                        float(result.prediction_probability[0])
                        if result.prediction_probability
                        and len(result.prediction_probability) > 0
                        else 0.5
                    )

                    # Filter by minimum confidence
                    if confidence >= model_config.min_confidence:
                        individual_predictions[model_id] = prediction
                        individual_confidences[model_id] = confidence

            except Exception as e:
                self.logger.warning(f"Error getting prediction from {model_id}: {e}")

        if not individual_predictions:
            return None

        # Combine predictions based on ensemble method
        if self.ensemble_method == EnsembleMethod.VOTING:
            final_prediction, confidence, voting_breakdown = self._voting_ensemble(
                individual_predictions, individual_confidences
            )
        elif self.ensemble_method == EnsembleMethod.WEIGHTED_AVERAGE:
            final_prediction, confidence = self._weighted_average_ensemble(
                individual_predictions, individual_confidences
            )
            voting_breakdown = {}
        elif self.ensemble_method == EnsembleMethod.STACKING:
            final_prediction, confidence = self._stacking_ensemble(
                individual_predictions, individual_confidences, features
            )
            voting_breakdown = {}
        elif self.ensemble_method == EnsembleMethod.DYNAMIC:
            final_prediction, confidence = self._dynamic_ensemble(
                individual_predictions, individual_confidences, features
            )
            voting_breakdown = {}
        else:  # PERFORMANCE_BASED
            final_prediction, confidence = self._performance_based_ensemble(
                individual_predictions, individual_confidences
            )
            voting_breakdown = {}

        return EnsemblePrediction(
            final_prediction=final_prediction,
            confidence=confidence,
            individual_predictions=individual_predictions,
            individual_confidences=individual_confidences,
            ensemble_method=self.ensemble_method,
            voting_breakdown=voting_breakdown,
            metadata={
                "model_count": len(individual_predictions),
                "prediction_variance": np.var(list(individual_predictions.values())),
                "agreement_score": self._calculate_agreement_score(
                    individual_predictions
                ),
            },
        )

    def update_model_performance(
        self, model_id: str, actual_outcome: float, predicted: float
    ) -> None:
        """
        Update performance tracking for individual model.

        Args:
            model_id: Model identifier
            actual_outcome: Actual outcome
            predicted: Predicted outcome
        """
        if model_id not in self.model_performance:
            return

        perf = self.model_performance[model_id]

        # Update prediction count
        perf["prediction_count"] += 1

        # Update success based on direction accuracy
        if (actual_outcome > 0 and predicted > 0) or (
            actual_outcome < 0 and predicted < 0
        ):
            perf["success_count"] += 1

        # Update accuracy
        if perf["prediction_count"] > 0:
            perf["accuracy"] = perf["success_count"] / perf["prediction_count"]

        perf["last_updated"] = datetime.now()

        # Update model weights if dynamic weighting is enabled
        if self.enable_dynamic_weights:
            self._update_model_weights()

    def get_model_performance(self) -> Dict[str, Dict[str, float]]:
        """Get performance metrics for all models."""
        return dict(self.model_performance)

    def update_model_config(self, model_id: str, config: Dict[str, Any]) -> None:
        """Update configuration for a specific model."""
        if model_id in self.model_configs:
            model_config = self.model_configs[model_id]
            for key, value in config.items():
                if hasattr(model_config, key):
                    setattr(model_config, key, value)
            self.logger.info(f"Updated config for model {model_id}")

    def _voting_ensemble(
        self, predictions: Dict[str, float], confidences: Dict[str, float]
    ) -> Tuple[float, float, Dict[str, int]]:
        """Combine predictions using majority voting."""
        # Convert predictions to votes (buy/sell/hold)
        votes = {"buy": 0, "sell": 0, "hold": 0}
        weighted_votes = {"buy": 0.0, "sell": 0.0, "hold": 0.0}

        for model_id, prediction in predictions.items():
            confidence = confidences.get(model_id, 0.5)
            weight = self.model_configs[model_id].weight

            if prediction > 0.1:
                votes["buy"] += 1
                weighted_votes["buy"] += confidence * weight
            elif prediction < -0.1:
                votes["sell"] += 1
                weighted_votes["sell"] += confidence * weight
            else:
                votes["hold"] += 1
                weighted_votes["hold"] += confidence * weight

        # Determine winner
        max_votes = max(votes.values())
        winners = [k for k, v in votes.items() if v == max_votes]

        # Use weighted votes to break ties
        if len(winners) == 1:
            winner = winners[0]
        else:
            winner = max(weighted_votes, key=weighted_votes.get)

        # Convert to numeric prediction
        if winner == "buy":
            final_prediction = max(predictions.values())
        elif winner == "sell":
            final_prediction = min(predictions.values())
        else:
            final_prediction = 0.0

        # Calculate confidence based on vote distribution
        total_votes = sum(votes.values())
        confidence = max(votes.values()) / total_votes if total_votes > 0 else 0.5

        return final_prediction, confidence, votes

    def _weighted_average_ensemble(
        self, predictions: Dict[str, float], confidences: Dict[str, float]
    ) -> Tuple[float, float]:
        """Combine predictions using weighted average."""
        weighted_sum = 0.0
        weight_sum = 0.0
        confidence_sum = 0.0

        for model_id, prediction in predictions.items():
            confidence = confidences.get(model_id, 0.5)
            weight = self.model_configs[model_id].weight

            # Weight by both model weight and confidence
            combined_weight = weight * confidence
            weighted_sum += prediction * combined_weight
            weight_sum += combined_weight
            confidence_sum += confidence

        final_prediction = weighted_sum / weight_sum if weight_sum > 0 else 0.0
        avg_confidence = confidence_sum / len(predictions) if predictions else 0.5

        return final_prediction, avg_confidence

    def _stacking_ensemble(
        self,
        predictions: Dict[str, float],
        confidences: Dict[str, float],
        features: Dict[str, float],
    ) -> Tuple[float, float]:
        """Combine predictions using stacking (meta-learner)."""
        # This is a simplified stacking implementation
        # In practice, this would use a trained meta-learner

        # For now, fall back to weighted average
        return self._weighted_average_ensemble(predictions, confidences)

    def _dynamic_ensemble(
        self,
        predictions: Dict[str, float],
        confidences: Dict[str, float],
        features: Dict[str, float],
    ) -> Tuple[float, float]:
        """Combine predictions using dynamic method selection."""
        # Choose ensemble method based on current conditions
        prediction_variance = np.var(list(predictions.values()))
        agreement_score = self._calculate_agreement_score(predictions)

        if agreement_score > 0.8:  # High agreement
            # Use simple average
            return np.mean(list(predictions.values())), np.mean(
                list(confidences.values())
            )
        elif prediction_variance > 0.5:  # High disagreement
            # Use voting to be more conservative
            final_pred, conf, _ = self._voting_ensemble(predictions, confidences)
            return final_pred, conf
        else:  # Moderate disagreement
            # Use weighted average
            return self._weighted_average_ensemble(predictions, confidences)

    def _performance_based_ensemble(
        self, predictions: Dict[str, float], confidences: Dict[str, float]
    ) -> Tuple[float, float]:
        """Combine predictions weighted by recent performance."""
        weighted_sum = 0.0
        weight_sum = 0.0
        confidence_sum = 0.0

        for model_id, prediction in predictions.items():
            base_weight = self.model_configs[model_id].weight
            performance_weight = self.model_performance[model_id]["accuracy"]
            confidence = confidences.get(model_id, 0.5)

            # Combined weight: base * performance * confidence
            combined_weight = base_weight * performance_weight * confidence
            weighted_sum += prediction * combined_weight
            weight_sum += combined_weight
            confidence_sum += confidence

        final_prediction = weighted_sum / weight_sum if weight_sum > 0 else 0.0
        avg_confidence = confidence_sum / len(predictions) if predictions else 0.5

        return final_prediction, avg_confidence

    def _calculate_agreement_score(self, predictions: Dict[str, float]) -> float:
        """Calculate agreement score among predictions."""
        if len(predictions) <= 1:
            return 1.0

        pred_values = list(predictions.values())
        variance = np.var(pred_values)

        # Lower variance = higher agreement
        # Normalize to [0, 1] range
        agreement = max(0.0, 1.0 - variance / 4.0)  # Assuming predictions in [-1, 1]
        return agreement

    def _update_ensemble_metrics(self, ensemble_prediction: EnsemblePrediction) -> None:
        """Update ensemble performance metrics."""
        self.ensemble_metrics["total_predictions"] += 1

        # Update diversity score
        if len(ensemble_prediction.individual_predictions) > 1:
            pred_variance = ensemble_prediction.metadata.get("prediction_variance", 0.0)
            self.ensemble_metrics["diversity_score"] = min(1.0, pred_variance / 2.0)

        # Update consensus rate
        agreement_score = ensemble_prediction.metadata.get("agreement_score", 0.0)
        self.ensemble_metrics["consensus_rate"] = agreement_score

    def _update_model_weights(self) -> None:
        """Update model weights based on recent performance."""
        # Calculate performance-based weights
        total_performance = sum(
            self.model_performance[model_id]["accuracy"]
            for model_id in self.model_performance
        )

        if total_performance > 0:
            for model_id, config in self.model_configs.items():
                performance = self.model_performance[model_id]["accuracy"]
                target_weight = performance / total_performance

                # Smooth weight update
                new_weight = (
                    1 - self.weight_learning_rate
                ) * config.weight + self.weight_learning_rate * target_weight

                config.weight = max(
                    0.1, min(2.0, new_weight)
                )  # Keep weights reasonable

    def _prediction_to_signal(self, prediction: float) -> PolicySignal:
        """Convert numeric prediction to policy signal."""
        if prediction > 0.6:
            return PolicySignal.STRONG_BUY
        elif prediction > 0.2:
            return PolicySignal.BUY
        elif prediction > 0.05:
            return PolicySignal.WEAK_BUY
        elif prediction > -0.05:
            return PolicySignal.NEUTRAL
        elif prediction > -0.2:
            return PolicySignal.WEAK_SELL
        elif prediction > -0.6:
            return PolicySignal.SELL
        else:
            return PolicySignal.STRONG_SELL
