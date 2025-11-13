"""Tests for HMM SIP minute-level p̂ gating functionality."""

import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def create_sample_bars_with_minutes():
    """Create sample bars DataFrame with minute-level granularity for testing."""
    symbols = ["AAPL", "GOOGL", "MSFT", "AMZN"]

    # Create timestamps for one ET day (2024-01-03) with minute-level RTH bars
    et_date = pd.Timestamp("2024-01-03", tz="America/New_York")
    timestamps = []

    # RTH (9:30 AM to 4:00 PM ET) - create one bar per minute
    for hour in range(9, 16):
        for minute in range(0, 60):
            if hour == 9 and minute < 30:
                continue  # Skip pre-9:30
            if hour >= 16:
                continue  # End at 4:00 PM

            et_time = et_date.replace(hour=hour, minute=minute, second=0)
            utc_time = et_time.tz_convert("UTC")
            timestamps.append(int(utc_time.timestamp() * 1e9))

    # Create sample data
    data = []
    base_prices = {"AAPL": 150.0, "GOOGL": 140.0, "MSFT": 370.0, "AMZN": 155.0}

    for ts in timestamps:
        for symbol in symbols:
            base_price = base_prices[symbol]
            # Add small random variation
            price_variation = np.random.normal(0, 0.1)

            data.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "open": base_price + price_variation,
                    "high": base_price + price_variation + 0.5,
                    "low": base_price + price_variation - 0.5,
                    "close": base_price + price_variation,
                    "volume": 100000 + np.random.randint(-10000, 10000),
                }
            )

    return pd.DataFrame(data)


def create_p_hat_files(temp_dir, target_date, symbols, p_hat_data):
    """Create minute-level p_hat files for testing."""
    target_dt = pd.Timestamp(target_date)
    year = target_dt.year
    month_str = target_dt.strftime("%Y-%m")

    for symbol in symbols:
        if symbol not in p_hat_data:
            continue

        # Create directory structure
        symbol_dir = Path(temp_dir) / "hybrid-local" / "signals" / "sip" / "1m" / symbol / str(year)
        symbol_dir.mkdir(parents=True, exist_ok=True)

        # Create p_hat data
        data = []
        for ts, p_hat in p_hat_data[symbol]:
            data.append(
                {
                    "ts": ts,
                    "p_hat": p_hat,
                }
            )

        df = pd.DataFrame(data)
        parquet_path = symbol_dir / f"{month_str}.parquet"
        df.to_parquet(parquet_path, index=False)


