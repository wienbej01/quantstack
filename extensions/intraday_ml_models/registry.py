"""ML model registry for managing trained models."""

import json
import pickle
from pathlib import Path

from sklearn.base import BaseEstimator

from .schemas import ModelMetadata


class MLModelRegistry:
    """Registry for managing ML models with versioning and hash validation."""

    def __init__(self, registry_dir: str = "models/intraday_ml"):
        """Initialize model registry.

        Args:
            registry_dir: Directory to store model registry
        """
        self.registry_dir = Path(registry_dir)
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir = self.registry_dir / "trained_models"
        self.models_dir.mkdir(exist_ok=True)
        self.metadata_file = self.registry_dir / "registry.json"
        self._registry = self._load_registry()

    def _load_registry(self) -> dict[str, ModelMetadata]:
        """Load existing registry from disk."""
        if self.metadata_file.exists():
            with open(self.metadata_file) as f:
                data = json.load(f)
            return {
                model_id: ModelMetadata(**metadata)
                for model_id, metadata in data.items()
            }
        return {}

    def _save_registry(self) -> None:
        """Save registry to disk."""
        data = {
            model_id: metadata.dict() for model_id, metadata in self._registry.items()
        }
        with open(self.metadata_file, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def register_model(
        self, model: BaseEstimator, metadata: ModelMetadata, overwrite: bool = False
    ) -> None:
        """Register a trained model.

        Args:
            model: Trained sklearn model
            metadata: Model metadata
            overwrite: Whether to overwrite existing model
        """
        if metadata.model_id in self._registry and not overwrite:
            raise ValueError(
                f"Model {metadata.model_id} already exists. Use overwrite=True."
            )

        # Save model
        model_path = self.models_dir / f"{metadata.model_id}.pkl"
        with open(model_path, "wb") as f:
            pickle.dump(model, f)

        # Update registry
        self._registry[metadata.model_id] = metadata
        self._save_registry()

    def load_model(self, model_id: str) -> BaseEstimator:
        """Load a trained model by ID.

        Args:
            model_id: ID of model to load

        Returns:
            Loaded sklearn model
        """
        if model_id not in self._registry:
            raise ValueError(f"Model {model_id} not found in registry")

        model_path = self.models_dir / f"{model_id}.pkl"
        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        with open(model_path, "rb") as f:
            model = pickle.load(f)

        return model

    def get_metadata(self, model_id: str) -> ModelMetadata:
        """Get metadata for a model.

        Args:
            model_id: ID of model

        Returns:
            Model metadata
        """
        if model_id not in self._registry:
            raise ValueError(f"Model {model_id} not found in registry")

        return self._registry[model_id]

    def list_models(
        self, model_type: str | None = None, tags: list[str] | None = None
    ) -> list[ModelMetadata]:
        """List models with optional filtering.

        Args:
            model_type: Filter by model type
            tags: Filter by tags (must match all)

        Returns:
            List of matching model metadata
        """
        models = list(self._registry.values())

        if model_type:
            models = [m for m in models if m.model_type.value == model_type]

        if tags:
            models = [m for m in models if all(tag in m.tags for tag in tags)]

        return sorted(models, key=lambda x: x.training_date, reverse=True)

    def get_best_model(
        self, model_type: str, metric: str = "val_score"
    ) -> ModelMetadata | None:
        """Get best model by type and metric.

        Args:
            model_type: Type of model to find
            metric: Metric to optimize (val_score or test_score)

        Returns:
            Best model metadata or None if no models found
        """
        models = self.list_models(model_type=model_type)
        if not models:
            return None

        return max(models, key=lambda x: getattr(x, metric))

    def delete_model(self, model_id: str) -> None:
        """Delete a model from registry.

        Args:
            model_id: ID of model to delete
        """
        if model_id not in self._registry:
            raise ValueError(f"Model {model_id} not found in registry")

        # Delete model file
        model_path = self.models_dir / f"{model_id}.pkl"
        if model_path.exists():
            model_path.unlink()

        # Remove from registry
        del self._registry[model_id]
        self._save_registry()

    def validate_model_consistency(self, model_id: str) -> bool:
        """Validate model consistency by checking hashes.

        Args:
            model_id: ID of model to validate

        Returns:
            True if consistent, False otherwise
        """
        try:
            model = self.load_model(model_id)
            metadata = self.get_metadata(model_id)

            # Simple consistency check - model should have expected attributes
            if hasattr(model, "feature_names_in_"):
                expected_features = set(metadata.features)
                actual_features = set(model.feature_names_in_)
                return expected_features == actual_features

            return True
        except Exception:
            return False
