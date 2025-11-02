#!/usr/bin/env python3
"""
Test and benchmark the production (vectorized) feature pack.
"""

import sys
import time
from pathlib import Path

import pandas as pd
import pytest
import yaml

# Add project paths
sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))

from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack

# Import the production feature pack
from qx_data.gold_loader import load_bars


@pytest.fixture(scope="module")
def test_data():
    """Load one day of real data for testing."""
    symbols = ["BAC"]
    dates = ["2024-01-04"]
    df = load_bars(
        root="/home/jacobw/gcs-mount",
        family="bars_1m",
        symbols=symbols,
        dates=dates,
    )
    # Keep timestamps as integers, as the backtest engine expects
    return df


@pytest.fixture(scope="module")
def feature_config():
    """Load the feature configuration."""
    config_path = Path("configs/extensions/intraday_ml/features.yaml")
    with open(config_path) as f:
        return yaml.safe_load(f)


def test_feature_pack_execution(test_data, feature_config):
    """Test that the production feature pack runs without errors and produces valid output."""
    print("\n--- Testing production feature pack execution ---")

    pack = IntradayMLFeaturePack(feature_config)

    start_time = time.time()
    features = pack.compute_features_vectorized(test_data)
    duration = time.time() - start_time
    print(f"Feature generation took: {duration:.4f} seconds")

    assert isinstance(features, pd.DataFrame)
    assert not features.empty
    assert (
        len(features.columns) > 20
    )  # Check that a reasonable number of features were generated
    print("✅ Feature pack executed successfully and produced a valid DataFrame.")
