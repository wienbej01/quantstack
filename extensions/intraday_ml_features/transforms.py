"""Custom feature transformations for intraday ML."""

import numpy as np
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple, Union
from dataclasses import dataclass
from sklearn.base import BaseEstimator, TransformerMixin
import warnings

warnings.filterwarnings("ignore")


@dataclass
class TransformResult:
    """Result of feature transformation."""
    transformed_features: pd.DataFrame
    transform_params: Dict[str, Any]
    feature_names: List[str]
    n_features: int


class LagTransformer(BaseEstimator, TransformerMixin):
    """Create lagged features for time series data."""

    def __init__(self, lags: List[int], fill_method: str = "bfill"):
        """
        Initialize lag transformer.

        Args:
            lags: List of lag periods
            fill_method: Method to fill NaN values ('bfill', 'ffill', 'zero')
        """
        self.lags = lags
        self.fill_method = fill_method
        self.feature_names = None

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "LagTransformer":
        """Fit transformer (just stores feature names)."""
        self.feature_names = X.columns.tolist()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create lagged features.

        Args:
            X: Input features

        Returns:
            DataFrame with lagged features
        """
        if not isinstance(X.index, pd.DatetimeIndex):
            raise ValueError("LagTransformer requires DatetimeIndex")

        lagged_features = []
        new_feature_names = []

        for col in self.feature_names:
            for lag in self.lags:
                lagged_col = X[col].shift(lag)
                lagged_features.append(lagged_col)
                new_feature_names.append(f"{col}_lag_{lag}")

        # Combine lagged features
        result = pd.concat(lagged_features, axis=1)
        result.columns = new_feature_names

        # Handle NaN values
        if self.fill_method == "bfill":
            result = result.bfill()
        elif self.fill_method == "ffill":
            result = result.ffill()
        elif self.fill_method == "zero":
            result = result.fillna(0)
        else:
            raise ValueError(f"Unknown fill method: {self.fill_method}")

        return result


class RollingTransformer(BaseEstimator, TransformerMixin):
    """Create rolling window features."""

    def __init__(self, windows: List[int], functions: List[str]):
        """
        Initialize rolling transformer.

        Args:
            windows: List of window sizes
            functions: List of functions to apply ('mean', 'std', 'min', 'max', 'median')
        """
        self.windows = windows
        self.functions = functions
        self.feature_names = None

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "RollingTransformer":
        """Fit transformer (just stores feature names)."""
        self.feature_names = X.columns.tolist()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create rolling window features.

        Args:
            X: Input features

        Returns:
            DataFrame with rolling features
        """
        if not isinstance(X.index, pd.DatetimeIndex):
            raise ValueError("RollingTransformer requires DatetimeIndex")

        rolling_features = []
        new_feature_names = []

        for col in self.feature_names:
            for window in self.windows:
                for func in self.functions:
                    if func == "mean":
                        rolled = X[col].rolling(window=window).mean()
                    elif func == "std":
                        rolled = X[col].rolling(window=window).std()
                    elif func == "min":
                        rolled = X[col].rolling(window=window).min()
                    elif func == "max":
                        rolled = X[col].rolling(window=window).max()
                    elif func == "median":
                        rolled = X[col].rolling(window=window).median()
                    elif func == "sum":
                        rolled = X[col].rolling(window=window).sum()
                    else:
                        raise ValueError(f"Unknown rolling function: {func}")

                    rolling_features.append(rolled)
                    new_feature_names.append(f"{col}_roll_{window}_{func}")

        # Combine rolling features
        result = pd.concat(rolling_features, axis=1)
        result.columns = new_feature_names

        return result


