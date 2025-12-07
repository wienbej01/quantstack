#!/usr/bin/env python3
"""Rolling training and backtest: 6-month train, 1-month val, 1-month OOS."""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def get_date_ranges():
    """Generate rolling date ranges."""
    ranges = []
    # Start: 2024-02 (train 2023-07 to 2023-12, val 2024-01)
    # End: 2025-09 (train 2025-02 to 2025-07, val 2025-08)
    
    start_year, start_month = 2024, 2
    end_year, end_month = 2025, 9
    
    current_year, current_month = start_year, start_month
    
    while (current_year < end_year) or (current_year == end_year and current_month <= end_month):
        # OOS month
        oos_start = datetime(current_year, current_month, 1).date()
        if current_month == 12:
            oos_end = datetime(current_year + 1, 1, 1).date()
        else:
            oos_end = datetime(current_year, current_month + 1, 1).date()
        
        # Val month (1 month before OOS)
        if current_month == 1:
            val_start = datetime(current_year - 1, 12, 1).date()
            val_end = oos_start
        else:
            val_start = datetime(current_year, current_month - 1, 1).date()
            val_end = oos_start
        
        # Train (6 months before val)
        train_year, train_month = current_year, current_month - 7
        if train_month <= 0:
            train_month += 12
            train_year -= 1
        train_start = datetime(train_year, train_month, 1).date()
        train_end = val_start
        
        ranges.append({
            "oos_month": f"{current_year}-{current_month:02d}",
            "train_start": train_start,
            "train_end": train_end,
            "val_start": val_start,
            "val_end": val_end,
            "oos_start": oos_start,
            "oos_end": oos_end,
        })
        
        # Next month
        current_month += 1
        if current_month > 12:
            current_month = 1
            current_year += 1
    
    return ranges


def train_models(train_df, val_df, feature_cols):
    """Train LONG and SHORT models."""
    X_train = train_df[feature_cols]
    X_val = val_df[feature_cols]
    
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
    
    # LONG model
    y_train_long = train_df["label_long"]
    y_val_long = val_df["label_long"]
    
    train_data = lgb.Dataset(X_train, label=y_train_long)
    val_data = lgb.Dataset(X_val, label=y_val_long, reference=train_data)
    
    model_long = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    
    auc_long = roc_auc_score(y_val_long, model_long.predict(X_val))
    
    # SHORT model
    y_train_short = train_df["label_short"]
    y_val_short = val_df["label_short"]
    
    train_data = lgb.Dataset(X_train, label=y_train_short)
    val_data = lgb.Dataset(X_val, label=y_val_short, reference=train_data)
    
    model_short = lgb.train(
        params,
        train_data,
        num_boost_round=500,
        valid_sets=[val_data],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    
    auc_short = roc_auc_score(y_val_short, model_short.predict(X_val))
    
    return model_long, model_short, auc_long, auc_short


def backtest(model_long, model_short, test_df, feature_cols, threshold=0.30):
    """Backtest on OOS data."""
    X_test = test_df[feature_cols]
    
    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)
    
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1
    
    signals = test_df[test_df["prediction"] != 0].copy()
    
    if len(signals) == 0:
        return None
    
    long_signals = signals[signals["prediction"] == 1]
    short_signals = signals[signals["prediction"] == -1]
    
    long_wins = (long_signals["forward_return"] > 0.015).sum() if len(long_signals) > 0 else 0
    short_wins = (short_signals["forward_return"] < -0.015).sum() if len(short_signals) > 0 else 0
    
    return {
        "total_signals": len(signals),
        "long_signals": len(long_signals),
        "short_signals": len(short_signals),
        "long_win_rate": long_wins / len(long_signals) if len(long_signals) > 0 else 0,
        "short_win_rate": short_wins / len(short_signals) if len(short_signals) > 0 else 0,
        "combined_win_rate": (long_wins + short_wins) / len(signals),
        "total_pnl": long_signals["forward_return"].sum() - short_signals["forward_return"].sum(),
        "avg_pnl": (long_signals["forward_return"].sum() - short_signals["forward_return"].sum()) / len(signals),
    }


