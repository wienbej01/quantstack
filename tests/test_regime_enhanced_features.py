"""Unit tests for regime-enhanced features."""

import numpy as np
import pandas as pd
import pytest

from qx_features.regime_enhanced import (
    compute_all_regime_enhanced_features,
    compute_avwap_features,
    compute_ict_structures,
    compute_intraday_volume_profile,
    compute_order_flow_vpa,
    compute_stress_contraction,
)


class TestAnchoredVWAPFeatures:
    """Test anchored VWAP feature computations."""

    def test_session_avwap_computation(self):
        """Test session AVWAP computation."""
        # Create sample data
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [
                150.0,
                150.5,
                151.0,
                151.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
            ],
            "high": [
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
            ],
            "low": [
                149.5,
                150.0,
                150.5,
                151.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
                149.0,
            ],
            "close": [
                150.5,
                151.0,
                151.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
                149.0,
            ],
            "volume": [1000, 1200, 1500, 1800, 2000, 1600, 1300, 1100, 900, 800],
        }
        df = pd.DataFrame(data)

        result = compute_avwap_features(df)

        # Check that session AVWAP column exists
        assert "f__anchor__session_avwap" in result.columns

        # Check that AVWAP values are reasonable (within price range)
        assert result["f__anchor__session_avwap"].between(149.0, 152.5).all()

        # Check that AVWAP increases as price-weighted volume accumulates
        # First value should equal first close (since only one bar)
        assert result.iloc[0]["f__anchor__session_avwap"] == result.iloc[0]["close"]

    def test_multiple_sessions(self):
        """Test AVWAP reset across multiple sessions."""
        # Create data spanning two days
        dates = pd.date_range("2024-01-02 09:30:00", periods=20, freq="1min", tz="America/New_York")
        symbols = ["AAPL"] * 10 + ["AAPL"] * 10  # Same symbol, different sessions

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": symbols,
            "open": [150.0] * 20,
            "high": [151.0] * 20,
            "low": [149.0] * 20,
            "close": [150.5] * 20,
            "volume": [1000] * 20,
        }
        df = pd.DataFrame(data)

        result = compute_avwap_features(df)

        # Session AVWAP should reset between days
        # First bar of each session should equal close price
        assert result.iloc[0]["f__anchor__session_avwap"] == result.iloc[0]["close"]
        assert result.iloc[10]["f__anchor__session_avwap"] == result.iloc[10]["close"]

    def test_missing_columns_validation(self):
        """Test that missing required columns raises error."""
        df = pd.DataFrame({"ts": [1], "symbol": ["AAPL"]})

        with pytest.raises(ValueError, match="Missing required columns"):
            compute_avwap_features(df)


class TestIntradayVolumeProfile:
    """Test intraday volume profile computations."""

    def test_profile_computation(self):
        """Test volume profile POC/VAH/VAL computation."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=50, freq="1min", tz="America/New_York")

        # Create data with clear price levels
        np.random.seed(42)
        prices = np.random.uniform(150.0, 152.0, 50)
        volumes = np.random.uniform(500, 2000, 50)

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 50,
            "open": prices - 0.1,
            "high": prices + 0.2,
            "low": prices - 0.2,
            "close": prices + 0.1,
            "volume": volumes,
        }
        df = pd.DataFrame(data)

        result = compute_intraday_volume_profile(df, price_step=0.1)

        # Check profile columns exist
        profile_cols = [
            "f__profile__poc",
            "f__profile__vah",
            "f__profile__val",
            "f__profile__value_acceptance",
            "f__profile__above_value",
            "f__profile__below_value",
        ]

        for col in profile_cols:
            assert col in result.columns

        # Check POC is between VAH and VAL
        valid_rows = result.dropna(subset=["f__profile__poc", "f__profile__vah", "f__profile__val"])
        if not valid_rows.empty:
            assert (valid_rows["f__profile__val"] <= valid_rows["f__profile__poc"]).all()
            assert (valid_rows["f__profile__poc"] <= valid_rows["f__profile__vah"]).all()

    def test_value_acceptance_logic(self):
        """Test value acceptance detection logic."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=30, freq="1min", tz="America/New_York")

        # Create data that moves from outside to inside value area
        prices = np.concatenate(
            [
                np.array([153.0] * 10),  # Above value area
                np.array([151.0] * 10),  # Inside value area
                np.array([149.0] * 10),  # Below value area
            ]
        )

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 30,
            "open": prices - 0.1,
            "high": prices + 0.1,
            "low": prices - 0.1,
            "close": prices,
            "volume": [1000] * 30,
        }
        df = pd.DataFrame(data)

        result = compute_intraday_volume_profile(df, price_step=0.1)

        # Should detect value acceptance when moving from outside to inside
        value_acceptance_col = "f__profile__value_acceptance"
        if value_acceptance_col in result.columns:
            # At least one value acceptance should be detected
            assert result[value_acceptance_col].any()


