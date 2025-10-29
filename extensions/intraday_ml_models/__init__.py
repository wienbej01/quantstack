"""Intraday ML models extension.

This module provides ML model training, registry, and inference capabilities
for intraday trading strategies while maintaining reproducibility and
strict compliance with intraday trading rules.
"""

from .predictors import MLPredictor
from .registry import MLModelRegistry
from .schemas import ModelConfig, ModelMetadata
from .trainers import MLModelTrainer

__version__ = "0.1.0"
__all__ = [
    "MLModelRegistry",
    "MLModelTrainer",
    "MLPredictor",
    "ModelConfig",
    "ModelMetadata",
]
