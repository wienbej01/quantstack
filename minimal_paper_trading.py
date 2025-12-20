#!/usr/bin/env python3
"""Minimal paper trading system with regime-aware ML."""

import os
import sys

sys.path.insert(0, "/home/jacobw/quantstack")

import logging
import pickle
import time
from datetime import datetime

import numpy as np
import pandas as pd

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger(__name__)


class MinimalPaperTrader:
    def __init__(self):
        self.models = self.load_models()
        self.symbols = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA", "META", "JPM"]
        self.positions = {}
        self.cash = 100000

    def load_models(self):
        """Load trained regime models."""
        models = {}
        model_dir = "/home/jacobw/quantstack/models/regime_aware"

        for regime in ["bull", "bear", "sideways"]:
            try:
                with open(f"{model_dir}/{regime}_model.pkl", "rb") as f:
                    models[regime] = pickle.load(f)
                logger.info(f"✅ Loaded {regime} model")
            except Exception as e:
                logger.error(f"❌ Failed to load {regime} model: {e}")

        return models

    def detect_regime(self):
        """Simple regime detection - normally would use market data."""
        # For demo, cycle through regimes
        hour = datetime.now().hour
        if hour < 12:
            return "bull"
        elif hour < 16:
            return "sideways"
        else:
            return "bear"

    def generate_mock_features(self, symbol):
        """Generate mock features for demo."""
        np.random.seed(hash(symbol + str(int(time.time()))) % 2**32)
        return np.random.randn(11)  # 11 features as per trained models

    def make_prediction(self, symbol):
        """Make ML prediction for symbol."""
        regime = self.detect_regime()

        if regime not in self.models:
            return 0

        features = self.generate_mock_features(symbol)
        model = self.models[regime]

        try:
            prediction = model.predict([features])[0]
            confidence = model.predict_proba([features])[0].max()
            return prediction if confidence > 0.6 else 0
        except:
            return 0

    def execute_trades(self):
        """Execute paper trades based on predictions."""
        trades = []

        for symbol in self.symbols:
            prediction = self.make_prediction(symbol)

            if abs(prediction) > 0.5:  # Confidence threshold
                position_size = min(1000, self.cash * 0.1)  # 10% of cash, max $1000

                trade = {
                    "symbol": symbol,
                    "action": "BUY" if prediction > 0 else "SELL",
                    "size": int(
                        position_size / 100
                    ),  # Convert to shares (assume $100/share)
                    "prediction": prediction,
                    "timestamp": datetime.now(),
                }

                trades.append(trade)
                logger.info(
                    f"📈 {trade['action']} {trade['size']} {symbol} (pred: {prediction:.3f})"
                )

        return trades

    def run_cycle(self):
        """Run one trading cycle."""
        logger.info(f"🔄 Trading cycle - Regime: {self.detect_regime()}")
        trades = self.execute_trades()
        logger.info(f"✅ Executed {len(trades)} trades")
        return trades


def main():
    """Main trading loop."""
    logger.info("🚀 Starting Minimal Paper Trading System")

    trader = MinimalPaperTrader()

    if not trader.models:
        logger.error("❌ No models loaded - exiting")
        return

    logger.info(f"📊 Trading {len(trader.symbols)} symbols")
    logger.info("🎯 Starting trading loop (Ctrl+C to stop)")

    cycle = 0
    try:
        while True:
            cycle += 1
            logger.info(f"\n--- Cycle {cycle} ---")

            trades = trader.run_cycle()

            # Sleep for 60 seconds between cycles
            logger.info("😴 Sleeping 60 seconds...")
            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("🛑 Shutdown requested")
    except Exception as e:
        logger.error(f"💥 Error: {e}")
    finally:
        logger.info("🔚 Paper trading stopped")


if __name__ == "__main__":
    main()