class DifferenceTransformer(BaseEstimator, TransformerMixin):
    """Create difference features for time series data."""

    def __init__(self, periods: List[int] = [1]):
        """
        Initialize difference transformer.

        Args:
            periods: List of difference periods
        """
        self.periods = periods
        self.feature_names = None

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "DifferenceTransformer":
        """Fit transformer (just stores feature names)."""
        self.feature_names = X.columns.tolist()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create difference features.

        Args:
            X: Input features

        Returns:
            DataFrame with difference features
        """
        if not isinstance(X.index, pd.DatetimeIndex):
            raise ValueError("DifferenceTransformer requires DatetimeIndex")

        diff_features = []
        new_feature_names = []

        for col in self.feature_names:
            for period in self.periods:
                diff_col = X[col].diff(periods=period)
                diff_features.append(diff_col)
                new_feature_names.append(f"{col}_diff_{period}")

        # Combine difference features
        result = pd.concat(diff_features, axis=1)
        result.columns = new_feature_names

        return result


class InteractionTransformer(BaseEstimator, TransformerMixin):
    """Create interaction features between pairs of features."""

    def __init__(self, interactions: Optional[List[Tuple[str, str]]] = None,
                 max_features: int = 20):
        """
        Initialize interaction transformer.

        Args:
            interactions: List of feature pairs to interact
            max_features: Maximum number of interaction features to create
        """
        self.interactions = interactions
        self.max_features = max_features
        self.selected_interactions = None

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "InteractionTransformer":
        """
        Fit interaction transformer.

        Selects top interactions based on correlation with target if provided.
        """
        feature_names = X.columns.tolist()

        if self.interactions is None:
            # Create all possible pairs
            all_interactions = []
            for i, feat1 in enumerate(feature_names):
                for feat2 in feature_names[i+1:]:
                    all_interactions.append((feat1, feat2))

            # If target is provided, select interactions by correlation
            if y is not None:
                interaction_scores = []
                for feat1, feat2 in all_interactions:
                    interaction = X[feat1] * X[feat2]
                    corr = abs(interaction.corr(y))
                    interaction_scores.append((corr, (feat1, feat2)))

                # Sort by correlation and select top
                interaction_scores.sort(reverse=True)
                self.selected_interactions = [pair for _, pair in interaction_scores[:self.max_features]]
            else:
                # Just take first N interactions
                self.selected_interactions = all_interactions[:self.max_features]
        else:
            self.selected_interactions = self.interactions

        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create interaction features.

        Args:
            X: Input features

        Returns:
            DataFrame with interaction features
        """
        if self.selected_interactions is None:
            raise ValueError("Transformer not fitted")

        interaction_features = []
        new_feature_names = []

        for feat1, feat2 in self.selected_interactions:
            if feat1 in X.columns and feat2 in X.columns:
                # Multiplication interaction
                interaction = X[feat1] * X[feat2]
                interaction_features.append(interaction)
                new_feature_names.append(f"{feat1}_x_{feat2}")

                # Ratio interaction (if second feature is not zero)
                ratio = X[feat1] / (X[feat2] + 1e-8)  # Add small epsilon to avoid division by zero
                interaction_features.append(ratio)
                new_feature_names.append(f"{feat1}_div_{feat2}")

        # Combine interaction features
        result = pd.concat(interaction_features, axis=1)
        result.columns = new_feature_names

        return result


