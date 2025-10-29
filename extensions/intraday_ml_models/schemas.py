"""Pydantic schemas for ML model configuration and metadata."""

from datetime import datetime
from typing import Any, Dict, List, Optional, Union
from enum import Enum

from pydantic import BaseModel, Field


class ModelType(str, Enum):
    """Supported model types."""
    CLASSIFICATION = "classification"
    REGRESSION = "regression"


class FeatureImportance(BaseModel):
    """Feature importance information."""
    feature_name: str = Field(..., description="Feature name")
    importance: float = Field(..., description="Feature importance score")
    rank: int = Field(..., description="Importance rank")


class ModelMetadata(BaseModel):
    """Metadata for trained ML models."""
    model_id: str = Field(..., description="Unique model identifier")
    model_type: ModelType = Field(..., description="Type of ML model")
    model_class: str = Field(..., description="Python class name")
    training_date: datetime = Field(..., description="When model was trained")
    features: List[str] = Field(..., description="Feature names used for training")
    target_column: str = Field(..., description="Target column name")
    train_samples: int = Field(..., description="Number of training samples")
    val_samples: int = Field(..., description="Number of validation samples")
    test_samples: int = Field(..., description="Number of test samples")
    train_score: float = Field(..., description="Training set performance")
    val_score: float = Field(..., description="Validation set performance")
    test_score: float = Field(..., description="Test set performance")
    feature_importance: List[FeatureImportance] = Field(..., description="Feature importance ranking")
    hyperparameters: Dict[str, Any] = Field(default_factory=dict, description="Model hyperparameters")
    random_seed: int = Field(..., description="Random seed for reproducibility")
    data_hash: str = Field(..., description="Hash of training data")
    model_hash: str = Field(..., description="Hash of trained model")
    tags: List[str] = Field(default_factory=list, description="Model tags")
    description: Optional[str] = Field(None, description="Model description")


class ModelConfig(BaseModel):
    """Configuration for ML model training and inference."""
    model_type: ModelType = Field(..., description="Type of model to train")
    model_class: str = Field(..., description="Python class for the model")
    hyperparameters: Dict[str, Any] = Field(default_factory=dict, description="Model hyperparameters")
    features: List[str] = Field(..., description="Feature columns to use")
    target_column: str = Field(..., description="Target column name")
    prediction_horizon_bars: int = Field(default=1, description="Bars ahead to predict")
    train_test_split: float = Field(default=0.2, description="Test set proportion")
    train_val_split: float = Field(default=0.2, description="Validation set proportion")
    random_seed: int = Field(default=42, description="Random seed")
    cross_validation_folds: int = Field(default=5, description="CV folds for hyperparameter tuning")
    feature_selection: bool = Field(default=False, description="Enable feature selection")
    feature_importance_threshold: float = Field(default=0.01, description="Min feature importance")
    scale_features: bool = Field(default=True, description="Enable feature scaling")


class PredictionResult(BaseModel):
    """Result of model prediction."""
    model_id: str = Field(..., description="ID of model used")
    timestamp: int = Field(..., description="Prediction timestamp (ns)")
    symbol: str = Field(..., description="Symbol prediction is for")
    features_used: List[str] = Field(..., description="Features used for prediction")
    prediction: Union[float, int] = Field(..., description="Model prediction")
    prediction_probability: Optional[float] = Field(None, description="Prediction confidence")
    feature_values: Dict[str, float] = Field(..., description="Feature values at prediction time")