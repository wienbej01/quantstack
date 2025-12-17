#!/usr/bin/env python3
"""Test Phase 1: Real IBKR Data Integration."""

import sys
from pathlib import Path

# Add both qx-data paths
qx_data_src = Path(__file__).parent.parent / "qx-data" / "src"
qx_data_root = Path(__file__).parent.parent / "qx-data"
sys.path.insert(0, str(qx_data_src))
sys.path.insert(0, str(qx_data_root))

from qx_data.live.ibkr_data import IBKRMarketDataManager
from qx_data.live.ml_predictor import RegimeAwarePredictor


def test_ibkr_connection():
    """Test 1: IBKR connection and data subscription."""
    print("\n=== Test 1: IBKR Connection ===")
    
    data_mgr = IBKRMarketDataManager(client_id=999)
    
    try:
        data_mgr.connect()
        print("✅ Connected to IBKR")
        
        # Test with 5 symbols
        test_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA"]
        print(f"\nSubscribing to {len(test_symbols)} symbols...")
        data_mgr.subscribe_symbols(test_symbols)
        print("✅ Subscribed to market data")
        
        # Get current data
        print("\nFetching current market data...")
        all_data = data_mgr.get_all_current_data()
        
        for symbol, data in all_data.items():
            print(f"  {symbol}: last=${data.get('last', 0):.2f}, vol={data.get('volume', 0):,}")
        
        if all_data:
            print("✅ Real-time data received")
        else:
            print("❌ No data received")
            return False
        
        data_mgr.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_historical_bars():
    """Test 2: Historical bars retrieval."""
    print("\n=== Test 2: Historical Bars ===")
    
    data_mgr = IBKRMarketDataManager(client_id=998)
    
    try:
        data_mgr.connect()
        
        symbol = "AAPL"
        print(f"\nFetching 20 1-minute bars for {symbol}...")
        bars = data_mgr.get_historical_bars(symbol, periods=20)
        
        if len(bars) > 0:
            print(f"✅ Retrieved {len(bars)} bars")
            print(f"  Latest: {bars.iloc[-1]['date']} close=${bars.iloc[-1]['close']:.2f}")
            
            # Compute relative strength
            closes = bars["close"].values
            if len(closes) >= 20:
                rel_strength_20 = (closes[-1] - closes[-20]) / closes[-20]
                print(f"  20-period rel strength: {rel_strength_20:.4f}")
        else:
            print("❌ No bars retrieved")
            return False
        
        data_mgr.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_cross_sectional_features():
    """Test 3: Cross-sectional feature computation."""
    print("\n=== Test 3: Cross-Sectional Features ===")
    
    data_mgr = IBKRMarketDataManager(client_id=997)
    
    try:
        data_mgr.connect()
        
        test_symbols = ["AAPL", "MSFT", "GOOGL", "TSLA", "NVDA", "META", "AMZN"]
        data_mgr.subscribe_symbols(test_symbols)
        
        print("\nComputing cross-sectional features...")
        all_data = data_mgr.get_all_current_data()
        features = data_mgr.compute_cross_sectional_features(all_data)
        
        if features:
            print(f"✅ Computed features for {len(features)} symbols")
            
            # Show sample
            sample_sym = list(features.keys())[0]
            print(f"\nSample features for {sample_sym}:")
            for key, val in features[sample_sym].items():
                print(f"  {key}: {val:.4f}")
        else:
            print("❌ No features computed")
            return False
        
        data_mgr.disconnect()
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def test_ml_predictor():
    """Test 4: ML predictor with real features."""
    print("\n=== Test 4: ML Predictor ===")
    
    try:
        predictor = RegimeAwarePredictor("./models/regime_aware")
        
        if not predictor.models:
            print("❌ No models loaded")
            return False
        
        print(f"✅ Loaded {len(predictor.models)} regime models")
        
        # Test with sample features
        test_features = {
            "cross_rank_ret": 0.65,
            "cross_rank_vol": 0.55,
            "sector_momentum": 0.02,
            "cross_dispersion": 0.015,
            "market_breadth": 0.58,
            "up_down_ratio": 1.2,
            "rel_strength_5": 0.01,
            "rel_strength_10": 0.015,
            "rel_strength_20": 0.02,
            "market_ret_5": 0.005,
            "market_ret_10": 0.008,
            "market_ret": 0.006,
            "market_volatility": 0.018,
        }
        
        print("\nTesting prediction with sample features...")
        prediction = predictor.predict("TEST", test_features)
        
        if prediction is not None:
            print(f"✅ Prediction: {prediction:.4f}")
            
            if prediction > 0.65:
                print("  Signal: BUY")
            elif prediction < 0.35:
                print("  Signal: SELL")
            else:
                print("  Signal: HOLD")
        else:
            print("❌ Prediction failed")
            return False
        
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False


def main():
    """Run all Phase 1 tests."""
    print("=" * 60)
    print("PHASE 1 VALIDATION: Real IBKR Data Integration")
    print("=" * 60)
    
    results = {
        "IBKR Connection": test_ibkr_connection(),
        "Historical Bars": test_historical_bars(),
        "Cross-Sectional Features": test_cross_sectional_features(),
        "ML Predictor": test_ml_predictor(),
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
        print("✅ ALL TESTS PASSED - Phase 1 Ready for Production")
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
