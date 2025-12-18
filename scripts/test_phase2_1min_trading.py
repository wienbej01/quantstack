#!/usr/bin/env python3
"""Test Phase 2: 1-Minute Trading Frequency."""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "qx-data"))

from qx_data.live.ibkr_data import IBKRMarketDataManager
from qx_data.live.performance_monitor import PerformanceMonitor


def test_parallel_historical_bars():
    """Test 1: Parallel historical bars fetching."""
    print("\n=== Test 1: Parallel Historical Bars ===")

    data_mgr = IBKRMarketDataManager(client_id=996)

    try:
        data_mgr.connect()

        # Test with 10 symbols
        test_symbols = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "TSLA",
            "NVDA",
            "META",
            "AMZN",
            "JPM",
            "BAC",
            "WMT",
        ]

        print(
            f"\nFetching 20-bar history for {len(test_symbols)} symbols in parallel..."
        )
        start = time.time()
        all_bars = data_mgr.get_all_historical_bars(test_symbols, periods=20)
        elapsed = time.time() - start

        print(f"✅ Fetched {len(all_bars)} symbol histories in {elapsed:.2f}s")

        if elapsed > 5:
            print(f"⚠️  Warning: Took {elapsed:.2f}s (target: <5s)")
        else:
            print(f"✅ Performance good: {elapsed:.2f}s < 5s target")

        # Show sample
        if all_bars:
            sample_sym = list(all_bars.keys())[0]
            print(f"\nSample: {sample_sym} has {len(all_bars[sample_sym])} bars")

        data_mgr.disconnect()
        return elapsed < 10  # Allow 10s max

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_optimized_cross_sectional():
    """Test 2: Optimized cross-sectional feature computation."""
    print("\n=== Test 2: Optimized Cross-Sectional Features ===")

    data_mgr = IBKRMarketDataManager(client_id=995)

    try:
        data_mgr.connect()

        # Test with 20 symbols
        test_symbols = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "TSLA",
            "NVDA",
            "META",
            "AMZN",
            "JPM",
            "BAC",
            "WMT",
            "XOM",
            "CVX",
            "PFE",
            "JNJ",
            "UNH",
            "HD",
            "DIS",
            "NFLX",
            "INTC",
            "CSCO",
        ]

        data_mgr.subscribe_symbols(test_symbols)

        print(
            f"\nComputing cross-sectional features for {len(test_symbols)} symbols..."
        )
        start = time.time()
        all_data = data_mgr.get_all_current_data()
        features = data_mgr.compute_cross_sectional_features(all_data)
        elapsed = time.time() - start

        print(f"✅ Computed features in {elapsed:.3f}s")

        if elapsed > 1:
            print(f"⚠️  Warning: Took {elapsed:.3f}s (target: <1s)")
        else:
            print(f"✅ Performance excellent: {elapsed:.3f}s < 1s target")

        print(f"Features computed for {len(features)} symbols")

        data_mgr.disconnect()
        return elapsed < 2  # Allow 2s max

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_full_cycle_timing():
    """Test 3: Full trading cycle timing."""
    print("\n=== Test 3: Full Cycle Timing ===")

    data_mgr = IBKRMarketDataManager(client_id=994)
    perf = PerformanceMonitor()

    try:
        data_mgr.connect()

        # Simulate full cycle with 40 symbols
        test_symbols = [
            "AAPL",
            "MSFT",
            "GOOGL",
            "TSLA",
            "NVDA",
            "META",
            "AMZN",
            "JPM",
            "BAC",
            "WMT",
            "XOM",
            "CVX",
            "PFE",
            "JNJ",
            "UNH",
            "HD",
            "DIS",
            "NFLX",
            "INTC",
            "CSCO",
            "AMD",
            "QCOM",
            "TXN",
            "AVGO",
            "ORCL",
            "IBM",
            "CRM",
            "ADBE",
            "PYPL",
            "SQ",
            "V",
            "MA",
            "AXP",
            "GS",
            "MS",
            "C",
            "USB",
            "PNC",
            "TFC",
            "SCHW",
        ]

        print(f"\nSimulating full trading cycle with {len(test_symbols)} symbols...")

        perf.start_cycle()

        # Phase 1: Subscribe
        print("  Phase 1: Subscribing to market data...")
        data_mgr.subscribe_symbols(test_symbols)

        # Phase 2: Fetch current data
        print("  Phase 2: Fetching current data...")
        phase_start = time.time()
        all_data = data_mgr.get_all_current_data()
        print(f"    -> {time.time() - phase_start:.2f}s")

        # Phase 3: Cross-sectional features
        print("  Phase 3: Computing cross-sectional features...")
        phase_start = time.time()
        features = data_mgr.compute_cross_sectional_features(all_data)
        print(f"    -> {time.time() - phase_start:.2f}s")

        # Phase 4: Historical bars (parallel)
        print("  Phase 4: Fetching historical bars (parallel)...")
        phase_start = time.time()
        all_bars = data_mgr.get_all_historical_bars(
            test_symbols[:10], periods=20
        )  # Sample 10
        hist_time = time.time() - phase_start
        print(f"    -> {hist_time:.2f}s")
        perf.record_phase("features", hist_time)

        # Phase 5: Simulate predictions (0.5s)
        print("  Phase 5: ML predictions (simulated)...")
        time.sleep(0.5)
        perf.record_phase("predictions", 0.5)

        # Phase 6: Simulate orders (1s)
        print("  Phase 6: Order placement (simulated)...")
        time.sleep(1.0)
        perf.record_phase("orders", 1.0)

        cycle_time = perf.end_cycle()

        print(f"\n✅ Full cycle completed in {cycle_time:.2f}s")

        if cycle_time > 60:
            print(f"❌ FAIL: Cycle took {cycle_time:.2f}s (must be <60s)")
            return False
        elif cycle_time > 45:
            print(f"⚠️  Warning: Cycle took {cycle_time:.2f}s (target: <30s)")
            return True
        else:
            print(f"✅ Excellent: Cycle took {cycle_time:.2f}s (well under 60s limit)")
            return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False
    finally:
        data_mgr.disconnect()


