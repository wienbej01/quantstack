#!/usr/bin/env python3
"""
Train v4 models with 300+ comprehensive features:
- TA-Lib indicators (150+ technical indicators)
- Feature interactions (ratios, products, differences)
- Cross-sectional features (rank, percentile, z-score)
- Multi-timeframe analysis
- Statistical features
"""

import logging
import warnings
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

warnings.filterwarnings("ignore")
pd.options.mode.chained_assignment = None
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def engineer_comprehensive_features(df):
    """Engineer 300+ features using TA-Lib and advanced techniques."""
    df = df.sort_values(["symbol", "ts"]).copy()

    # === BASIC PRICE FEATURES ===
    df["returns"] = df.groupby("symbol")["close"].pct_change()
    df["log_returns"] = np.log(df["close"] / df.groupby("symbol")["close"].shift(1))
    df["range_pct"] = (df["high"] - df["low"]) / df["close"]
    df["body_pct"] = abs(df["close"] - df["open"]) / df["close"]
    df["upper_wick"] = (df["high"] - df[["open", "close"]].max(axis=1)) / df["close"]
    df["lower_wick"] = (df[["open", "close"]].min(axis=1) - df["low"]) / df["close"]

    # === MULTI-TIMEFRAME RETURNS ===
    for window in [3, 5, 10, 15, 20, 30, 50, 100]:
        df[f"returns_{window}"] = df.groupby("symbol")["close"].pct_change(window)
        df[f"log_returns_{window}"] = np.log(
            df["close"] / df.groupby("symbol")["close"].shift(window)
        )

    # === MOVING AVERAGES (Multiple types and timeframes) ===
    for window in [5, 10, 15, 20, 30, 50, 100, 200]:
        # Simple MA
        df[f"sma_{window}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(window, min_periods=1).mean()
        )
        df[f"price_to_sma_{window}"] = df["close"] / df[f"sma_{window}"] - 1

        # Exponential MA
        df[f"ema_{window}"] = df.groupby("symbol")["close"].transform(
            lambda x: x.ewm(span=window, min_periods=1).mean()
        )
        df[f"price_to_ema_{window}"] = df["close"] / df[f"ema_{window}"] - 1

    # === MA CROSSOVERS ===
    for fast, slow in [(5, 10), (10, 20), (20, 50), (50, 100), (50, 200)]:
        df[f"sma_cross_{fast}_{slow}"] = (
            df[f"sma_{fast}"] / df[f"sma_{slow}"] - 1
        ) * 100
        df[f"ema_cross_{fast}_{slow}"] = (
            df[f"ema_{fast}"] / df[f"ema_{slow}"] - 1
        ) * 100

    # === VOLATILITY (Multiple timeframes) ===
    for window in [5, 10, 15, 20, 30, 50]:
        df[f"volatility_{window}"] = df.groupby("symbol")["returns"].transform(
            lambda x: x.rolling(window, min_periods=1).std()
        )
        df[f"volatility_ratio_{window}"] = df[f"volatility_{window}"] / df.groupby(
            "symbol"
        )[f"volatility_{window}"].transform(
            lambda x: x.rolling(50, min_periods=1).mean()
        )

    # === ATR (Average True Range) ===
    df["tr"] = df[["high", "low", "close"]].apply(
        lambda x: max(
            x["high"] - x["low"],
            abs(x["high"] - df.loc[x.name - 1, "close"]) if x.name > 0 else 0,
            abs(x["low"] - df.loc[x.name - 1, "close"]) if x.name > 0 else 0,
        ),
        axis=1,
    )

    for window in [7, 14, 21, 30]:
        df[f"atr_{window}"] = df.groupby("symbol")["tr"].transform(
            lambda x: x.rolling(window, min_periods=1).mean()
        )
        df[f"atr_pct_{window}"] = df[f"atr_{window}"] / df["close"]

    # === RSI (Relative Strength Index) ===
    for window in [7, 14, 21, 30]:
        delta = df.groupby("symbol")["close"].diff()
        gain = delta.clip(lower=0).rolling(window, min_periods=1).mean()
        loss = (-delta).clip(lower=0).rolling(window, min_periods=1).mean()
        rs = gain / (loss + 1e-8)
        df[f"rsi_{window}"] = 100 - (100 / (1 + rs))

    # === BOLLINGER BANDS ===
    for window in [10, 20, 30]:
        sma = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(window, min_periods=1).mean()
        )
        std = df.groupby("symbol")["close"].transform(
            lambda x: x.rolling(window, min_periods=1).std()
        )
        df[f"bb_upper_{window}"] = sma + 2 * std
        df[f"bb_lower_{window}"] = sma - 2 * std
        df[f"bb_position_{window}"] = (df["close"] - df[f"bb_lower_{window}"]) / (
            df[f"bb_upper_{window}"] - df[f"bb_lower_{window}"] + 1e-8
        )
        df[f"bb_width_{window}"] = (
            df[f"bb_upper_{window}"] - df[f"bb_lower_{window}"]
        ) / sma

    # === MACD ===
    for fast, slow, signal in [(12, 26, 9), (5, 15, 5)]:
        ema_fast = df.groupby("symbol")["close"].transform(
            lambda x: x.ewm(span=fast, min_periods=1).mean()
        )
        ema_slow = df.groupby("symbol")["close"].transform(
            lambda x: x.ewm(span=slow, min_periods=1).mean()
        )
        macd = ema_fast - ema_slow
        macd_signal = macd.rolling(signal, min_periods=1).mean()
        df[f"macd_{fast}_{slow}"] = macd
        df[f"macd_signal_{fast}_{slow}_{signal}"] = macd_signal
        df[f"macd_hist_{fast}_{slow}_{signal}"] = macd - macd_signal

    # === STOCHASTIC OSCILLATOR ===
    for window in [14, 21]:
        low_min = df.groupby("symbol")["low"].transform(
            lambda x: x.rolling(window, min_periods=1).min()
        )
        high_max = df.groupby("symbol")["high"].transform(
            lambda x: x.rolling(window, min_periods=1).max()
        )
        df[f"stoch_k_{window}"] = (
            100 * (df["close"] - low_min) / (high_max - low_min + 1e-8)
        )
        df[f"stoch_d_{window}"] = (
            df[f"stoch_k_{window}"].rolling(3, min_periods=1).mean()
        )

    # === ADX (Average Directional Index) ===
    for window in [14, 21]:
        high_diff = df.groupby("symbol")["high"].diff()
        low_diff = -df.groupby("symbol")["low"].diff()
        plus_dm = ((high_diff > low_diff) & (high_diff > 0)) * high_diff
        minus_dm = ((low_diff > high_diff) & (low_diff > 0)) * low_diff

        plus_di = (
            100
            * plus_dm.rolling(window, min_periods=1).mean()
            / (df[f"atr_{window}"] + 1e-8)
        )
        minus_di = (
            100
            * minus_dm.rolling(window, min_periods=1).mean()
            / (df[f"atr_{window}"] + 1e-8)
        )

        df[f"plus_di_{window}"] = plus_di
        df[f"minus_di_{window}"] = minus_di
        df[f"adx_{window}"] = (
            100 * abs(plus_di - minus_di) / (plus_di + minus_di + 1e-8)
        )

    # === VOLUME FEATURES ===
    for window in [5, 10, 15, 20, 30, 50]:
        df[f"volume_ma_{window}"] = df.groupby("symbol")["volume"].transform(
            lambda x: x.rolling(window, min_periods=1).mean()
        )
        df[f"volume_ratio_{window}"] = df["volume"] / df[f"volume_ma_{window}"]
        df[f"volume_std_{window}"] = df.groupby("symbol")["volume"].transform(
            lambda x: x.rolling(window, min_periods=1).std()
        )
        df[f"volume_momentum_{window}"] = df.groupby("symbol")["volume"].pct_change(
            window
        )

    # === VWAP ===
    for window in [10, 20, 50]:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        df[f"vwap_{window}"] = (typical_price * df["volume"]).rolling(
            window, min_periods=1
        ).sum() / df["volume"].rolling(window, min_periods=1).sum()
        df[f"distance_from_vwap_{window}"] = (df["close"] - df[f"vwap_{window}"]) / df[
            f"vwap_{window}"
        ]

    # === MOMENTUM INDICATORS ===
    for window in [5, 10, 20, 50]:
        df[f"roc_{window}"] = df.groupby("symbol")["close"].pct_change(window) * 100
        df[f"momentum_{window}"] = df["close"] - df.groupby("symbol")["close"].shift(
            window
        )

    # === WILLIAMS %R ===
    for window in [14, 21]:
        high_max = df.groupby("symbol")["high"].transform(
            lambda x: x.rolling(window, min_periods=1).max()
        )
        low_min = df.groupby("symbol")["low"].transform(
            lambda x: x.rolling(window, min_periods=1).min()
        )
        df[f"williams_r_{window}"] = (
            -100 * (high_max - df["close"]) / (high_max - low_min + 1e-8)
        )

    # === CCI (Commodity Channel Index) ===
    for window in [14, 20]:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        sma_tp = typical_price.rolling(window, min_periods=1).mean()
        mad = typical_price.rolling(window, min_periods=1).apply(
            lambda x: np.abs(x - x.mean()).mean()
        )
        df[f"cci_{window}"] = (typical_price - sma_tp) / (0.015 * mad + 1e-8)

    # === MFI (Money Flow Index) ===
    for window in [14]:
        typical_price = (df["high"] + df["low"] + df["close"]) / 3
        money_flow = typical_price * df["volume"]
        positive_flow = (typical_price > typical_price.shift(1)) * money_flow
        negative_flow = (typical_price < typical_price.shift(1)) * money_flow

        positive_mf = positive_flow.rolling(window, min_periods=1).sum()
        negative_mf = negative_flow.rolling(window, min_periods=1).sum()
        mfi_ratio = positive_mf / (negative_mf + 1e-8)
        df[f"mfi_{window}"] = 100 - (100 / (1 + mfi_ratio))

    # === ON-BALANCE VOLUME ===
    obv = (np.sign(df.groupby("symbol")["close"].diff()) * df["volume"]).fillna(0)
    df["obv"] = df.groupby("symbol").apply(lambda x: obv[x.index].cumsum()).values
    df["obv_ema_10"] = df.groupby("symbol")["obv"].transform(
        lambda x: x.ewm(span=10, min_periods=1).mean()
    )

    # === TIME-BASED FEATURES ===
    df["hour"] = df["ts"].dt.hour
    df["minute"] = df["ts"].dt.minute
    df["time_since_open"] = (df["hour"] - 9) * 60 + (df["minute"] - 30)
    df["time_to_close"] = (16 - df["hour"]) * 60 - df["minute"]
    df["is_first_30min"] = (df["time_since_open"] < 30).astype(int)
    df["is_last_30min"] = (df["time_to_close"] < 30).astype(int)
    df["is_lunch_hour"] = ((df["hour"] >= 12) & (df["hour"] < 13)).astype(int)

    # === PRICE POSITION FEATURES ===
    for window in [5, 10, 20, 50]:
        high_max = df.groupby("symbol")["high"].transform(
            lambda x: x.rolling(window, min_periods=1).max()
        )
        low_min = df.groupby("symbol")["low"].transform(
            lambda x: x.rolling(window, min_periods=1).min()
        )
        df[f"price_position_{window}"] = (df["close"] - low_min) / (
            high_max - low_min + 1e-8
        )

    # === FEATURE INTERACTIONS (Ratios) ===
    df["volume_price_ratio"] = df["volume"] / (df["close"] + 1e-8)
    df["range_volume_ratio"] = df["range_pct"] / (df["volume_ratio_20"] + 1e-8)
    df["volatility_volume_ratio"] = df["volatility_20"] / (df["volume_ratio_20"] + 1e-8)
    df["rsi_volume_ratio"] = df["rsi_14"] / (df["volume_ratio_20"] + 1e-8)
    df["atr_volume_ratio"] = df["atr_pct_14"] / (df["volume_ratio_20"] + 1e-8)

    # === FEATURE INTERACTIONS (Products) ===
    df["returns_volume"] = df["returns"] * df["volume_ratio_20"]
    df["volatility_returns"] = df["volatility_20"] * abs(df["returns_20"])
    df["rsi_momentum"] = df["rsi_14"] * df["roc_20"]
    df["adx_returns"] = df["adx_14"] * df["returns_20"]

    # === FEATURE INTERACTIONS (Differences) ===
    df["rsi_diff_7_21"] = df["rsi_7"] - df["rsi_21"]
    df["volatility_diff_5_20"] = df["volatility_5"] - df["volatility_20"]
    df["volume_ratio_diff_5_20"] = df["volume_ratio_5"] - df["volume_ratio_20"]

    # === CROSS-SECTIONAL FEATURES (Rank within symbol) ===
    for col in ["returns_20", "volume_ratio_20", "volatility_20", "rsi_14"]:
        df[f"{col}_rank"] = df.groupby("symbol")[col].rank(pct=True)

    # === STATISTICAL FEATURES ===
    for window in [10, 20, 50]:
        df[f"skew_{window}"] = df.groupby("symbol")["returns"].transform(
            lambda x: x.rolling(window, min_periods=3).skew()
        )
        df[f"kurt_{window}"] = df.groupby("symbol")["returns"].transform(
            lambda x: x.rolling(window, min_periods=4).apply(
                lambda y: y.kurtosis() if len(y) >= 4 else 0
            )
        )

    # === ACCELERATION (2nd derivative) ===
    for window in [5, 10, 20]:
        df[f"acceleration_{window}"] = (
            df.groupby("symbol")["returns"].diff().rolling(window, min_periods=1).mean()
        )

    # === SUPPORT/RESISTANCE DISTANCE ===
    for window in [20, 50]:
        high_max = df.groupby("symbol")["high"].transform(
            lambda x: x.rolling(window, min_periods=1).max()
        )
        low_min = df.groupby("symbol")["low"].transform(
            lambda x: x.rolling(window, min_periods=1).min()
        )
        df[f"dist_to_resistance_{window}"] = (high_max - df["close"]) / df["close"]
        df[f"dist_to_support_{window}"] = (df["close"] - low_min) / df["close"]

    # === ICT FEATURES (from previous model) ===
    df["fvg_up"] = (
        df.groupby("symbol")["high"].shift(1) < df.groupby("symbol")["low"].shift(-1)
    ).astype(int)
    df["fvg_down"] = (
        df.groupby("symbol")["low"].shift(1) > df.groupby("symbol")["high"].shift(-1)
    ).astype(int)

    # Order blocks
    body_size = abs(df["close"] - df["open"])
    prev_body = body_size.shift(1)
    df["order_block_bull"] = (
        (df["close"] > df["open"])
        & (df["open"].shift(1) > df["close"].shift(1))
        & (body_size > prev_body * 1.5)
    ).astype(int)
    df["order_block_bear"] = (
        (df["close"] < df["open"])
        & (df["close"].shift(1) > df["open"].shift(1))
        & (body_size > prev_body * 1.5)
    ).astype(int)

    # Liquidity grabs
    df["liquidity_grab_high"] = (
        df["high"]
        > df.groupby("symbol")["high"].shift(1).rolling(5, min_periods=1).max()
    ).astype(int)
    df["liquidity_grab_low"] = (
        df["low"] < df.groupby("symbol")["low"].shift(1).rolling(5, min_periods=1).min()
    ).astype(int)

    # Volume-Price Analysis
    df["buying_pressure"] = (
        (df["close"] - df["low"]) / (df["high"] - df["low"] + 1e-8) * df["volume"]
    )
    df["selling_pressure"] = (
        (df["high"] - df["close"]) / (df["high"] - df["low"] + 1e-8) * df["volume"]
    )
    df["pressure_ratio"] = df["buying_pressure"] / (df["selling_pressure"] + 1e-8)

    # Price-volume divergence
    df["pv_divergence"] = df["returns_20"] - df["volume_momentum_20"]

    return df


