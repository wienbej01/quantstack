"""Performance benchmark for HMM SIP selector on 1000+ symbols."""

import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from qx_screener.hmm_sip import HMMSIPConfig, HMMSIPUniverseSelector


def create_large_synthetic_dataset(num_symbols: int = 1000) -> pd.DataFrame:
    """Create synthetic dataset with 1000+ symbols for performance testing."""
    symbols = [f"SYM{i:04d}" for i in range(num_symbols)]

    # Create 2 days of data with 5-minute bars
    dates = pd.date_range("2024-01-08", "2024-01-09", freq="D")

    bars = []
    for date in dates:
        # Create 5-minute bars from 4:00 AM to 4:00 PM ET (10 hours = 120 bars per day)
        timestamps = pd.date_range(
            start=f"{date} 04:00:00",
            end=f"{date} 16:00:00",
            freq="5min",
            tz="America/New_York",
        )

        for ts in timestamps:
            for symbol in symbols:
                # Generate realistic price data
                base_price = 100 + np.random.normal(0, 20)
                base_price = max(base_price, 10)  # Ensure positive prices

                # Add some intraday variation
                hour = ts.hour
                if hour < 9:  # Premarket - lower volume
                    volume = np.random.randint(1000, 10000)
                else:  # RTH - higher volume
                    volume = np.random.randint(5000, 50000)

                # Generate OHLC
                close = base_price + np.random.normal(0, 0.5)
                high = close + abs(np.random.normal(0, 0.2))
                low = close - abs(np.random.normal(0, 0.2))
                open_price = low + (high - low) * np.random.random()

                bars.append(
                    {
                        "ts": int(
                            ts.tz_convert("UTC").timestamp() * 1e9
                        ),  # Convert to nanoseconds
                        "symbol": symbol,
                        "open": round(open_price, 2),
                        "high": round(high, 2),
                        "low": round(low, 2),
                        "close": round(close, 2),
                        "volume": volume,
                    }
                )

    return pd.DataFrame(bars)


def create_external_topk_file(symbols: list[str], temp_dir: Path) -> Path:
    """Create external Top-K parquet file for testing."""
    scores = np.random.uniform(0.5, 2.0, len(symbols))
    df = pd.DataFrame({"sym": symbols, "score": scores})
    df = df.sort_values("score", ascending=False)

    parquet_path = temp_dir / "2024-01-09_pre.parquet"
    df.to_parquet(parquet_path, index=False)
    return parquet_path


def test_performance_1000_symbols_external_file():
    """Benchmark performance with 1000 symbols and external file (should be < 30s)."""
    print("Creating 1000-symbol synthetic dataset...")
    bars_df = create_large_synthetic_dataset(1000)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)

        # Create external Top-K file
        top_symbols = [f"SYM{i:04d}" for i in range(50)]  # Top 50 symbols
        create_external_topk_file(top_symbols, temp_path)

        # Configure selector to use temp directory
        config = HMMSIPConfig(
            top_k=40, external_premarket_root=str(temp_path), enable_gold_fallback=True
        )

        selector = HMMSIPUniverseSelector(config)

        print(f"Running selector with {len(bars_df):,} bars...")
        start_time = time.time()

        universe_map = selector.select(bars_df, ref={"target_date": "2024-01-09"})

        elapsed_time = time.time() - start_time

        print(f"Selection completed in {elapsed_time:.2f} seconds")
        print(f"Universe map contains {len(universe_map)} timestamps")

        # Verify we got results
        assert len(universe_map) > 0, "Selector should return some universe data"

        # Performance assertion - should be under 30 seconds
        assert (
            elapsed_time < 30.0
        ), f"Selector took {elapsed_time:.2f}s, should be < 30s"

        print(f"✅ Performance test passed: {elapsed_time:.2f}s < 30s")


def test_performance_1000_symbols_gold_fallback():
    """Benchmark performance with 1000 symbols using Gold fallback (should be < 30s)."""
    print("Creating 1000-symbol synthetic dataset...")
    bars_df = create_large_synthetic_dataset(1000)

    # Configure selector for Gold fallback only (no external files)
    config = HMMSIPConfig(
        top_k=40,
        external_premarket_root="/nonexistent/path",  # Force fallback
        enable_gold_fallback=True,
    )

    selector = HMMSIPUniverseSelector(config)

    print(f"Running Gold fallback selector with {len(bars_df):,} bars...")
    start_time = time.time()

    universe_map = selector.select(bars_df, ref={"target_date": "2024-01-09"})

    elapsed_time = time.time() - start_time

    print(f"Gold fallback completed in {elapsed_time:.2f} seconds")
    print(f"Universe map contains {len(universe_map)} timestamps")

    # Verify we got results
    assert len(universe_map) > 0, "Gold fallback should return some universe data"

    # Performance assertion - should be under 30 seconds
    assert (
        elapsed_time < 30.0
    ), f"Gold fallback took {elapsed_time:.2f}s, should be < 30s"

    print(f"✅ Gold fallback performance test passed: {elapsed_time:.2f}s < 30s")


if __name__ == "__main__":
    print("Running HMM SIP performance benchmarks...")
    print("=" * 60)

    test_performance_1000_symbols_external_file()
    print()
    test_performance_1000_symbols_gold_fallback()

    print()
    print("🎉 All performance benchmarks passed!")