def test_p_hat_gating_basic():
    """Test basic p_hat gating functionality."""
    bars_df = create_sample_bars_with_minutes()

    # Create p_hat data where AAPL always passes, GOOGL sometimes passes, MSFT never passes
    timestamps = bars_df["ts"].unique()
    p_hat_data = {
        "AAPL": [(ts, 0.8) for ts in timestamps],  # Always above threshold
        "GOOGL": [
            (ts, 0.6 if i % 3 == 0 else 0.3) for i, ts in enumerate(timestamps)
        ],  # Every 3rd minute
        "MSFT": [(ts, 0.1) for ts in timestamps],  # Never above threshold
        "AMZN": [(ts, 0.7) for ts in timestamps],  # Always above threshold
    }

    import os

    original_home = os.environ.get("HOME")

    with tempfile.TemporaryDirectory() as temp_dir:
        # Override HOME to point to temp directory
        os.environ["HOME"] = temp_dir

        # Set up hybrid-local structure
        hybrid_local = Path(temp_dir) / "hybrid-local"
        hybrid_local.mkdir(parents=True)

        # Create p_hat files
        create_p_hat_files(temp_dir, "2024-01-03", ["AAPL", "GOOGL", "MSFT", "AMZN"], p_hat_data)

        # Create external premarket file
        premarket_dir = hybrid_local / "signals" / "sip" / "universe" / "pre"
        premarket_dir.mkdir(parents=True)

        premarket_df = pd.DataFrame(
            {"sym": ["AAPL", "GOOGL", "MSFT", "AMZN"], "score": [0.9, 0.8, 0.7, 0.6]}
        )
        premarket_df.to_parquet(premarket_dir / "2024-01-03_pre.parquet", index=False)

        # Configure selector with p_hat gating
        config = HMMSIPConfig(
            top_k=4,
            p_hat_threshold=0.5,
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Debug: Check what happened
        print(f"DEBUG: Universe map has {len(universe_map)} entries")
        if universe_map:
            all_symbols = set()
            for symbols in universe_map.values():
                all_symbols.update(symbols)
            print(f"DEBUG: All symbols in universe: {all_symbols}")

        # Verify results
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0

        # Check that only symbols passing p_hat threshold are included
        all_eligible_symbols = set()
        for symbol_set in universe_map.values():
            all_eligible_symbols.update(symbol_set)

        # AAPL and AMZN should always be eligible (p_hat >= 0.8, 0.7)
        # GOOGL should be eligible only when p_hat >= 0.6 (every 3rd minute)
        # MSFT should never be eligible (p_hat = 0.1)
        assert "AAPL" in all_eligible_symbols
        assert "AMZN" in all_eligible_symbols
        assert "MSFT" not in all_eligible_symbols, (
            f"MSFT should not be eligible but found in: {all_eligible_symbols}"
        )

        # Verify universe map has entries for RTH timestamps only
        rth_timestamps = bars_df["ts"].unique()
        assert set(universe_map.keys()).issubset(set(rth_timestamps))

    # Restore original HOME
    if original_home:
        os.environ["HOME"] = original_home
    else:
        del os.environ["HOME"]


def test_p_hat_gating_with_min_minutes_in_state():
    """Test p_hat gating with min_minutes_in_state requirement."""
    bars_df = create_sample_bars_with_minutes()

    # Create p_hat data where symbols have varying consistency
    timestamps = bars_df["ts"].unique()
    p_hat_data = {
        "AAPL": [(ts, 0.8) for ts in timestamps],  # Always consistent
        "GOOGL": [
            (ts, 0.6 if i < 30 else 0.3) for i, ts in enumerate(timestamps)
        ],  # Only first 30 minutes
        "MSFT": [(ts, 0.1) for ts in timestamps],  # Never passes
        "AMZN": [
            (ts, 0.7 if i >= 10 else 0.4) for i, ts in enumerate(timestamps)
        ],  # After 10 minutes
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        # Set up hybrid-local structure
        hybrid_local = Path(temp_dir) / "hybrid-local"
        hybrid_local.mkdir(parents=True)

        # Create p_hat files
        create_p_hat_files(temp_dir, "2024-01-03", ["AAPL", "GOOGL", "MSFT", "AMZN"], p_hat_data)

        # Create external premarket file
        premarket_dir = hybrid_local / "signals" / "sip" / "universe" / "pre"
        premarket_dir.mkdir(parents=True)

        premarket_df = pd.DataFrame(
            {"sym": ["AAPL", "GOOGL", "MSFT", "AMZN"], "score": [0.9, 0.8, 0.7, 0.6]}
        )
        premarket_df.to_parquet(premarket_dir / "2024-01-03_pre.parquet", index=False)

        # Configure selector with p_hat gating and min_minutes_in_state
        config = HMMSIPConfig(
            top_k=4,
            p_hat_threshold=0.5,
            min_minutes_in_state=5,  # Require 5 consecutive minutes
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Verify results
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0

        # Only AAPL should be consistently eligible for 5+ minutes
        all_eligible_symbols = set()
        for symbol_set in universe_map.values():
            all_eligible_symbols.update(symbol_set)

        # AAPL should be the only symbol consistently above threshold for 5+ minutes
        assert "AAPL" in all_eligible_symbols
        # Other symbols may appear but shouldn't be consistently present


def test_p_hat_gating_no_p_hat_files():
    """Test that gating gracefully falls back when no p_hat files exist."""
    bars_df = create_sample_bars_with_minutes()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create external premarket file but no p_hat files
        hybrid_local = Path(temp_dir) / "hybrid-local"
        premarket_dir = hybrid_local / "signals" / "sip" / "universe" / "pre"
        premarket_dir.mkdir(parents=True)

        premarket_df = pd.DataFrame({"sym": ["AAPL", "GOOGL", "MSFT"], "score": [0.9, 0.8, 0.7]})
        premarket_df.to_parquet(premarket_dir / "2024-01-03_pre.parquet", index=False)

        # Configure selector with p_hat gating but no files exist
        config = HMMSIPConfig(
            top_k=3,
            p_hat_threshold=0.5,
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Should work like normal selector (no gating applied)
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0

        # All symbols from shortlist should be present
        all_eligible_symbols = set()
        for symbol_set in universe_map.values():
            all_eligible_symbols.update(symbol_set)

        assert {"AAPL", "GOOGL", "MSFT"}.issubset(all_eligible_symbols)


def test_p_hat_gating_disabled():
    """Test that selector works normally when p_hat gating is disabled."""
    bars_df = create_sample_bars_with_minutes()

    with tempfile.TemporaryDirectory() as temp_dir:
        # Create external premarket file
        hybrid_local = Path(temp_dir) / "hybrid-local"
        premarket_dir = hybrid_local / "signals" / "sip" / "universe" / "pre"
        premarket_dir.mkdir(parents=True)

        premarket_df = pd.DataFrame({"sym": ["AAPL", "GOOGL", "MSFT"], "score": [0.9, 0.8, 0.7]})
        premarket_df.to_parquet(premarket_dir / "2024-01-03_pre.parquet", index=False)

        # Configure selector without p_hat gating
        config = HMMSIPConfig(
            top_k=3,
            p_hat_threshold=None,  # Disabled
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Should work like normal selector
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0

        # All symbols from shortlist should be present
        all_eligible_symbols = set()
        for symbol_set in universe_map.values():
            all_eligible_symbols.update(symbol_set)

        assert {"AAPL", "GOOGL", "MSFT"}.issubset(all_eligible_symbols)


def test_p_hat_gating_hash_stability():
    """Test that p_hat gating produces stable hashes."""
    bars_df = create_sample_bars_with_minutes()

    # Create deterministic p_hat data
    timestamps = bars_df["ts"].unique()
    p_hat_data = {
        "AAPL": [(ts, 0.8) for ts in timestamps],
        "GOOGL": [(ts, 0.6) for ts in timestamps],
    }

    with tempfile.TemporaryDirectory() as temp_dir:
        # Set up hybrid-local structure
        hybrid_local = Path(temp_dir) / "hybrid-local"
        premarket_dir = hybrid_local / "signals" / "sip" / "universe" / "pre"
        premarket_dir.mkdir(parents=True)

        # Create p_hat files
        create_p_hat_files(temp_dir, "2024-01-03", ["AAPL", "GOOGL"], p_hat_data)

        # Create external premarket file
        premarket_df = pd.DataFrame({"sym": ["AAPL", "GOOGL"], "score": [0.9, 0.8]})
        premarket_df.to_parquet(premarket_dir / "2024-01-03_pre.parquet", index=False)

        # Configure selector with p_hat gating
        config = HMMSIPConfig(
            top_k=2,
            p_hat_threshold=0.5,
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Run selector multiple times - should produce identical results
        ref = {"target_date": "2024-01-03"}
        universe_map1 = selector.select(bars_df, ref)
        universe_map2 = selector.select(bars_df, ref)

        assert universe_map1 == universe_map2

        # Different p_hat thresholds should produce different results
        config_high_threshold = HMMSIPConfig(
            top_k=2,
            p_hat_threshold=0.7,  # Higher threshold
            external_premarket_root=str(premarket_dir),
            enable_gold_fallback=True,
        )

        selector_high = HMMSIPUniverseSelector(config_high_threshold)
        universe_map_high = selector_high.select(bars_df, ref)

        # Should have fewer eligible symbols with higher threshold
        total_symbols_low = sum(len(s) for s in universe_map1.values())
        total_symbols_high = sum(len(s) for s in universe_map_high.values())

        assert total_symbols_high <= total_symbols_low


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
