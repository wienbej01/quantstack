"""Model I/O Module for Intraday ML

Versioned model saving and loading with comprehensive model cards for
reproducibility and auditability.
"""

import hashlib
import json
import pickle
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import lightgbm as lgb
import pandas as pd

from extensions.intraday_ml_models.train_lgbm import TrainingResult


@dataclass
class ModelCard:
    """Comprehensive model card for model documentation and reproducibility."""

    # Basic metadata
    model_name: str
    version: str
    created_at: str
    model_type: str
    model_config: dict[str, Any]

    # Training data information
    training_metadata: dict[str, Any]
    features_hash: str
    targets_hash: str

    # Performance metrics
    metrics: dict[str, Any]

    # Optional fields with defaults
    created_by: str = "intraday_ml_pipeline"

    # Validation results
    cross_validation: dict[str, Any] | None = None

    # Feature information
    feature_names: list | None = None
    feature_importance: dict[str, float] | None = None
    top_features: list | None = None

    # Model parameters
    model_params: dict[str, Any] | None = None

    # Reproducibility
    random_seed: int | None = None
    training_environment: dict[str, Any] | None = None

    # Usage information
    intended_use: str = "Intraday prominent moves prediction"
    limitations: list | None = None
    ethical_considerations: list | None = None

    # Version control
    git_commit: str | None = None
    code_version: str | None = None


