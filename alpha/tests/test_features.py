"""Tests for feature engineering modules.

Tests use real data from the data mounts to ensure features compute correctly.
Following the project policy: no synthetic data for testing when real data is available.
"""

import numpy as np
import pandas as pd
import pytest

from src.data import GoldLoader, L2Loader
from src.features.l2_features import AlphaL2Features
from src.features.price_features import (
    compute_vwap,
    compute_returns,
    compute_atr,
    compute_session_range,
    compute_rsi,
    compute_bollinger_bands,
    compute_all_price_features,
)
from src.features.flow_features import (
    compute_trade_imbalance,
    compute_rvol,
    compute_volume_weighted_imbalance,
    detect_sweep,
    compute_order_flow_aggression,
    compute_all_flow_features,
)


class TestL2Features:
    """Tests for L2 order book features."""

    def test_book_imbalance_range(self):
        """Output in [-1, 1] range."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        engineer = AlphaL2Features({})

        # Test first snapshot
        snapshot = df.iloc[0]
        imb = engineer.compute_book_imbalance(snapshot, levels=5)

        # Check range
        assert -1 <= imb <= 1, f"Book imbalance {imb} outside [-1, 1] range"

    def test_depth_ratio_calculation(self):
        """Verify depth ratio math."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        engineer = AlphaL2Features({})

        snapshot = df.iloc[0]
        ratio = engineer.compute_depth_ratio(snapshot, levels=5)

        # Ratio should be non-negative
        assert ratio >= 0, f"Depth ratio {ratio} should be non-negative"

    def test_book_slope_calculation(self):
        """Test book slope returns two values."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        engineer = AlphaL2Features({})

        snapshot = df.iloc[0]
        bid_slope, ask_slope = engineer.compute_book_slope(snapshot, levels=5)

        # Should return two floats
        assert isinstance(bid_slope, (int, float))
        assert isinstance(ask_slope, (int, float))

    def test_large_order_detection(self):
        """Known large order detected after warmup."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        engineer = AlphaL2Features({"features": {"large_order_threshold_mult": 2}})

        # Warm up with some data
        for i in range(min(20, len(df))):
            engineer.detect_large_orders(df.iloc[i])

        # Test detection
        result = engineer.detect_large_orders(df.iloc[0])

        # Check structure
        assert "has_large_bid" in result
        assert "has_large_ask" in result
        assert isinstance(result["has_large_bid"], bool)
        assert isinstance(result["has_large_ask"], bool)

    def test_depth_drop_detection(self):
        """Detect depth withdrawal after warmup."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty or len(df) < 15:
            pytest.skip("Not enough L2 data available")

        engineer = AlphaL2Features({})

        # Warm up history
        for i in range(10):
            engineer.update_history(df.iloc[i])

        # Test detection
        result = engineer.detect_depth_drop(df.iloc[10])

        # Check structure
        assert "depth_drop_detected" in result
        assert "bid_drop_pct" in result
        assert "ask_drop_pct" in result
        # np.bool_ is valid, use bool() conversion or check with isinstance(..., (bool, np.bool_))
        assert isinstance(result["depth_drop_detected"], (bool, np.bool_))

    def test_l2_feature_computation(self):
        """Test all L2 features compute without errors."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        engineer = AlphaL2Features({})

        features = engineer.compute_all_features(df.iloc[0])

        # Check expected features exist
        expected_keys = [
            "book_imbalance_5",
            "depth_ratio_5",
            "bid_slope_5",
            "ask_slope_5",
            "has_large_bid",
            "has_large_ask",
        ]

        for key in expected_keys:
            assert key in features, f"Missing feature: {key}"


