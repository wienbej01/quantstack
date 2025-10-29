"""ML-powered portfolio optimization for intraday trading."""

import logging
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import warnings
warnings.filterwarnings('ignore')

from extensions.intraday_ml_models.predictors import MLPredictor
from extensions.intraday_ml_models.registry import MLModelRegistry


class OptimizationMethod(Enum):
    """Portfolio optimization methods."""
    EQUAL_WEIGHT = "equal_weight"
    MEAN_VARIANCE = "mean_variance"
    RISK_PARITY = "risk_parity"
    HIERARCHICAL = "hierarchical"
    ML_ENHANCED = "ml_enhanced"


@dataclass
class PortfolioMetrics:
    """Portfolio performance metrics."""
    expected_return: float
    volatility: float
    sharpe_ratio: float
    max_drawdown: float
    var_95: float  # Value at Risk 95%
    diversification_ratio: float
    turnover: float = 0.0


@dataclass
class OptimizationResult:
    """Portfolio optimization result."""
    weights: Dict[str, float]
    expected_return: float
    volatility: float
    sharpe_ratio: float
    metrics: PortfolioMetrics
    optimization_method: OptimizationMethod
    constraints_satisfied: bool
    warnings: List[str] = field(default_factory=list)


class PortfolioOptimizer:
    """ML-powered portfolio optimizer for intraday trading."""

    def __init__(
        self,
        optimization_method: OptimizationMethod = OptimizationMethod.MEAN_VARIANCE,
        risk_free_rate: float = 0.02,
        max_weight: float = 0.3,
        min_weight: float = 0.0,
        ml_model_id: Optional[str] = None,
        registry: Optional[MLModelRegistry] = None
    ):
        """
        Initialize portfolio optimizer.

        Args:
            optimization_method: Optimization method to use
            risk_free_rate: Risk-free rate for Sharpe ratio calculation
            max_weight: Maximum weight for any single asset
            min_weight: Minimum weight for any asset
            ml_model_id: ML model ID for ML-enhanced optimization
            registry: Model registry instance
        """
        self.optimization_method = optimization_method
        self.risk_free_rate = risk_free_rate
        self.max_weight = max_weight
        self.min_weight = min_weight
        self.registry = registry or MLModelRegistry()
        self.logger = logging.getLogger(__name__)

        # Load ML model if specified
        self.ml_predictor = None
        if ml_model_id and optimization_method == OptimizationMethod.ML_ENHANCED:
            try:
                self.ml_predictor = MLPredictor(ml_model_id, self.registry)
                self.logger.info(f"Loaded ML model for portfolio optimization: {ml_model_id}")
            except Exception as e:
                self.logger.error(f"Failed to load ML model {ml_model_id}: {e}")

    def optimize_portfolio(
        self,
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame,
        current_weights: Optional[Dict[str, float]] = None,
        additional_features: Optional[Dict[str, Dict[str, float]]] = None
    ) -> OptimizationResult:
        """
        Optimize portfolio weights.

        Args:
            expected_returns: Expected returns for each asset
            covariance_matrix: Covariance matrix of returns
            current_weights: Current portfolio weights
            additional_features: Additional features for ML models

        Returns:
            Optimization result
        """
        assets = list(expected_returns.keys())

        if self.optimization_method == OptimizationMethod.EQUAL_WEIGHT:
            result = self._equal_weight_optimization(assets)
        elif self.optimization_method == OptimizationMethod.MEAN_VARIANCE:
            result = self._mean_variance_optimization(expected_returns, covariance_matrix, assets)
        elif self.optimization_method == OptimizationMethod.RISK_PARITY:
            result = self._risk_parity_optimization(covariance_matrix, assets)
        elif self.optimization_method == OptimizationMethod.HIERARCHICAL:
            result = self._hierarchical_optimization(expected_returns, covariance_matrix, assets)
        elif self.optimization_method == OptimizationMethod.ML_ENHANCED:
            result = self._ml_enhanced_optimization(
                expected_returns, covariance_matrix, assets, additional_features
            )
        else:
            raise ValueError(f"Unknown optimization method: {self.optimization_method}")

        # Calculate portfolio metrics
        metrics = self._calculate_portfolio_metrics(
            result.weights, expected_returns, covariance_matrix
        )

        # Calculate turnover if current weights provided
        if current_weights:
            turnover = self._calculate_turnover(current_weights, result.weights)
            metrics.turnover = turnover

        # Check constraints
        constraints_satisfied, warnings = self._check_constraints(result.weights, expected_returns)

        return OptimizationResult(
            weights=result.weights,
            expected_return=result.expected_return,
            volatility=result.volatility,
            sharpe_ratio=result.sharpe_ratio,
            metrics=metrics,
            optimization_method=self.optimization_method,
            constraints_satisfied=constraints_satisfied,
            warnings=warnings
        )

    def _equal_weight_optimization(self, assets: List[str]) -> OptimizationResult:
        """Equal weight portfolio optimization."""
        n_assets = len(assets)
        weight = 1.0 / n_assets
        weights = {asset: weight for asset in assets}

        # Simple metrics calculation
        expected_return = 0.1  # 10% annual return assumption
        volatility = 0.15  # 15% annual volatility assumption
        sharpe_ratio = (expected_return - self.risk_free_rate) / volatility

        return OptimizationResult(
            weights=weights,
            expected_return=expected_return,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            metrics=PortfolioMetrics(
                expected_return=expected_return,
                volatility=volatility,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=0.2,
                var_95=0.05,
                diversification_ratio=1.0
            ),
            optimization_method=self.optimization_method,
            constraints_satisfied=True
        )

    def _mean_variance_optimization(
        self,
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame,
        assets: List[str]
    ) -> OptimizationResult:
        """Mean-variance optimization (Markowitz)."""
        # Convert to numpy arrays
        mu = np.array([expected_returns[asset] for asset in assets])
        sigma = covariance_matrix.loc[assets, assets].values

        # Simple mean-variance optimization
        try:
            # Inverse of covariance matrix
            sigma_inv = np.linalg.inv(sigma)

            # Weights for maximum Sharpe ratio
            ones = np.ones((len(assets), 1))
            sigma_inv_ones = sigma_inv @ ones

            # Market portfolio weights
            weights_market = sigma_inv @ mu / (ones.T @ sigma_inv @ mu)

            # Normalize weights
            weights = weights_market.flatten()

            # Ensure weights are positive and within bounds
            weights = np.clip(weights, self.min_weight, self.max_weight)
            weights = weights / np.sum(weights)

            # Calculate metrics
            expected_return = np.dot(weights, mu)
            volatility = np.sqrt(np.dot(weights.T, np.dot(sigma, weights)))
            sharpe_ratio = (expected_return - self.risk_free_rate) / volatility if volatility > 0 else 0

            weights_dict = {asset: float(weight) for asset, weight in zip(assets, weights)}

            return OptimizationResult(
                weights=weights_dict,
                expected_return=float(expected_return),
                volatility=float(volatility),
                sharpe_ratio=float(sharpe_ratio),
                metrics=PortfolioMetrics(
                    expected_return=float(expected_return),
                    volatility=float(volatility),
                    sharpe_ratio=float(sharpe_ratio),
                    max_drawdown=0.2,
                    var_95=0.05,
                    diversification_ratio=1.0
                ),
                optimization_method=self.optimization_method,
                constraints_satisfied=True
            )

        except Exception as e:
            self.logger.error(f"Mean-variance optimization failed: {e}")
            return self._equal_weight_optimization(assets)

    def _risk_parity_optimization(
        self,
        covariance_matrix: pd.DataFrame,
        assets: List[str]
    ) -> OptimizationResult:
        """Risk parity optimization."""
        try:
            sigma = covariance_matrix.loc[assets, assets].values

            # Simple risk parity: equal risk contribution
            # Start with equal weights and iterate
            weights = np.ones(len(assets)) / len(assets)

            for _ in range(100):  # Simple iteration
                # Calculate marginal risk contributions
                portfolio_vol = np.sqrt(np.dot(weights.T, np.dot(sigma, weights)))
                marginal_contrib = np.dot(sigma, weights) / portfolio_vol
                contrib = weights * marginal_contrib

                # Update weights to equalize contributions
                target_contrib = np.mean(contrib)
                weights = weights * target_contrib / contrib
                weights = np.clip(weights, self.min_weight, self.max_weight)
                weights = weights / np.sum(weights)

            # Calculate metrics
            expected_return = 0.08  # Assume 8% return
            volatility = np.sqrt(np.dot(weights.T, np.dot(sigma, weights)))
            sharpe_ratio = (expected_return - self.risk_free_rate) / volatility

            weights_dict = {asset: float(weight) for asset, weight in zip(assets, weights)}

            return OptimizationResult(
                weights=weights_dict,
                expected_return=float(expected_return),
                volatility=float(volatility),
                sharpe_ratio=float(sharpe_ratio),
                metrics=PortfolioMetrics(
                    expected_return=float(expected_return),
                    volatility=float(volatility),
                    sharpe_ratio=float(sharpe_ratio),
                    max_drawdown=0.15,
                    var_95=0.04,
                    diversification_ratio=1.2
                ),
                optimization_method=self.optimization_method,
                constraints_satisfied=True
            )

        except Exception as e:
            self.logger.error(f"Risk parity optimization failed: {e}")
            return self._equal_weight_optimization(assets)

    def _hierarchical_optimization(
        self,
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame,
        assets: List[str]
    ) -> OptimizationResult:
        """Hierarchical risk parity optimization."""
        # Simplified HRP implementation
        try:
            # Calculate distance matrix based on correlation
            correlation = covariance_matrix.corr()
            distance = np.sqrt(0.5 * (1 - correlation))

            # Simple hierarchical clustering
            np.fill_diagonal(distance.values, 0)
            linkage = self._simple_linkage(distance.values)

            # Recursive bisection
            weights = self._recursive_bisection(expected_returns, covariance_matrix, linkage, assets)

            # Calculate metrics
            mu = np.array([expected_returns[asset] for asset in assets])
            sigma = covariance_matrix.loc[assets, assets].values
            expected_return = np.dot(list(weights.values()), mu)
            volatility = np.sqrt(np.dot(list(weights.values()), np.dot(sigma, list(weights.values()))))
            sharpe_ratio = (expected_return - self.risk_free_rate) / volatility

            return OptimizationResult(
                weights=weights,
                expected_return=float(expected_return),
                volatility=float(volatility),
                sharpe_ratio=float(sharpe_ratio),
                metrics=PortfolioMetrics(
                    expected_return=float(expected_return),
                    volatility=float(volatility),
                    sharpe_ratio=float(sharpe_ratio),
                    max_drawdown=0.18,
                    var_95=0.045,
                    diversification_ratio=1.3
                ),
                optimization_method=self.optimization_method,
                constraints_satisfied=True
            )

        except Exception as e:
            self.logger.error(f"Hierarchical optimization failed: {e}")
            return self._equal_weight_optimization(assets)

    def _ml_enhanced_optimization(
        self,
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame,
        assets: List[str],
        additional_features: Optional[Dict[str, Dict[str, float]]] = None
    ) -> OptimizationResult:
        """ML-enhanced portfolio optimization."""
        if not self.ml_predictor:
            self.logger.warning("ML model not available, falling back to mean-variance")
            return self._mean_variance_optimization(expected_returns, covariance_matrix, assets)

        try:
            # Get ML predictions for each asset
            ml_weights = {}
            for asset in assets:
                features = {
                    "expected_return": expected_returns[asset],
                    "volatility": np.sqrt(covariance_matrix.loc[asset, asset]),
                    "market_beta": additional_features.get(asset, {}).get("market_beta", 1.0),
                    "momentum": additional_features.get(asset, {}).get("momentum", 0.0),
                    "volume_ratio": additional_features.get(asset, {}).get("volume_ratio", 1.0),
                    "liquidity_score": additional_features.get(asset, {}).get("liquidity_score", 0.5)
                }

                result = self.ml_predictor.predict(features)
                ml_weights[asset] = float(result.prediction)

            # Normalize ML weights
            ml_weight_sum = sum(abs(w) for w in ml_weights.values())
            if ml_weight_sum > 0:
                ml_weights = {k: abs(v) / ml_weight_sum for k, v in ml_weights.items()}

            # Blend with traditional mean-variance
            mv_result = self._mean_variance_optimization(expected_returns, covariance_matrix, assets)
            blend_factor = 0.6  # 60% ML, 40% traditional

            final_weights = {}
            for asset in assets:
                final_weights[asset] = (
                    blend_factor * ml_weights.get(asset, 0) +
                    (1 - blend_factor) * mv_result.weights.get(asset, 0)
                )

            # Normalize final weights
            total_weight = sum(final_weights.values())
            if total_weight > 0:
                final_weights = {k: v / total_weight for k, v in final_weights.items()}

            # Apply bounds
            final_weights = {k: min(max(v, self.min_weight), self.max_weight) for k, v in final_weights.items()}
            total_weight = sum(final_weights.values())
            final_weights = {k: v / total_weight for k, v in final_weights.items()}

            # Calculate metrics
            mu = np.array([expected_returns[asset] for asset in assets])
            sigma = covariance_matrix.loc[assets, assets].values
            weights_array = np.array([final_weights[asset] for asset in assets])
            expected_return = np.dot(weights_array, mu)
            volatility = np.sqrt(np.dot(weights_array.T, np.dot(sigma, weights_array)))
            sharpe_ratio = (expected_return - self.risk_free_rate) / volatility

            return OptimizationResult(
                weights=final_weights,
                expected_return=float(expected_return),
                volatility=float(volatility),
                sharpe_ratio=float(sharpe_ratio),
                metrics=PortfolioMetrics(
                    expected_return=float(expected_return),
                    volatility=float(volatility),
                    sharpe_ratio=float(sharpe_ratio),
                    max_drawdown=0.16,
                    var_95=0.042,
                    diversification_ratio=1.25
                ),
                optimization_method=self.optimization_method,
                constraints_satisfied=True
            )

        except Exception as e:
            self.logger.error(f"ML-enhanced optimization failed: {e}")
            return self._mean_variance_optimization(expected_returns, covariance_matrix, assets)

    def _simple_linkage(self, distance_matrix: np.ndarray) -> np.ndarray:
        """Simple hierarchical linkage clustering."""
        n = distance_matrix.shape[0]
        linkage = []
        clusters = [[i] for i in range(n)]

        while len(clusters) > 1:
            # Find closest clusters
            min_dist = float('inf')
            merge_i, merge_j = -1, -1

            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    # Calculate distance between clusters
                    cluster_i = clusters[i]
                    cluster_j = clusters[j]
                    dist = np.mean([distance_matrix[a, b] for a in cluster_i for b in cluster_j])

                    if dist < min_dist:
                        min_dist = dist
                        merge_i, merge_j = i, j

            # Merge clusters
            new_cluster = clusters[merge_i] + clusters[merge_j]
            clusters = [c for idx, c in enumerate(clusters) if idx not in [merge_i, merge_j]]
            clusters.append(new_cluster)
            linkage.append([merge_i, merge_j, min_dist, len(new_cluster)])

        return np.array(linkage)

    def _recursive_bisection(
        self,
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame,
        linkage: np.ndarray,
        assets: List[str]
    ) -> Dict[str, float]:
        """Recursive bisection for HRP."""
        if len(assets) == 1:
            return {assets[0]: 1.0}

        # Simple implementation - return equal weights
        n_assets = len(assets)
        weight = 1.0 / n_assets
        return {asset: weight for asset in assets}

    def _calculate_portfolio_metrics(
        self,
        weights: Dict[str, float],
        expected_returns: Dict[str, float],
        covariance_matrix: pd.DataFrame
    ) -> PortfolioMetrics:
        """Calculate portfolio metrics."""
        assets = list(weights.keys())
        weights_array = np.array([weights[asset] for asset in assets])
        returns_array = np.array([expected_returns[asset] for asset in assets])
        cov_matrix = covariance_matrix.loc[assets, assets].values

        # Expected return and volatility
        expected_return = np.dot(weights_array, returns_array)
        volatility = np.sqrt(np.dot(weights_array.T, np.dot(cov_matrix, weights_array)))

        # Sharpe ratio
        sharpe_ratio = (expected_return - self.risk_free_rate) / volatility if volatility > 0 else 0

        # Simplified metrics
        max_drawdown = 0.2  # Assumed
        var_95 = volatility * 1.65  # 95% VaR
        diversification_ratio = 1.0 / (np.sum(weights_array ** 2))  # Inverse Herfindahl index

        return PortfolioMetrics(
            expected_return=float(expected_return),
            volatility=float(volatility),
            sharpe_ratio=float(sharpe_ratio),
            max_drawdown=max_drawdown,
            var_95=float(var_95),
            diversification_ratio=float(diversification_ratio)
        )

    def _calculate_turnover(self, current_weights: Dict[str, float], new_weights: Dict[str, float]) -> float:
        """Calculate portfolio turnover."""
        all_assets = set(current_weights.keys()) | set(new_weights.keys())
        turnover = 0.0

        for asset in all_assets:
            current_weight = current_weights.get(asset, 0.0)
            new_weight = new_weights.get(asset, 0.0)
            turnover += abs(new_weight - current_weight)

        return turnover / 2.0  # Divide by 2 for standard turnover definition

    def _check_constraints(self, weights: Dict[str, float], expected_returns: Dict[str, float]) -> Tuple[bool, List[str]]:
        """Check portfolio constraints."""
        warnings = []
        constraints_satisfied = True

        # Check weight bounds
        for asset, weight in weights.items():
            if weight < self.min_weight - 1e-6:
                warnings.append(f"Weight for {asset} ({weight:.3f}) below minimum ({self.min_weight})")
                constraints_satisfied = False
            if weight > self.max_weight + 1e-6:
                warnings.append(f"Weight for {asset} ({weight:.3f}) above maximum ({self.max_weight})")
                constraints_satisfied = False

        # Check sum of weights
        weight_sum = sum(weights.values())
        if abs(weight_sum - 1.0) > 1e-4:
            warnings.append(f"Weights sum to {weight_sum:.4f}, expected 1.0")
            constraints_satisfied = False

        # Check for concentrated positions
        max_concentration = max(weights.values())
        if max_concentration > 0.25:
            warnings.append(f"High concentration: {max_concentration:.1%} in single asset")

        return constraints_satisfied, warnings

    def update_optimization_method(self, new_method: OptimizationMethod, ml_model_id: Optional[str] = None):
        """Update optimization method."""
        self.optimization_method = new_method

        if new_method == OptimizationMethod.ML_ENHANCED and ml_model_id:
            try:
                self.ml_predictor = MLPredictor(ml_model_id, self.registry)
                self.logger.info(f"Updated ML model for optimization: {ml_model_id}")
            except Exception as e:
                self.logger.error(f"Failed to load new ML model {ml_model_id}: {e}")
                self.ml_predictor = None