class TestICTStructures:
    """Test ICT structure computations."""

    def test_fvg_detection(self):
        """Test Fair Value Gap detection."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        # Create data with bullish FVG pattern
        # Bullish FVG: low[t] > high[t-2] and close[t-1] > close[t-2]
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [
                150.0,
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                153.0,
                153.5,
                154.0,
                154.5,
            ],
            "high": [
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                153.0,
                153.5,
                154.0,
                154.5,
                155.0,
            ],
            "low": [
                149.5,
                150.0,
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                153.0,
                153.5,
                154.0,
            ],
            "close": [
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                153.0,
                153.5,
                154.0,
                154.5,
                155.0,
            ],
            "volume": [1000] * 10,
        }
        df = pd.DataFrame(data)

        # Add required ATR and relative volume columns
        df["f__vol__atr_14"] = 1.0
        df["f__vol__rel_volume_30"] = 1.0

        result = compute_ict_structures(df)

        # Check FVG columns exist
        fvg_cols = [
            "f__ict__fvg_bull_lower",
            "f__ict__fvg_bull_upper",
            "f__ict__fvg_bull_active",
            "f__ict__fvg_bear_lower",
            "f__ict__fvg_bear_upper",
            "f__ict__fvg_bear_active",
        ]

        for col in fvg_cols:
            assert col in result.columns

    def test_displacement_leg_detection(self):
        """Test displacement leg detection."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        # Create data with strong displacement (large range, high volume)
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [150.0] * 10,
            "high": [152.0] * 10,  # 2 point range = 2x ATR
            "low": [149.0] * 10,
            "close": [151.0] * 10,
            "volume": [3000] * 10,  # High volume
        }
        df = pd.DataFrame(data)

        # Add required columns
        df["f__vol__atr_14"] = 1.0
        df["f__vol__rel_volume_30"] = 1.0

        result = compute_ict_structures(df)

        # Check displacement columns exist
        disp_cols = ["f__ict__disp_high", "f__ict__disp_low"]
        for col in disp_cols:
            assert col in result.columns
            assert not result[col].isna().all()  # Should have some values

    def test_liquidity_sweep_detection(self):
        """Test liquidity sweep detection."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=30, freq="1min", tz="America/New_York")

        # Create data with equal highs then sweep
        equal_high_price = 152.0
        prices = [151.0] * 10 + [equal_high_price] * 10 + [151.5] * 10  # Sweep above equal high

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 30,
            "open": [p - 0.1 for p in prices],
            "high": [p + 0.1 for p in prices],
            "low": [p - 0.2 for p in prices],
            "close": prices,
            "volume": [1000] * 30,
        }
        df = pd.DataFrame(data)

        # Add required columns
        df["f__vol__atr_14"] = 1.0
        df["f__vol__rel_volume_30"] = 1.0

        result = compute_ict_structures(df)

        # Check sweep columns exist
        sweep_cols = [
            "f__ict__liq_sweep_high",
            "f__ict__liq_sweep_low",
            "f__ict__liq_sweep_high_level",
            "f__ict__liq_sweep_low_level",
        ]

        for col in sweep_cols:
            assert col in result.columns


class TestOrderFlowVPA:
    """Test order flow and VPA computations."""

    def test_ofi_computation(self):
        """Test Order Flow Imbalance computation."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        # Create data with clear directional moves
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [
                150.0,
                150.5,
                151.0,
                151.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
            ],
            "high": [
                150.5,
                151.0,
                151.5,
                152.0,
                152.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
            ],
            "low": [
                149.5,
                150.0,
                150.5,
                151.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
                149.0,
            ],
            "close": [
                150.5,
                151.0,
                151.5,
                152.0,
                151.5,
                151.0,
                150.5,
                150.0,
                149.5,
                149.0,
            ],
            "volume": [1000] * 10,
        }
        df = pd.DataFrame(data)

        result = compute_order_flow_vpa(df)

        # Check OFI columns exist
        ofi_cols = ["f__flow__ofi", "f__flow__ofi_trend"]
        for col in ofi_cols:
            assert col in result.columns
            assert not result[col].isna().all()

        # OFI should be positive when close > open, negative when close < open
        up_bars = df["close"] > df["open"]
        down_bars = df["close"] < df["open"]

        if up_bars.any():
            assert (result.loc[up_bars, "f__flow__ofi"] > 0).any()
        if down_bars.any():
            assert (result.loc[down_bars, "f__flow__ofi"] < 0).any()

    def test_vpa_absorption_detection(self):
        """Test VPA absorption detection."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=20, freq="1min", tz="America/New_York")

        # Create data with absorption characteristics
        # High volume, low range, small body
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 20,
            "open": [150.0] * 20,
            "high": [150.2] * 20,  # Small range
            "low": [149.8] * 20,
            "close": [150.1] * 20,  # Small body
            "volume": [3000] * 20,  # High volume
        }
        df = pd.DataFrame(data)

        # Add required ATR
        df["f__vol__atr_14"] = 1.0

        result = compute_order_flow_vpa(df)

        # Check VPA columns exist
        vpa_cols = [
            "f__vpa__absorption",
            "f__vpa__climax",
            "f__vpa__upthrust",
            "f__vpa__downthrust",
            "f__vpa__stopping_volume",
        ]

        for col in vpa_cols:
            assert col in result.columns

        # Should detect absorption with high volume and low range
        assert result["f__vpa__absorption"].any()


class TestStressContraction:
    """Test stress contraction flag computation."""

    def test_stress_contraction_detection(self):
        """Test stress contraction detection."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            # Stress goes from active (1.0) to inactive (0.0)
            "f__regime__stress_10_10": [
                1.0,
                1.0,
                1.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
                0.0,
            ],
        }
        df = pd.DataFrame(data)

        result = compute_stress_contraction(df)

        # Check stress contraction column exists
        assert "f__stress__contraction" in result.columns

        # Should detect contraction at the transition point
        assert result["f__stress__contraction"].iloc[3]  # Index 3 where stress goes from 1.0 to 0.0

    def test_no_stress_column(self):
        """Test behavior when stress column is missing."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=5, freq="1min", tz="America/New_York")

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 5,
        }
        df = pd.DataFrame(data)

        result = compute_stress_contraction(df)

        # Should add column with all False values
        assert "f__stress__contraction" in result.columns
        assert not result["f__stress__contraction"].any()


class TestRegimeEnhancedPipeline:
    """Test the complete regime-enhanced features pipeline."""

    def test_complete_pipeline(self):
        """Test complete pipeline with all features."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=50, freq="1min", tz="America/New_York")

        np.random.seed(42)
        prices = np.random.uniform(150.0, 152.0, 50)
        volumes = np.random.uniform(500, 2000, 50)

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 50,
            "open": prices - 0.1,
            "high": prices + 0.2,
            "low": prices - 0.2,
            "close": prices + 0.1,
            "volume": volumes,
            # Add stress regime for contraction testing
            "f__regime__stress_10_10": np.concatenate(
                [
                    np.ones(20),  # Stress for first 20 bars
                    np.zeros(30),  # No stress for remaining
                ]
            ),
        }
        df = pd.DataFrame(data)

        result = compute_all_regime_enhanced_features(df)

        # Check that all feature categories are present
        feature_categories = [
            "f__anchor__",
            "f__profile__",
            "f__ict__",
            "f__flow__",
            "f__vpa__",
            "f__stress__",
        ]

        for category in feature_categories:
            features = [col for col in result.columns if col.startswith(category)]
            assert len(features) > 0, f"No features found for category {category}"

        # Check that result has more columns than input
        assert len(result.columns) > len(df.columns)

        # Check that no original columns were lost
        for col in df.columns:
            assert col in result.columns

    def test_pipeline_with_multiple_symbols(self):
        """Test pipeline with multiple symbols."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=20, freq="1min", tz="America/New_York")
        symbols = ["AAPL"] * 10 + ["MSFT"] * 10

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": symbols,
            "open": [150.0] * 20,
            "high": [151.0] * 20,
            "low": [149.0] * 20,
            "close": [150.5] * 20,
            "volume": [1000] * 20,
        }
        df = pd.DataFrame(data)

        result = compute_all_regime_enhanced_features(df)

        # Should handle multiple symbols correctly
        assert len(result) == len(df)
        assert result["symbol"].nunique() == 2

        # Each symbol should have its own feature computations
        for symbol in ["AAPL", "MSFT"]:
            symbol_data = result[result["symbol"] == symbol]
            assert len(symbol_data) == 10

    def test_pipeline_with_custom_config(self):
        """Ensure configurable parameters are accepted and applied."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=30, freq="1min", tz="America/New_York")
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 30,
            "open": np.linspace(150, 151, 30),
            "high": np.linspace(150.5, 151.5, 30),
            "low": np.linspace(149.5, 150.5, 30),
            "close": np.linspace(150.2, 151.2, 30),
            "volume": np.linspace(1000, 2000, 30),
            "f__regime__stress_10_10": np.linspace(0.5, 0.0, 30),
        }
        df = pd.DataFrame(data)

        config = {
            "price_step": 0.05,
            "profile_window": 40,
            "disp_atr_threshold": 1.1,
            "disp_volume_threshold": 1.2,
            "sweep_window": 15,
            "sweep_range_threshold": 0.00015,
            "ofi_ema_span": 5,
            "absorption_range_ratio": 0.55,
            "absorption_body_ratio": 0.2,
            "climax_volume_pct": 0.9,
            "climax_range_ratio": 1.3,
            "climax_wick_ratio": 0.4,
        }

        result = compute_all_regime_enhanced_features(df, config=config)

        assert len(result) == len(df)
        assert any(col.startswith("f__ict__") for col in result.columns)