class ModelIO:
    """Handles versioned model saving and loading with model cards."""

    def __init__(self, model_dir: str | Path, config: dict[str, Any] | None = None):
        """Initialize ModelIO with model directory.

        Args:
            model_dir: Directory to save/load models
            config: Optional model configuration
        """
        self.model_dir = Path(model_dir)
        self.model_dir.mkdir(parents=True, exist_ok=True)
        self.config = config or {}

    def save_model(
        self,
        training_result: TrainingResult,
        model_name: str,
        version: str | None = None,
        save_format: str = "joblib",
        compression: bool = True,
    ) -> dict[str, Any]:
        """Save trained model with model card.

        Args:
            training_result: Result from training
            model_name: Name of the model
            version: Model version (auto-generated if None)
            save_format: Format for saving model ("joblib" or "pickle")
            compression: Whether to compress saved files

        Returns:
            Dictionary with save information
        """
        if version is None:
            version = self._generate_version()

        # Create model card
        model_card = self._create_model_card(training_result, model_name, version)

        # Save model files
        save_paths = self._save_model_files(
            training_result, model_card, model_name, save_format, compression
        )

        # Save model card
        model_card_path = self.model_dir / f"{model_name}_{version}_model_card.json"
        with open(model_card_path, "w") as f:
            json.dump(asdict(model_card), f, indent=2, default=str)

        return {
            "model_name": model_name,
            "version": version,
            "model_path": str(save_paths["model_path"]),
            "calibrated_model_path": str(save_paths["calibrated_model_path"]),
            "model_card_path": str(model_card_path),
            "created_at": model_card.created_at,
        }

    def load_model(
        self,
        model_name: str,
        version: str,
        load_calibrated: bool = True,
        load_format: str = "joblib",
    ) -> dict[str, Any]:
        """Load model and model card.

        Args:
            model_name: Name of the model
            version: Model version
            load_calibrated: Whether to load calibrated model
            load_format: Format for loading model

        Returns:
            Dictionary with loaded model and metadata
        """
        # Load model card
        model_card_path = self.model_dir / f"{model_name}_{version}_model_card.json"
        if not model_card_path.exists():
            raise FileNotFoundError(f"Model card not found: {model_card_path}")

        with open(model_card_path) as f:
            model_card_dict = json.load(f)

        model_card = ModelCard(**model_card_dict)

        # Load model
        if load_calibrated:
            model_path = (
                self.model_dir / f"{model_name}_{version}_calibrated.{load_format}"
            )
        else:
            model_path = self.model_dir / f"{model_name}_{version}_raw.{load_format}"

        if not model_path.exists():
            raise FileNotFoundError(f"Model file not found: {model_path}")

        if load_format == "joblib":
            model = joblib.load(model_path)
        else:
            with open(model_path, "rb") as f:
                model = pickle.load(f)

        return {
            "model": model,
            "model_card": model_card,
            "model_path": str(model_path),
            "model_card_path": str(model_card_path),
        }

    def list_models(self, model_name: str | None = None) -> pd.DataFrame:
        """List available models.

        Args:
            model_name: Filter by model name (optional)

        Returns:
            DataFrame with available models
        """
        models = []

        for file_path in self.model_dir.glob("*_model_card.json"):
            try:
                with open(file_path) as f:
                    model_card_dict = json.load(f)

                model_card = ModelCard(**model_card_dict)

                if model_name is None or model_card.model_name == model_name:
                    models.append(
                        {
                            "model_name": model_card.model_name,
                            "version": model_card.version,
                            "created_at": model_card.created_at,
                            "model_type": model_card.model_type,
                            "accuracy": model_card.metrics.get("accuracy"),
                            "f1_macro": model_card.metrics.get("f1_macro"),
                            "brier_score": model_card.metrics.get("brier_score"),
                        }
                    )
            except Exception as e:
                print(f"Error loading model card {file_path}: {e}")

        if models:
            return pd.DataFrame(models).sort_values("created_at", ascending=False)
        else:
            return pd.DataFrame()

    def get_model_info(self, model_name: str, version: str) -> ModelCard:
        """Get detailed model information.

        Args:
            model_name: Name of the model
            version: Model version

        Returns:
            ModelCard with detailed information
        """
        model_card_path = self.model_dir / f"{model_name}_{version}_model_card.json"
        with open(model_card_path) as f:
            model_card_dict = json.load(f)

        return ModelCard(**model_card_dict)

    def _generate_version(self) -> str:
        """Generate version string based on timestamp and hash."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        content_hash = hashlib.md5(timestamp.encode()).hexdigest()[:8]
        return f"v1.0.{timestamp}_{content_hash}"

    def _create_model_card(
        self, training_result: TrainingResult, model_name: str, version: str
    ) -> ModelCard:
        """Create comprehensive model card."""
        # Extract feature names from training metadata
        feature_names = training_result.training_metadata.get("feature_count", 0)

        # Create model card
        model_card = ModelCard(
            model_name=model_name,
            version=version,
            created_at=datetime.utcnow().isoformat() + "Z",
            model_type=training_result.model.__class__.__name__,
            model_config=self.config,
            training_metadata=training_result.training_metadata,
            features_hash=training_result.training_metadata.get("features_hash", ""),
            targets_hash=training_result.training_metadata.get("targets_hash", ""),
            metrics=training_result.metrics,
            cross_validation=None,  # Could be added if CV results available
            feature_names=(
                [f"feature_{i}" for i in range(feature_names)]
                if feature_names
                else None
            ),
            feature_importance=training_result.metrics.get("feature_importance"),
            top_features=training_result.metrics.get("top_features"),
            model_params=training_result.model.get_params(),
            random_seed=self.config.get("reproducibility", {}).get("seed"),
            training_environment={
                "python_version": "3.x",
                "lightgbm_version": lgb.__version__,
                "training_time_seconds": training_result.training_time_seconds,
            },
            intended_use="Intraday prominent moves prediction for tri-class classification",
            limitations=[
                "Trained on specific market conditions",
                "Requires regular retraining",
                "Performance may vary across market regimes",
            ],
            ethical_considerations=[
                "Model should not be used as sole decision maker",
                "Human oversight required",
                "Model biases should be regularly evaluated",
            ],
        )

        return model_card

    def _save_model_files(
        self,
        training_result: TrainingResult,
        model_card: ModelCard,
        model_name: str,
        save_format: str,
        compression: bool,
    ) -> dict[str, Path]:
        """Save model files with proper naming."""
        base_name = f"{model_name}_{model_card.version}"

        # Save raw model
        raw_model_path = self.model_dir / f"{base_name}_raw.{save_format}"
        if save_format == "joblib":
            joblib.dump(training_result.model, raw_model_path, compress=compression)
        else:
            with open(raw_model_path, "wb") as f:
                pickle.dump(training_result.model, f)

        # Save calibrated model
        calibrated_model_path = self.model_dir / f"{base_name}_calibrated.{save_format}"
        if save_format == "joblib":
            joblib.dump(
                training_result.calibrated_model,
                calibrated_model_path,
                compress=compression,
            )
        else:
            with open(calibrated_model_path, "wb") as f:
                pickle.dump(training_result.calibrated_model, f)

        return {
            "model_path": raw_model_path,
            "calibrated_model_path": calibrated_model_path,
        }


def save_model_with_card(
    training_result: TrainingResult,
    model_dir: str | Path,
    model_name: str,
    version: str | None = None,
) -> dict[str, Any]:
    """Convenience function to save model with model card.

    Args:
        training_result: Result from training
        model_dir: Directory to save model
        model_name: Name of the model
        version: Model version (auto-generated if None)

    Returns:
        Dictionary with save information
    """
    model_io = ModelIO(model_dir)
    return model_io.save_model(training_result, model_name, version)


def load_model_with_card(
    model_dir: str | Path,
    model_name: str,
    version: str,
    load_calibrated: bool = True,
) -> dict[str, Any]:
    """Convenience function to load model with model card.

    Args:
        model_dir: Directory containing model
        model_name: Name of the model
        version: Model version
        load_calibrated: Whether to load calibrated model

    Returns:
        Dictionary with loaded model and metadata
    """
    model_io = ModelIO(model_dir)
    return model_io.load_model(model_name, version, load_calibrated)