class BinningTransformer(BaseEstimator, TransformerMixin):
    """Bin continuous features into categorical bins."""

    def __init__(self, n_bins: int = 5, strategy: str = "quantile"):
        """
        Initialize binning transformer.

        Args:
            n_bins: Number of bins
            strategy: Binning strategy ('uniform', 'quantile', 'kmeans')
        """
        self.n_bins = n_bins
        self.strategy = strategy
        self.bin_edges = {}

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "BinningTransformer":
        """Fit binning transformer."""
        for col in X.columns:
            if self.strategy == "uniform":
                _, bins = pd.cut(X[col], bins=self.n_bins, retbins=True, duplicates='drop')
            elif self.strategy == "quantile":
                _, bins = pd.qcut(X[col], q=self.n_bins, retbins=True, duplicates='drop')
            else:
                raise ValueError(f"Unknown binning strategy: {self.strategy}")

            self.bin_edges[col] = bins

        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Transform features using binning.

        Args:
            X: Input features

        Returns:
            DataFrame with binned features
        """
        binned_features = []

        for col in X.columns:
            if col in self.bin_edges:
                binned = pd.cut(X[col], bins=self.bin_edges[col], include_lowest=True)
                # Convert to one-hot encoding
                dummies = pd.get_dummies(binned, prefix=col)
                binned_features.append(dummies)

        # Combine binned features
        if binned_features:
            result = pd.concat(binned_features, axis=1)
            return result
        else:
            return pd.DataFrame(index=X.index)


class TechnicalIndicatorTransformer(BaseEstimator, TransformerMixin):
    """Create technical indicator features."""

    def __init__(self, indicators: List[str] = None):
        """
        Initialize technical indicator transformer.

        Args:
            indicators: List of indicators to create
        """
        if indicators is None:
            indicators = ["rsi", "macd", "bb", "stoch", "williams"]
        self.indicators = indicators
        self.feature_names = None

    def fit(self, X: pd.DataFrame, y: Optional[pd.Series] = None) -> "TechnicalIndicatorTransformer":
        """Fit transformer (just stores feature names)."""
        self.feature_names = X.columns.tolist()
        return self

    def transform(self, X: pd.DataFrame) -> pd.DataFrame:
        """
        Create technical indicator features.

        Args:
            X: Input features (expects OHLCV data)

        Returns:
            DataFrame with technical indicators
        """
        if not isinstance(X.index, pd.DatetimeIndex):
            raise ValueError("TechnicalIndicatorTransformer requires DatetimeIndex")

        indicator_features = []
        new_feature_names = []

        # Identify OHLC columns
        open_col = self._find_column(X, ["open", "Open", "OPEN"])
        high_col = self._find_column(X, ["high", "High", "HIGH"])
        low_col = self._find_column(X, ["low", "Low", "LOW"])
        close_col = self._find_column(X, ["close", "Close", "CLOSE"])
        volume_col = self._find_column(X, ["volume", "Volume", "VOLUME"])

        for indicator in self.indicators:
            if indicator == "rsi" and close_col:
                rsi = self._calculate_rsi(X[close_col])
                indicator_features.append(rsi)
                new_feature_names.append(f"{close_col}_rsi")

            elif indicator == "macd" and close_col:
                macd_line, signal_line = self._calculate_macd(X[close_col])
                indicator_features.extend([macd_line, signal_line])
                new_feature_names.extend([f"{close_col}_macd", f"{close_col}_macd_signal"])

            elif indicator == "bb" and close_col:
                bb_upper, bb_lower = self._calculate_bollinger_bands(X[close_col])
                bb_width = bb_upper - bb_lower
                bb_position = (X[close_col] - bb_lower) / bb_width
                indicator_features.extend([bb_upper, bb_lower, bb_position])
                new_feature_names.extend([f"{close_col}_bb_upper", f"{close_col}_bb_lower", f"{close_col}_bb_position"])

            elif indicator == "stoch" and all([high_col, low_col, close_col]):
                stoch_k, stoch_d = self._calculate_stochastic(X[high_col], X[low_col], X[close_col])
                indicator_features.extend([stoch_k, stoch_d])
                new_feature_names.extend([f"{close_col}_stoch_k", f"{close_col}_stoch_d"])

            elif indicator == "williams" and all([high_col, low_col, close_col]):
                williams_r = self._calculate_williams_r(X[high_col], X[low_col], X[close_col])
                indicator_features.append(williams_r)
                new_feature_names.append(f"{close_col}_williams_r")

        # Combine indicator features
        if indicator_features:
            result = pd.concat(indicator_features, axis=1)
            result.columns = new_feature_names
            return result
        else:
            return pd.DataFrame(index=X.index)

    def _find_column(self, X: pd.DataFrame, candidates: List[str]) -> Optional[str]:
        """Find column name from candidates."""
        for candidate in candidates:
            if candidate in X.columns:
                return candidate
        return None

    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> pd.Series:
        """Calculate RSI indicator."""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _calculate_macd(self, prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series]:
        """Calculate MACD indicator."""
        exp1 = prices.ewm(span=fast).mean()
        exp2 = prices.ewm(span=slow).mean()
        macd = exp1 - exp2
        signal = macd.ewm(span=signal).mean()
        return macd, signal

    def _calculate_bollinger_bands(self, prices: pd.Series, period: int = 20, std_dev: int = 2) -> Tuple[pd.Series, pd.Series]:
        """Calculate Bollinger Bands."""
        sma = prices.rolling(window=period).mean()
        std = prices.rolling(window=period).std()
        upper_band = sma + (std * std_dev)
        lower_band = sma - (std * std_dev)
        return upper_band, lower_band

    def _calculate_stochastic(self, high: pd.Series, low: pd.Series, close: pd.Series, k_period: int = 14, d_period: int = 3) -> Tuple[pd.Series, pd.Series]:
        """Calculate Stochastic oscillator."""
        lowest_low = low.rolling(window=k_period).min()
        highest_high = high.rolling(window=k_period).max()
        k_percent = 100 * ((close - lowest_low) / (highest_high - lowest_low))
        d_percent = k_percent.rolling(window=d_period).mean()
        return k_percent, d_percent

    def _calculate_williams_r(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """Calculate Williams %R."""
        highest_high = high.rolling(window=period).max()
        lowest_low = low.rolling(window=period).min()
        wr = -100 * ((highest_high - close) / (highest_high - lowest_low))
        return wr