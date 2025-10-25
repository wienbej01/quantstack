"""Tests for feature scanner v2."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from qx_scan.feature_scan import (
    cluster_duplicates,
    parse_for_features,
    scan_features_v2,
    should_include_file,
)


class TestFeatureScanV2:
    """Test feature scanner v2 functionality."""

    def test_should_include_file_allowlist(self):
        """Test file inclusion based on allowlist/denylist."""
        # Mock ALLOWLIST_ROOTS
        with patch("qx_scan.feature_scan.ALLOWLIST_ROOTS", ["/tmp/test_repo"]):
            # Allowed file
            allowed = Path("/tmp/test_repo/src/features.py")
            assert should_include_file(allowed)

            # Denied file
            denied = Path("/tmp/test_repo/.venv/lib/features.py")
            assert not should_include_file(denied)

            # Not in allowlist
            not_allowed = Path("/tmp/other_repo/src/features.py")
            assert not should_include_file(not_allowed)

    @pytest.fixture
    def sample_feature_file(self, tmp_path):
        """Create a sample Python file with feature functions."""
        content = '''
import pandas as pd

def f__test__vwap(df):
    """Calculate VWAP."""
    return df["close"] * df["volume"] / df["volume"].sum()

def old_feature_name(df):
    """Old style feature."""
    return df["close"].rolling(10).mean()

def non_feature_function(x):
    """Not a feature."""
    return x + 1
'''
        file_path = tmp_path / "features.py"
        file_path.write_text(content)
        return file_path

    def test_parse_for_features(self, sample_feature_file):
        """Test parsing features from file."""
        features = parse_for_features(sample_feature_file)

        # Should find f__test__vwap and old_feature_name, but not non_feature_function
        assert len(features) == 2

        names = [f["name"] for f in features]
        assert "f__test__vwap" in names
        assert "old_feature_name" in names
        assert "non_feature_function" not in names

        # Check standardization
        for feat in features:
            if feat["name"] == "old_feature_name":
                assert feat["needs_adapter"]
                assert feat["standardized_name"] == "f__features__old_feature_name"

    def test_cluster_duplicates(self):
        """Test duplicate clustering by content hash."""
        features = [
            {"name": "feat1", "content_hash": "hash1", "reuse_count": 1},
            {"name": "feat2", "content_hash": "hash1", "reuse_count": 1},  # Duplicate
            {"name": "feat3", "content_hash": "hash2", "reuse_count": 1},
        ]

        clustered = cluster_duplicates(features)

        # Should have 3 features, but duplicates marked
        assert len(clustered) == 3
        hash1_features = [f for f in clustered if f["content_hash"] == "hash1"]
        assert all(f["reuse_count"] == 2 for f in hash1_features)

    @patch("qx_scan.feature_scan.ALLOWLIST_ROOTS", [])
    def test_scan_features_v2_no_venv_noise(self):
        """Test that scan returns zero entries from .venv or denied paths."""
        result = scan_features_v2()

        # Should have empty catalog if no repos exist
        assert len(result["catalog"]) == 0

    def test_scan_features_v2_outputs(self, tmp_path):
        """Test that scan generates required outputs."""
        # Mock scan to return sample data
        sample_result = {
            "catalog": [
                {
                    "name": "test_feature",
                    "standardized_name": "f__test__test_feature",
                    "type": "function",
                    "file": "/tmp/test.py",
                    "callable": "test.test_feature",
                    "inputs": ["df"],
                    "outputs": ["feature_col"],
                    "feature_names": ["f__test__test_feature"],
                    "purity_flags": {"idempotent": True, "pure": True},
                    "reuse_count": 1,
                    "content_hash": "hash1",
                    "needs_adapter": False,
                    "docstring": "Test feature",
                }
            ],
            "conforming": [],
            "needing_adapters": [],
        }

        with patch("qx_scan.feature_scan.scan_features_v2", return_value=sample_result):
            from qx_scan.feature_scan import main

            main()

            out_dir = Path("~/quantstack/qx-scan/out").expanduser()
            assert (out_dir / "features_catalog_v2.json").exists()
            assert (out_dir / "features_catalog_v2.md").exists()
            assert (out_dir / "feature_adapters_todo.md").exists()

            # Check JSON content
            with open(out_dir / "features_catalog_v2.json") as f:
                data = json.load(f)
            assert "catalog" in data
