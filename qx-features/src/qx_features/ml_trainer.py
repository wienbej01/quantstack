"""
ML Trainer Scaffold

Simple classifier trainer with model hashing and artifact saving.
Provides a foundation for training ML models on VPA features.
"""

import hashlib
import json
import pathlib
import pickle
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler


class ModelTrainer:
    """Simple ML model trainer with artifact management."""

    def __init__(
        self,
        model_type: str = "random_forest",
        random_state: int = 42,
        model_params: dict[str, Any] | None = None,
    ):
        """
        Initialize model trainer.

        Args:
            model_type: Type of model ('random_forest', 'logistic_regression')
            random_state: Random seed for reproducibility
            model_params: Additional model parameters
        """
        self.model_type = model_type
        self.random_state = random_state
        self.model_params = model_params or {}
        self.model = None
        self.scaler = None
        self.feature_names = None
        self.training_metadata = {}

    def create_model(self) -> BaseEstimator:
        """Create the model instance."""
        if self.model_type == "random_forest":
            default_params = {
                "n_estimators": 100,
                "max_depth": 10,
                "min_samples_split": 5,
                "min_samples_leaf": 2,
                "random_state": self.random_state,
            }
            params = {**default_params, **self.model_params}
            return RandomForestClassifier(**params)

        elif self.model_type == "logistic_regression":
            default_params = {
                "random_state": self.random_state,
                "max_iter": 1000,
                "C": 1.0,
            }
            params = {**default_params, **self.model_params}
            return LogisticRegression(**params)

        else:
            raise ValueError(f"Unsupported model type: {self.model_type}")

    def prepare_data(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        scale_features: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Prepare training data.

        Args:
            X: Feature DataFrame
            y: Target Series
            scale_features: Whether to scale features

        Returns:
            Tuple of (X_array, y_array)
        """
        # Store feature names
        self.feature_names = list(X.columns)

        # Convert to numpy arrays
        X_array = X.values.astype(np.float32)
        y_array = y.values

        # Handle NaN values
        mask = ~np.isnan(X_array).any(axis=1)
        X_array = X_array[mask]
        y_array = y_array[mask]

        # Scale features if requested
        if scale_features:
            self.scaler = StandardScaler()
            X_array = self.scaler.fit_transform(X_array)

        return X_array, y_array

    def train(
        self,
        X_train: pd.DataFrame,
        y_train: pd.Series,
        X_valid: pd.DataFrame | None = None,
        y_valid: pd.Series | None = None,
        scale_features: bool = True,
    ) -> dict[str, Any]:
        """
        Train the model.

        Args:
            X_train: Training features
            y_train: Training targets
            X_valid: Validation features (optional)
            y_valid: Validation targets (optional)
            scale_features: Whether to scale features

        Returns:
            Training results dictionary
        """
        # Create model
        self.model = self.create_model()

        # Prepare data
        X_train_prep, y_train_prep = self.prepare_data(X_train, y_train, scale_features)

        # Train model
        self.model.fit(X_train_prep, y_train_prep)

        # Calculate training metrics
        train_pred = self.model.predict(X_train_prep)
        train_proba = (
            self.model.predict_proba(X_train_prep)[:, 1]
            if hasattr(self.model, "predict_proba")
            else None
        )

        train_metrics = {
            "accuracy": float(np.mean(train_pred == y_train_prep)),
            "n_samples": len(X_train_prep),
        }

        if train_proba is not None:
            train_metrics["roc_auc"] = float(roc_auc_score(y_train_prep, train_proba))

        # Validation metrics if validation data provided
        valid_metrics = {}
        if X_valid is not None and y_valid is not None:
            X_valid_prep, y_valid_prep = self.prepare_data(X_valid, y_valid, scale_features)
            valid_pred = self.model.predict(X_valid_prep)
            valid_proba = (
                self.model.predict_proba(X_valid_prep)[:, 1]
                if hasattr(self.model, "predict_proba")
                else None
            )

            valid_metrics = {
                "accuracy": float(np.mean(valid_pred == y_valid_prep)),
                "n_samples": len(X_valid_prep),
            }

            if valid_proba is not None:
                valid_metrics["roc_auc"] = float(roc_auc_score(y_valid_prep, valid_proba))

        # Store training metadata
        self.training_metadata = {
            "model_type": self.model_type,
            "model_params": self.model_params,
            "feature_names": self.feature_names,
            "n_features": len(self.feature_names),
            "scale_features": scale_features,
            "random_state": self.random_state,
            "trained_at": datetime.now().isoformat(),
            "train_metrics": train_metrics,
            "valid_metrics": valid_metrics,
        }

        return {
            "train_metrics": train_metrics,
            "valid_metrics": valid_metrics,
            "feature_names": self.feature_names,
            "model_metadata": self.training_metadata,
        }

    def predict(
        self,
        X: pd.DataFrame,
        return_proba: bool = False,
    ) -> np.ndarray | tuple[np.ndarray, np.ndarray]:
        """
        Make predictions.

        Args:
            X: Feature DataFrame
            return_proba: Whether to return probabilities

        Returns:
            Predictions (and optionally probabilities)
        """
        if self.model is None:
            raise ValueError("Model not trained yet")

        # Prepare data
        X_array = X[self.feature_names].values.astype(np.float32)

        # Handle NaN values
        mask = ~np.isnan(X_array).any(axis=1)
        X_array = X_array[mask]

        # Scale features if scaler was used
        if self.scaler is not None:
            X_array = self.scaler.transform(X_array)

        # Make predictions
        predictions = self.model.predict(X_array)

        if return_proba and hasattr(self.model, "predict_proba"):
            probabilities = self.model.predict_proba(X_array)[:, 1]
            return predictions, probabilities

        return predictions

    def get_feature_importance(self) -> dict[str, float] | None:
        """Get feature importance if available."""
        if self.model is None or self.feature_names is None:
            return None

        if hasattr(self.model, "feature_importances_"):
            importance = self.model.feature_importances_
            return dict(zip(self.feature_names, importance.tolist(), strict=False))

        return None

    def compute_model_hash(self) -> str:
        """Compute hash for the trained model."""
        if self.model is None:
            raise ValueError("Model not trained yet")

        # Create a string representation of the model
        model_str = f"{self.model_type}_{self.model_params}_{self.random_state}"

        # Add feature names
        if self.feature_names:
            model_str += f"_features:{','.join(sorted(self.feature_names))}"

        # Add training metadata
        if self.training_metadata:
            metrics_str = json.dumps(
                self.training_metadata.get("train_metrics", {}), sort_keys=True
            )
            model_str += f"_metrics:{metrics_str}"

        # Compute hash
        return hashlib.sha256(model_str.encode()).hexdigest()[:16]

    def save_model(
        self,
        output_dir: str | pathlib.Path,
        include_scaler: bool = True,
        format: str = "pickle",
    ) -> dict[str, Any]:
        """
        Save the trained model and artifacts.

        Args:
            output_dir: Output directory
            include_scaler: Whether to save the scaler
            format: Save format ('pickle' or 'joblib')

        Returns:
            Model manifest dictionary
        """
        if self.model is None:
            raise ValueError("Model not trained yet")

        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save model
        model_file = output_path / f"model.{format}"
        if format == "pickle":
            with open(model_file, "wb") as f:
                pickle.dump(self.model, f)
        elif format == "joblib":
            from joblib import dump

            dump(self.model, model_file)
        else:
            raise ValueError(f"Unsupported format: {format}")

        # Save scaler if requested
        scaler_file = None
        if include_scaler and self.scaler is not None:
            scaler_file = output_path / f"scaler.{format}"
            if format == "pickle":
                with open(scaler_file, "wb") as f:
                    pickle.dump(self.scaler, f)
            elif format == "joblib":
                from joblib import dump

                dump(self.scaler, scaler_file)

        # Save feature names
        feature_file = output_path / "features.json"
        with open(feature_file, "w") as f:
            json.dump(self.feature_names, f, indent=2)

        # Compute model hash
        model_hash = self.compute_model_hash()

        # Create manifest
        manifest = {
            "model_id": f"model_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "model_hash": model_hash,
            "model_type": self.model_type,
            "model_params": self.model_params,
            "feature_names": self.feature_names,
            "n_features": len(self.feature_names) if self.feature_names else 0,
            "has_scaler": self.scaler is not None,
            "scaler_file": str(scaler_file.name) if scaler_file else None,
            "model_file": str(model_file.name),
            "feature_file": str(feature_file.name),
            "random_state": self.random_state,
            "training_metadata": self.training_metadata,
            "created_at": datetime.now().isoformat(),
        }

        # Add feature importance if available
        feature_importance = self.get_feature_importance()
        if feature_importance:
            manifest["feature_importance"] = feature_importance

        # Save manifest
        manifest_file = output_path / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        return manifest

    @classmethod
    def load_model(
        cls,
        model_dir: str | pathlib.Path,
        format: str = "pickle",
    ) -> "ModelTrainer":
        """
        Load a trained model from directory.

        Args:
            model_dir: Directory containing model artifacts
            format: Model format ('pickle' or 'joblib')

        Returns:
            Loaded ModelTrainer instance
        """
        model_path = pathlib.Path(model_dir)

        # Load manifest
        manifest_file = model_path / "manifest.json"
        if not manifest_file.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_file}")

        with open(manifest_file) as f:
            manifest = json.load(f)

        # Create trainer instance
        trainer = cls(
            model_type=manifest["model_type"],
            random_state=manifest["random_state"],
            model_params=manifest["model_params"],
        )

        # Load model
        model_file = model_path / manifest["model_file"]
        if format == "pickle":
            with open(model_file, "rb") as f:
                trainer.model = pickle.load(f)
        elif format == "joblib":
            from joblib import load

            trainer.model = load(model_file)

        # Load scaler if available
        if manifest.get("scaler_file") and manifest.get("has_scaler"):
            scaler_file = model_path / manifest["scaler_file"]
            if format == "pickle":
                with open(scaler_file, "rb") as f:
                    trainer.scaler = pickle.load(f)
            elif format == "joblib":
                from joblib import load

                trainer.scaler = load(scaler_file)

        # Load feature names
        feature_file = model_path / "features.json"
        with open(feature_file) as f:
            trainer.feature_names = json.load(f)

        # Load training metadata
        trainer.training_metadata = manifest.get("training_metadata", {})

        return trainer


def train_simple_classifier(
    train_df: pd.DataFrame,
    valid_df: pd.DataFrame,
    feature_cols: list[str],
    target_col: str,
    output_dir: str | pathlib.Path,
    model_type: str = "random_forest",
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Convenience function to train a simple classifier.

    Args:
        train_df: Training DataFrame
        valid_df: Validation DataFrame
        feature_cols: List of feature columns
        target_col: Target column name
        output_dir: Output directory for model
        model_type: Type of model to train
        random_state: Random seed

    Returns:
        Training results and model manifest
    """
    # Prepare data
    X_train = train_df[feature_cols]
    y_train = train_df[target_col]
    X_valid = valid_df[feature_cols]
    y_valid = valid_df[target_col]

    # Create trainer
    trainer = ModelTrainer(
        model_type=model_type,
        random_state=random_state,
    )

    # Train model
    results = trainer.train(X_train, y_train, X_valid, y_valid)

    # Save model
    manifest = trainer.save_model(output_dir)

    return {
        "training_results": results,
        "model_manifest": manifest,
        "feature_importance": trainer.get_feature_importance(),
    }