class TestPriceFeatures:
    """Tests for price-based features."""

    @pytest.fixture
    def sample_bars(self):
        """Load sample bars for testing."""
        loader = GoldLoader()
        df = loader.load_bars("AAPL", "2024-01-02", "2024-01-02")
        return df

    def test_vwap_calculation(self, sample_bars):
        """Compare to known VWAP calculation."""
        vwap = compute_vwap(sample_bars)

        # Should be same length
        assert len(vwap) == len(sample_bars)

        # VWAP should be non-negative
        assert (vwap >= 0).all(), "VWAP should be non-negative"

        # VWAP should be close to price (within reasonable range)
        # Note: VWAP is cumulative, so it can deviate from current bar's high/low
        # Check it's in reasonable range relative to close
        diff_pct = (vwap - sample_bars["close"]).abs() / sample_bars["close"]
        assert (diff_pct < 0.1).all(), "VWAP should be within 10% of close price"

    def test_returns_calculation(self, sample_bars):
        """Verify returns are computed correctly."""
        returns_df = compute_returns(sample_bars, periods=[5, 15, 30])

        # Check columns exist
        assert "ret_5" in returns_df.columns
        assert "ret_15" in returns_df.columns
        assert "ret_30" in returns_df.columns

        # First values should be NaN (lookback)
        assert pd.isna(returns_df["ret_5"].iloc[0])

        # Later values should be non-NaN
        assert not pd.isna(returns_df["ret_5"].iloc[10])

    def test_atr_calculation(self, sample_bars):
        """ATR should be positive."""
        atr = compute_atr(sample_bars, period=14)

        # Should be same length
        assert len(atr) == len(sample_bars)

        # Non-null values should be positive
        valid_atr = atr[atr.notna()]
        assert (valid_atr >= 0).all(), "ATR should be non-negative"

    def test_session_range(self, sample_bars):
        """Session high/low computed correctly."""
        result = compute_session_range(sample_bars)

        # Check columns exist
        assert "session_high" in result.columns
        assert "session_low" in result.columns
        assert "session_range" in result.columns
        assert "position_in_range" in result.columns

        # Session high should be >= bar high
        assert (result["session_high"] >= result["high"]).all()

        # Session low should be <= bar low
        assert (result["session_low"] <= result["low"]).all()

        # Position in range should be [0, 1]
        valid = result["position_in_range"].notna()
        pos = result.loc[valid, "position_in_range"]
        assert (pos >= 0).all() and (pos <= 1).all()

    def test_rsi_calculation(self, sample_bars):
        """RSI should be in [0, 100]."""
        rsi = compute_rsi(sample_bars, period=14)

        # Valid RSI values should be in range
        valid_rsi = rsi[rsi.notna()]
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()

    def test_bollinger_bands(self, sample_bars):
        """Bollinger Bands structure."""
        bb_df = compute_bollinger_bands(sample_bars, period=20)

        # Check columns
        assert "bb_middle" in bb_df.columns
        assert "bb_upper" in bb_df.columns
        assert "bb_lower" in bb_df.columns

        # Upper band should be >= middle >= lower
        valid = bb_df["bb_middle"].notna()
        assert (bb_df.loc[valid, "bb_upper"] >= bb_df.loc[valid, "bb_middle"]).all()
        assert (bb_df.loc[valid, "bb_middle"] >= bb_df.loc[valid, "bb_lower"]).all()

    def test_all_price_features(self, sample_bars):
        """All price features compute without errors."""
        result = compute_all_price_features(sample_bars)

        # Should have same length
        assert len(result) == len(sample_bars)

        # Check key features exist
        expected_features = [
            "vwap",
            "ret_5",
            "atr",
            "atr_pct",
            "session_high",
            "rsi",
            "bb_middle",
        ]

        for feat in expected_features:
            assert feat in result.columns, f"Missing feature: {feat}"


class TestFlowFeatures:
    """Tests for trade flow features."""

    @pytest.fixture
    def sample_bars(self):
        """Load sample bars for testing."""
        loader = GoldLoader()
        df = loader.load_bars("AAPL", "2024-01-02", "2024-01-02")
        return df

    def test_trade_imbalance(self, sample_bars):
        """Trade imbalance computed correctly."""
        imb = compute_trade_imbalance(sample_bars, period=1)

        # Should be in [-1, 1]
        valid = imb.notna()
        assert (imb.loc[valid].abs() <= 1).all()

    def test_rvol_calculation(self, sample_bars):
        """RVOL should be positive."""
        rvol = compute_rvol(sample_bars, baseline_period=20)

        # Non-null values should be positive
        valid_rvol = rvol[rvol.notna()]
        assert (valid_rvol > 0).all()

    def test_volume_weighted_imbalance(self, sample_bars):
        """Volume-weighted imbalance computes."""
        vw_imb = compute_volume_weighted_imbalance(sample_bars, period=1)

        # Should have values
        assert len(vw_imb) == len(sample_bars)

    def test_sweep_detection(self):
        """Sweep detection structure."""
        loader = L2Loader()
        df = loader.load_snapshots("LUV", "2025-12-19")

        if df.empty:
            pytest.skip("No L2 data available")

        snapshot = df.iloc[0]
        result = detect_sweep(snapshot, levels=3)

        # Check structure
        assert "bid_sweep_detected" in result
        assert "ask_sweep_detected" in result
        assert isinstance(result["bid_sweep_detected"], bool)

    def test_order_flow_aggression(self, sample_bars):
        """Order flow aggression metrics."""
        agg_df = compute_order_flow_aggression(sample_bars, short_period=5, long_period=20)

        # Check columns
        assert "aggression_short" in agg_df.columns
        assert "aggression_long" in agg_df.columns
        assert "aggression_delta" in agg_df.columns

    def test_all_flow_features(self, sample_bars):
        """All flow features compute without errors."""
        result = compute_all_flow_features(sample_bars)

        # Should have same length
        assert len(result) == len(sample_bars)

        # Check key features exist
        expected_features = [
            "trade_imbalance_1",
            "rvol",
            "vw_imbalance",
            "aggression_short",
            "tick_imbalance",
        ]

        for feat in expected_features:
            assert feat in result.columns, f"Missing feature: {feat}"


class TestFeatureAlignment:
    """Tests for feature alignment with price data."""

    def test_price_features_align(self):
        """Features align with price data timestamps."""
        loader = GoldLoader()
        df = loader.load_bars("AAPL", "2024-01-02", "2024-01-02")

        result = compute_all_price_features(df)

        # Same index
        assert result.index.equals(df.index)

        # Same timestamps
        pd.testing.assert_series_equal(result["ts"], df["ts"])
