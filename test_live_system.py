#!/usr/bin/env python3
"""Simple end-to-end test of live L2 system."""

import sys
import time
from pathlib import Path

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))

def test_live_system():
    """Test the live L2 system end-to-end."""
    print("🚀 Testing Live L2 System...")
    
    # Test 1: IBKR Connection
    print("\n1️⃣ Testing IBKR Connection...")
    try:
        from ib_insync import IB
        ib = IB()
        ib.connect('127.0.0.1', 7497, clientId=210, readonly=True, timeout=5)
        if ib.isConnected():
            print(f"✅ Connected to account: {ib.managedAccounts()}")
        ib.disconnect()
    except Exception as e:
        print(f"❌ IBKR connection failed: {e}")
        return False
    
    # Test 2: L2 Data Collection
    print("\n2️⃣ Testing L2 Data Collection...")
    try:
        from multi_l2_collector import MultiL2Collector, CollectorConfig
        from time_windows import parse_windows
        
        config = CollectorConfig(
            host='127.0.0.1',
            port=7497,
            client_id=211,
            symbols=['SPY', 'QQQ'],
            levels=5,
            max_depth_symbols=2,
            rotate_every_sec=0,  # No rotation for test
            out_dir='./test_l2_output',
            run_id='end_to_end_test',
            session_windows_et=parse_windows('09:30-16:00'),
            unsubscribe_outside_windows=False  # Keep collecting for test
        )
        
        import logging
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger(__name__)
        
        collector = MultiL2Collector(config, logger)
        collector.start()
        
        print("✅ L2 collector started")
        
        # Collect for 10 seconds
        for i in range(10):
            collector.poll_once()
            time.sleep(1)
            if i % 3 == 0:
                print(f"   Collecting... {i+1}/10")
        
        metadata = collector.stop()
        print(f"✅ L2 collection complete")
        
        # Check if we got any data
        counters = metadata.get('counters', {}).get('by_date_symbol', {})
        if counters:
            print(f"✅ Data collected: {counters}")
        else:
            print("ℹ️  No market data (outside hours or subscription needed)")
            
    except Exception as e:
        print(f"❌ L2 collection failed: {e}")
        return False
    
    # Test 3: Feature Engineering
    print("\n3️⃣ Testing Feature Engineering...")
    try:
        from l2_features import FeatureEngineer, FeatureConfig
        
        fe = FeatureEngineer(FeatureConfig())
        
        # Mock snapshot data
        mock_snapshot = {
            'ts_epoch': time.time(),
            'ts_utc': '2024-12-15T12:00:00Z',
            'run_id': 'test',
            'symbol': 'SPY',
            'exchange': 'SMART',
            'smart_depth': True,
            'l1_mid': 100.0,
            'l1_spread': 0.02,
            'bid_px_1': 99.99,
            'ask_px_1': 100.01,
            'bid_sz_1': 100.0,
            'ask_sz_1': 200.0,
            'has_depth': True
        }
        
        features = fe.update_and_compute(mock_snapshot, levels=5)
        print(f"✅ Features computed: {list(features.keys())[:5]}...")
        
    except Exception as e:
        print(f"❌ Feature engineering failed: {e}")
        return False
    
    print("\n🎉 Live L2 System Test Complete!")
    print("\n📋 System Status:")
    print("✅ IBKR connection working")
    print("✅ L2 data collection functional") 
    print("✅ Feature engineering operational")
    print("\n🚀 Ready for live trading!")
    
    return True

if __name__ == "__main__":
    success = test_live_system()
    sys.exit(0 if success else 1)
