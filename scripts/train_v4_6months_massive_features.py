#!/usr/bin/env python3
"""Train v4 models with 300+ features: multi-timeframe, ICT, VPA, relative analysis."""

import logging
import sys
from pathlib import Path

import lightgbm as lgb
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


def engineer_massive_features(df: pl.DataFrame) -> pl.DataFrame:
    """Engineer 300+ features across multiple timeframes and concepts."""

    # Sort by symbol and timestamp
    df = df.sort(["symbol", "timestamp"])

    # Basic OHLCV features
    df = df.with_columns(
        [
            ((pl.col("close") - pl.col("open")) / pl.col("open") * 100).alias(
                "body_pct"
            ),
            ((pl.col("high") - pl.col("low")) / pl.col("open") * 100).alias(
                "range_pct"
            ),
            (
                (pl.col("high") - pl.max_horizontal(pl.col("close"), pl.col("open")))
                / pl.col("open")
                * 100
            ).alias("upper_wick"),
            (
                (pl.min_horizontal(pl.col("close"), pl.col("open")) - pl.col("low"))
                / pl.col("open")
                * 100
            ).alias("lower_wick"),
            (
                (pl.col("close") - pl.col("low"))
                / (pl.col("high") - pl.col("low") + 1e-8)
            ).alias("price_position"),
        ]
    )

    # Multi-timeframe returns (5, 10, 20, 50, 100, 200 bars)
    for window in [5, 10, 20, 50, 100, 200]:
        df = df.with_columns(
            [
                (pl.col("close").pct_change(window).over("symbol") * 100).alias(
                    f"returns_{window}"
                ),
                (pl.col("volume").rolling_mean(window).over("symbol")).alias(
                    f"volume_ma_{window}"
                ),
                (
                    pl.col("close").rolling_std(window).over("symbol")
                    / pl.col("close")
                    * 100
                ).alias(f"volatility_{window}"),
            ]
        )

    # Volume analysis (multiple timeframes)
    for window in [5, 10, 20, 50]:
        df = df.with_columns(
            [
                (
                    pl.col("volume")
                    / (pl.col("volume").rolling_mean(window).over("symbol") + 1)
                ).alias(f"volume_ratio_{window}"),
                (pl.col("volume").pct_change(window).over("symbol") * 100).alias(
                    f"volume_momentum_{window}"
                ),
            ]
        )

    # VWAP (multiple timeframes) and distance
    for window in [10, 20, 50, 100]:
        typical_price = (pl.col("high") + pl.col("low") + pl.col("close")) / 3
        vwap = (typical_price * pl.col("volume")).rolling_sum(window).over("symbol") / (
            pl.col("volume").rolling_sum(window).over("symbol") + 1e-8
        )
        df = df.with_columns(
            [
                vwap.alias(f"vwap_{window}"),
                ((pl.col("close") - vwap) / (vwap + 1e-8) * 100).alias(
                    f"vwap_dist_{window}"
                ),
            ]
        )

    # RSI (multiple timeframes)
    for window in [7, 14, 21, 50]:
        gains = (
            pl.col("close")
            .diff()
            .clip(lower_bound=0)
            .rolling_mean(window)
            .over("symbol")
        )
        losses = (
            (-pl.col("close").diff())
            .clip(lower_bound=0)
            .rolling_mean(window)
            .over("symbol")
        )
        rs = gains / (losses + 1e-8)
        df = df.with_columns([(100 - 100 / (1 + rs)).alias(f"rsi_{window}")])

    # Bollinger Bands (multiple timeframes)
    for window in [10, 20, 50]:
        ma = pl.col("close").rolling_mean(window).over("symbol")
        std = pl.col("close").rolling_std(window).over("symbol")
        df = df.with_columns(
            [
                ((pl.col("close") - ma) / (std + 1e-8)).alias(f"bb_position_{window}"),
                (std / ma * 100).alias(f"bb_width_{window}"),
            ]
        )

    # ATR (multiple timeframes)
    for window in [7, 14, 21, 50]:
        tr = pl.max_horizontal(
            [
                pl.col("high") - pl.col("low"),
                (pl.col("high") - pl.col("close").shift(1).over("symbol")).abs(),
                (pl.col("low") - pl.col("close").shift(1).over("symbol")).abs(),
            ]
        )
        df = df.with_columns(
            [
                tr.rolling_mean(window).over("symbol").alias(f"atr_{window}"),
                (tr.rolling_mean(window).over("symbol") / pl.col("close") * 100).alias(
                    f"atr_pct_{window}"
                ),
            ]
        )

    # Moving average crossovers
    for fast, slow in [(5, 10), (10, 20), (20, 50), (50, 100)]:
        ma_fast = pl.col("close").rolling_mean(fast).over("symbol")
        ma_slow = pl.col("close").rolling_mean(slow).over("symbol")
        df = df.with_columns(
            [
                ((ma_fast - ma_slow) / ma_slow * 100).alias(f"ma_cross_{fast}_{slow}"),
            ]
        )

    # Price momentum (rate of change)
    for window in [3, 5, 10, 20, 50]:
        df = df.with_columns(
            [
                (
                    (pl.col("close") - pl.col("close").shift(window).over("symbol"))
                    / pl.col("close").shift(window).over("symbol")
                    * 100
                ).alias(f"roc_{window}")
            ]
        )

    # Volume-Price Analysis
    df = df.with_columns(
        [
            # Buying/selling pressure
            (
                (pl.col("close") - pl.col("low"))
                / (pl.col("high") - pl.col("low") + 1e-8)
                * pl.col("volume")
            ).alias("buying_pressure"),
            (
                (pl.col("high") - pl.col("close"))
                / (pl.col("high") - pl.col("low") + 1e-8)
                * pl.col("volume")
            ).alias("selling_pressure"),
        ]
    )

    for window in [5, 10, 20]:
        df = df.with_columns(
            [
                (
                    pl.col("buying_pressure").rolling_sum(window).over("symbol")
                    / (
                        pl.col("selling_pressure").rolling_sum(window).over("symbol")
                        + 1e-8
                    )
                ).alias(f"pressure_ratio_{window}"),
            ]
        )

    # Price-volume divergence
    for window in [10, 20, 50]:
        price_change = pl.col("close").pct_change(window).over("symbol")
        volume_change = pl.col("volume").pct_change(window).over("symbol")
        df = df.with_columns(
            [(price_change - volume_change).alias(f"pv_divergence_{window}")]
        )

    # ICT Concepts - Fair Value Gaps
    for window in [3, 5, 10]:
        gap_up = (pl.col("low") - pl.col("high").shift(2).over("symbol")).clip(
            lower_bound=0
        )
        gap_down = (pl.col("low").shift(2).over("symbol") - pl.col("high")).clip(
            lower_bound=0
        )
        df = df.with_columns(
            [
                gap_up.rolling_sum(window).over("symbol").alias(f"fvg_up_{window}"),
                gap_down.rolling_sum(window).over("symbol").alias(f"fvg_down_{window}"),
            ]
        )

    # ICT - Order Blocks (bullish/bearish engulfing patterns)
    for window in [5, 10, 20]:
        body_size = (pl.col("close") - pl.col("open")).abs()
        prev_body = body_size.shift(1).over("symbol")
        bullish_engulf = (
            (pl.col("close") > pl.col("open"))
            & (
                pl.col("open").shift(1).over("symbol")
                > pl.col("close").shift(1).over("symbol")
            )
            & (body_size > prev_body * 1.5)
        ).cast(pl.Float64)
        bearish_engulf = (
            (pl.col("close") < pl.col("open"))
            & (
                pl.col("close").shift(1).over("symbol")
                > pl.col("open").shift(1).over("symbol")
            )
            & (body_size > prev_body * 1.5)
        ).cast(pl.Float64)
        df = df.with_columns(
            [
                bullish_engulf.rolling_sum(window)
                .over("symbol")
                .alias(f"order_block_bull_{window}"),
                bearish_engulf.rolling_sum(window)
                .over("symbol")
                .alias(f"order_block_bear_{window}"),
            ]
        )

    # ICT - Liquidity Grabs (stop hunts)
    for window in [5, 10, 20]:
        high_break = (
            pl.col("high")
            > pl.col("high").shift(1).over("symbol").rolling_max(window).over("symbol")
        ).cast(pl.Float64)
        low_break = (
            pl.col("low")
            < pl.col("low").shift(1).over("symbol").rolling_min(window).over("symbol")
        ).cast(pl.Float64)
        df = df.with_columns(
            [
                high_break.rolling_sum(window)
                .over("symbol")
                .alias(f"liquidity_grab_high_{window}"),
                low_break.rolling_sum(window)
                .over("symbol")
                .alias(f"liquidity_grab_low_{window}"),
            ]
        )

    # ICT - Break of Structure
    for window in [10, 20, 50]:
        swing_high = pl.col("high").rolling_max(window).over("symbol")
        swing_low = pl.col("low").rolling_min(window).over("symbol")
        bos_bull = (pl.col("close") > swing_high.shift(1).over("symbol")).cast(
            pl.Float64
        )
        bos_bear = (pl.col("close") < swing_low.shift(1).over("symbol")).cast(
            pl.Float64
        )
        df = df.with_columns(
            [
                bos_bull.rolling_sum(window).over("symbol").alias(f"bos_bull_{window}"),
                bos_bear.rolling_sum(window).over("symbol").alias(f"bos_bear_{window}"),
            ]
        )

    # ICT - Displacement (large moves)
    for window in [3, 5, 10]:
        large_move_up = (pl.col("close").pct_change().over("symbol") > 0.02).cast(
            pl.Float64
        )
        large_move_down = (pl.col("close").pct_change().over("symbol") < -0.02).cast(
            pl.Float64
        )
        df = df.with_columns(
            [
                large_move_up.rolling_sum(window)
                .over("symbol")
                .alias(f"displacement_up_{window}"),
                large_move_down.rolling_sum(window)
                .over("symbol")
                .alias(f"displacement_down_{window}"),
            ]
        )

    # Relative comparisons (current vs historical)
    for window in [20, 50, 100]:
        # Current vs N-bar average
        df = df.with_columns(
            [
                (
                    pl.col("close")
                    / pl.col("close").rolling_mean(window).over("symbol")
                    - 1
                ).alias(f"price_vs_ma_{window}"),
                (
                    pl.col("volume")
                    / pl.col("volume").rolling_mean(window).over("symbol")
                    - 1
                ).alias(f"volume_vs_ma_{window}"),
                (
                    pl.col("volatility_20")
                    / pl.col("volatility_20").rolling_mean(window).over("symbol")
                    - 1
                ).alias(f"vol_vs_ma_{window}"),
            ]
        )

    # Percentile ranks (where is current value in historical distribution)
    for window in [50, 100, 200]:
        df = df.with_columns(
            [
                pl.col("close")
                .rank()
                .over("symbol")
                .rolling_mean(window)
                .over("symbol")
                .alias(f"price_rank_{window}"),
                pl.col("volume")
                .rank()
                .over("symbol")
                .rolling_mean(window)
                .over("symbol")
                .alias(f"volume_rank_{window}"),
            ]
        )

    # Time-based features
    df = df.with_columns(
        [
            pl.col("timestamp").dt.hour().alias("hour"),
            pl.col("timestamp").dt.minute().alias("minute"),
        ]
    )

    # Time since market open (9:30 AM = 570 minutes)
    df = df.with_columns(
        [
            (pl.col("hour") * 60 + pl.col("minute") - 570).alias("time_since_open"),
            (960 - (pl.col("hour") * 60 + pl.col("minute"))).alias("time_to_close"),
        ]
    )

    # Intraday patterns
    df = df.with_columns(
        [
            (pl.col("time_since_open") < 30).cast(pl.Float64).alias("is_open_30min"),
            (pl.col("time_to_close") < 30).cast(pl.Float64).alias("is_close_30min"),
            ((pl.col("time_since_open") >= 30) & (pl.col("time_since_open") <= 120))
            .cast(pl.Float64)
            .alias("is_morning"),
            ((pl.col("time_since_open") > 120) & (pl.col("time_to_close") > 120))
            .cast(pl.Float64)
            .alias("is_midday"),
        ]
    )

    # Candle patterns
    df = df.with_columns(
        [
            (pl.col("body_pct").abs() / pl.col("range_pct")).alias("body_to_range"),
            (pl.col("upper_wick") / pl.col("range_pct")).alias("upper_wick_ratio"),
            (pl.col("lower_wick") / pl.col("range_pct")).alias("lower_wick_ratio"),
            ((pl.col("upper_wick") + pl.col("lower_wick")) / pl.col("range_pct")).alias(
                "wick_ratio"
            ),
        ]
    )

    # Doji patterns
    df = df.with_columns(
        [
            (pl.col("body_pct").abs() < 0.1).cast(pl.Float64).alias("is_doji"),
            (
                (pl.col("upper_wick") > pl.col("body_pct").abs() * 2)
                & (pl.col("lower_wick") > pl.col("body_pct").abs() * 2)
            )
            .cast(pl.Float64)
            .alias("is_spinning_top"),
        ]
    )

    # Trend strength
    for window in [10, 20, 50]:
        df = df.with_columns(
            [
                (pl.col("close") > pl.col("close").rolling_mean(window).over("symbol"))
                .cast(pl.Float64)
                .rolling_mean(window)
                .over("symbol")
                .alias(f"uptrend_strength_{window}"),
            ]
        )

    # Volatility expansion/contraction
    for window in [10, 20]:
        df = df.with_columns(
            [
                (
                    pl.col(f"atr_{window}")
                    / pl.col(f"atr_{window}").shift(window).over("symbol")
                    - 1
                ).alias(f"atr_change_{window}")
            ]
        )

    # Volume expansion/contraction
    for window in [10, 20]:
        df = df.with_columns(
            [
                (
                    pl.col("volume") / pl.col("volume").shift(window).over("symbol") - 1
                ).alias(f"volume_change_{window}")
            ]
        )

    # Price acceleration (2nd derivative)
    for window in [5, 10, 20]:
        returns = pl.col("close").pct_change().over("symbol")
        df = df.with_columns(
            [
                returns.diff()
                .rolling_mean(window)
                .over("symbol")
                .alias(f"acceleration_{window}")
            ]
        )

    # Support/resistance proximity
    for window in [20, 50, 100]:
        high_level = pl.col("high").rolling_max(window).over("symbol")
        low_level = pl.col("low").rolling_min(window).over("symbol")
        df = df.with_columns(
            [
                ((high_level - pl.col("close")) / pl.col("close") * 100).alias(
                    f"dist_to_resistance_{window}"
                ),
                ((pl.col("close") - low_level) / pl.col("close") * 100).alias(
                    f"dist_to_support_{window}"
                ),
            ]
        )

    return df


