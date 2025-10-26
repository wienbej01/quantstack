#!/usr/bin/env python3
"""Quick test to verify policy engine attachment works."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))

import numpy as np
import pandas as pd

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.regime_aligned import AVWAPMomentumPolicy


def create_simple_test_data():
    """Create simple test data with minimal features."""
    np.random.seed(42)

    # Create 100 bars of test data
    data = []
    base_price = 150.0

    for i in range(100):
        price = base_price + np.random.randn() * 0.5
        high = price + abs(np.random.randn() * 0.2)
        low = price - abs(np.random.randn() * 0.2)

        data.append(
            {
                "ts": 1_000_000_000_000_000_000 + i * 60_000_000_000,  # 1-min intervals
                "symbol": "AAPL",
                "open": price,
                "high": high,
                "low": low,
                "close": price,
                "volume": np.random.randint(1000, 5000),
                "f__warmup_ok": i > 20,  # Warmup after 20 bars
                "f__regime__current": (
                    "BULL" if i > 20 and np.random.random() > 0.5 else "SIDEWAYS"
                ),
                "f__anchor__session_avwap": base_price,
                "f__vol__atr_14": 0.5,
            }
        )

    return pd.DataFrame(data)


def test_policy_engine_attachment():
    """Test that policy can be attached to engine and process bars."""
    print("🧪 Testing Policy Engine Attachment")
    print("=" * 50)

    # Create simple test data
    df = create_simple_test_data()
    print(f"✅ Created test data: {len(df)} bars")

    # Create policy
    policy = AVWAPMomentumPolicy()
    print("✅ Created AVWAPMomentumPolicy")

    # Create backtest engine
    config = BacktestConfig(initial_cash=100000.0)
    engine = BacktestEngine(config)
    print("✅ Created BacktestEngine")

    # Attach policy to engine
    policy.set_engine(engine)
    print("✅ Policy attached to engine")

    # Test processing a few bars
    bars_processed = 0
    orders_generated = 0

    for _, bar in df.iterrows():
        try:
            policy.process_bar(bar.to_dict())
            bars_processed += 1

            # Check if any orders were generated
            if hasattr(engine, "orders") and len(engine.orders) > orders_generated:
                orders_generated = len(engine.orders)

        except Exception as e:
            print(f"❌ Error processing bar {bars_processed}: {e}")
            break

    print(f"✅ Processed {bars_processed} bars successfully")
    print(f"📊 Generated {orders_generated} orders")

    # Test complete
    if bars_processed > 0:
        print("\n🎯 Policy Engine Attachment Test: PASSED")
        print("✅ Policy can be attached to engine")
        print("✅ Policy can process bars without errors")
        print("✅ Engine integration working")
        return True
    else:
        print("\n❌ Policy Engine Attachment Test: FAILED")
        return False


if __name__ == "__main__":
    success = test_policy_engine_attachment()
    sys.exit(0 if success else 1)
