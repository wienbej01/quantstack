#!/usr/bin/env python3
"""Test L2 integration with quantstack."""

import logging
import sys
import time
from pathlib import Path

# Add transalpha L2 to path
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))

from qx_data.live.l2_collector import QuantstackL2Collector


def test_l2_collection():
    """Test L2 data collection."""
    logging.basicConfig(level=logging.INFO)

    # Test configuration
    config = {
        "host": "127.0.0.1",
        "port": 7497,
        "client_id": 101,
        "levels": 5,
        "max_symbols": 2,
        "rotate_seconds": 60,
        "output_dir": "./test_l2_data",
        "run_id": "test_integration",
        "windows": ["09:30-16:00"],
    }

    # Test symbols (use liquid ETFs)
    test_symbols = ["SPY", "QQQ"]

    print(f"Testing L2 collection for: {test_symbols}")

    # Create collector
    collector = QuantstackL2Collector(test_symbols, config)

    try:
        # Start collection
        print("Starting L2 collection...")
        collector.start_collection()

        # Collect for 30 seconds
        for i in range(30):
            collector.poll_once()

            # Show features every 5 seconds
            if i % 5 == 0:
                for symbol in test_symbols:
                    features = collector.get_latest_features(symbol)
                    if features:
                        print(
                            f"{symbol}: mid={features.get('mid')}, "
                            f"obi_1={features.get('obi_1')}, "
                            f"has_depth={features.get('has_depth')}"
                        )

            time.sleep(1)

    except Exception as e:
        print(f"Error: {e}")
    finally:
        # Stop and get metadata
        metadata = collector.stop_collection()
        print(f"Collection complete. Metadata: {metadata}")


if __name__ == "__main__":
    test_l2_collection()
