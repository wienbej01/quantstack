"""Intraday ML models extension.

This module provides ML model training, registry, and inference capabilities
for intraday trading strategies while maintaining reproducibility and
strict compliance with intraday trading rules.
"""

from .registry import MLModelRegistry
from .trainers import MLModelTrainer
from .predictors import MLPredictor
from .schemas import ModelConfig, ModelMetadata

__version__ = "0.1.0"
__all__ = [
    "MLModelRegistry",
    "MLModelTrainer",
    "MLPredictor",
    "ModelConfig",
    "ModelMetadata",
]