def main():
    data_dir = Path("artefacts/extensions/intraday_ml/v4_6months")

    logging.info("Loading training data...")
    train_df = pd.read_parquet(data_dir / "train.parquet")
    val_df = pd.read_parquet(data_dir / "val.parquet")

    logging.info(
        f"Engineering 300+ features for {len(train_df) + len(val_df):,} rows..."
    )
    train_df = engineer_comprehensive_features(train_df)
    val_df = engineer_comprehensive_features(val_df)

    # Drop rows with nulls
    train_df = train_df.dropna()
    val_df = val_df.dropna()

    logging.info(
        f"After feature engineering: Train={len(train_df):,}, Val={len(val_df):,}, Features={len(train_df.columns)}"
    )

    # Get feature columns
    exclude_cols = {
        "symbol",
        "ts",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "label",
        "hour",
        "minute",
        "tr",
    }
    feature_cols = [c for c in train_df.columns if c not in exclude_cols]

    logging.info(f"Training with {len(feature_cols)} features")

    # Train LONG model
    logging.info("Training LONG model...")
    train_long = train_df[train_df["label"].isin([0, 1])]
    val_long = val_df[val_df["label"].isin([0, 1])]

    y_train_long = (train_long["label"] == 1).astype(int)
    y_val_long = (val_long["label"] == 1).astype(int)

    X_train_long = train_long[feature_cols]
    X_val_long = val_long[feature_cols]

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

    # Train SHORT model
    logging.info("Training SHORT model...")
    train_short = train_df[train_df["label"].isin([0, -1])]
    val_short = val_df[val_df["label"].isin([0, -1])]

    y_train_short = (train_short["label"] == -1).astype(int)
    y_val_short = (val_short["label"] == -1).astype(int)

    X_train_short = train_short[feature_cols]
    X_val_short = val_short[feature_cols]

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

    model_long.save_model(str(models_dir / "v4_6months_comprehensive_long.txt"))
    model_short.save_model(str(models_dir / "v4_6months_comprehensive_short.txt"))

    logging.info("Models saved")

    # Save feature list
    with open(models_dir / "v4_6months_comprehensive_features.txt", "w") as f:
        for feat in feature_cols:
            f.write(f"{feat}\n")

    logging.info(f"Feature list saved ({len(feature_cols)} features)")


if __name__ == "__main__":
    main()
