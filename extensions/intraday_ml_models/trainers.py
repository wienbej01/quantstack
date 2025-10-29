"""ML model training utilities for intraday trading."""

import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, Type, Union

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.metrics import accuracy_score, mean_squared_error, r2_score
from sklearn.model_selection import GridSearchCV, TimeSeriesSplit
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC, SVR

from qx_core.hashers import hash_dataframe

from .registry import MLModelRegistry
from .schemas import ModelConfig, ModelMetadata, FeatureImportance, ModelType


class MLModelTrainer:
    """Trainer for ML models with reproducible workflow."""

    # Supported model classes
    MODEL_CLASSES = {
        "RandomForestClassifier": RandomForestClassifier,
        "RandomForestRegressor": RandomForestRegressor,
        "LogisticRegression": LogisticRegression,
        "LinearRegression": LinearRegression,
        "SVC": SVC,
        "SVR": SVR,
    }

    def __init__(self, registry: Optional[MLModelRegistry] = None):
        """Initialize trainer.

        Args:
            registry: Model registry instance (creates default if None)
        """
        self.registry = registry or MLModelRegistry()

    def prepare_training_data(
        self,
        bars: pd.DataFrame,
        config: ModelConfig,
        target_column: Optional[str] = None
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """Prepare training data with proper feature/target alignment.

        Args:
            bars: DataFrame with OHLCV and features
            config: Model configuration
            target_column: Override target column from config

        Returns:
            Tuple of (features_df, target_series)
        """
        # Use provided target or config default
        target_col = target_column or config.target_column

        # Validate required columns exist
        missing_features = [f for f in config.features if f not in bars.columns]
        if missing_features:
            raise ValueError(f"Missing feature columns: {missing_features}")

        if target_col not in bars.columns:
            raise ValueError(f"Target column '{target_col}' not found")

        # Extract features
        features_df = bars[config.features].copy()

        # Create forward-looking target based on horizon
        target_series = self._create_forward_target(
            bars, target_col, config.prediction_horizon_bars
        )

        # Align features and target (remove rows where target is NaN)
        valid_mask = target_series.notna()
        features_df = features_df[valid_mask]
        target_series = target_series[valid_mask]

        return features_df, target_series

    def _create_forward_target(
        self,
        bars: pd.DataFrame,
        target_column: str,
        horizon_bars: int
    ) -> pd.Series:
        """Create forward-looking target variable.

        Args:
            bars: DataFrame with price data
            target_column: Base column for target (e.g., 'close')
            horizon_bars: Number of bars ahead to predict

        Returns:
            Series with forward returns
        """
        # Group by symbol to avoid look-ahead across symbols
        targets = []

        for symbol, group in bars.groupby('symbol'):
            group_sorted = group.sort_values('ts')

            if target_column == 'close' or target_column in ['open', 'high', 'low']:
                # Price-based target: forward return
                current_price = group_sorted[target_column].values
                future_price = group_sorted[target_column].shift(-horizon_bars).values
                forward_return = (future_price - current_price) / current_price

                target_series = pd.Series(
                    forward_return,
                    index=group_sorted.index,
                    name=f'{target_column}_forward_{horizon_bars}_ret'
                )
            else:
                # Generic forward target
                target_series = group_sorted[target_column].shift(-horizon_bars)

            targets.append(target_series)

        # Concatenate all symbol targets
        return pd.concat(targets).sort_index()

    def train_model(
        self,
        bars: pd.DataFrame,
        config: ModelConfig,
        model_id: Optional[str] = None,
        description: Optional[str] = None
    ) -> ModelMetadata:
        """Train an ML model according to configuration.

        Args:
            bars: Training data with features
            config: Model configuration
            model_id: Optional model ID (generated if None)
            description: Optional model description

        Returns:
            Model metadata
        """
        # Generate model ID if not provided
        if model_id is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_id = f"{config.model_type.value}_{timestamp}"

        # Prepare training data
        features_df, target_series = self.prepare_training_data(bars, config)

        # Create train/val/test splits with time series awareness
        train_df, val_df, test_df, train_y, val_y, test_y = self._time_series_split(
            features_df, target_series, config.train_test_split, config.train_val_split
        )

        # Scale features if requested
        scaler = None
        if config.scale_features:
            scaler = StandardScaler()
            train_df = pd.DataFrame(
                scaler.fit_transform(train_df),
                index=train_df.index,
                columns=train_df.columns
            )
            val_df = pd.DataFrame(
                scaler.transform(val_df),
                index=val_df.index,
                columns=val_df.columns
            )
            test_df = pd.DataFrame(
                scaler.transform(test_df),
                index=test_df.index,
                columns=test_df.columns
            )

        # Get model class and instantiate
        model_class = self.MODEL_CLASSES.get(config.model_class)
        if model_class is None:
            raise ValueError(f"Unsupported model class: {config.model_class}")

        # Train with hyperparameter tuning if specified
        if config.hyperparameters:
            model = self._train_with_hyperparameter_tuning(
                model_class, train_df, train_y, val_df, val_y, config
            )
        else:
            model = model_class(random_state=config.random_seed)
            model.fit(train_df, train_y)

        # Evaluate model
        train_score = self._evaluate_model(model, train_df, train_y, config.model_type)
        val_score = self._evaluate_model(model, val_df, val_y, config.model_type)
        test_score = self._evaluate_model(model, test_df, test_y, config.model_type)

        # Calculate feature importance
        feature_importance = self._calculate_feature_importance(
            model, config.features, config.model_type
        )

        # Create model metadata
        metadata = ModelMetadata(
            model_id=model_id,
            model_type=config.model_type,
            model_class=config.model_class,
            training_date=datetime.now(),
            features=config.features,
            target_column=config.target_column,
            train_samples=len(train_df),
            val_samples=len(val_df),
            test_samples=len(test_df),
            train_score=train_score,
            val_score=val_score,
            test_score=test_score,
            feature_importance=feature_importance,
            hyperparameters=config.hyperparameters,
            random_seed=config.random_seed,
            data_hash=hash_dataframe(bars[config.features + [config.target_column]]),
            model_hash=self._hash_model(model),
            description=description
        )

        # Save scaler with model if used
        if scaler is not None:
            model.scaler = scaler

        # Register model
        self.registry.register_model(model, metadata)

        return metadata

    def _time_series_split(
        self,
        features: pd.DataFrame,
        target: pd.Series,
        test_split: float,
        val_split: float
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.Series, pd.Series, pd.Series]:
        """Split data into train/val/test with time series awareness."""
        n_samples = len(features)

        # Calculate split indices
        test_start = int(n_samples * (1 - test_split))
        val_start = int(test_start * (1 - val_split))

        # Split data
        train_df = features.iloc[:val_start]
        val_df = features.iloc[val_start:test_start]
        test_df = features.iloc[test_start:]

        train_y = target.iloc[:val_start]
        val_y = target.iloc[val_start:test_start]
        test_y = target.iloc[test_start:]

        return train_df, val_df, test_df, train_y, val_y, test_y

    def _train_with_hyperparameter_tuning(
        self,
        model_class: Type[BaseEstimator],
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_val: pd.DataFrame,
        y_val: pd.Series,
        config: ModelConfig
    ) -> BaseEstimator:
        """Train model with hyperparameter tuning using time series CV."""
        # Create base model
        base_model = model_class(random_state=config.random_seed)

        # Use time series split for CV
        tscv = TimeSeriesSplit(n_splits=config.cross_validation_folds)

        # Grid search with hyperparameters
        grid_search = GridSearchCV(
            base_model,
            config.hyperparameters,
            cv=tscv,
            scoring='accuracy' if config.model_type.value == "classification" else 'neg_mean_squared_error',
            n_jobs=-1,
            verbose=0
        )

        # Fit on combined train+val data for CV
        X_combined = pd.concat([X_train, X_val])
        y_combined = pd.concat([y_train, y_val])

        grid_search.fit(X_combined, y_combined)

        return grid_search.best_estimator_

    def _evaluate_model(
        self,
        model: BaseEstimator,
        X: pd.DataFrame,
        y: pd.Series,
        model_type: ModelType
    ) -> float:
        """Evaluate model performance."""
        y_pred = model.predict(X)

        if model_type.value == "classification":
            return accuracy_score(y, y_pred)
        else:  # REGRESSION
            return r2_score(y, y_pred)

    def _calculate_feature_importance(
        self,
        model: BaseEstimator,
        feature_names: List[str],
        model_type: ModelType
    ) -> List[FeatureImportance]:
        """Calculate feature importance."""
        importance_scores = []

        if hasattr(model, 'feature_importances_'):
            # Tree-based models
            importance_scores = model.feature_importances_
        elif hasattr(model, 'coef_'):
            # Linear models
            importance_scores = np.abs(model.coef_)
            if len(importance_scores.shape) > 1:
                importance_scores = importance_scores[0]  # Take first class for multi-class
        else:
            # Default: equal importance
            importance_scores = np.ones(len(feature_names)) / len(feature_names)

        # Create feature importance objects
        feature_importance = []
        for i, (feature, score) in enumerate(zip(feature_names, importance_scores)):
            feature_importance.append(
                FeatureImportance(
                    feature_name=feature,
                    importance=float(score),
                    rank=i + 1
                )
            )

        # Sort by importance
        feature_importance.sort(key=lambda x: x.importance, reverse=True)

        # Update ranks
        for i, fi in enumerate(feature_importance):
            fi.rank = i + 1

        return feature_importance

    def _hash_model(self, model: BaseEstimator) -> str:
        """Create hash of model for integrity checking."""
        # Hash model parameters and state
        model_state = {
            'class': model.__class__.__name__,
            'params': model.get_params(),
        }

        if hasattr(model, 'feature_importances_'):
            model_state['feature_importances_'] = model.feature_importances_.tolist()

        if hasattr(model, 'coef_'):
            model_state['coef_'] = model.coef_.tolist()

        model_str = json.dumps(model_state, sort_keys=True)
        return hashlib.sha256(model_str.encode()).hexdigest()[:16]