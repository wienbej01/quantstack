#!/usr/bin/env python3
"""Start paper trading system with L2 data collection - no Polygon dependency."""

import sys
from pathlib import Path

# Add paths
repo_root = Path(__file__).parent
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, str(repo_root / "qx-data" / "src"))

import logging
import os
import time
from datetime import datetime

import pytz

from qx_data.live.ibkr_data import IBKRMarketDataManager
from qx_data.live.l2_collector import QuantstackL2Collector
from qx_data.live.ml_predictor import PaperTrader, RegimeAwarePredictor
from qx_data.live.performance_monitor import PerformanceMonitor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/live_trading.log"), logging.StreamHandler()],
)

logger = logging.getLogger(__name__)


def main():
    """Start paper trading with L2 collection."""

    # Create directories
    Path("logs").mkdir(exist_ok=True)
    l2_root = Path(
        os.environ.get("L2_DATA_ROOT", "/home/jacobw/quantstack/data/l2")
    ).expanduser()
    (l2_root / "live_l2").mkdir(parents=True, exist_ok=True)

    logger.info("🚀 Starting Paper Trading System with L2 Data Collection")

    # Use a predefined symbol list for now (top NYSE stocks)
    symbols = [
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "TSLA",
        "NVDA",
        "META",
        "JPM",
        "V",
        "JNJ",
    ]

    # Initialize components
    logger.info("📊 Initializing ML Predictor...")
    ml_predictor = RegimeAwarePredictor("./models/regime_aware")

    logger.info("💰 Initializing Paper Trader...")
    paper_trader = PaperTrader()

    logger.info("📈 Initializing IBKR Data Manager...")
    ibkr_manager = IBKRMarketDataManager()

    logger.info("📊 Initializing L2 Collector...")
    l2_collector = QuantstackL2Collector(
        symbols=symbols[:6],
        output_dir=str(l2_root / "live_l2"),  # Top 6 for L2 collection
    )

    logger.info("⏱️  Initializing Performance Monitor...")
    perf_monitor = PerformanceMonitor()

    logger.info("✅ All components initialized")
    logger.info(f"📋 Trading {len(symbols)} symbols")
    logger.info(f"📊 Collecting L2 data for {len(symbols[:6])} symbols")
    logger.info("🎯 Starting trading loop...")

    # Trading loop
    cycle_count = 0
    et_tz = pytz.timezone("America/New_York")

    try:
        while True:
            cycle_start = time.time()
            cycle_count += 1

            current_time = datetime.now(et_tz)
            logger.info(
                f"🔄 Cycle {cycle_count} - {current_time.strftime('%H:%M:%S ET')}"
            )

            # Check if market is open (9:30-16:00 ET)
            market_time = current_time.time()
            if not (
                market_time >= datetime.strptime("09:30", "%H:%M").time()
                and market_time <= datetime.strptime("16:00", "%H:%M").time()
            ):
                logger.info("🌙 Market closed - sleeping 60 seconds")
                time.sleep(60)
                continue

            try:
                # 1. Collect L2 data
                logger.info("📊 Collecting L2 data...")
                l2_collector.collect_batch()

                # 2. Get market data for predictions
                logger.info("📈 Getting market data...")
                market_data = ibkr_manager.get_market_data_batch(symbols)

                # 3. Make predictions
                logger.info("🤖 Making ML predictions...")
                predictions = ml_predictor.predict_batch(market_data)

                # 4. Execute trades
                logger.info("💰 Executing trades...")
                trades = paper_trader.execute_trades(predictions)

                # 5. Monitor performance
                cycle_time = time.time() - cycle_start
                perf_monitor.record_cycle(cycle_time, len(trades))

                logger.info(
                    f"✅ Cycle complete - {cycle_time:.1f}s, {len(trades)} trades"
                )

            except Exception as e:
                logger.error(f"❌ Cycle error: {e}")

            # Sleep for 1 minute between cycles
            time.sleep(60)

    except KeyboardInterrupt:
        logger.info("🛑 Shutdown requested")
    except Exception as e:
        logger.error(f"💥 System error: {e}")
    finally:
        logger.info("🔚 Paper trading system stopped")


if __name__ == "__main__":
    main()
