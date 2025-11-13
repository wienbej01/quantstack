"""
Volume Price Action (VPA) Feature Pack

Implements 5 pattern flags for volume-price action analysis:
- p__vpa__volume_spike: Abnormal volume spike
- p__vpa__price_breakout: Price breaks recent range
- p__vpa__volume_divergence: Volume-price divergence
- p__vpa__absorption: Volume absorption at price levels
- p__vpa__climax: Volume climax patterns

Each flag has optional confidence scores: conf__vpa__<pattern>
"""

import numpy as np
import pandas as pd


def compute_vpa_features(
    df: pd.DataFrame,
    volume_spike_threshold: float = 2.0,
    price_breakout_window: int = 20,
    divergence_window: int = 10,
    absorption_lookback: int = 5,
    climax_volume_pct: float = 0.95,
) -> pd.DataFrame:
    """
    Compute VPA pattern flags and confidence scores.

    Args:
        df: DataFrame with OHLCV data
        volume_spike_threshold: Threshold for volume spike detection (multiple of avg)
        price_breakout_window: Window for price breakout detection
        divergence_window: Window for volume-price divergence
        absorption_lookback: Lookback for absorption detection
        climax_volume_pct: Percentile for volume climax detection

    Returns:
        DataFrame with VPA features added
    """
    df = df.copy()

    # 1. Volume Spike Detection
    df["volume_avg"] = df["volume"].rolling(window=20, min_periods=10).mean()
    df["volume_ratio"] = df["volume"] / df["volume_avg"]
    df["p__vpa__volume_spike"] = (df["volume_ratio"] > volume_spike_threshold).astype(bool)
    df["conf__vpa__volume_spike"] = np.clip(
        (df["volume_ratio"] - 1.0) / (volume_spike_threshold - 1.0), 0, 1
    )

    # 2. Price Breakout Detection
    df["price_high_max"] = df["high"].rolling(window=price_breakout_window, min_periods=10).max()
    df["price_low_min"] = df["low"].rolling(window=price_breakout_window, min_periods=10).min()
    df["price_range"] = df["price_high_max"] - df["price_low_min"]

    # Bullish breakout: close above previous high
    df["bullish_breakout"] = (df["close"] > df["price_high_max"].shift(1)).astype(bool)
    # Bearish breakout: close below previous low
    df["bearish_breakout"] = (df["close"] < df["price_low_min"].shift(1)).astype(bool)
    df["p__vpa__price_breakout"] = (df["bullish_breakout"] | df["bearish_breakout"]).astype(bool)

    # Confidence based on how much the breakout exceeds the previous range
    df["breakout_strength"] = np.where(
        df["bullish_breakout"] == 1,
        (df["close"] - df["price_high_max"].shift(1)) / df["price_range"].shift(1),
        np.where(
            df["bearish_breakout"] == 1,
            (df["price_low_min"].shift(1) - df["close"]) / df["price_range"].shift(1),
            0,
        ),
    )
    df["conf__vpa__price_breakout"] = np.clip(df["breakout_strength"] * 2, 0, 1)

    # 3. Volume-Price Divergence
    df["price_change"] = df["close"].pct_change()
    df["volume_change"] = df["volume"].pct_change()

    # Price up but volume down (bearish divergence)
    df["bearish_divergence"] = ((df["price_change"] > 0) & (df["volume_change"] < -0.1)).astype(
        bool
    )
    # Price down but volume up (bullish divergence)
    df["bullish_divergence"] = ((df["price_change"] < 0) & (df["volume_change"] > 0.1)).astype(bool)
    df["p__vpa__volume_divergence"] = (df["bearish_divergence"] | df["bullish_divergence"]).astype(
        bool
    )

    # Confidence based on magnitude of divergence
    df["divergence_magnitude"] = np.abs(df["price_change"]) * np.abs(df["volume_change"])
    df["conf__vpa__volume_divergence"] = np.clip(df["divergence_magnitude"] * 5, 0, 1)

    # 4. Volume Absorption Detection
    # High volume but little price movement suggests absorption
    df["price_movement"] = np.abs(df["close"] - df["open"])
    df["price_movement_avg"] = (
        df["price_movement"].rolling(window=absorption_lookback, min_periods=3).mean()
    )
    df["volume_price_ratio"] = df["volume"] / (df["price_movement"] + 1e-8)

    df["vpr_high"] = df["volume_price_ratio"] > df["volume_price_ratio"].rolling(
        window=20, min_periods=10
    ).quantile(0.8)
    df["low_price_movement"] = df["price_movement"] < df["price_movement_avg"] * 0.5
    df["p__vpa__absorption"] = (
        df["vpr_high"] & df["low_price_movement"] & (df["volume"] > df["volume_avg"])
    ).astype(bool)

    # Confidence based on how high the volume-price ratio is
    df["vpr_percentile"] = (
        df["volume_price_ratio"].rolling(window=50, min_periods=20).rank(pct=True)
    )
    df["conf__vpa__absorption"] = np.clip((df["vpr_percentile"] - 0.8) * 5, 0, 1)

    # 5. Volume Climax Detection
    df["volume_percentile"] = df["volume"].rolling(window=50, min_periods=20).rank(pct=True)
    df["p__vpa__climax"] = (df["volume_percentile"] > climax_volume_pct).astype(bool)

    # Confidence based on how extreme the volume is
    df["conf__vpa__climax"] = np.clip(
        (df["volume_percentile"] - climax_volume_pct) / (1.0 - climax_volume_pct), 0, 1
    )

    # Clean up intermediate columns
    intermediate_cols = [
        "volume_avg",
        "volume_ratio",
        "price_high_max",
        "price_low_min",
        "price_range",
        "bullish_breakout",
        "bearish_breakout",
        "breakout_strength",
        "price_change",
        "volume_change",
        "bearish_divergence",
        "bullish_divergence",
        "divergence_magnitude",
        "price_movement",
        "price_movement_avg",
        "volume_price_ratio",
        "vpr_high",
        "low_price_movement",
        "vpr_percentile",
        "volume_percentile",
    ]

    df = df.drop(columns=[col for col in intermediate_cols if col in df.columns])

    return df


