"""Advanced feature selection methods for intraday ML."""

import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.feature_selection import (
    RFE,
    RFECV,
    SelectKBest,
    SelectPercentile,
    f_classif,
    f_regression,
    mutual_info_classif,
    mutual_info_regression,
)
from sklearn.linear_model import LassoCV

warnings.filterwarnings("ignore")


@dataclass
class SelectionResult:
    """Result of feature selection."""

    selected_features: list[str]
    feature_scores: dict[str, float]
    feature_ranks: dict[str, int]
    selection_method: str
    n_features_selected: int
    support_mask: np.ndarray


class FeatureSelector:
    """Advanced feature selection for intraday trading features."""

    def __init__(self):
        self.fitted_selector = None
        self.feature_names = None
        self.selection_method = None

    def select_univariate(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        method: str = "k_best",
        k: int = 10,
        percentile: int = 50,
        task_type: str = "regression",
    ) -> SelectionResult:
        """
        Univariate feature selection.

        Args:
            X: Feature matrix
            y: Target variable
            method: Selection method ('k_best', 'percentile')
            k: Number of top features to select
            percentile: Percentile of features to keep
            task_type: 'regression' or 'classification'

        Returns:
            SelectionResult with selected features and scores
        """
        self.feature_names = X.columns.tolist()

        # Choose scoring function
        score_func = f_regression if task_type == "regression" else f_classif

        # Create selector
        if method == "k_best":
            selector = SelectKBest(score_func=score_func, k=k)
        elif method == "percentile":
            selector = SelectPercentile(score_func=score_func, percentile=percentile)
        else:
            raise ValueError(f"Unknown univariate method: {method}")

        # Fit selector
        selector.fit_transform(X, y)
        self.fitted_selector = selector
        self.selection_method = f"univariate_{method}"

        # Get selected features and scores
        selected_mask = selector.get_support()
        selected_features = [
            self.feature_names[i]
            for i in range(len(self.feature_names))
            if selected_mask[i]
        ]

        # Get feature scores and ranks
        scores = selector.scores_
        feature_scores = {
            self.feature_names[i]: scores[i] for i in range(len(self.feature_names))
        }

        # Rank features by score
        sorted_indices = np.argsort(scores)[::-1]  # Descending order
        feature_ranks = {
            self.feature_names[i]: rank + 1 for rank, i in enumerate(sorted_indices)
        }

        return SelectionResult(
            selected_features=selected_features,
            feature_scores=feature_scores,
            feature_ranks=feature_ranks,
            selection_method=self.selection_method,
            n_features_selected=len(selected_features),
            support_mask=selected_mask,
        )

    def select_mutual_info(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        k: int = 10,
        task_type: str = "regression",
        random_state: int = 42,
    ) -> SelectionResult:
        """
        Mutual information feature selection.

        Args:
            X: Feature matrix
            y: Target variable
            k: Number of top features to select
            task_type: 'regression' or 'classification'
            random_state: Random seed

        Returns:
            SelectionResult with selected features and scores
        """
        self.feature_names = X.columns.tolist()

        # Choose scoring function
        score_func = (
            mutual_info_regression if task_type == "regression" else mutual_info_classif
        )

        # Calculate mutual information scores
        scores = score_func(X, y, random_state=random_state)

        # Get top k features
        k = min(k, len(scores))
        top_indices = np.argsort(scores)[::-1][:k]

        # Create selection mask
        selected_mask = np.zeros(len(scores), dtype=bool)
        selected_mask[top_indices] = True

        selected_features = [self.feature_names[i] for i in top_indices]

        # Create feature scores and ranks
        feature_scores = {
            self.feature_names[i]: scores[i] for i in range(len(self.feature_names))
        }
        sorted_indices = np.argsort(scores)[::-1]
        feature_ranks = {
            self.feature_names[i]: rank + 1 for rank, i in enumerate(sorted_indices)
        }

        # Store selector info
        self.selection_method = "mutual_info"
        self.fitted_selector = type(
            "MockSelector", (), {"get_support": lambda self: selected_mask}
        )()

        return SelectionResult(
            selected_features=selected_features,
            feature_scores=feature_scores,
            feature_ranks=feature_ranks,
            selection_method=self.selection_method,
            n_features_selected=len(selected_features),
            support_mask=selected_mask,
        )

    def select_rfe(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        estimator: Any | None = None,
        n_features: int = 10,
        step: float = 0.1,
        cv: bool = False,
        task_type: str = "regression",
        random_state: int = 42,
    ) -> SelectionResult:
        """
        Recursive Feature Elimination.

        Args:
            X: Feature matrix
            y: Target variable
            estimator: Model to use for feature importance
            n_features: Number of features to select
            step: Step size for elimination
            cv: Whether to use cross-validation
            task_type: 'regression' or 'classification'
            random_state: Random seed

        Returns:
            SelectionResult with selected features and rankings
        """
        self.feature_names = X.columns.tolist()

        # Create default estimator if not provided
        if estimator is None:
            if task_type == "regression":
                estimator = RandomForestRegressor(
                    n_estimators=100, max_depth=5, random_state=random_state, n_jobs=-1
                )
            else:
                estimator = RandomForestClassifier(
                    n_estimators=100, max_depth=5, random_state=random_state, n_jobs=-1
                )

        # Create RFE selector
        if cv:
            selector = RFECV(
                estimator=estimator,
                step=step,
                cv=5,
                scoring=(
                    "neg_mean_squared_error"
                    if task_type == "regression"
                    else "accuracy"
                ),
                n_jobs=-1,
            )
        else:
            selector = RFE(
                estimator=estimator, n_features_to_select=n_features, step=step
            )

        # Fit selector
        selector.fit_transform(X, y)
        self.fitted_selector = selector
        self.selection_method = f"rfe_{'cv' if cv else 'fixed'}"

        # Get selected features
        selected_mask = selector.get_support()
        selected_features = [
            self.feature_names[i]
            for i in range(len(self.feature_names))
            if selected_mask[i]
        ]

        # Get feature rankings
        if hasattr(selector, "ranking_"):
            feature_ranks = {
                self.feature_names[i]: selector.ranking_[i]
                for i in range(len(self.feature_names))
            }
        else:
            feature_ranks = {
                name: 1 if name in selected_features else len(selected_features) + 1
                for name in self.feature_names
            }

        # Create dummy scores (use inverse ranking as score)
        max_rank = max(feature_ranks.values())
        feature_scores = {
            name: (max_rank - rank + 1) / max_rank
            for name, rank in feature_ranks.items()
        }

        return SelectionResult(
            selected_features=selected_features,
            feature_scores=feature_scores,
            feature_ranks=feature_ranks,
            selection_method=self.selection_method,
            n_features_selected=len(selected_features),
            support_mask=selected_mask,
        )

    def select_lasso(
        self,
        X: pd.DataFrame,
        y: pd.Series,
        cv: int = 5,
        max_features: int | None = None,
        random_state: int = 42,
    ) -> SelectionResult:
        """
        Lasso-based feature selection.

        Args:
            X: Feature matrix
            y: Target variable
            cv: Number of cross-validation folds
            max_features: Maximum number of features to select
            random_state: Random seed

        Returns:
            SelectionResult with selected features and coefficients
        """
        self.feature_names = X.columns.tolist()

        # Fit Lasso CV
        lasso = LassoCV(cv=cv, random_state=random_state, max_iter=2000, n_jobs=-1)
        lasso.fit(X, y)

        # Get non-zero coefficients
        coef = lasso.coef_
        non_zero_mask = np.abs(coef) > 1e-6  # Small threshold to avoid numerical issues

        selected_features = [
            self.feature_names[i]
            for i in range(len(self.feature_names))
            if non_zero_mask[i]
        ]

        # Limit number of features if specified
        if max_features and len(selected_features) > max_features:
            # Sort by absolute coefficient and take top features
            abs_coef = np.abs(coef[non_zero_mask])
            top_indices = np.argsort(abs_coef)[::-1][:max_features]
            selected_features = [selected_features[i] for i in top_indices]

            # Update mask
            non_zero_mask = np.zeros(len(self.feature_names), dtype=bool)
            for i, feature in enumerate(self.feature_names):
                if feature in selected_features:
                    non_zero_mask[i] = True

        # Create feature scores and ranks
        feature_scores = {
            self.feature_names[i]: abs(coef[i]) for i in range(len(self.feature_names))
        }
        sorted_indices = np.argsort(list(feature_scores.values()))[::-1]
        feature_ranks = {
            self.feature_names[i]: rank + 1 for rank, i in enumerate(sorted_indices)
        }

        # Store selector info
        self.selection_method = "lasso"
        self.fitted_selector = lasso

        return SelectionResult(
            selected_features=selected_features,
            feature_scores=feature_scores,
            feature_ranks=feature_ranks,
            selection_method=self.selection_method,
            n_features_selected=len(selected_features),
            support_mask=non_zero_mask,
        )

    def select_correlation_filter(
        self, X: pd.DataFrame, threshold: float = 0.95
    ) -> SelectionResult:
        """
        Remove highly correlated features.

        Args:
            X: Feature matrix
            threshold: Correlation threshold for removal

        Returns:
            SelectionResult with filtered features
        """
        self.feature_names = X.columns.tolist()

        # Calculate correlation matrix
        corr_matrix = X.corr().abs()

        # Find highly correlated feature pairs
        upper_tri = corr_matrix.where(
            np.triu(np.ones(corr_matrix.shape), k=1).astype(bool)
        )

        # Identify features to remove
        to_remove = set()
        for column in upper_tri.columns:
            highly_correlated = upper_tri[column][upper_tri[column] > threshold]
            if len(highly_correlated) > 0:
                to_remove.add(column)

        # Create selection mask
        selected_features = [col for col in self.feature_names if col not in to_remove]
        selected_mask = [col in selected_features for col in self.feature_names]

        # Create scores (use variance as score)
        feature_scores = {col: X[col].var() for col in self.feature_names}
        feature_ranks = {
            col: rank + 1
            for rank, col in enumerate(
                sorted(
                    feature_scores.keys(), key=lambda x: feature_scores[x], reverse=True
                )
            )
        }

        # Store selector info
        self.selection_method = "correlation_filter"
        self.fitted_selector = type(
            "MockSelector", (), {"get_support": lambda self: selected_mask}
        )()

        return SelectionResult(
            selected_features=selected_features,
            feature_scores=feature_scores,
            feature_ranks=feature_ranks,
            selection_method=self.selection_method,
            n_features_selected=len(selected_features),
            support_mask=np.array(selected_mask),
        )

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Transform data using fitted selector.

        Args:
            X: Input features

        Returns:
            Transformed features
        """
        if self.fitted_selector is None:
            raise ValueError("Selector not fitted. Call a selection method first.")

        if hasattr(self.fitted_selector, "transform"):
            X_transformed = self.fitted_selector.transform(X)
            return pd.DataFrame(
                X_transformed, columns=self.get_selected_features(), index=X.index
            )
        else:
            # For custom selectors
            selected_mask = self.fitted_selector.get_support()
            selected_features = [
                self.feature_names[i]
                for i in range(len(self.feature_names))
                if selected_mask[i]
            ]
            return X[selected_features]

    def get_selected_features(self) -> list[str]:
        """Get list of selected feature names."""
        if self.fitted_selector is None:
            raise ValueError("Selector not fitted.")

        selected_mask = self.fitted_selector.get_support()
        return [
            self.feature_names[i]
            for i in range(len(self.feature_names))
            if selected_mask[i]
        ]

    def get_feature_importance(self) -> dict[str, float]:
        """Get feature importance scores."""
        if self.fitted_selector is None:
            raise ValueError("Selector not fitted.")

        if hasattr(self.fitted_selector, "coef_"):
            # Linear models
            importance = np.abs(self.fitted_selector.coef_)
        elif hasattr(self.fitted_selector, "feature_importances_"):
            # Tree-based models
            importance = self.fitted_selector.feature_importances_
        elif hasattr(self.fitted_selector, "scores_"):
            # Univariate selectors
            importance = self.fitted_selector.scores_
        else:
            raise ValueError("Cannot extract feature importance from fitted selector.")

        return {
            self.feature_names[i]: importance[i] for i in range(len(self.feature_names))
        }
