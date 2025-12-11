#!/usr/bin/env python3
"""Train v4 models on full gold universe (505 symbols, 6 months)."""

import logging
from pathlib import Path

import lightgbm as lgb
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def load_data():
    """Load feature store and SIP membership."""
    features_path = Path("run/daily_features_full_gold_6months/features.parquet")
    sip_path = Path("run/sip_membership_full_gold_6months/sip_membership.parquet")

    logging.info(f"Loading features: {features_path}")
    features = pl.read_parquet(features_path)

    logging.info(f"Loading SIP: {sip_path}")
    sip = pl.read_parquet(sip_path)

    # Join to filter only SIP symbols
    df = features.join(
        sip.select(["date", "symbol"]), on=["date", "symbol"], how="inner"
    )

    logging.info(
        f"After SIP filter: {len(df):,} rows, {df['symbol'].n_unique()} symbols"
    )
    return df


def engineer_features(df):
    """Create 30 ICT features."""
    df = df.sort(["symbol", "date"])

    # Returns
    df = df.with_columns(
        [
            (pl.col("close").pct_change().over("symbol")).alias("returns"),
            (pl.col("close").pct_change(5).over("symbol")).alias("returns_5"),
            (pl.col("close").pct_change(10).over("symbol")).alias("returns_10"),
            (pl.col("close").pct_change(20).over("symbol")).alias("returns_20"),
        ]
    )

    # Price structure
    df = df.with_columns(
        [
            ((pl.col("high") - pl.col("low")) / pl.col("close")).alias("range_pct"),
            ((pl.col("close") - pl.col("open")).abs() / pl.col("close")).alias(
                "body_pct"
            ),
        ]
    )

    # Wicks (need max/min of open/close)
    df = df.with_columns(
        [
            pl.max_horizontal("open", "close").alias("candle_top"),
            pl.min_horizontal("open", "close").alias("candle_bottom"),
        ]
    )
    df = df.with_columns(
        [
            ((pl.col("high") - pl.col("candle_top")) / pl.col("close")).alias(
                "upper_wick"
            ),
            ((pl.col("candle_bottom") - pl.col("low")) / pl.col("close")).alias(
                "lower_wick"
            ),
        ]
    )

    # Volume
    df = df.with_columns(
        [
            (pl.col("volume").rolling_mean(5).over("symbol")).alias("volume_ma5"),
            (pl.col("volume").rolling_mean(20).over("symbol")).alias("volume_ma20"),
        ]
    )
    df = df.with_columns(
        [
            (pl.col("volume") / pl.col("volume_ma5")).alias("volume_ratio"),
            (pl.col("volume") / pl.col("volume_ma20")).alias("volume_ratio_20"),
        ]
    )

    # Volatility
    df = df.with_columns(
        [
            (pl.col("returns").rolling_std(5).over("symbol")).alias("volatility_5"),
            (pl.col("returns").rolling_std(20).over("symbol")).alias("volatility_20"),
        ]
    )

    # Price position
    df = df.with_columns(
        [
            (pl.col("high").rolling_max(5).over("symbol")).alias("high_5"),
            (pl.col("low").rolling_min(5).over("symbol")).alias("low_5"),
        ]
    )
    df = df.with_columns(
        [
            (
                (pl.col("close") - pl.col("low_5"))
                / (pl.col("high_5") - pl.col("low_5") + 1e-8)
            ).alias("price_position"),
        ]
    )

    # ICT: Fair Value Gap
    df = df.with_columns(
        [
            pl.col("high").shift(1).over("symbol").alias("prev_high"),
            pl.col("low").shift(1).over("symbol").alias("prev_low"),
            pl.col("low").shift(-1).over("symbol").alias("next_low"),
            pl.col("high").shift(-1).over("symbol").alias("next_high"),
        ]
    )
    df = df.with_columns(
        [
            (pl.col("prev_high") < pl.col("next_low")).cast(pl.Int8).alias("fvg_up"),
            (pl.col("prev_low") > pl.col("next_high")).cast(pl.Int8).alias("fvg_down"),
        ]
    )

    # ICT: Displacement
    df = df.with_columns(
        [
            (pl.col("returns").abs() > (pl.col("volatility_5") * 2))
            .cast(pl.Int8)
            .alias("displacement"),
        ]
    )
    df = df.with_columns(
        [
            ((pl.col("returns") > 0) & (pl.col("displacement") == 1))
            .cast(pl.Int8)
            .alias("displacement_up"),
            ((pl.col("returns") < 0) & (pl.col("displacement") == 1))
            .cast(pl.Int8)
            .alias("displacement_down"),
        ]
    )

    # ICT: Order blocks
    df = df.with_columns(
        [
            (pl.col("close") > pl.col("open")).cast(pl.Int8).alias("is_bullish"),
            (pl.col("close") < pl.col("open")).cast(pl.Int8).alias("is_bearish"),
        ]
    )

    # VPA: Effort vs Result
    df = df.with_columns(
        [
            (pl.col("volume_ratio") / (pl.col("range_pct") + 1e-8)).alias(
                "effort_result_ratio"
            ),
        ]
    )

    # ATR-based features
    df = df.with_columns(
        [
            (pl.col("atr14") / pl.col("close")).alias("atr_pct"),
            (pl.col("range_pct") / (pl.col("atr14") / pl.col("close") + 1e-8)).alias(
                "range_atr_ratio"
            ),
        ]
    )

    return df


