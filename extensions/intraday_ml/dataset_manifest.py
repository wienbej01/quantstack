"""Dataset Manifest for Intraday ML

Creates and manages dataset manifests with data hashing for reproducibility.
Emits manifests with symbol lists, date ranges, and data integrity hashes.
"""

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import dateutil.relativedelta
import pandas as pd

from qx_core.hashers import hash_dataframe


def _ts_to_iso(value: Any) -> str:
    """Convert assorted timestamp representations to ISO8601 strings."""
    ts = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(ts):
        return str(value)
    return ts.isoformat()


from .universe_adapter import IntradayMLUniverseAdapter


@dataclass
class DatasetManifest:
    """Dataset manifest with metadata and hashes."""

    # Basic metadata (no defaults first)
    created_at: str
    gold_root: str
    symbols: list[str]
    date_ranges: dict[str, dict[str, str]]  # split -> {start, end}
    data_hash: str
    config_hash: str
    universe_hash: str
    universe_config: dict[str, Any]
    cuts_config: dict[str, Any]
    splits_config: dict[str, Any]
    total_symbols: int
    total_days: int
    universe_stats: dict[str, Any]
    features_hash: str | None = None
    version: str = "1.0"  # Default values last


class DatasetManifestBuilder:
    """Builder for creating dataset manifests."""

    def __init__(
        self,
        gold_root: str,
        universe_config: dict[str, Any],
        cuts_config: dict[str, Any],
        splits_config: dict[str, Any],
        features_config: dict[str, Any] | None = None,
    ):
        """Initialize manifest builder.

        Args:
            gold_root: Path to Gold data root
            universe_config: Universe configuration dictionary
            cuts_config: Cut times configuration dictionary
            splits_config: Split configuration dictionary
            features_config: Features configuration dictionary
        """
        self.gold_root = gold_root
        self.universe_config = universe_config
        self.cuts_config = cuts_config
        self.splits_config = splits_config
        self.features_config = features_config

        self.universe_adapter = IntradayMLUniverseAdapter(universe_config)

    def build_manifest(
        self, candidate_symbols: list[str], output_path: Path | None = None
    ) -> DatasetManifest:
        """Build dataset manifest with hashes and metadata.

        Args:
            candidate_symbols: List of candidate symbols to screen
            output_path: Optional path to save manifest

        Returns:
            DatasetManifest instance
        """
        # Generate date splits
        date_ranges = self._generate_date_ranges()

        # Build universe and compute hashes
        all_dates = []
        for _split_name, split_dates in date_ranges.items():
            if split_dates and "start" in split_dates and "end" in split_dates:
                all_dates.extend(self._get_date_list(split_dates["start"], split_dates["end"]))
        all_dates = sorted(set(all_dates))

        # Load data for hashing
        from qx_data.gold_loader import load_bars

        bars = load_bars(
            root=self.gold_root,
            family="bars_1m",
            symbols=candidate_symbols,
            dates=all_dates,
            validate=True,
            sort=True,
        )

        # Compute hashes
        data_hash = self._compute_data_hash(bars)
        config_hash = self._compute_config_hash()

        # Build universe
        universe = self.universe_adapter.build_universe(
            gold_root=self.gold_root,
            symbols=candidate_symbols,
            dates=all_dates,
            date_ranges=date_ranges,
            collect_diagnostics=True,
        )
        universe_hash = self._compute_universe_hash(universe)

        # Get universe statistics
        universe_stats = self.universe_adapter.get_eligibility_counts(universe)
        selected_symbols = universe["symbol"].tolist()

        # Compute features hash if features config is available
        features_hash = None
        if self.features_config:
            features_hash = self._compute_features_hash(
                bars[bars["symbol"].isin(selected_symbols)], self.features_config
            )

        # Create manifest
        manifest = DatasetManifest(
            created_at=datetime.utcnow().isoformat() + "Z",
            gold_root=self.gold_root,
            symbols=selected_symbols,
            date_ranges=date_ranges,
            data_hash=data_hash,
            config_hash=config_hash,
            universe_hash=universe_hash,
            universe_config=self.universe_config,
            cuts_config=self.cuts_config,
            splits_config=self.splits_config,
            total_symbols=len(selected_symbols),
            total_days=len(all_dates),
            universe_stats=universe_stats,
            features_hash=features_hash,
        )

        # Save if path provided
        if output_path:
            self._save_manifest(manifest, output_path)

        return manifest

    def get_last_universe_report(self) -> dict[str, dict] | None:
        """Expose the latest universe diagnostics collected during manifest build."""
        return self.universe_adapter.get_last_screening_report()

    def _generate_date_ranges(self) -> dict[str, dict[str, str]]:
        """Generate Train/Val/OOS date ranges from config."""
        if "train" in self.splits_config and "start" in self.splits_config["train"]:
            return {
                "train": self.splits_config["train"],
                "val": self.splits_config.get("val", {}),
                "test": self.splits_config.get("test", {}),
                "oos": self.splits_config.get("oos", {}),
            }

        # Fallback to original logic
        # Parse pilot start date
        start_date = datetime.strptime(
            self.splits_config.get("pilot_start_date", "2024-01-01"), "%Y-%m-%d"
        )

        # Get durations
        train_months = self.splits_config.get("train_months", 12)
        val_months = self.splits_config.get("val_months", 1)
        oos_months = self.splits_config.get("oos_months", 1)

        # Calculate end dates

        train_end = (
            start_date
            + dateutil.relativedelta.relativedelta(months=train_months)
            - dateutil.relativedelta.relativedelta(days=1)
        )
        val_start = train_end + dateutil.relativedelta.relativedelta(days=1)
        val_end = (
            val_start
            + dateutil.relativedelta.relativedelta(months=val_months)
            - dateutil.relativedelta.relativedelta(days=1)
        )
        oos_start = val_end + dateutil.relativedelta.relativedelta(days=1)
        oos_end = (
            oos_start
            + dateutil.relativedelta.relativedelta(months=oos_months)
            - dateutil.relativedelta.relativedelta(days=1)
        )

        return {
            "train": {
                "start": start_date.strftime("%Y-%m-%d"),
                "end": train_end.strftime("%Y-%m-%d"),
            },
            "val": {
                "start": val_start.strftime("%Y-%m-%d"),
                "end": val_end.strftime("%Y-%m-%d"),
            },
            "oos": {
                "start": oos_start.strftime("%Y-%m-%d"),
                "end": oos_end.strftime("%Y-%m-%d"),
            },
        }

    def _get_date_list(self, start_date: str, end_date: str) -> list[str]:
        """Get list of dates between start and end inclusive."""
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        dates = []
        current = start
        while current <= end:
            dates.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        return dates

    def _compute_data_hash(self, bars: pd.DataFrame) -> str:
        """Compute hash of the loaded data."""
        # Hash core columns for data integrity
        core_cols = ["ts", "symbol", "open", "high", "low", "close", "volume"]
        return hash_dataframe(bars, cols=core_cols, index=False)

    def _compute_config_hash(self) -> str:
        """Compute hash of all configuration dictionaries."""
        config_data = {
            "universe": self.universe_config,
            "cuts": self.cuts_config,
            "splits": self.splits_config,
        }
        config_str = json.dumps(config_data, sort_keys=True, default=str)
        return hashlib.blake2b(config_str.encode()).hexdigest()

    def _compute_universe_hash(self, universe: pd.DataFrame) -> str:
        """Compute hash of selected universe."""
        # Hash symbol list and key metrics
        universe_data = {
            "symbols": sorted(universe["symbol"].tolist()),
            "prices": universe["close"].round(2).tolist(),
            "volumes": (universe["volume"].tolist() if "volume" in universe.columns else []),
        }
        universe_str = json.dumps(universe_data, sort_keys=True, default=str)
        return hashlib.blake2b(universe_str.encode()).hexdigest()

    def _compute_features_hash(self, bars: pd.DataFrame, features_config: dict[str, Any]) -> str:
        """Compute features hash for given data and configuration.

        Args:
            bars: DataFrame with bar data
            features_config: Features configuration dictionary

        Returns:
            Hash string for feature identification
        """
        feature_info = {
            "symbols": sorted(bars["symbol"].unique().tolist()),
            "date_range": [
                _ts_to_iso(bars["ts"].min()),
                _ts_to_iso(bars["ts"].max()),
            ],
            "features_config": features_config,
            "data_hash": hash_dataframe(bars, cols=["open", "high", "low", "close", "volume"]),
        }
        feature_str = json.dumps(feature_info, sort_keys=True, default=str)
        return hashlib.blake2b(feature_str.encode()).hexdigest()

    def _save_manifest(self, manifest: DatasetManifest, output_path: Path):
        """Save manifest to file."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        manifest_dict = asdict(manifest)
        with open(output_path, "w") as f:
            json.dump(manifest_dict, f, indent=2, default=str)


def intraday_ml_get_data_hash(symbols: list[str], dates: list[str], vendor: str = "gold") -> str:
    """Compute data hash for given symbols and dates.

    Args:
        symbols: List of symbols
        dates: List of date strings
        vendor: Data vendor identifier

    Returns:
        Hash string for data identification
    """
    data_info = {
        "symbols": sorted(symbols),
        "dates": sorted(dates),
        "vendor": vendor,
        "family": "bars_1m",
    }
    data_str = json.dumps(data_info, sort_keys=True)
    return hashlib.blake2b(data_str.encode()).hexdigest()


def intraday_ml_get_features_hash(bars: pd.DataFrame, features_config: dict[str, Any]) -> str:
    """Compute features hash for given data and configuration.

    Args:
        bars: DataFrame with bar data
        features_config: Features configuration dictionary

    Returns:
        Hash string for feature identification
    """
    feature_info = {
        "symbols": sorted(bars["symbol"].unique().tolist()),
        "date_range": [
            _ts_to_iso(bars["ts"].min()),
            _ts_to_iso(bars["ts"].max()),
        ],
        "features_config": features_config,
        "data_hash": hash_dataframe(bars, cols=["open", "high", "low", "close", "volume"]),
    }
    feature_str = json.dumps(feature_info, sort_keys=True, default=str)
    return hashlib.blake2b(feature_str.encode()).hexdigest()
