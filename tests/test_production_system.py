#!/usr/bin/env python3
"""Test production trading system components."""

import os
import sys
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, "qx-data")


def test_production_system():
    """Test all production components."""
    print("🚀 Testing Production Trading System...")

    # Test 1: Polygon API
    print("\n1️⃣ Testing Polygon SIP Selection...")
    try:
        from qx_data.live.polygon_sip import PolygonSIPSelector

        if not os.getenv("POLYGON_API_KEY"):
            print("❌ POLYGON_API_KEY not set")
            return False

        sip = PolygonSIPSelector()
        universe = sip.get_sip_universe(top_k=10)  # Small test
        nyse_symbols = sip.get_nyse_symbols(universe)

        print(f"✅ SIP universe: {universe[:5]}... ({len(universe)} total)")
        print(f"✅ NYSE symbols: {nyse_symbols[:3]}... ({len(nyse_symbols)} total)")

    except Exception as e:
        print(f"❌ Polygon SIP failed: {e}")
        return False

    # Test 2: ML Predictor
    print("\n2️⃣ Testing ML Predictor...")
    try:
        from qx_data.live.ml_predictor import RegimeAwarePredictor

        predictor = RegimeAwarePredictor("./models/regime_aware")

        # Mock prediction
        mock_data = {"volatility": 0.2, "volume": 1000000}
        prediction = predictor.predict("AAPL", mock_data)

        print(f"✅ ML predictor loaded (prediction: {prediction})")

    except Exception as e:
        print(f"❌ ML predictor failed: {e}")
        return False

    # Test 3: Paper Trader
    print("\n3️⃣ Testing Paper Trader Connection...")
    try:
        from qx_data.live.ml_predictor import PaperTrader

        trader = PaperTrader()
        connected = trader.connect()

        if connected:
            positions = trader.get_positions()
            print(f"✅ Paper trader connected (positions: {len(positions)})")
            trader.disconnect()
        else:
            print("❌ Paper trader connection failed")
            return False

    except Exception as e:
        print(f"❌ Paper trader failed: {e}")
        return False

    # Test 4: L2 Collector
    print("\n4️⃣ Testing L2 Collector...")
    try:
        from qx_data.live.l2_collector import QuantstackL2Collector

        config = {
            "host": "127.0.0.1",
            "port": 7497,
            "client_id": 350,
            "levels": 5,
            "max_symbols": 2,
            "rotate_seconds": 0,
            "output_dir": "./test_production_l2",
            "run_id": "production_test",
            "windows": "09:30-16:00",
        }

        collector = QuantstackL2Collector(["SPY", "JPM"], config)
        print("✅ L2 collector initialized")

    except Exception as e:
        print(f"❌ L2 collector failed: {e}")
        return False

    print("\n🎉 Production System Test Complete!")
    print("\n📋 System Ready:")
    print("✅ Polygon SIP selection operational")
    print("✅ ML predictor loaded")
    print("✅ Paper trading connection working")
    print("✅ L2 data collection ready")
    print("\n🚀 Ready for production deployment!")

    return True


if __name__ == "__main__":
    success = test_production_system()
    sys.exit(0 if success else 1)