def create_labels(df, forward_periods=5, profit_threshold=0.015):
    """Create LONG/SHORT labels."""
    df = df.sort(["symbol", "date"])

    # Forward returns
    df = df.with_columns(
        [
            pl.col("close")
            .shift(-forward_periods)
            .over("symbol")
            .alias("future_close"),
        ]
    )
    df = df.with_columns(
        [
            ((pl.col("future_close") - pl.col("close")) / pl.col("close")).alias(
                "forward_return"
            ),
        ]
    )

    # Labels
    df = df.with_columns(
        [
            pl.when(pl.col("forward_return") > profit_threshold)
            .then(1)
            .otherwise(0)
            .alias("label_long"),
            pl.when(pl.col("forward_return") < -profit_threshold)
            .then(1)
            .otherwise(0)
            .alias("label_short"),
        ]
    )

    return df


def main():
    logging.info("=" * 80)
    logging.info("TRAINING V4 MODELS - FULL GOLD UNIVERSE")
    logging.info("=" * 80)

    # Load data
    df = load_data()

    # Engineer features
    logging.info("Engineering features...")
    df = engineer_features(df)

    # Create labels
    logging.info("Creating labels...")
    df = create_labels(df)

    # Drop nulls
    df = df.drop_nulls()
    logging.info(f"After dropping nulls: {len(df):,} rows")

    # Feature columns (30 features)
    feature_cols = [
        "returns",
        "returns_5",
        "returns_10",
        "returns_20",
        "range_pct",
        "body_pct",
        "upper_wick",
        "lower_wick",
        "volume_ratio",
        "volume_ratio_20",
        "volatility_5",
        "volatility_20",
        "price_position",
        "gap_pct",
        "atr_pct",
        "range_atr_ratio",
        "fvg_up",
        "fvg_down",
        "displacement",
        "displacement_up",
        "displacement_down",
        "is_bullish",
        "is_bearish",
        "effort_result_ratio",
    ]

    # Convert to pandas for LightGBM
    df_pd = df.to_pandas()

    # Split: first 80% train, last 20% validation
    split_idx = int(len(df_pd) * 0.8)
    train = df_pd.iloc[:split_idx]
    val = df_pd.iloc[split_idx:]

    logging.info(f"Train: {len(train):,} rows")
    logging.info(f"Val: {len(val):,} rows")

    # Train LONG model
    logging.info("\n" + "=" * 80)
    logging.info("TRAINING LONG MODEL")
    logging.info("=" * 80)

    X_train = train[feature_cols]
    y_train = train["label_long"]
    X_val = val[feature_cols]
    y_val = val["label_long"]

    logging.info(f"Positive rate: {y_train.mean():.2%}")

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

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
    }

    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Evaluate
    y_pred = model_long.predict(X_val)
    auc = roc_auc_score(y_val, y_pred)
    logging.info(f"LONG Model AUC: {auc:.4f}")

    # Save
    model_path = Path("models/v4_full_gold_long.txt")
    model_path.parent.mkdir(exist_ok=True)
    model_long.save_model(str(model_path))
    logging.info(f"Saved: {model_path}")

    # Train SHORT model
    logging.info("\n" + "=" * 80)
    logging.info("TRAINING SHORT MODEL")
    logging.info("=" * 80)

    y_train = train["label_short"]
    y_val = val["label_short"]

    logging.info(f"Positive rate: {y_train.mean():.2%}")

    train_data = lgb.Dataset(X_train, label=y_train)
    val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)

    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(50)],
    )

    # Evaluate
    y_pred = model_short.predict(X_val)
    auc = roc_auc_score(y_val, y_pred)
    logging.info(f"SHORT Model AUC: {auc:.4f}")

    # Save
    model_path = Path("models/v4_full_gold_short.txt")
    model_short.save_model(str(model_path))
    logging.info(f"Saved: {model_path}")

    logging.info("\n" + "=" * 80)
    logging.info("TRAINING COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