def main():
    logging.info("=" * 80)
    logging.info("ROLLING TRAINING AND BACKTEST")
    logging.info("=" * 80)
    
    # Load data
    features_path = Path("run/intraday_features_rolling/features.parquet")
    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)
    df = df.drop_nulls()
    df_pd = df.to_pandas()
    
    logging.info(f"Data: {len(df_pd):,} bars")
    
    # Feature columns
    feature_cols = [
        "returns", "returns_5", "returns_10", "returns_20",
        "range_pct", "body_pct", "upper_wick", "lower_wick",
        "volume_ratio", "volume_ratio_20",
        "volatility_5", "volatility_20",
        "time_since_open", "time_to_close",
        "price_position",
        "fvg_up", "fvg_down", "fvg_size_pct",
        "displacement_up", "displacement_down",
        "order_block_bull", "order_block_bear",
        "liquidity_grab_high", "liquidity_grab_low",
        "bos_up", "bos_down",
        "pressure_ratio", "distance_from_vwap",
        "volume_momentum", "pv_divergence",
    ]
    
    # Get date ranges
    ranges = get_date_ranges()
    logging.info(f"Rolling iterations: {len(ranges)}")
    
    # Output directories
    models_dir = Path("run/rolling_results/models")
    models_dir.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    for i, range_info in enumerate(ranges, 1):
        oos_month = range_info["oos_month"]
        logging.info("")
        logging.info("=" * 80)
        logging.info(f"ITERATION {i}/{len(ranges)}: OOS {oos_month}")
        logging.info("=" * 80)
        logging.info(f"Train: {range_info['train_start']} to {range_info['train_end']}")
        logging.info(f"Val: {range_info['val_start']} to {range_info['val_end']}")
        logging.info(f"OOS: {range_info['oos_start']} to {range_info['oos_end']}")
        
        # Split data
        train_df = df_pd[(df_pd["date"] >= range_info["train_start"]) & (df_pd["date"] < range_info["train_end"])]
        val_df = df_pd[(df_pd["date"] >= range_info["val_start"]) & (df_pd["date"] < range_info["val_end"])]
        test_df = df_pd[(df_pd["date"] >= range_info["oos_start"]) & (df_pd["date"] < range_info["oos_end"])]
        
        logging.info(f"Train: {len(train_df):,} bars")
        logging.info(f"Val: {len(val_df):,} bars")
        logging.info(f"OOS: {len(test_df):,} bars")
        
        if len(train_df) == 0 or len(val_df) == 0 or len(test_df) == 0:
            logging.warning("Insufficient data, skipping")
            continue
        
        # Train
        logging.info("Training models...")
        model_long, model_short, auc_long, auc_short = train_models(train_df, val_df, feature_cols)
        logging.info(f"LONG AUC: {auc_long:.4f}, SHORT AUC: {auc_short:.4f}")
        
        # Save models
        model_long.save_model(str(models_dir / f"{oos_month}_long.txt"))
        model_short.save_model(str(models_dir / f"{oos_month}_short.txt"))
        
        # Backtest
        logging.info("Backtesting...")
        metrics = backtest(model_long, model_short, test_df.copy(), feature_cols)
        
        if metrics:
            logging.info(f"Signals: {metrics['total_signals']}")
            logging.info(f"Win Rate: {metrics['combined_win_rate']:.2%}")
            logging.info(f"Total P&L: {metrics['total_pnl']:.2%}")
            
            results.append({
                "oos_month": oos_month,
                "auc_long": auc_long,
                "auc_short": auc_short,
                **metrics
            })
        else:
            logging.warning("No signals generated")
    
    # Save results
    results_df = pd.DataFrame(results)
    results_file = Path("run/rolling_results/metrics.csv")
    results_df.to_csv(results_file, index=False)
    
    logging.info("")
    logging.info("=" * 80)
    logging.info("ROLLING BACKTEST COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Results saved to: {results_file}")
    
    # Summary
    logging.info("")
    logging.info("SUMMARY:")
    logging.info(f"Total iterations: {len(results)}")
    logging.info(f"Avg win rate: {results_df['combined_win_rate'].mean():.2%}")
    logging.info(f"Total P&L: {results_df['total_pnl'].sum():.2%}")
    logging.info(f"Total signals: {results_df['total_signals'].sum()}")


if __name__ == "__main__":
    main()
