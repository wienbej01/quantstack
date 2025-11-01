"""Tests for HMM SIP Universe Selector MVP."""

import tempfile
from pathlib import Path

import pandas as pd
import pytest
from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def create_sample_bars():
    """Create sample bars DataFrame for testing."""
    # Create timestamps for two ET days (2024-01-02 and 2024-01-03)
    # This ensures we have previous day close data for gap calculations
    timestamps = []
    symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA"]

    # Base prices for each symbol (will be used for close prices)
    base_prices = {symbol: 100.0 + hash(symbol) % 50 for symbol in symbols}

    for day_offset in [0, 1]:  # Day 0 = 2024-01-02, Day 1 = 2024-01-03
        et_date = pd.Timestamp("2024-01-02", tz="America/New_York") + pd.Timedelta(
            days=day_offset
        )

        # Pre-market (4:00 AM to 9:29 AM ET)
        for hour in range(4, 9):
            for minute in range(0, 60):
                et_time = et_date.replace(hour=hour, minute=minute)
                utc_time = et_time.tz_convert("UTC")
                timestamps.append((int(utc_time.value), day_offset))

        # RTH (9:30 AM to 4:00 PM ET)
        for hour in range(9, 16):
            for minute in range(0, 60):
                if hour == 9 and minute < 30:
                    continue
                if hour >= 16:
                    continue
                et_time = et_date.replace(hour=hour, minute=minute)
                utc_time = et_time.tz_convert("UTC")
                timestamps.append((int(utc_time.value), day_offset))

    # Create sample data
    data = []
    for ts, day_offset in timestamps:
        for symbol in symbols:
            base_price = base_prices[symbol]
            # Add some variation and a gap for day 1 (2024-01-03)
            if day_offset == 1:  # Second day - create a gap
                open_price = base_price * 1.02  # 2% gap up
                close_price = base_price * 1.015  # Slight pullback
            else:  # First day - normal prices
                open_price = base_price
                close_price = base_price

            data.append(
                {
                    "ts": ts,
                    "symbol": symbol,
                    "open": open_price,
                    "high": open_price * 1.01,
                    "low": open_price * 0.99,
                    "close": close_price,
                    "volume": 1000000 + hash(symbol) % 500000,
                }
            )

    return pd.DataFrame(data)


def create_external_premarket_file(temp_dir, date_str, symbols=None, scores=None):
    """Create external premarket file for testing."""
    if symbols is None:
        symbols = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "META", "NVDA"]

    if scores is None:
        scores = [0.9, 0.85, 0.8, 0.75, 0.7, 0.65, 0.6]

    # Ensure we have at least as many scores as symbols
    scores = scores[: len(symbols)]
    while len(scores) < len(symbols):
        scores.append(0.5)

    data = []
    for symbol, score in zip(symbols, scores, strict=False):
        data.append(
            {
                "sym": symbol,
                "score": score,
                "rank": 1,
            }
        )

    df = pd.DataFrame(data)
    # Create file directly in temp_dir (selector expects this path structure)
    parquet_path = Path(temp_dir) / f"{date_str}_pre.parquet"
    df.to_parquet(parquet_path, index=False)

    return parquet_path


