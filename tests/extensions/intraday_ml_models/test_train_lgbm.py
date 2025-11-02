"""Tests for LightGBMTrainer."""

import unittest

import numpy as np
import pandas as pd
import yaml

from extensions.intraday_ml_models.train_lgbm import LightGBMTrainer


class TestLightGBMTrainer(unittest.TestCase):
    def setUp(self):
        """Set up test data."""
        self.features = pd.DataFrame(
            {
                "f__feature1": np.random.rand(100),
                "f__feature2": np.random.rand(100),
            }
        )
        self.labels = pd.Series(np.random.randint(0, 3, 100), name="label")

    def test_trainer_with_loose_config(self):
        """Test that the trainer can be configured with the loose config."""
        with open("configs/extensions/intraday_ml/model_lgbm_loose.yaml") as f:
            config = yaml.safe_load(f)

        trainer = LightGBMTrainer(config)
        result = trainer.train_model(
            self.features, self.labels, "features_hash", "targets_hash"
        )

        self.assertIsNotNone(result.model)
        self.assertEqual(result.calibrated_model, result.model)  # No calibration

        # Check probability shape
        probs = result.model.predict_proba(self.features)
        self.assertEqual(probs.shape, (100, 3))

    def test_metrics_include_trade_density(self):
        """Test that the metrics dictionary includes the trade_density key."""
        with open("configs/extensions/intraday_ml/model_lgbm_loose.yaml") as f:
            config = yaml.safe_load(f)

        trainer = LightGBMTrainer(config)
        result = trainer.train_model(
            self.features, self.labels, "features_hash", "targets_hash"
        )

        self.assertIn("trade_density", result.metrics)
        self.assertIsInstance(result.metrics["trade_density"], float)


if __name__ == "__main__":
    unittest.main()
