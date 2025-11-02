"""Sprint M1 Smoke Test

Tests the data loading and universe building pipeline for pilot symbols.
Validates that configs load, universe builds, and manifests generate correctly.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder

# Test imports
from extensions.intraday_ml.universe_adapter import IntradayMLUniverseAdapter


def test_universe_config_loading():
    """Test that universe config loads and validates correctly."""
    config_path = Path("configs/extensions/intraday_ml/universe.yaml")

    assert config_path.exists(), "universe.yaml should exist"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required fields
    assert "min_price" in config
    assert "max_price" in config
    assert config["min_price"] == 5.0
    assert config["max_price"] == 50.0

    # Validate ADV filter
    assert "min_avg_daily_volume" in config
    assert config["min_avg_daily_volume"] == 1_000_000


def test_cuts_config_loading():
    """Test that cuts config loads and validates correctly."""
    config_path = Path("configs/extensions/intraday_ml/cuts.yaml")

    assert config_path.exists(), "cuts.yaml should exist"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required fields
    assert "decision_cuts" in config
    assert "timezone" in config
    assert len(config["decision_cuts"]) == 4

    # Validate cut times
    expected_cuts = ["09:35:00", "11:00:00", "13:30:00", "14:30:00"]
    assert config["decision_cuts"] == expected_cuts


def test_splits_config_loading():
    """Test that splits config loads and validates correctly."""
    config_path = Path("configs/extensions/intraday_ml/splits.yaml")

    assert config_path.exists(), "splits.yaml should exist"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Validate required fields
    assert "train_months" in config
    assert "val_months" in config
    assert "oos_months" in config
    assert "embargo_days" in config

    # Validate durations
    assert config["train_months"] == 6
    assert config["val_months"] == 1
    assert config["oos_months"] == 1
    assert config["embargo_days"] == 5


def test_pilot_splits_window_lengths():
    """Pilot splits config uses shortened 6/1/1 window."""
    config_path = Path("configs/extensions/intraday_ml/splits_pilot.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    assert config["train"] == {"start": "2024-01-01", "end": "2024-06-30"}
    assert config["test"] == {"start": "2024-07-01", "end": "2024-07-31"}
    assert config["oos"] == {"start": "2024-08-01", "end": "2024-08-31"}


def test_universe_adapter_initialization():
    """Test that universe adapter initializes with correct config."""
    config_path = Path("configs/extensions/intraday_ml/universe.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    adapter = IntradayMLUniverseAdapter(config)

    # Validate SIP config mapping
    assert adapter.sip_config.min_price == 5.0
    assert adapter.sip_config.max_price == 50.0
    assert adapter.sip_config.top_n == 12


@patch("qx_data.gold_loader.load_bars")
def test_dataset_manifest_builder_initialization(mock_load_bars):
    """Test that dataset manifest builder initializes correctly."""
    # Load configs
    with open("configs/extensions/intraday_ml/universe.yaml") as f:
        universe_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/cuts.yaml") as f:
        cuts_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/splits.yaml") as f:
        splits_config = yaml.safe_load(f)

    builder = DatasetManifestBuilder(
        gold_root="/fake/gold/root",
        universe_config=universe_config,
        cuts_config=cuts_config,
        splits_config=splits_config,
    )

    # Validate initialization
    assert builder.gold_root == "/fake/gold/root"
    assert builder.universe_config == universe_config
    assert builder.cuts_config == cuts_config
    assert builder.splits_config == splits_config


def test_date_range_generation():
    """Test that date ranges generate correctly from config."""
    with open("configs/extensions/intraday_ml/splits.yaml") as f:
        splits_config = yaml.safe_load(f)

    with open("configs/extensions/intraday_ml/universe.yaml") as f:
        universe_config = yaml.safe_load(f)

    with open("configs/extensions/intraday_ml/cuts.yaml") as f:
        cuts_config = yaml.safe_load(f)

    builder = DatasetManifestBuilder(
        gold_root="/fake/gold/root",
        universe_config=universe_config,
        cuts_config=cuts_config,
        splits_config=splits_config,
    )

    date_ranges = builder._generate_date_ranges()

    # Validate split structure
    assert "train" in date_ranges
    assert "val" in date_ranges
    assert "oos" in date_ranges

    # Validate no overlap (simplified check)
    train_end = date_ranges["train"]["end"]
    val_start = date_ranges["val"]["start"]
    val_end = date_ranges["val"]["end"]
    oos_start = date_ranges["oos"]["start"]

    assert train_end < val_start
    assert val_end < oos_start


def test_smoke_build_pilot_symbols():
    """Smoke test building dataset for pilot symbols.

    This test validates the manifest generation process without requiring real data.
    It mocks the universe building to focus on manifest creation logic.
    """
    # Load configs
    with open("configs/extensions/intraday_ml/universe.yaml") as f:
        universe_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/cuts.yaml") as f:
        cuts_config = yaml.safe_load(f)
    with open("configs/extensions/intraday_ml/splits.yaml") as f:
        splits_config = yaml.safe_load(f)

    # Mock data loading to simulate pilot universe
    mock_bars_data = {
        "ts": ["2024-01-02 09:30:00"] * 4,
        "symbol": ["AAPL", "MSFT", "SPY", "QQQ"],
        "open": [150.0, 250.0, 400.0, 350.0],
        "high": [151.0, 251.0, 401.0, 351.0],
        "low": [149.0, 249.0, 399.0, 349.0],
        "close": [150.5, 250.5, 400.5, 350.5],
        "volume": [1_000_000, 800_000, 2_000_000, 1_500_000],
    }

    import pandas as pd

    mock_bars = pd.DataFrame(mock_bars_data)
    mock_bars["ts"] = pd.to_datetime(mock_bars["ts"])

    # Mock universe DataFrame
    mock_universe = pd.DataFrame(
        {
            "symbol": ["AAPL", "MSFT", "SPY", "QQQ"],
            "close": [150.5, 250.5, 400.5, 350.5],
            "volume": [1_000_000, 800_000, 2_000_000, 1_500_000],
            "relative_volume": [1.2, 0.9, 1.5, 1.1],
        }
    )

    # Mock both load_bars calls and build_universe
    with (
        patch("qx_data.gold_loader.load_bars", return_value=mock_bars),
        patch(
            "extensions.intraday_ml.universe_adapter.IntradayMLUniverseAdapter.build_universe",
            return_value=mock_universe,
        ),
    ):
        builder = DatasetManifestBuilder(
            gold_root="/fake/gold/root",
            universe_config=universe_config,
            cuts_config=cuts_config,
            splits_config=splits_config,
        )

        # Build manifest with pilot symbols
        candidate_symbols = ["AAPL", "MSFT", "SPY", "QQQ"]

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.json"

            manifest = builder.build_manifest(
                candidate_symbols=candidate_symbols, output_path=manifest_path
            )

            # Validate manifest structure
            assert manifest.total_symbols >= 4
            assert manifest.total_days > 0
            assert manifest.data_hash is not None
            assert manifest.config_hash is not None
            assert manifest.universe_hash is not None

            # Validate manifest file creation
            assert manifest_path.exists()

            # Validate manifest JSON structure
            with open(manifest_path) as f:
                saved_manifest = json.load(f)

            assert "symbols" in saved_manifest
            assert "date_ranges" in saved_manifest
            assert "data_hash" in saved_manifest
            assert len(saved_manifest["symbols"]) >= 4


if __name__ == "__main__":
    # Run tests when called directly
    pytest.main([__file__, "-v"])