def test_hmm_sip_selector_with_external_file():
    """Test HMM SIP selector with external premarket file."""
    # Create sample data
    bars_df = create_sample_bars()

    # Create temporary external file
    with tempfile.TemporaryDirectory() as temp_dir:
        create_external_premarket_file(temp_dir, "2024-01-03")

        # Configure selector
        config = HMMSIPConfig(
            top_k=5, external_premarket_root=str(temp_dir), enable_gold_fallback=False
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Verify results
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0  # Should have RTH bars

        # Check that all timestamps map to the same symbol set
        symbol_sets = list(universe_map.values())
        assert all(symbol_set == symbol_sets[0] for symbol_set in symbol_sets)

        # Should have top 5 symbols
        assert len(symbol_sets[0]) == 5


def test_hmm_sip_selector_no_external_file():
    """Test HMM SIP selector without external file (should return empty)."""
    bars_df = create_sample_bars()

    # Configure selector without fallback
    config = HMMSIPConfig(
        top_k=5, external_premarket_root="/nonexistent/path", enable_gold_fallback=False
    )

    selector = HMMSIPUniverseSelector(config)

    # Select universe
    ref = {"target_date": "2024-01-03"}
    universe_map = selector.select(bars_df, ref)

    # Should return empty dict when no external file and no fallback
    assert universe_map == {}


def test_hmm_sip_selector_gold_fallback():
    """Test HMM SIP selector with Gold fallback."""
    bars_df = create_sample_bars()

    # Configure selector with fallback
    config = HMMSIPConfig(
        top_k=3,
        score_floor=0.0,  # No score floor for testing
        external_premarket_root="/nonexistent/path",
        enable_gold_fallback=True,
    )

    selector = HMMSIPUniverseSelector(config)

    # Select universe
    ref = {"target_date": "2024-01-03"}
    universe_map = selector.select(bars_df, ref)

    # Should return some results from Gold fallback
    assert isinstance(universe_map, dict)
    assert len(universe_map) > 0

    # Should have top 3 symbols
    symbol_sets = list(universe_map.values())
    assert len(symbol_sets[0]) == 3


def test_hmm_sip_selector_score_floor():
    """Test HMM SIP selector with score floor."""
    bars_df = create_sample_bars()

    # Create external file with scores
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create low scores that will be filtered by score floor
        create_external_premarket_file(
            temp_dir,
            "2024-01-03",
            symbols=["AAPL", "GOOGL", "MSFT"],
            scores=[0.1, 0.15, 0.2],  # All below 0.5 floor
        )

        # Configure selector with high score floor
        config = HMMSIPConfig(
            top_k=5,
            score_floor=0.5,
            external_premarket_root=str(temp_dir),
            enable_gold_fallback=True,
        )

        selector = HMMSIPUniverseSelector(config)

        # Select universe
        ref = {"target_date": "2024-01-03"}
        universe_map = selector.select(bars_df, ref)

        # Should use Gold fallback since all external scores are below floor
        assert isinstance(universe_map, dict)
        assert len(universe_map) > 0

        # Should have some symbols from Gold fallback
        symbol_sets = list(universe_map.values())
        assert len(symbol_sets[0]) > 0


def test_hmm_sip_selector_missing_target_date():
    """Test HMM SIP selector without target_date."""
    bars_df = create_sample_bars()

    config = HMMSIPConfig()
    selector = HMMSIPUniverseSelector(config)

    # Should raise ValueError without target_date
    with pytest.raises(ValueError, match="target_date required"):
        selector.select(bars_df, {})


def test_hmm_sip_selector_rth_filtering():
    """Test that only RTH bars are included in universe map."""
    # Use the comprehensive sample bars which include premarket and RTH data
    bars_df = create_sample_bars()

    # Create a config that will use Gold fallback
    config = HMMSIPConfig(
        top_k=1, enable_gold_fallback=True, external_premarket_root="/nonexistent/path"
    )

    selector = HMMSIPUniverseSelector(config)

    # Select universe
    ref = {"target_date": "2024-01-03"}
    universe_map = selector.select(bars_df, ref)

    # Should return some RTH timestamps
    assert len(universe_map) > 0

    # All timestamps should be RTH (9:30 AM - 4:00 PM ET)
    # Convert to ET to verify
    bars_et = pd.DataFrame([{"ts": ts} for ts in universe_map])
    bars_et["ts_et"] = pd.to_datetime(bars_et["ts"], unit="ns", utc=True).dt.tz_convert(
        "America/New_York"
    )

    # Check that all timestamps are during RTH
    for ts_et in bars_et["ts_et"]:
        assert (ts_et.hour > 9) or (
            ts_et.hour == 9 and ts_et.minute >= 30
        ), f"Timestamp {ts_et} is not in RTH"
        assert ts_et.hour < 16, f"Timestamp {ts_et} is not in RTH"

    # Should have exactly 1 symbol per timestamp (top_k=1)
    for symbol_set in universe_map.values():
        assert len(symbol_set) == 1


def test_hmm_sip_selector_deterministic():
    """Test that selector produces deterministic results."""
    bars_df = create_sample_bars()

    config = HMMSIPConfig(
        top_k=3, enable_gold_fallback=True, external_premarket_root="/nonexistent/path"
    )

    selector = HMMSIPUniverseSelector(config)

    ref = {"target_date": "2024-01-03"}

    # Multiple calls should produce identical results
    universe_map1 = selector.select(bars_df, ref)
    universe_map2 = selector.select(bars_df, ref)

    assert universe_map1 == universe_map2

    # Timestamp keys should be sorted
    timestamps = list(universe_map1.keys())
    assert timestamps == sorted(timestamps)


def test_hmm_sip_config_defaults():
    """Test HMM SIP config defaults."""
    config = HMMSIPConfig()

    assert config.top_k == 40
    assert config.score_floor == 0.0
    assert config.enable_gold_fallback
    assert config.p_hat_threshold is None
    assert config.min_minutes_in_state == 0
    assert "hybrid-local" in config.external_premarket_root
