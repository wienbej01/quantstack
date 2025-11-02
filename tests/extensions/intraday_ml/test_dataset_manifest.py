"""Tests for DatasetManifestBuilder."""

import unittest

from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder


class TestDatasetManifestBuilder(unittest.TestCase):
    def test_generate_date_ranges_from_fixed_dates(self):
        """Test that date ranges are correctly generated from fixed dates."""
        splits_config = {
            "train": {"start": "2025-07-01", "end": "2025-09-30"},
            "test": {"start": "2025-10-01", "end": "2025-10-31"},
            "oos": {"start": "2025-11-01", "end": "2025-11-30"},
        }
        builder = DatasetManifestBuilder(
            gold_root="",
            universe_config={},
            cuts_config={},
            splits_config=splits_config,
        )
        date_ranges = builder._generate_date_ranges()
        self.assertEqual(date_ranges["train"]["start"], "2025-07-01")
        self.assertEqual(date_ranges["train"]["end"], "2025-09-30")
        self.assertEqual(date_ranges["test"]["start"], "2025-10-01")
        self.assertEqual(date_ranges["test"]["end"], "2025-10-31")
        self.assertEqual(date_ranges["oos"]["start"], "2025-11-01")
        self.assertEqual(date_ranges["oos"]["end"], "2025-11-30")

    def test_generate_date_ranges_from_rules(self):
        """Test that date ranges are correctly generated from rules."""
        splits_config = {
            "pilot_start_date": "2024-01-01",
            "train_months": 2,
            "val_months": 1,
            "oos_months": 1,
        }
        builder = DatasetManifestBuilder(
            gold_root="",
            universe_config={},
            cuts_config={},
            splits_config=splits_config,
        )
        date_ranges = builder._generate_date_ranges()
        self.assertEqual(date_ranges["train"]["start"], "2024-01-01")
        self.assertEqual(date_ranges["train"]["end"], "2024-02-29")
        self.assertEqual(date_ranges["val"]["start"], "2024-03-01")
        self.assertEqual(date_ranges["val"]["end"], "2024-03-31")
        self.assertEqual(date_ranges["oos"]["start"], "2024-04-01")
        self.assertEqual(date_ranges["oos"]["end"], "2024-04-30")


if __name__ == "__main__":
    unittest.main()
