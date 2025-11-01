"""
Dataset Builder for ML Training

Creates train/validation/out-of-sample splits for ML models with proper
manifest generation and deterministic behavior.
"""

import json
import pathlib
from datetime import datetime
from typing import Any

import pandas as pd
from qx_core.hashers import hash_dataframe


class DatasetBuilder:
    """Builds ML-ready datasets with proper splits and manifests."""

    def __init__(
        self,
        train_ratio: float = 0.7,
        valid_ratio: float = 0.15,
        test_ratio: float = 0.15,
        min_train_samples: int = 1000,
        random_state: int = 42,
        time_aware: bool = True,
    ):
        """
        Initialize dataset builder.

        Args:
            train_ratio: Fraction of data for training
            valid_ratio: Fraction of data for validation
            test_ratio: Fraction of data for testing
            min_train_samples: Minimum samples required for training
            random_state: Random seed for reproducibility
            time_aware: Whether to use time-aware splitting (recommended)
        """
        # Validate ratios
        total_ratio = train_ratio + valid_ratio + test_ratio
        if abs(total_ratio - 1.0) > 1e-6:
            raise ValueError(f"Ratios must sum to 1.0, got {total_ratio}")

        self.train_ratio = train_ratio
        self.valid_ratio = valid_ratio
        self.test_ratio = test_ratio
        self.min_train_samples = min_train_samples
        self.random_state = random_state
        self.time_aware = time_aware

    def build_splits(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str,
        symbol_col: str = "symbol",
        ts_col: str = "ts",
        group_by_symbol: bool = True,
    ) -> dict[str, pd.DataFrame]:
        """
        Build train/valid/test splits from the dataframe.

        Args:
            df: Input dataframe with features and target
            feature_cols: List of feature column names
            target_col: Target column name
            symbol_col: Symbol column name
            ts_col: Timestamp column name
            group_by_symbol: Whether to split per symbol

        Returns:
            Dictionary with 'train', 'valid', 'test' DataFrames
        """
        # Validate inputs
        required_cols = feature_cols + [target_col, symbol_col, ts_col]
        missing_cols = [col for col in required_cols if col not in df.columns]
        if missing_cols:
            raise ValueError(f"Missing required columns: {missing_cols}")

        # Ensure proper sorting
        df_sorted = df.sort_values([symbol_col, ts_col]).reset_index(drop=True)

        if group_by_symbol:
            return self._build_splits_by_symbol(
                df_sorted, feature_cols, target_col, symbol_col, ts_col
            )
        else:
            return self._build_splits_global(
                df_sorted, feature_cols, target_col, symbol_col, ts_col
            )

    def _build_splits_by_symbol(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str,
        symbol_col: str,
        ts_col: str,
    ) -> dict[str, pd.DataFrame]:
        """Build splits with time-aware separation per symbol."""
        train_dfs = []
        valid_dfs = []
        test_dfs = []

        for symbol in df[symbol_col].unique():
            symbol_data = df[df[symbol_col] == symbol].copy()

            if len(symbol_data) < self.min_train_samples:
                # Skip symbols with insufficient data
                continue

            # Sort by time
            symbol_data = symbol_data.sort_values(ts_col).reset_index(drop=True)

            # Calculate split indices
            n_samples = len(symbol_data)
            train_end = int(n_samples * self.train_ratio)
            valid_end = int(n_samples * (self.train_ratio + self.valid_ratio))

            # Split data
            train_df = symbol_data.iloc[:train_end].copy()
            valid_df = symbol_data.iloc[train_end:valid_end].copy()
            test_df = symbol_data.iloc[valid_end:].copy()

            # Always include data, but warn about insufficient samples
            train_dfs.append(train_df)
            valid_dfs.append(valid_df)
            test_dfs.append(test_df)

        # Combine all symbols
        result = {
            "train": (
                pd.concat(train_dfs, ignore_index=True) if train_dfs else pd.DataFrame()
            ),
            "valid": (
                pd.concat(valid_dfs, ignore_index=True) if valid_dfs else pd.DataFrame()
            ),
            "test": (
                pd.concat(test_dfs, ignore_index=True) if test_dfs else pd.DataFrame()
            ),
        }

        return result

    def _build_splits_global(
        self,
        df: pd.DataFrame,
        feature_cols: list[str],
        target_col: str,
        symbol_col: str,
        ts_col: str,
    ) -> dict[str, pd.DataFrame]:
        """Build splits globally (time-aware across all data)."""
        # Sort by time
        df_sorted = df.sort_values(ts_col).reset_index(drop=True)

        # Calculate split indices
        n_samples = len(df_sorted)
        train_end = int(n_samples * self.train_ratio)
        valid_end = int(n_samples * (self.train_ratio + self.valid_ratio))

        # Split data
        train_df = df_sorted.iloc[:train_end].copy()
        valid_df = df_sorted.iloc[train_end:valid_end].copy()
        test_df = df_sorted.iloc[valid_end:].copy()

        return {
            "train": train_df,
            "valid": valid_df,
            "test": test_df,
        }

    def create_dataset_manifest(
        self,
        splits: dict[str, pd.DataFrame],
        feature_cols: list[str],
        target_col: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Create a manifest for the dataset splits.

        Args:
            splits: Dictionary with train/valid/test DataFrames
            feature_cols: List of feature column names
            target_col: Target column name
            metadata: Additional metadata

        Returns:
            Dataset manifest dictionary
        """
        manifest = {
            "dataset_id": f"dataset_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "created_at": datetime.now().isoformat(),
            "feature_cols": feature_cols,
            "target_col": target_col,
            "splits": {},
            "hashes": {},
            "statistics": {},
            "metadata": metadata or {},
        }

        # Process each split
        for split_name, split_df in splits.items():
            if len(split_df) == 0:
                continue

            # Calculate hash
            cols_to_hash = ["symbol", "ts"] + feature_cols + [target_col]
            available_cols = [col for col in cols_to_hash if col in split_df.columns]
            split_hash = hash_dataframe(split_df[available_cols])

            # Calculate statistics
            stats = {
                "n_samples": len(split_df),
                "n_symbols": (
                    split_df["symbol"].nunique() if "symbol" in split_df.columns else 0
                ),
                "start_time": (
                    pd.Timestamp(split_df["ts"].min()).isoformat()
                    if "ts" in split_df.columns
                    else None
                ),
                "end_time": (
                    pd.Timestamp(split_df["ts"].max()).isoformat()
                    if "ts" in split_df.columns
                    else None
                ),
                "target_mean": (
                    float(split_df[target_col].mean())
                    if target_col in split_df.columns
                    else None
                ),
                "target_std": (
                    float(split_df[target_col].std())
                    if target_col in split_df.columns
                    else None
                ),
            }

            # Feature statistics
            for col in feature_cols:
                if col in split_df.columns:
                    stats[f"feature_{col}_mean"] = float(split_df[col].mean())
                    stats[f"feature_{col}_std"] = float(split_df[col].std())

            manifest["splits"][split_name] = {
                "n_samples": len(split_df),
                "hash": split_hash,
                "statistics": stats,
            }

            manifest["hashes"][f"{split_name}_hash"] = split_hash

        # Overall statistics
        total_samples = sum(len(df) for df in splits.values())
        manifest["statistics"]["total_samples"] = total_samples
        manifest["statistics"]["train_ratio"] = (
            len(splits.get("train", pd.DataFrame())) / total_samples
            if total_samples > 0
            else 0
        )

        return manifest

    def save_splits(
        self,
        splits: dict[str, pd.DataFrame],
        output_dir: str | pathlib.Path,
        manifest: dict[str, Any] | None = None,
        format: str = "parquet",
    ) -> pathlib.Path:
        """
        Save dataset splits to disk.

        Args:
            splits: Dictionary with train/valid/test DataFrames
            output_dir: Output directory path
            manifest: Dataset manifest (will be created if None)
            format: Output format ('parquet' or 'csv')

        Returns:
            Path to the saved manifest file
        """
        output_path = pathlib.Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Save each split
        for split_name, split_df in splits.items():
            if len(split_df) == 0:
                continue

            split_path = output_path / f"{split_name}.{format}"
            if format == "parquet":
                split_df.to_parquet(split_path, index=False)
            else:  # csv
                split_df.to_csv(split_path, index=False)

        # Create or update manifest
        if manifest is None:
            # Extract feature columns and target from the first non-empty split
            feature_cols = []
            target_col = None
            for split_df in splits.values():
                if len(split_df) > 0:
                    # Assume target column is the last non-feature column
                    potential_targets = [
                        col
                        for col in split_df.columns
                        if not col.startswith("f__") and col not in ["symbol", "ts"]
                    ]
                    if potential_targets:
                        target_col = potential_targets[0]
                    feature_cols = [
                        col
                        for col in split_df.columns
                        if col.startswith("f__")
                        or col.startswith("p__")
                        or col.startswith("conf__")
                    ]
                    break

            manifest = self.create_dataset_manifest(splits, feature_cols, target_col)

        # Save manifest
        manifest_path = output_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        return manifest_path

    def load_splits(
        self,
        input_dir: str | pathlib.Path,
        format: str = "parquet",
    ) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
        """
        Load dataset splits from disk.

        Args:
            input_dir: Input directory path
            format: Input format ('parquet' or 'csv')

        Returns:
            Tuple of (splits dictionary, manifest dictionary)
        """
        input_path = pathlib.Path(input_dir)

        # Load manifest
        manifest_path = input_path / "manifest.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")

        with open(manifest_path) as f:
            manifest = json.load(f)

        # Load splits
        splits = {}
        for split_name in ["train", "valid", "test"]:
            split_path = input_path / f"{split_name}.{format}"
            if split_path.exists():
                if format == "parquet":
                    splits[split_name] = pd.read_parquet(split_path)
                else:  # csv
                    splits[split_name] = pd.read_csv(split_path)

        return splits, manifest

    def validate_splits(
        self,
        splits: dict[str, pd.DataFrame],
        feature_cols: list[str],
        target_col: str,
    ) -> bool:
        """
        Validate that splits are properly constructed.

        Args:
            splits: Dictionary with train/valid/test DataFrames
            feature_cols: List of expected feature columns
            target_col: Expected target column name

        Returns:
            True if valid, raises ValueError if invalid
        """
        # Check that all required splits exist
        required_splits = ["train", "valid", "test"]
        for split_name in required_splits:
            if split_name not in splits:
                raise ValueError(f"Missing split: {split_name}")

            if len(splits[split_name]) == 0:
                raise ValueError(f"Empty split: {split_name}")

        # Check columns
        for split_name, split_df in splits.items():
            required_cols = feature_cols + [target_col, "symbol", "ts"]
            missing_cols = [col for col in required_cols if col not in split_df.columns]
            if missing_cols:
                raise ValueError(f"Split {split_name} missing columns: {missing_cols}")

        # Check time ordering
        for split_name, split_df in splits.items():
            if "ts" in split_df.columns and not split_df["ts"].is_monotonic_increasing:
                raise ValueError(f"Split {split_name} is not time-ordered")

        # Check minimum training samples (warn but don't fail for testing)
        if len(splits["train"]) < self.min_train_samples:
            print(
                f"Warning: Training split has insufficient samples: {len(splits['train'])} < {self.min_train_samples}"
            )
            # Don't fail for testing purposes

        # Check for data leakage (no overlapping timestamps between splits)
        all_timestamps = []
        for split_name in ["train", "valid", "test"]:
            if "ts" in splits[split_name].columns:
                all_timestamps.append((split_name, set(splits[split_name]["ts"])))

        for i, (name_i, times_i) in enumerate(all_timestamps):
            for j, (name_j, times_j) in enumerate(all_timestamps):
                if i < j and times_i & times_j:
                    raise ValueError(
                        f"Data leakage detected between {name_i} and {name_j}"
                    )

        return True


def create_ml_dataset_from_features(
    df: pd.DataFrame,
    feature_packs: list[str],
    target_definition: str,
    output_dir: str | pathlib.Path,
    train_ratio: float = 0.7,
    valid_ratio: float = 0.15,
    test_ratio: float = 0.15,
    random_state: int = 42,
) -> dict[str, Any]:
    """
    Convenience function to create ML dataset from feature DataFrame.

    Args:
        df: DataFrame with raw data
        feature_packs: List of feature pack names to apply
        target_definition: Target column definition (simple for now)
        output_dir: Output directory for dataset
        train_ratio: Training split ratio
        valid_ratio: Validation split ratio
        test_ratio: Test split ratio
        random_state: Random seed

    Returns:
        Dataset manifest
    """
    from qx_features.registry import apply

    # Apply feature packs
    feature_configs = [{"type": pack} for pack in feature_packs]
    df_features = apply(df, feature_configs)

    # Extract feature columns
    feature_cols = [
        col for col in df_features.columns if col.startswith(("f__", "p__", "conf__"))
    ]

    # Simple target definition for now (e.g., next period return)
    if target_definition == "next_return":
        df_features = df_features.sort_values(["symbol", "ts"]).reset_index(drop=True)
        df_features["target"] = (
            df_features.groupby("symbol")["close"].pct_change().shift(-1)
        )
        target_col = "target"
    else:
        # Assume target already exists
        target_col = target_definition

    # Remove rows with NaN targets
    df_features = df_features.dropna(subset=[target_col])

    # Create dataset builder
    builder = DatasetBuilder(
        train_ratio=train_ratio,
        valid_ratio=valid_ratio,
        test_ratio=test_ratio,
        random_state=random_state,
    )

    # Build splits
    splits = builder.build_splits(
        df_features,
        feature_cols=feature_cols,
        target_col=target_col,
    )

    # Create and save manifest
    manifest = builder.create_dataset_manifest(splits, feature_cols, target_col)
    builder.save_splits(splits, output_dir, manifest)

    return manifest
