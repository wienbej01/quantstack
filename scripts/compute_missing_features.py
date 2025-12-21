#!/usr/bin/env python3
"""Compute missing features for Sep-Dec 2025 data."""

import logging
from pathlib import Path
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def compute_features(df: pl.DataFrame) -> pl.DataFrame:
    """Compute all derived features from OHLCV data."""
    
    # Sort by symbol and timestamp
    df = df.sort(["symbol", "timestamp"])
    
    # Basic returns
    df = df.with_columns([
        ((pl.col("close") - pl.col("open")) / pl.col("open")).alias("returns"),
        ((pl.col("close") / pl.col("close").shift(1).over("symbol")) - 1).alias("ret_1m"),
        (pl.col("close") / pl.col("close").shift(1).over("symbol")).log().alias("log_ret_1m"),
    ])
    
    # Multi-period returns
    for period in [5, 10, 20]:
        df = df.with_columns([
            pl.col("returns").rolling_sum(period, min_periods=1).over("symbol").alias(f"returns_{period}")
        ])
    
    # Range and body
    df = df.with_columns([
        ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("range_pct"),
        ((pl.col("close") - pl.col("open")).abs() / pl.col("close")).alias("body_pct"),
        pl.max_horizontal("open", "close").alias("candle_top"),
        pl.min_horizontal("open", "close").alias("candle_bottom"),
    ])
    
    # Wicks
    df = df.with_columns([
        (pl.col("high") - pl.col("candle_top")).alias("upper_wick"),
        (pl.col("candle_bottom") - pl.col("low")).alias("lower_wick"),
    ])
    
    # Volume features
    df = df.with_columns([
        pl.col("volume").rolling_mean(5, min_periods=1).over("symbol").alias("volume_ma5"),
        pl.col("volume").rolling_mean(20, min_periods=1).over("symbol").alias("volume_ma20"),
    ])
    df = df.with_columns([
        (pl.col("volume") / pl.col("volume_ma5")).alias("volume_ratio"),
        (pl.col("volume") / pl.col("volume_ma20")).alias("volume_ratio_20"),
    ])
    
    # Volatility
    df = df.with_columns([
        pl.col("returns").rolling_std(5, min_periods=1).over("symbol").alias("volatility_5"),
        pl.col("returns").rolling_std(20, min_periods=1).over("symbol").alias("volatility_20"),
        pl.col("range_pct").rolling_mean(14, min_periods=1).over("symbol").alias("atr"),
    ])
    
    # Time features (assuming bar_index is available)
    df = df.with_columns([
        pl.col("bar_index").alias("time_since_open"),
        (390 - pl.col("bar_index")).alias("time_to_close"),
    ])
    
    # High/Low lookback
    df = df.with_columns([
        pl.col("high").rolling_max(5, min_periods=1).over("symbol").alias("high_5"),
        pl.col("low").rolling_min(5, min_periods=1).over("symbol").alias("low_5"),
    ])
    
    # Price position
    df = df.with_columns([
        ((pl.col("close") - pl.col("low_5")) / (pl.col("high_5") - pl.col("low_5"))).alias("price_position")
    ])
    
    # Previous high/low
    df = df.with_columns([
        pl.col("high").shift(1).over("symbol").alias("prev_high"),
        pl.col("low").shift(1).over("symbol").alias("prev_low"),
        pl.col("low").shift(-1).over("symbol").alias("next_low"),
        pl.col("high").shift(-1).over("symbol").alias("next_high"),
    ])
    
    # ICT features - FVG
    df = df.with_columns([
        (pl.col("low") > pl.col("high").shift(2).over("symbol")).cast(pl.Int64).alias("fvg_up"),
        (pl.col("high") < pl.col("low").shift(2).over("symbol")).cast(pl.Int64).alias("fvg_down"),
    ])
    df = df.with_columns([
        (pl.col("low") - pl.col("high").shift(2).over("symbol")).alias("fvg_size"),
    ])
    df = df.with_columns([
        (pl.col("fvg_size") / pl.col("close")).alias("fvg_size_pct"),
    ])
    
    # Displacement
    df = df.with_columns([
        ((pl.col("close") > pl.col("high").shift(1).over("symbol")) & 
         (pl.col("range_pct") > pl.col("range_pct").rolling_mean(5, min_periods=1).over("symbol") * 1.5)).cast(pl.Int64).alias("displacement_up"),
        ((pl.col("close") < pl.col("low").shift(1).over("symbol")) & 
         (pl.col("range_pct") > pl.col("range_pct").rolling_mean(5, min_periods=1).over("symbol") * 1.5)).cast(pl.Int64).alias("displacement_down"),
    ])
    
    # Candle patterns
    df = df.with_columns([
        (pl.col("close") > pl.col("open")).cast(pl.Int64).alias("is_bullish"),
        (pl.col("close") < pl.col("open")).cast(pl.Int64).alias("is_bearish"),
    ])
    df = df.with_columns([
        pl.col("is_bearish").shift(1).over("symbol").cast(pl.Float64).alias("prev_bearish"),
        pl.col("is_bullish").shift(1).over("symbol").cast(pl.Float64).alias("prev_bullish"),
    ])
    
    # Order blocks
    df = df.with_columns([
        ((pl.col("prev_bearish") == 1) & (pl.col("is_bullish") == 1) & (pl.col("close") > pl.col("prev_high"))).cast(pl.Int64).alias("order_block_bull"),
        ((pl.col("prev_bullish") == 1) & (pl.col("is_bearish") == 1) & (pl.col("close") < pl.col("prev_low"))).cast(pl.Int64).alias("order_block_bear"),
    ])
    
    # Previous high/low 5
    df = df.with_columns([
        pl.col("high_5").shift(1).over("symbol").alias("prev_high_5"),
        pl.col("low_5").shift(1).over("symbol").alias("prev_low_5"),
    ])
    
    # Liquidity grabs
    df = df.with_columns([
        ((pl.col("high") > pl.col("prev_high_5")) & (pl.col("close") < pl.col("prev_high_5"))).cast(pl.Int64).alias("liquidity_grab_high"),
        ((pl.col("low") < pl.col("prev_low_5")) & (pl.col("close") > pl.col("prev_low_5"))).cast(pl.Int64).alias("liquidity_grab_low"),
    ])
    
    # Break of structure
    df = df.with_columns([
        (pl.col("high") > pl.col("high").shift(1).over("symbol")).cast(pl.Int64).alias("bos_up"),
        (pl.col("low") < pl.col("low").shift(1).over("symbol")).cast(pl.Int64).alias("bos_down"),
    ])
    
    # Volume analysis
    df = df.with_columns([
        (pl.col("volume") * pl.col("is_bullish")).alias("up_volume"),
        (pl.col("volume") * pl.col("is_bearish")).alias("down_volume"),
    ])
    df = df.with_columns([
        pl.col("up_volume").rolling_sum(5, min_periods=1).over("symbol").alias("up_volume_5"),
        pl.col("down_volume").rolling_sum(5, min_periods=1).over("symbol").alias("down_volume_5"),
    ])
    df = df.with_columns([
        (pl.col("up_volume_5") / (pl.col("up_volume_5") + pl.col("down_volume_5"))).alias("pressure_ratio"),
    ])
    
    # VWAP
    df = df.with_columns([
        ((pl.col("high") + pl.col("low") + pl.col("close")) / 3).alias("typical_price"),
    ])
    df = df.with_columns([
        (pl.col("typical_price") * pl.col("volume")).cum_sum().over("symbol").alias("vwap_num"),
        pl.col("volume").cum_sum().over("symbol").alias("vwap_den"),
    ])
    df = df.with_columns([
        (pl.col("vwap_num") / pl.col("vwap_den")).alias("vwap"),
    ])
    df = df.with_columns([
        ((pl.col("close") - pl.col("vwap")) / pl.col("vwap")).alias("distance_from_vwap"),
    ])
    
    # Volume momentum
    df = df.with_columns([
        (pl.col("volume") / pl.col("volume").shift(1).over("symbol") - 1).alias("volume_momentum"),
    ])
    
    # Price/volume changes
    df = df.with_columns([
        pl.col("close").pct_change().over("symbol").alias("price_pct_change"),
        pl.col("volume").pct_change().over("symbol").alias("volume_pct_change"),
    ])
    df = df.with_columns([
        pl.col("price_pct_change").rolling_sum(5).over("symbol").alias("price_change_5"),
        pl.col("volume_pct_change").rolling_sum(5).over("symbol").alias("volume_change_5"),
    ])
    
    # PV divergence
    df = df.with_columns([
        (pl.col("price_change_5") * pl.col("volume_change_5")).alias("pv_divergence"),
    ])
    
    # Forward return (target)
    df = df.with_columns([
        pl.col("returns").shift(-30).over("symbol").alias("forward_return"),
    ])
    
    # Labels
    df = df.with_columns([
        (pl.col("forward_return") > 0.001).cast(pl.Int64).alias("label_long"),
        (pl.col("forward_return") < -0.001).cast(pl.Int64).alias("label_short"),
    ])
    
    return df

