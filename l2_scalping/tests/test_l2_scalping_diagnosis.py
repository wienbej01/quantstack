#!/usr/bin/env python3
"""
L2 Scalping Diagnostic Test
Tests all components to identify why no trades occurred.
"""

import os
import sys

sys.path.insert(0, "/home/jacobw/quantstack")
sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src")

import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def test_sip_integration():
    """Test 1: SIP symbol loading"""
    logger.info("=" * 60)
    logger.info("TEST 1: SIP Integration")
    logger.info("=" * 60)

    try:
        from data.sip_integration import get_scalping_symbols

        symbols = get_scalping_symbols()
        logger.info(f"✓ SIP symbols loaded: {symbols}")
        return len(symbols) > 0
    except Exception as e:
        logger.error(f"✗ SIP integration failed: {e}", exc_info=True)
        return False


def test_platform_connection():
    """Test 2: Platform connectivity"""
    logger.info("=" * 60)
    logger.info("TEST 2: Platform Connection")
    logger.info("=" * 60)

    try:
        from cpapi.platform_client import IBKRPlatformClient

        client = IBKRPlatformClient("test-diagnostic", "Test Diagnostic")
        success = client.register(["market-data"])

        if success:
            logger.info("✓ Platform connection successful")
            client.unregister()
            return True
        else:
            logger.error("✗ Platform registration failed")
            return False
    except Exception as e:
        logger.error(f"✗ Platform connection failed: {e}", exc_info=True)
        return False


def test_market_data_retrieval():
    """Test 3: Market data retrieval"""
    logger.info("=" * 60)
    logger.info("TEST 3: Market Data Retrieval")
    logger.info("=" * 60)

    try:
        from cpapi.platform_client import IBKRPlatformClient

        client = IBKRPlatformClient("test-market-data", "Test Market Data")
        client.register(["market-data"])

        # Search for INTC
        contracts = client.search_contracts("INTC", "STK")
        if not contracts:
            logger.error("✗ No contracts found for INTC")
            client.unregister()
            return False

        conid = contracts[0].get("conid")
        logger.info(f"✓ Found INTC contract: conid={conid}")

        # Get market snapshot
        snapshot = client.get_market_snapshot([conid])
        if snapshot:
            logger.info(f"✓ Market snapshot received: {snapshot[0]}")
            logger.info(f"  Fields available: {list(snapshot[0].keys())}")
        else:
            logger.error("✗ No market snapshot received")
            client.unregister()
            return False

        client.unregister()
        return True
    except Exception as e:
        logger.error(f"✗ Market data retrieval failed: {e}", exc_info=True)
        return False


def test_l2_snapshot_format():
    """Test 4: L2 Snapshot format compatibility"""
    logger.info("=" * 60)
    logger.info("TEST 4: L2 Snapshot Format")
    logger.info("=" * 60)

    try:
        # Check what L2DataFeed provides
        from data.l2_feed import L2Snapshot as FeedSnapshot

        logger.info(f"✓ L2DataFeed snapshot fields: {FeedSnapshot.__annotations__}")

        # Check what signal generator expects
        from signals.l2_signals import L2Snapshot as SignalSnapshot

        logger.info(f"✓ Signal generator expects: {SignalSnapshot.__annotations__}")

        # Check compatibility
        feed_fields = set(FeedSnapshot.__annotations__.keys())
        signal_fields = set(SignalSnapshot.__annotations__.keys())

        missing = signal_fields - feed_fields
        if missing:
            logger.error(f"✗ CRITICAL: Missing fields in L2DataFeed: {missing}")
            logger.error(
                "  Signal generator cannot process snapshots without these fields!"
            )
            return False
        else:
            logger.info("✓ All required fields present")
            return True

    except Exception as e:
        logger.error(f"✗ Snapshot format check failed: {e}", exc_info=True)
        return False


def test_signal_generation():
    """Test 5: Signal generation with mock data"""
    logger.info("=" * 60)
    logger.info("TEST 5: Signal Generation")
    logger.info("=" * 60)

    try:
        from pathlib import Path

        import yaml
        from signals.l2_signals import L2SignalGenerator, L2Snapshot, SignalType

        # Load config
        config_path = Path("/home/jacobw/quantstack/l2_scalping/config/strategy.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        generator = L2SignalGenerator(config)

        # Create mock snapshot with strong buy signal
        snapshot = L2Snapshot(
            symbol="TEST",
            timestamp=datetime.now().timestamp(),
            mid=100.0,
            spread=0.01,
            obi_1=0.8,  # Strong buy pressure
            obi_5=0.7,
            depth_bid=100000.0,
            depth_ask=50000.0,
            pressure=0.5,
        )

        signal = generator.generate_signal(snapshot)
        logger.info(
            f"✓ Signal generated: {signal.signal_type.name} (strength={signal.strength:.2f}, confidence={signal.confidence:.2f})"
        )

        if signal.signal_type == SignalType.NONE:
            logger.warning("  Signal is NONE - check thresholds in strategy.yaml")

        return True
    except Exception as e:
        logger.error(f"✗ Signal generation failed: {e}", exc_info=True)
        return False


def test_order_manager():
    """Test 6: Order manager connectivity"""
    logger.info("=" * 60)
    logger.info("TEST 6: Order Manager")
    logger.info("=" * 60)

    try:
        from pathlib import Path

        import yaml
        from execution.order_manager import IBKROrderManager

        config_path = Path("/home/jacobw/quantstack/l2_scalping/config/ibkr.yaml")
        with open(config_path) as f:
            config = yaml.safe_load(f)

        manager = IBKROrderManager(config)
        connected = manager.connect()

        if connected:
            logger.info("✓ Order manager connected")
            health = manager.health_check()
            logger.info(f"  Health: {health}")
            manager.disconnect()
            return True
        else:
            logger.error("✗ Order manager connection failed")
            return False
    except Exception as e:
        logger.error(f"✗ Order manager test failed: {e}", exc_info=True)
        return False


def main():
    """Run all diagnostic tests"""
    logger.info("=" * 60)
    logger.info("L2 SCALPING DIAGNOSTIC TEST")
    logger.info("=" * 60)

    results = {
        "SIP Integration": test_sip_integration(),
        "Platform Connection": test_platform_connection(),
        "Market Data Retrieval": test_market_data_retrieval(),
        "L2 Snapshot Format": test_l2_snapshot_format(),
        "Signal Generation": test_signal_generation(),
        "Order Manager": test_order_manager(),
    }

    logger.info("=" * 60)
    logger.info("DIAGNOSTIC SUMMARY")
    logger.info("=" * 60)

    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {test_name}")

    all_passed = all(results.values())
    if all_passed:
        logger.info("\n✓ All tests passed - system should be operational")
    else:
        logger.error("\n✗ Some tests failed - see errors above")
        logger.error(
            "CRITICAL ISSUE: L2DataFeed does not provide required fields for signal generation!"
        )

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