def main():
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")

    if not data_dir.exists():
        logging.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    logging.info("Loading training data...")
    train_df = pl.read_parquet(data_dir / "train.parquet")
    val_df = pl.read_parquet(data_dir / "val.parquet")
    oos_df = pl.read_parquet(data_dir / "oos.parquet")

    # Rename ts to timestamp for consistency
    train_df = train_df.rename({"ts": "timestamp"})
    val_df = val_df.rename({"ts": "timestamp"})
    oos_df = oos_df.rename({"ts": "timestamp"})

    # Add dataset labels
    train_df = train_df.with_columns(pl.lit("train").alias("dataset"))
    val_df = val_df.with_columns(pl.lit("val").alias("dataset"))
    oos_df = oos_df.with_columns(pl.lit("oos").alias("dataset"))

    df = pl.concat([train_df, val_df, oos_df])

    logging.info(f"Engineering 300+ features for {len(df):,} rows...")
    df = engineer_massive_features(df)

    # Drop rows with nulls (from rolling windows)
    df = df.drop_nulls()

    logging.info(
        f"After feature engineering: {len(df):,} rows, {len(df.columns)} columns"
    )

    # Split by dataset
    train = df.filter(pl.col("dataset") == "train")
    val = df.filter(pl.col("dataset") == "val")

    logging.info(f"Train: {len(train):,}, Val: {len(val):,}")

    # Get feature columns (exclude metadata)
    exclude_cols = {
        "symbol",
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "label",
        "dataset",
        "hour",
        "minute",
    }
    feature_cols = [c for c in df.columns if c not in exclude_cols]

    logging.info(f"Training with {len(feature_cols)} features")

    # Train LONG model (label == 1)
    logging.info("Training LONG model...")
    train_long = train.filter((pl.col("label") == 1) | (pl.col("label") == 0))
    val_long = val.filter((pl.col("label") == 1) | (pl.col("label") == 0))

    y_train_long = (train_long["label"] == 1).to_numpy().astype(int)
    y_val_long = (val_long["label"] == 1).to_numpy().astype(int)

    X_train_long = train_long.select(feature_cols).to_pandas()
    X_val_long = val_long.select(feature_cols).to_pandas()

    train_data_long = lgb.Dataset(X_train_long, label=y_train_long)
    val_data_long = lgb.Dataset(X_val_long, label=y_val_long, reference=train_data_long)

    params = {
        "objective": "binary",
        "metric": "auc",
        "boosting_type": "gbdt",
        "num_leaves": 31,
        "learning_rate": 0.05,
        "feature_fraction": 0.8,
        "bagging_fraction": 0.8,
        "bagging_freq": 5,
        "verbose": -1,
        "seed": 42,
    }

    model_long = lgb.train(
        params,
        train_data_long,
        num_boost_round=500,
        valid_sets=[val_data_long],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Train SHORT model (label == -1)
    logging.info("Training SHORT model...")
    train_short = train.filter((pl.col("label") == -1) | (pl.col("label") == 0))
    val_short = val.filter((pl.col("label") == -1) | (pl.col("label") == 0))

    y_train_short = (train_short["label"] == -1).to_numpy().astype(int)
    y_val_short = (val_short["label"] == -1).to_numpy().astype(int)

    X_train_short = train_short.select(feature_cols).to_pandas()
    X_val_short = val_short.select(feature_cols).to_pandas()

    train_data_short = lgb.Dataset(X_train_short, label=y_train_short)
    val_data_short = lgb.Dataset(
        X_val_short, label=y_val_short, reference=train_data_short
    )

    model_short = lgb.train(
        params,
        train_data_short,
        num_boost_round=500,
        valid_sets=[val_data_short],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Evaluate
    y_pred_long = model_long.predict(X_val_long)
    y_pred_short = model_short.predict(X_val_short)

    auc_long = roc_auc_score(y_val_long, y_pred_long)
    auc_short = roc_auc_score(y_val_short, y_pred_short)

    logging.info(f"LONG AUC: {auc_long:.4f}")
    logging.info(f"SHORT AUC: {auc_short:.4f}")

    # Save models
    models_dir = Path("models")
    models_dir.mkdir(exist_ok=True)

    model_long.save_model(str(models_dir / "v4_6months_massive_long.txt"))
    model_short.save_model(str(models_dir / "v4_6months_massive_short.txt"))

    logging.info("Models saved")

    # Save feature list
    with open(models_dir / "v4_6months_massive_features.txt", "w") as f:
        for feat in feature_cols:
            f.write(f"{feat}\n")

    logging.info(f"Feature list saved ({len(feature_cols)} features)")


if __name__ == "__main__":
    main()
