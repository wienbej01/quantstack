#!/usr/bin/env python3
"""Compare 13-feature baseline vs 30 ICT features."""

import logging
from pathlib import Path

import lightgbm as lgb
import polars as pl
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def backtest_model(model_long, model_short, df_pd, feature_cols, threshold=0.30):
    """Run backtest and return metrics."""
    X = df_pd[feature_cols]
    
    # Predictions
    df_pd["prob_long"] = model_long.predict(X)
    df_pd["prob_short"] = model_short.predict(X)
    
    df_pd["signal_long"] = (df_pd["prob_long"] >= threshold).astype(int)
    df_pd["signal_short"] = (df_pd["prob_short"] >= threshold).astype(int)
    
    df_pd["prediction"] = 0
    df_pd.loc[df_pd["signal_long"] == 1, "prediction"] = 1
    df_pd.loc[df_pd["signal_short"] == 1, "prediction"] = -1
    
    # Filter to signals
    signals = df_pd[df_pd["prediction"] != 0].copy()
    
    if len(signals) == 0:
        return None
    
    # Metrics
    long_signals = signals[signals["prediction"] == 1]
    short_signals = signals[signals["prediction"] == -1]
    
    long_wins = (long_signals["forward_return"] > 0.015).sum() if len(long_signals) > 0 else 0
    short_wins = (short_signals["forward_return"] < -0.015).sum() if len(short_signals) > 0 else 0
    
    long_win_rate = long_wins / len(long_signals) if len(long_signals) > 0 else 0
    short_win_rate = short_wins / len(short_signals) if len(short_signals) > 0 else 0
    combined_win_rate = (long_wins + short_wins) / len(signals)
    
    long_total_return = long_signals["forward_return"].sum() if len(long_signals) > 0 else 0
    short_total_return = -short_signals["forward_return"].sum() if len(short_signals) > 0 else 0
    total_pnl = long_total_return + short_total_return
    
    long_avg_return = long_signals["forward_return"].mean() if len(long_signals) > 0 else 0
    short_avg_return = -short_signals["forward_return"].mean() if len(short_signals) > 0 else 0
    avg_pnl = total_pnl / len(signals)
    
    signals_per_day = len(signals) / signals["date"].nunique()
    
    return {
        "total_signals": len(signals),
        "long_signals": len(long_signals),
        "short_signals": len(short_signals),
        "long_win_rate": long_win_rate,
        "short_win_rate": short_win_rate,
        "combined_win_rate": combined_win_rate,
        "long_total_return": long_total_return,
        "short_total_return": short_total_return,
        "total_pnl": total_pnl,
        "long_avg_return": long_avg_return,
        "short_avg_return": short_avg_return,
        "avg_pnl": avg_pnl,
        "signals_per_day": signals_per_day,
        "trading_days": signals["date"].nunique(),
    }


def main():
    logging.info("=" * 80)
    logging.info("COMPARING 13-FEATURE vs 30-FEATURE MODELS")
    logging.info("=" * 80)
    
    # Load 13-feature models
    logging.info("\nLoading 13-feature models...")
    model_13_long = lgb.Booster(model_file="models/v4_intraday_sip_long.txt")
    model_13_short = lgb.Booster(model_file="models/v4_intraday_sip_short.txt")
    
    # Load 30-feature models
    logging.info("Loading 30-feature models...")
    model_30_long = lgb.Booster(model_file="models/v4_intraday_30ict_long.txt")
    model_30_short = lgb.Booster(model_file="models/v4_intraday_30ict_short.txt")
    
    # Load data
    logging.info("\nLoading 13-feature data...")
    df_13 = pl.read_parquet("run/intraday_features_sip_6months/features.parquet")
    df_13 = df_13.drop_nulls()
    df_13_pd = df_13.to_pandas()
    
    logging.info("Loading 30-feature data...")
    df_30 = pl.read_parquet("run/intraday_features_sip_6months/features_30ict.parquet")
    df_30 = df_30.drop_nulls()
    df_30_pd = df_30.to_pandas()
    
    logging.info(f"13-feature data: {len(df_13_pd):,} bars")
    logging.info(f"30-feature data: {len(df_30_pd):,} bars")
    
    # Feature columns
    features_13 = [
        "returns", "returns_5", "returns_10", "returns_20",
        "range_pct", "body_pct",
        "volume_ratio", "volume_ratio_20",
        "volatility_5", "volatility_20",
        "time_since_open", "time_to_close",
        "price_position",
    ]
    
    features_30 = [
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
    
    # Backtest 13-feature model
    logging.info("\n" + "=" * 80)
    logging.info("BACKTESTING 13-FEATURE MODEL")
    logging.info("=" * 80)
    metrics_13 = backtest_model(model_13_long, model_13_short, df_13_pd.copy(), features_13)
    
    # Backtest 30-feature model
    logging.info("\n" + "=" * 80)
    logging.info("BACKTESTING 30-FEATURE MODEL")
    logging.info("=" * 80)
    metrics_30 = backtest_model(model_30_long, model_30_short, df_30_pd.copy(), features_30)
    
    # Comparison
    logging.info("\n" + "=" * 80)
    logging.info("COMPARISON REPORT")
    logging.info("=" * 80)
    
    comparison = pd.DataFrame({
        "13 Features": metrics_13,
        "30 Features": metrics_30,
    }).T
    
    logging.info("\n" + comparison.to_string())
    
    # Calculate improvements
    logging.info("\n" + "=" * 80)
    logging.info("IMPROVEMENTS (30 vs 13)")
    logging.info("=" * 80)
    
    improvements = {
        "Win Rate": (metrics_30["combined_win_rate"] - metrics_13["combined_win_rate"]) * 100,
        "Total P&L": (metrics_30["total_pnl"] - metrics_13["total_pnl"]) * 100,
        "Avg P&L": (metrics_30["avg_pnl"] - metrics_13["avg_pnl"]) * 100,
        "Signals": metrics_30["total_signals"] - metrics_13["total_signals"],
        "Signals/Day": metrics_30["signals_per_day"] - metrics_13["signals_per_day"],
    }
    
    for metric, value in improvements.items():
        sign = "+" if value > 0 else ""
        if "P&L" in metric or "Win Rate" in metric:
            logging.info(f"  {metric}: {sign}{value:.2f}%")
        else:
            logging.info(f"  {metric}: {sign}{value:.1f}")
    
    # Save report
    output_dir = Path("run/comparison_13_vs_30")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with open(output_dir / "comparison_report.txt", "w") as f:
        f.write("COMPARISON: 13-FEATURE vs 30-FEATURE MODELS\n")
        f.write("=" * 80 + "\n\n")
        f.write(comparison.to_string())
        f.write("\n\n")
        f.write("IMPROVEMENTS (30 vs 13)\n")
        f.write("=" * 80 + "\n")
        for metric, value in improvements.items():
            sign = "+" if value > 0 else ""
            if "P&L" in metric or "Win Rate" in metric:
                f.write(f"  {metric}: {sign}{value:.2f}%\n")
            else:
                f.write(f"  {metric}: {sign}{value:.1f}\n")
    
    logging.info(f"\nSaved report to: {output_dir}/comparison_report.txt")
    
    logging.info("\n" + "=" * 80)
    logging.info("COMPARISON COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