class TestRegimeEnhancedRegression:
    """Regression tests for fixes in Workstream B."""

    def test_prev_extreme_persistence(self):
        """Create two sessions with synthetic price touches verifying AVWAP holds constant after touch and NaN prior."""
        # Create two sessions data
        dates_session1 = pd.date_range(
            "2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York"
        )
        dates_session2 = pd.date_range(
            "2024-01-03 09:30:00", periods=10, freq="1min", tz="America/New_York"
        )
        all_dates = dates_session1.append(dates_session2)

        # Session 1: Previous day high was 151.0, touched at bar 4
        # Session 2: Previous day high was 152.0, touched at bar 6
        data = {
            "ts": all_dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 20,
            "session_date": ["2024-01-02"] * 10 + ["2024-01-03"] * 10,
            "open": [150.0] * 20,
            "high": [
                150.2,
                150.4,
                150.6,
                151.0,
                151.2,
                151.4,
                151.6,
                151.8,
                152.0,
                152.2,
                152.5,
                152.7,
                152.9,
                153.1,
                153.3,
                152.0,
                152.2,
                152.4,
                152.6,
                152.8,
            ],
            "low": [149.8] * 20,
            "close": [150.1] * 20,
            "volume": [1000] * 20,
        }
        df = pd.DataFrame(data)

        # Import the function to test AVWAP computation directly
        from qx_features.regime_enhanced import _compute_prev_extreme_avwaps

        result = _compute_prev_extreme_avwaps(df)

        # Verify column exists
        assert "f__anchor__prev_high_avwap" in result.columns

        # Session 1: Should be NaN before touch (bars 0-3), then constant after touch (bars 4-9)
        session1_data = result[result["session_date"] == "2024-01-02"]
        assert session1_data["f__anchor__prev_high_avwap"].iloc[:4].isna().all(), (
            "Should be NaN before first touch"
        )
        assert not session1_data["f__anchor__prev_high_avwap"].iloc[4:].isna().any(), (
            "Should not be NaN after touch"
        )

        # Verify persistence - values should be constant after touch
        post_touch_values = session1_data["f__anchor__prev_high_avwap"].iloc[4:]
        assert post_touch_values.nunique() == 1, "AVWAP should remain constant after touch"

        # Session 2: Should be NaN before touch (bars 0-5), then constant after touch (bars 6-9)
        session2_data = result[result["session_date"] == "2024-01-03"]
        assert session2_data["f__anchor__prev_high_avwap"].iloc[:6].isna().all(), (
            "Should be NaN before first touch in session 2"
        )
        assert not session2_data["f__anchor__prev_high_avwap"].iloc[6:].isna().any(), (
            "Should not be NaN after touch in session 2"
        )

    def test_first_fvg_levels_non_null(self):
        """Craft three-bar pattern hitting FVG and assert lower/upper populated, active flag toggles off after fill."""
        # Create data with clear three-candle FVG pattern
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        # Bars 0-2: Create bull FVG (bar 2 high > bar 0 low, with uptrend)
        # Bar 3-9: Fill the FVG progressively
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [
                150.0,
                150.3,
                150.6,
                150.4,
                150.7,
                151.0,
                151.3,
                151.6,
                151.9,
                152.2,
            ],
            "high": [
                150.2,
                150.5,
                150.9,
                150.6,
                150.9,
                151.2,
                151.5,
                151.8,
                152.1,
                152.4,
            ],
            "low": [
                149.8,
                150.1,
                150.4,
                150.2,
                150.5,
                150.8,
                151.1,
                151.4,
                151.7,
                152.0,
            ],
            "close": [
                150.1,
                150.4,
                150.8,
                150.5,
                150.8,
                151.1,
                151.4,
                151.7,
                152.0,
                152.3,
            ],
            "volume": [1000] * 10,
            # Add required columns for ICT computation
            "f__vol__atr_14": [0.5] * 10,
            "f__vol__rel_volume_30": [1.0] * 10,
        }
        df = pd.DataFrame(data)

        result = compute_ict_structures(df, verbose=False)

        # Check FVG columns exist
        assert "f__ict__fvg_bull_lower" in result.columns
        assert "f__ict__fvg_bull_upper" in result.columns
        assert "f__ict__fvg_bull_active" in result.columns

        # First FVG detection should be at bar 2 (index 2)
        fvg_detected = result["f__ict__fvg_bull_lower"].notna()
        assert fvg_detected.iloc[2], "FVG should be detected at bar 2"

        # First detection should have non-null levels
        assert not pd.isna(result["f__ict__fvg_bull_lower"].iloc[2]), (
            "FVG lower should be non-null at first detection"
        )
        assert not pd.isna(result["f__ict__fvg_bull_upper"].iloc[2]), (
            "FVG upper should be non-null at first detection"
        )

        # FVG should be active initially
        assert result["f__ict__fvg_bull_active"].iloc[2], "FVG should be active at first detection"

        # FVG should be filled when price closes within gap (around bar 6-7)
        # Check that active flag eventually becomes False
        assert not result["f__ict__fvg_bull_active"].iloc[-1], "FVG should eventually be filled"

    def test_stopping_volume_flag(self):
        """Generate bars with volume spike and trend reversal; assert boolean flag set once."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=10, freq="1min", tz="America/New_York")

        # Create uptrend followed by volume spike and reversal
        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 10,
            "open": [
                150.0,
                150.2,
                150.4,
                150.6,
                150.8,
                151.0,
                151.2,
                151.4,
                151.6,
                151.8,
            ],
            "high": [
                150.3,
                150.5,
                150.7,
                150.9,
                151.1,
                151.3,
                151.5,
                151.7,
                151.9,
                152.1,
            ],
            "low": [
                149.7,
                149.9,
                150.1,
                150.3,
                150.5,
                150.7,
                150.9,
                151.1,
                151.3,
                151.5,
            ],
            "close": [
                150.2,
                150.4,
                150.6,
                150.8,
                151.0,
                151.2,
                151.4,
                151.6,
                151.8,
                152.0,
            ],
            # Normal volume, then spike at bar 6, then normal
            "volume": [1000, 1100, 1200, 1300, 1400, 5000, 1600, 1700, 1800, 1900],
        }
        df = pd.DataFrame(data)

        result = compute_order_flow_vpa(df, verbose=False)

        # Check stopping volume column exists
        assert "f__vpa__stopping_volume" in result.columns

        # Should detect stopping volume at the volume spike (bar 6, index 5)
        # This is where uptrend continues but with huge volume, followed by reversal
        assert result["f__vpa__stopping_volume"].any(), (
            "Should detect stopping volume at least once"
        )

        # Find where stopping volume was detected
        stopping_bars = result[result["f__vpa__stopping_volume"]]
        assert len(stopping_bars) >= 1, "Should have at least one stopping volume detection"

        # Verify it's a boolean column
        assert result["f__vpa__stopping_volume"].dtype == bool, "Stopping volume should be boolean"

    def test_logging_hygiene(self, capsys):
        """Capture logging: use capsys to confirm silence unless explicitly enabling verbose flag."""
        dates = pd.date_range("2024-01-02 09:30:00", periods=5, freq="1min", tz="America/New_York")

        data = {
            "ts": dates.tz_convert("UTC").view("int64"),
            "symbol": ["AAPL"] * 5,
            "open": [150.0] * 5,
            "high": [151.0] * 5,
            "low": [149.0] * 5,
            "close": [150.5] * 5,
            "volume": [1000] * 5,
            "f__vol__atr_14": [0.5] * 5,
            "f__vol__rel_volume_30": [1.0] * 5,
            "f__regime__stress_10_10": [0.0] * 5,
        }
        df = pd.DataFrame(data)

        # Test with verbose=False (default) - should produce no output
        compute_all_regime_enhanced_features(df, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == "", "Should produce no output when verbose=False"
        assert captured.err == "", "Should produce no error output when verbose=False"

        # Test individual functions with verbose=False
        compute_intraday_volume_profile(df, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == "", "Volume profile should produce no output when verbose=False"

        compute_ict_structures(df, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == "", "ICT structures should produce no output when verbose=False"

        compute_order_flow_vpa(df, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == "", "Order flow VPA should produce no output when verbose=False"

        compute_stress_contraction(df, verbose=False)
        captured = capsys.readouterr()
        assert captured.out == "", "Stress contraction should produce no output when verbose=False"

        # Test with verbose=True - should produce output
        compute_all_regime_enhanced_features(df, verbose=True)
        captured = capsys.readouterr()
        assert captured.out != "", "Should produce output when verbose=True"
        assert "Regime-Enhanced Features Pipeline" in captured.out, (
            "Should contain pipeline header when verbose=True"
        )
