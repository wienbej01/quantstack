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

        # Relax guards for synthetic data
        guard = config.setdefault("training", {}).setdefault("abstention_guard", {})
        guard["max_trade_density"] = 1.0
        guard["min_abstention_rate"] = 0.0
        guard["fail_on_worse_than_baseline"] = False

        trainer = LightGBMTrainer(config)
        result = trainer.train_model(self.features, self.labels, "features_hash", "targets_hash")

        self.assertIsNotNone(result.model)
        self.assertIsNotNone(result.calibrated_model)

        # Check probability shape
        probs = result.model.predict_proba(self.features)
        self.assertEqual(probs.shape, (100, 3))

    def test_metrics_include_trade_density(self):
        """Test that the metrics dictionary includes the trade_density key."""
        with open("configs/extensions/intraday_ml/model_lgbm_loose.yaml") as f:
            config = yaml.safe_load(f)

        guard = config.setdefault("training", {}).setdefault("abstention_guard", {})
        guard["max_trade_density"] = 1.0
        guard["min_abstention_rate"] = 0.0
        guard["fail_on_worse_than_baseline"] = False

        trainer = LightGBMTrainer(config)
        result = trainer.train_model(self.features, self.labels, "features_hash", "targets_hash")

        self.assertIn("trade_density", result.metrics)
        self.assertIsInstance(result.metrics["trade_density"], float)

    def test_training_guard_blocks_high_trade_density(self):
        """Ensure guard rails raise when trade density is excessive."""
        with open("configs/extensions/intraday_ml/model_lgbm_loose.yaml") as f:
            config = yaml.safe_load(f)

        config.setdefault("training", {}).setdefault("abstention_guard", {})[
            "max_trade_density"
        ] = 0.1

        trainer = LightGBMTrainer(config)
        high_churn_labels = pd.Series(np.random.choice([-1, 1], size=120), name="label")

        with self.assertRaises(ValueError):
            trainer.train_model(self.features, high_churn_labels, "hash_f", "hash_t")

    def test_topk_metrics_present(self):
        """Top-K metrics should be computed when enabled."""
        with open("configs/extensions/intraday_ml/model_lgbm_loose.yaml") as f:
            config = yaml.safe_load(f)

        guard = config.setdefault("training", {}).setdefault("abstention_guard", {})
        guard["max_trade_density"] = 1.0
        guard["min_abstention_rate"] = 0.0
        guard["fail_on_worse_than_baseline"] = False

        trainer = LightGBMTrainer(config)
        result = trainer.train_model(self.features, self.labels, "f_hash", "t_hash")

        topk = result.metrics.get("topk_metrics")
        self.assertIsInstance(topk, dict)
        self.assertIn("estimated_days", topk)


if __name__ == "__main__":
    unittest.main()
