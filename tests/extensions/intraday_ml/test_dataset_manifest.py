"""Tests for DatasetManifestBuilder."""

import pandas as pd
import unittest
from unittest.mock import patch

from extensions.intraday_ml.dataset_manifest import DatasetManifestBuilder
from extensions.intraday_ml.universe_adapter import IntradayMLUniverseAdapter


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

    def test_collects_universe_diagnostics(self):
        """Ensure manifest builder retains diagnostics produced by the universe adapter."""
        splits_config = {
            "train": {"start": "2025-01-01", "end": "2025-01-02"},
            "val": {"start": "2025-01-03", "end": "2025-01-03"},
            "oos": {"start": "2025-01-04", "end": "2025-01-04"},
        }

        fake_bars = pd.DataFrame(
            {
                "ts": [1, 2],
                "symbol": ["A", "A"],
                "open": [1, 1],
                "high": [2, 2],
                "low": [0.5, 0.5],
                "close": [1.0, 1.0],
                "volume": [100, 100],
            }
        )

        diagnostics = {
            "A": {
                "coverage": {"total_days": 4, "train_days": 2, "val_days": 1, "oos_days": 1},
                "avg_daily_dollar_volume": 500_000.0,
                "latest_close": 1.0,
                "relative_volume": 1.2,
                "selected": True,
                "reasons": [],
            }
        }

        def fake_build_universe(
            self,
            gold_root: str,
            symbols: list[str],
            dates: list[str],
            reference_date: str | None = None,
            date_ranges: dict[str, dict[str, str]] | None = None,
            collect_diagnostics: bool | None = None,
        ) -> pd.DataFrame:
            self._last_screening_report = diagnostics
            return pd.DataFrame(
                {
                    "symbol": ["A"],
                    "close": [1.0],
                    "volume": [100],
                    "relative_volume": [1.0],
                    "dollar_volume": [100],
                }
            )

        with patch("qx_data.gold_loader.load_bars", return_value=fake_bars), patch.object(
            IntradayMLUniverseAdapter, "build_universe", fake_build_universe
        ):
            builder = DatasetManifestBuilder(
                gold_root="",
                universe_config={},
                cuts_config={},
                splits_config=splits_config,
            )
            builder.build_manifest(candidate_symbols=["A"], output_path=None)

        report = builder.get_last_universe_report()
        self.assertIsNotNone(report)
        self.assertIn("A", report)
        self.assertEqual(report["A"]["coverage"]["train_days"], 2)
        self.assertTrue(report["A"]["selected"])
        self.assertEqual(report["A"]["avg_daily_dollar_volume"], 500_000.0)


if __name__ == "__main__":
    unittest.main()