def main():
    logging.info("=" * 80)
    logging.info("COMPUTING FEATURES FOR SEP-DEC 2025 DATA")
    logging.info("=" * 80)
    
    # Load data
    features_path = Path("run/intraday_features_rolling/features.parquet")
    df = pl.read_parquet(features_path)
    logging.info(f"Loaded {len(df):,} rows")
    
    # Split into old (with features) and new (needs features)
    df_old = df.filter(pl.col("timestamp").dt.date() < pl.date(2025, 9, 10))
    df_new = df.filter(pl.col("timestamp").dt.date() >= pl.date(2025, 9, 10))
    
    logging.info(f"Old data (with features): {len(df_old):,} rows")
    logging.info(f"New data (needs features): {len(df_new):,} rows")
    
    # Compute features for new data
    logging.info("Computing features...")
    df_new_computed = compute_features(df_new)
    
    # Verify features computed
    returns_non_null = df_new_computed["returns"].drop_nulls().len()
    logging.info(f"Returns computed: {returns_non_null:,} / {len(df_new_computed):,}")
    
    forward_non_null = df_new_computed["forward_return"].drop_nulls().len()
    logging.info(f"Forward return computed: {forward_non_null:,} / {len(df_new_computed):,}")
    
    # Combine - align columns
    old_cols = set(df_old.columns)
    new_cols = set(df_new_computed.columns)
    
    # Remove extra columns from new data
    extra_cols = new_cols - old_cols
    if extra_cols:
        logging.info(f"Removing extra columns: {extra_cols}")
        df_new_computed = df_new_computed.drop(list(extra_cols))
    
    # Add missing columns to new data
    missing_cols = old_cols - new_cols
    for col in missing_cols:
        dtype = df_old.select(pl.col(col)).dtypes[0]
        df_new_computed = df_new_computed.with_columns(pl.lit(None).cast(dtype).alias(col))
    
    # Reorder to match
    df_new_computed = df_new_computed.select(df_old.columns)
    
    combined = pl.concat([df_old, df_new_computed])
    logging.info(f"Combined: {len(combined):,} rows")
    
    # Save
    combined.write_parquet(features_path)
    logging.info(f"Saved to {features_path}")
    logging.info("🎉 Features computed successfully!")

if __name__ == "__main__":
    main()
