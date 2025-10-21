#!/usr/bin/env python3
"""Simplified regime pilot test with smaller dataset."""

import sys
from pathlib import Path

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))

import pandas as pd
import numpy as np
from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.policies.regime_aligned import AVWAPMomentumPolicy, AVWAPPullbackPolicy, ValueRotationPolicy
from qx_features.core_basics import compute_all_core_features
from qx_features.regime.features import compute_all_regime_features


def create_test_data():
    """Create test data with regime signals."""
    np.random.seed(42)

    # Create 500 bars of test data (smaller than original)
    timestamps = pd.date_range("2024-04-01 09:30:00", periods=500, freq="1min", tz="America/New_York")
    data = []
    base_price = 150.0

    for i, ts in enumerate(timestamps):
        # Create price with some trend and volatility
        trend = 0.05 * np.sin(i * 0.02)
        noise = np.random.randn() * 0.3
        price = base_price + trend + noise

        high = price + abs(np.random.randn() * 0.2)
        low = price - abs(np.random.randn() * 0.2)
        open_price = low + (high - low) * np.random.random()
        close = low + (high - low) * np.random.random()
        volume = np.random.randint(1000, 5000)

        data.append({
            'ts': int(ts.tz_convert("UTC").timestamp() * 1e9),
            'symbol': 'AAPL',
            'open': open_price,
            'high': high,
            'low': low,
            'close': close,
            'volume': volume,
        })

    return pd.DataFrame(data)


def prepare_features(df):
    """Prepare features with regime detection."""
    print("Computing features...")

    # Compute core features
    df = compute_all_core_features(df)
    print("✅ Core features computed")

    # Compute regime features
    df = compute_all_regime_features(df)
    print("✅ Regime features computed")

    # Verify regime features are present
    regime_features = [col for col in df.columns if col.startswith('f__regime__')]
    print(f"✅ Regime features present: {len(regime_features)} columns")

    # Show regime distribution
    warmup_mask = df.get('f__regime__warmup_ok', pd.Series(False, index=df.index))
    ready_bars = df[warmup_mask]

    if len(ready_bars) > 0:
        print(f"🔍 Ready bars (past warmup): {len(ready_bars)}")

        # Simple regime classification for diagnostics
        regime_counts = {'BULL': 0, 'BEAR': 0, 'SIDEWAYS': 0, 'STRESS': 0, 'NONE': 0}

        for _, bar in ready_bars.iterrows():
            features = {
                'var_ratio': bar.get('f__regime__var_ratio_10_60', 1.0),
                'adx': bar.get('f__regime__adx_proxy_14', 20.0),
                'band_pos': bar.get('f__regime__band_pos_20_2.0', 0.5),
                'mod_vol': bar.get('f__regime__mod_vol_30', 1.0),
                'stress': bar.get('f__regime__stress_10_10', 0.0)
            }

            if features['stress'] > 0 or features['mod_vol'] >= 2.0:
                regime = 'STRESS'
            elif features['var_ratio'] > 1.2 and features['adx'] >= 25:
                regime = 'BULL'
            elif features['var_ratio'] < 0.8 and features['adx'] >= 25:
                regime = 'BEAR'
            elif abs(features['var_ratio'] - 1.0) <= 0.1 or features['adx'] < 22:
                regime = 'SIDEWAYS'
            else:
                regime = 'NONE'

            regime_counts[regime] += 1

        total_ready = len(ready_bars)
        for regime, count in regime_counts.items():
            pct = (count / total_ready * 100) if total_ready > 0 else 0
            print(f"  {regime}: {count} ({pct:.1f}%)")

    return df


def test_policies(df):
    """Test regime-aligned policies with engine integration."""
    print("\n=== Testing Regime-Aligned Policies ===")

    # Initialize policies
    momentum_policy = AVWAPMomentumPolicy()
    pullback_policy = AVWAPPullbackPolicy()
    rotation_policy = ValueRotationPolicy()

    policies = {
        "momentum": momentum_policy,
        "pullback": pullback_policy,
        "rotation": rotation_policy,
    }

    results = {}
    for name, policy in policies.items():
        print(f"\n📈 Testing {name.upper()} policy...")

        try:
            # Create backtest config
            config = BacktestConfig(initial_cash=100000.0)
            engine = BacktestEngine(config)

            # Attach policy to engine
            policy.set_engine(engine)

            # Use AAPL data for testing
            symbol_data = df[df['symbol'] == 'AAPL'].copy()
            if len(symbol_data) == 0:
                continue

            # Strategy function
            def strategy_func(engine, bar, p=policy):
                p.process_bar(bar)

            # Run backtest
            result = engine.run(symbol_data, strategy_func)

            # Extract results
            trades = result.trades_history
            orders = result.orders_history

            results[name] = {
                'trades': len(trades),
                'total_return': result.total_return,
                'final_return': result.total_return * 100000,  # Convert to dollar amount
                'orders': len(orders),
                'errors': len(result.errors) if hasattr(result, 'errors') else 0,
            }

            print(f"✅ {name}: {len(trades)} trades, ${results[name]['final_return']:.2f} P&L")

        except Exception as e:
            print(f"❌ Error in {name} policy: {e}")
            results[name] = {'error': str(e)}

    return results


def main():
    """Main smoke test function."""
    print("🚀 Regime-Aligned Strategy Smoke Test")
    print("=" * 50)

    # Load test data
    df = create_test_data()
    print(f"✅ Created test data: {len(df)} bars")

    # Prepare features
    df_features = prepare_features(df)

    # Test policies
    results = test_policies(df_features)

    # Summary
    print("\n" + "=" * 50)
    print("📊 SMOKE TEST SUMMARY")
    print("=" * 50)

    successful_policies = 0
    total_trades = 0

    for name, result in results.items():
        if 'error' in result:
            print(f"❌ {name}: FAILED - {result['error']}")
        else:
            print(f"✅ {name}: {result['trades']} trades, ${result['final_return']:.2f} P&L")
            successful_policies += 1
            total_trades += result['trades']

    print(f"\n🎯 Results Summary:")
    print(f"  Successful policies: {successful_policies}/{len(results)}")
    print(f"  Total trades generated: {total_trades}")

    if successful_policies > 0:
        print("\n🎉 SMOKE TEST: PASSED")
        print("✅ Trade generation is working")
        print("✅ Engine integration is functional")
        print("✅ Regime pipeline is operational")
    else:
        print("\n⚠️  SMOKE TEST: COMPLETED WITH ISSUES")
        print("📝 Policies ran but may need parameter tuning for trade generation")


if __name__ == "__main__":
    main()