def get_vpa_feature_names() -> list:
    """Get list of all VPA feature names."""
    return [
        "p__vpa__volume_spike",
        "p__vpa__price_breakout",
        "p__vpa__volume_divergence",
        "p__vpa__absorption",
        "p__vpa__climax",
        "conf__vpa__volume_spike",
        "conf__vpa__price_breakout",
        "conf__vpa__volume_divergence",
        "conf__vpa__absorption",
        "conf__vpa__climax",
    ]


def validate_vpa_features(df: pd.DataFrame) -> bool:
    """Validate that VPA features are properly computed."""
    required_features = get_vpa_feature_names()

    # Check that all required features exist
    missing_features = [f for f in required_features if f not in df.columns]
    if missing_features:
        print(f"Missing VPA features: {missing_features}")
        return False

    # Check that pattern flags are binary (0 or 1)
    pattern_flags = [f for f in required_features if f.startswith("p__vpa__")]
    for flag in pattern_flags:
        unique_vals = df[flag].unique()
        if not all(val in [0, 1] for val in unique_vals):
            print(f"Pattern flag {flag} has non-binary values: {unique_vals}")
            return False

    # Check that confidence scores are in [0, 1]
    conf_scores = [f for f in required_features if f.startswith("conf__vpa__")]
    for conf in conf_scores:
        if df[conf].min() < 0 or df[conf].max() > 1:
            print(
                f"Confidence score {conf} out of [0,1] range: min={df[conf].min():.3f}, max={df[conf].max():.3f}"
            )
            return False

    return True