def test_performance_monitor():
    """Test 4: Performance monitoring."""
    print("\n=== Test 4: Performance Monitor ===")

    try:
        perf = PerformanceMonitor()

        # Simulate 5 cycles
        print("\nSimulating 5 trading cycles...")
        for i in range(5):
            perf.start_cycle()
            time.sleep(0.1)  # Simulate work
            perf.record_phase("features", 0.05)
            perf.record_phase("predictions", 0.03)
            perf.record_phase("orders", 0.02)
            perf.end_cycle()

        # Get stats
        stats = perf.get_stats()

        print(f"✅ Tracked {stats['total_cycles']} cycles")
        print(f"  Avg cycle time: {stats['avg_cycle_time']:.3f}s")
        print(f"  Avg feature time: {stats['avg_feature_time']:.3f}s")
        print(f"  Skip rate: {stats['skip_rate']*100:.1f}%")

        # Test skip detection
        perf.start_cycle()
        time.sleep(0.05)
        should_skip = perf.should_skip_cycle()

        if should_skip:
            print("❌ False positive: Should not skip at 0.05s")
            return False

        print("✅ Skip detection working correctly")

        return True

    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def main():
    """Run all Phase 2 tests."""
    print("=" * 60)
    print("PHASE 2 VALIDATION: 1-Minute Trading Frequency")
    print("=" * 60)

    results = {
        "Parallel Historical Bars": test_parallel_historical_bars(),
        "Optimized Cross-Sectional": test_optimized_cross_sectional(),
        "Full Cycle Timing": test_full_cycle_timing(),
        "Performance Monitor": test_performance_monitor(),
    }

    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{test_name}: {status}")

    all_passed = all(results.values())

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED - Phase 2 Ready for Production")
        print("\nNext Steps:")
        print("1. Stop current system: kill $(cat live_trading.pid)")
        print("2. Restart with 1-min trading: ./start_live_system.sh")
        print("3. Monitor logs: tail -f logs/live_trading.log")
        print("4. Watch for cycle times <60s and skip rate <5%")
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
    print("=" * 60)

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
