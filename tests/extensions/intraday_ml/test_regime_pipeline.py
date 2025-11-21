import unittest
from unittest.mock import MagicMock, patch
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

from extensions.intraday_ml.market_context import load_market_context
from extensions.intraday_ml.feature_pack import IntradayMLFeaturePack
from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy

class TestRegimePipeline(unittest.TestCase):
    
    def setUp(self):
        # Mock data for feature pack
        dates = pd.date_range(start="2024-01-01 09:30", periods=100, freq="1min", tz="UTC")
        self.df = pd.DataFrame({
            "ts": dates,
            "symbol": "AAPL",
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.5,
            "volume": 1000
        })
        # Add some volatility
        self.df["close"] = 100 + np.random.randn(100)
        
        # Mock Market Context
        self.market_context = pd.DataFrame({
            "SPY_close": 400 + np.random.randn(100),
            "VIX_close": 20 + np.random.randn(100)
        }, index=dates)

    @patch("extensions.intraday_ml.market_context.load_bars")
    def test_load_market_context(self, mock_load_bars):
        # Mock return from load_bars
        mock_df = pd.DataFrame({
            "ts": [pd.Timestamp("2024-01-01 09:30", tz="UTC")],
            "symbol": ["SPY"],
            "close": [400.0],
            "open": [400.0], 
            "high": [400.0], 
            "low": [400.0], 
            "volume": [1000]
        })
        mock_load_bars.return_value = mock_df
        
        df = load_market_context("2024-01-01", "2024-01-01")
        self.assertIn("SPY_close", df.columns)
        self.assertIsInstance(df.index, pd.DatetimeIndex)

    def test_feature_generation(self):
        config = {
            "families": {
                "market_relative_strength": {"enabled": True},
                "market_regime": {"enabled": True},
                "price_volume_proxy": {"enabled": True}
            }
        }
        pack = IntradayMLFeaturePack(config)
        ts_cut = self.df["ts"].iloc[-1]
        
        features = pack.compute_features(self.df, ts_cut, market_context=self.market_context)
        
        # Check existence of new features
        self.assertIn("f__mkt__rel_str_15m", features.columns)
        self.assertIn("f__regime__vix_level", features.columns)
        self.assertIn("f__vpa__ease_of_movement", features.columns)
        
        # Check logic for VIX (should match market_context)
        # Since df and market_context are aligned by row in this test setup:
        self.assertTrue(np.allclose(features["f__regime__vix_level"].values, self.market_context["VIX_close"].values))

    def test_policy_regime_gate(self):
        config = {
            "regime": {"max_vix": 30.0},
            "sector_limits": {"max_per_sector": 1, "map": {"AAPL": "Tech"}}
        }
        policy = IntradayMLDecisionPolicy(config)
        
        # Case 1: High VIX -> Reject
        row = pd.Series({
            "ts": pd.Timestamp("2024-01-01 15:00", tz="UTC"),
            "symbol": "AAPL",
            "f__regime__vix_level": 35.0, # > 30
            "prob_long": 0.6,
            "prob_short": 0.1,
            "prob_neutral": 0.3,
            "close": 100.0
        })
        
        orders, rejections = policy.process_signals(pd.DataFrame([row]))
        self.assertTrue(orders.empty)
        self.assertFalse(rejections.empty)
        self.assertEqual(rejections.iloc[0]["reason"], "regime_high_vix")

        # Case 2: Normal VIX -> Accept
        row["f__regime__vix_level"] = 20.0
        orders, rejections = policy.process_signals(pd.DataFrame([row]))
        self.assertFalse(orders.empty)
        
        # Case 3: Sector Limit
        policy.active_sector_counts = {"Tech": 1} # Limit reached
        orders, rejections = policy.process_signals(pd.DataFrame([row]))
        self.assertTrue(orders.empty)
        self.assertEqual(rejections.iloc[0]["reason"], "max_sector_exposure")

if __name__ == "__main__":
    unittest.main()
