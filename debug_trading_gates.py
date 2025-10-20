#!/usr/bin/env python3
"""
Debug script to identify why no trades are being generated.
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from qx_data.gold_loader import load_bars
from qx_features.registry import apply
import pandas as pd

def debug_trading_gates():
    """Debug why no trades are being generated."""

    print("🔍 Debugging Trading Gates - Why No Trades?")
    print("=" * 60)

    # Load some sample data
    print("\n1. Loading sample data...")
    try:
        data = load_bars(
            root="/home/jacobw/gcs-mount",
            family="bars_1m",
            symbols=["AAPL"],
            dates=["2024-01-02"]
        )
        print(f"✅ Loaded {len(data)} bars for AAPL on 2024-01-02")
    except Exception as e:
        print(f"❌ Error loading data: {e}")
        return

    # Check basic data structure
    print(f"\n2. Data structure:")
    print(f"   Columns: {list(data.columns)}")
    print(f"   Sample rows: {len(data)}")
    print(f"   Time range: {data.index.min()} to {data.index.max()}")

    # Check price ranges
    print(f"\n3. Price analysis:")
    print(f"   Close price range: ${data['close'].min():.2f} - ${data['close'].max():.2f}")
    print(f"   Price change: {((data['close'].iloc[-1] / data['close'].iloc[0]) - 1) * 100:.2f}%")

    # Apply features
    print(f"\n4. Applying features...")
    try:
        features_config = [
            {"type": "core_basics", "params": {"vwap_window_m": 30}}
        ]
        data_with_features = apply(data, features_config)
        print(f"✅ Features applied")
        print(f"   New columns: {[col for col in data_with_features.columns if col.startswith('f__')]}")
    except Exception as e:
        print(f"❌ Error applying features: {e}")
        return

    # Check VWAP values
    vwap_col = "f__ta__vwap_30"
    if vwap_col in data_with_features.columns:
        print(f"\n5. VWAP analysis:")
        vwap_data = data_with_features[vwap_col].dropna()
        if len(vwap_data) > 0:
            print(f"   VWAP range: ${vwap_data.min():.2f} - ${vwap_data.max():.2f}")

            # Check trading signals
            close_data = data_with_features['close'].reindex(vwap_data.index)
            vwap_data = vwap_data.reindex(close_data.index)

            # Calculate deviations
            deviation_pct = ((close_data - vwap_data) / vwap_data) * 100

            print(f"   Max deviation below VWAP: {deviation_pct.min():.2f}%")
            print(f"   Max deviation above VWAP: {deviation_pct.max():.2f}%")

            # Count potential signals
            buy_signals = (deviation_pct < -0.5).sum()
            sell_signals = (deviation_pct > 0.5).sum()

            print(f"   Potential buy signals (< -0.5%): {buy_signals}")
            print(f"   Potential sell signals (> 0.5%): {sell_signals}")

            if buy_signals > 0 or sell_signals > 0:
                print(f"✅ Trading signals detected!")

                # Show some examples
                print(f"\n6. Sample trading opportunities:")
                buy_examples = deviation_pct[deviation_pct < -0.5].head(3)
                sell_examples = deviation_pct[deviation_pct > 0.5].head(3)

                if len(buy_examples) > 0:
                    print(f"   Buy opportunities:")
                    for timestamp, deviation in buy_examples.items():
                        close_price = close_data.loc[timestamp]
                        vwap_price = vwap_data.loc[timestamp]
                        print(f"     {timestamp}: Close=${close_price:.2f}, VWAP=${vwap_price:.2f}, Deviation={deviation:.2f}%")

                if len(sell_examples) > 0:
                    print(f"   Sell opportunities:")
                    for timestamp, deviation in sell_examples.items():
                        close_price = close_data.loc[timestamp]
                        vwap_price = vwap_data.loc[timestamp]
                        print(f"     {timestamp}: Close=${close_price:.2f}, VWAP=${vwap_price:.2f}, Deviation={deviation:.2f}%")
            else:
                print(f"❌ No trading signals detected - deviation threshold too strict?")
                print(f"   Consider loosening thresholds from ±0.5% to ±0.1%")
        else:
            print(f"❌ No VWAP data available")
    else:
        print(f"❌ VWAP column '{vwap_col}' not found")

    print(f"\n7. Summary:")
    print(f"   Data loaded: ✅")
    print(f"   Features applied: ✅" if vwap_col in data_with_features.columns else "   Features applied: ❌")
    print(f"   Trading signals: {'✅' if buy_signals > 0 or sell_signals > 0 else '❌'}")

    if buy_signals == 0 and sell_signals == 0:
        print(f"\n🚨 DIAGNOSIS: No trading signals detected!")
        print(f"   Possible causes:")
        print(f"   1. VWAP calculation window too long (30 minutes)")
        print(f"   2. Trading thresholds too strict (±0.5%)")
        print(f"   3. Market conditions too stable (low volatility)")
        print(f"   4. Data quality issues")

if __name__ == "__main__":
    debug_trading_gates()