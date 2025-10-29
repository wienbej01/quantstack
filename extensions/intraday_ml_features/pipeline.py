"""Feature engineering pipeline for intraday ML."""

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from sklearn.preprocessing import StandardScaler, RobustScaler, MinMaxScaler, QuantileTransformer
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline as SklearnPipeline

from .selection import FeatureSelector


class FeaturePipeline:
    """Advanced feature engineering pipeline for intraday trading."""

    def __init__(self):
        self.steps = {}
        self.scalers = {}
        self.pca = None
        self.feature_selector = None
        self.fitted = False
        self.feature_names = None

    def add_scaling_step(self, method: str = "standard", **kwargs):
        """
        Add scaling step to pipeline.

        Args:
            method: Scaling method ('standard', 'minmax', 'robust', 'quantile')
            **kwargs: Additional parameters for scaler
        """
        if method == "standard":
            scaler = StandardScaler(**kwargs)
        elif method == "minmax":
            scaler = MinMaxScaler(**kwargs)
        elif method == "robust":
            scaler = RobustScaler(**kwargs)
        elif method == "quantile":
            scaler = QuantileTransformer(**kwargs)
        else:
            raise ValueError(f"Unknown scaling method: {method}")

        self.steps["scaling"] = {
            "method": method,
            "scaler": scaler,
            "params": kwargs
        }

    def add_pca_step(self, n_components: Optional[int] = None, explained_variance_ratio: float = 0.95, **kwargs):
        """
        Add PCA dimensionality reduction step.

        Args:
            n_components: Number of components to keep
            explained_variance_ratio: Minimum explained variance ratio
            **kwargs: Additional parameters for PCA
        """
        self.steps["pca"] = {
            "n_components": n_components,
            "explained_variance_ratio": explained_variance_ratio,
            "params": kwargs
        }

    def add_feature_selection_step(self, method: str = "mutual_info", **kwargs):
        """
        Add feature selection step.

        Args:
            method: Selection method ('mutual_info', 'univariate', 'rfe', 'lasso')
            **kwargs: Additional parameters for feature selector
        """
        self.steps["feature_selection"] = {
            "method": method,
            "params": kwargs
        }

    def add_custom_transform(self, transform_func, name: str, **kwargs):
        """
        Add custom transformation step.

        Args:
            transform_func: Function to apply to features
            name: Name of the transformation step
            **kwargs: Additional parameters
        """
        self.steps[name] = {
            "transform_func": transform_func,
            "params": kwargs
        }

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "FeaturePipeline":
        """
        Fit the pipeline to training data.

        Args:
            X: Feature matrix
            y: Target variable (optional, needed for some steps)

        Returns:
            Self
        """
        self.feature_names = X.columns.tolist()
        X_transformed = X.copy()

        # Apply scaling step
        if "scaling" in self.steps:
            scaler = self.steps["scaling"]["scaler"]
            X_transformed = pd.DataFrame(
                scaler.fit_transform(X_transformed),
                columns=X_transformed.columns,
                index=X_transformed.index
            )
            self.scalers["scaling"] = scaler

        # Apply PCA step
        if "pca" in self.steps:
            pca_config = self.steps["pca"]
            n_components = pca_config["n_components"]
            explained_variance_ratio = pca_config["explained_variance_ratio"]

            if n_components is None:
                # Find optimal number of components
                pca_temp = PCA(**pca_config["params"])
                pca_temp.fit(X_transformed)
                cumsum_ratio = np.cumsum(pca_temp.explained_variance_ratio_)
                n_components = np.argmax(cumsum_ratio >= explained_variance_ratio) + 1

            self.pca = PCA(n_components=n_components, **pca_config["params"])
            X_transformed = pd.DataFrame(
                self.pca.fit_transform(X_transformed),
                columns=[f"PC{i+1}" for i in range(n_components)],
                index=X_transformed.index
            )

        # Apply feature selection step
        if "feature_selection" in self.steps and y is not None:
            selector_config = self.steps["feature_selection"]
            method = selector_config["method"]
            params = selector_config["params"]

            self.feature_selector = FeatureSelector()

            if method == "mutual_info":
                result = self.feature_selector.select_mutual_info(X_transformed, y, **params)
            elif method == "univariate":
                result = self.feature_selector.select_univariate(X_transformed, y, **params)
            elif method == "rfe":
                result = self.feature_selector.select_rfe(X_transformed, y, **params)
            elif method == "lasso":
                result = self.feature_selector.select_lasso(X_transformed, y, **params)
            else:
                raise ValueError(f"Unknown feature selection method: {method}")

            X_transformed = X_transformed[result.selected_features]

        # Apply custom transforms
        for step_name, step_config in self.steps.items():
            if step_name not in ["scaling", "pca", "feature_selection"]:
                transform_func = step_config["transform_func"]
                X_transformed = transform_func(X_transformed, **step_config["params"])

        self.fitted = True
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Transform new data using fitted pipeline.

        Args:
            X: Feature matrix

        Returns:
            Transformed features
        """
        if not self.fitted:
            raise ValueError("Pipeline must be fitted before transforming data")

        X_transformed = X.copy()

        # Apply scaling
        if "scaling" in self.scalers:
            scaler = self.scalers["scaling"]
            X_transformed = pd.DataFrame(
                scaler.transform(X_transformed),
                columns=X_transformed.columns,
                index=X_transformed.index
            )

        # Apply PCA
        if self.pca is not None:
            X_transformed = pd.DataFrame(
                self.pca.transform(X_transformed),
                columns=[f"PC{i+1}" for i in range(self.pca.n_components_)],
                index=X_transformed.index
            )

        # Apply feature selection
        if self.feature_selector is not None:
            X_transformed = self.feature_selector.transform(X_transformed)

        # Apply custom transforms
        for step_name, step_config in self.steps.items():
            if step_name not in ["scaling", "pca", "feature_selection"]:
                transform_func = step_config["transform_func"]
                X_transformed = transform_func(X_transformed, **step_config["params"])

        return X_transformed

    def fit_transform(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> pd.DataFrame:
        """
        Fit pipeline and transform data.

        Args:
            X: Feature matrix
            y: Target variable (optional)

        Returns:
            Transformed features
        """
        return self.fit(X, y).transform(X)

    def get_feature_names(self) -> List[str]:
        """Get names of features after pipeline transformation."""
        if not self.fitted:
            raise ValueError("Pipeline must be fitted first")

        if self.feature_selector is not None:
            return self.feature_selector.get_selected_features()
        elif self.pca is not None:
            return [f"PC{i+1}" for i in range(self.pca.n_components_)]
        else:
            return self.feature_names

    def get_step_params(self, step_name: str) -> Dict[str, Any]:
        """Get parameters for a specific step."""
        if step_name not in self.steps:
            raise ValueError(f"Step '{step_name}' not found in pipeline")
        return self.steps[step_name].copy()