#!/usr/bin/env python3
"""Simple test to check data loading and HMM SIP."""

import sys
from pathlib import Path

import pandas as pd
import yaml

# Add all qx modules to Python path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root / "qx-core" / "src"))
sys.path.insert(0, str(project_root / "qx-data" / "src"))
sys.path.insert(0, str(project_root / "qx-features" / "src"))
sys.path.insert(0, str(project_root / "qx-screener" / "src"))
sys.path.insert(0, str(project_root / "qx-backtest" / "src"))

from qx_core.validators import validate_bars_dataframe
from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def main():
    print("Simple HMM SIP test")
    print("=" * 40)

    # Load configuration
    config_path = Path(__file__).parent / "experiments" / "vwap_revert" / "strategy.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    print(f"Testing with {len(config['symbols'])} symbols")
    print(f"Date range: {config['dates'][0]} to {config['dates'][2]}")  # Just first 3 days

    # Load data for just 3 days (disable validation to handle duplicates ourselves)
    test_dates = config["dates"][:3]
    bars = load_bars(
        root=config["gold_root"],
        family=config["family"],
        symbols=config["symbols"],
        dates=test_dates,
        validate=False,
    )

    print(f"Loaded {len(bars):,} bars")
    print(f"Symbols: {sorted(bars['symbol'].unique())}")

    # Fix timestamps if needed
    if bars["ts"].max() < 1e12:
        bars["ts"] = bars["ts"] * 1e9

    # Convert timestamps for display
    bars["dt"] = pd.to_datetime(bars["ts"], unit="ns")
    print(f"Date range: {bars['dt'].min()} to {bars['dt'].max()}")

    # Remove duplicates
    before = len(bars)
    bars = bars.drop_duplicates(subset=["symbol", "ts"], keep="last")
    after = len(bars)
    if before != after:
        print(f"Removed {before - after} duplicates")

    print(f"Final dataset: {len(bars):,} bars")

    # Validate
    try:
        validate_bars_dataframe(bars)
        print("✓ Data validation passed")
    except Exception as e:
        print(f"✗ Data validation failed: {e}")
        return

    # Apply features
    print("Applying features...")
    feature_df = compute_all_core_features(bars, vwap_window=30, rvol_window=30, atr_window=14)
    print(f"✓ Features applied, shape: {feature_df.shape}")

    # Test HMM SIP
    print("Testing HMM SIP...")
    sip_config = HMMSIPConfig(mode="daily", score_floor=0.0, top_k=5, enable_gold_fallback=True)

    sip_selector = HMMSIPUniverseSelector(sip_config)
    ref_context = {"target_date": test_dates[0]}

    universe_map = sip_selector.select(feature_df, ref_context)
    print(f"✓ HMM SIP completed, universe for {len(universe_map)} timestamps")

    if universe_map:
        avg_size = sum(len(s) for s in universe_map.values()) / len(universe_map)
        print(f"Average universe size: {avg_size:.1f}")

        first_ts = min(universe_map.keys())
        first_universe = sorted(universe_map[first_ts])
        print(f"Example universe: {first_universe}")

    print("✓ Simple test completed successfully!")


if __name__ == "__main__":
    main()
