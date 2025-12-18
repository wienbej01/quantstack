#!/usr/bin/env python3
"""Minimal live trading using proven system components."""

import logging
import sys
import time
from pathlib import Path

# Add paths for L2 system
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))


def main():
    """Start minimal live trading system."""

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/minimal_live.log"),
            logging.StreamHandler(),
        ],
    )
    logger = logging.getLogger(__name__)

    logger.info("🚀 Starting Minimal Live Trading System")

    # NYSE symbols for L2 collection (opening + power hour)
    symbols = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA", "TSLA"]

    try:
        from multi_l2_collector import CollectorConfig, MultiL2Collector
        from time_windows import parse_windows

        # Configure L2 collection for opening and power hour
        config = CollectorConfig(
            host="127.0.0.1",
            port=7497,
            client_id=300,
            symbols=symbols,
            levels=10,
            max_depth_symbols=6,
            rotate_every_sec=600,  # 10 minutes
            out_dir="./data/live_l2",
            run_id=f'live_{time.strftime("%Y%m%d")}',
            session_windows_et=parse_windows("09:30-10:30,15:00-16:00"),
            unsubscribe_outside_windows=True,
        )

        collector = MultiL2Collector(config, logger)
        collector.start()

        logger.info(f"✅ L2 collection started for {len(symbols)} symbols")
        logger.info(f"📊 Collection windows: 09:30-10:30, 15:00-16:00 ET")
        logger.info(f"💾 Output: ./data/live_l2/run_id=live_{time.strftime('%Y%m%d')}")

        # Main loop - collect L2 data and log status
        loop_count = 0
        while True:
            try:
                collector.poll_once()

                # Log status every 60 seconds
                if loop_count % 60 == 0:
                    logger.info(f"📈 Live system running - loop {loop_count}")

                loop_count += 1
                time.sleep(1)

            except KeyboardInterrupt:
                logger.info("🛑 Received interrupt signal")
                break
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                time.sleep(5)

    except Exception as e:
        logger.error(f"❌ System startup failed: {e}")
        return False

    finally:
        try:
            metadata = collector.stop()
            logger.info("✅ L2 collection stopped")
            logger.info(f"📊 Collection metadata: {metadata}")
        except:
            pass

    logger.info("🏁 Minimal live trading system stopped")
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
