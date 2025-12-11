#!/usr/bin/env python3
"""Backtest v4 intraday SIP models."""

import logging
from pathlib import Path

import lightgbm as lgb
import polars as pl

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")


def main():
    logging.info("=" * 80)
    logging.info("BACKTESTING V4 INTRADAY SIP MODELS")
    logging.info("=" * 80)

    # Load models
    model_long = lgb.Booster(model_file="models/v4_intraday_sip_long.txt")
    model_short = lgb.Booster(model_file="models/v4_intraday_sip_short.txt")
    logging.info("Loaded models")

    # Load features
    features_path = Path("run/intraday_features_sip_6months/features.parquet")
    logging.info(f"Loading features: {features_path}")
    df = pl.read_parquet(features_path)

    # Drop nulls
    df = df.drop_nulls()
    logging.info(
        f"Data: {len(df):,} bars, {df['symbol'].n_unique()} symbols, {df['date'].n_unique()} dates"
    )

    # Feature columns
    feature_cols = [
        "returns",
        "returns_5",
        "returns_10",
        "returns_20",
        "range_pct",
        "body_pct",
        "volume_ratio",
        "volume_ratio_20",
        "volatility_5",
        "volatility_20",
        "time_since_open",
        "time_to_close",
        "price_position",
    ]

    # Convert to pandas for prediction
    df_pd = df.to_pandas()
    X = df_pd[feature_cols]

    # Generate predictions
    logging.info("Generating predictions...")
    df_pd["prob_long"] = model_long.predict(X)
    df_pd["prob_short"] = model_short.predict(X)

    # Apply thresholds
    threshold_long = 0.30
    threshold_short = 0.30

    df_pd["signal_long"] = (df_pd["prob_long"] >= threshold_long).astype(int)
    df_pd["signal_short"] = (df_pd["prob_short"] >= threshold_short).astype(int)

    # Combine signals
    df_pd["prediction"] = 0  # Neutral
    df_pd.loc[df_pd["signal_long"] == 1, "prediction"] = 1  # Long
    df_pd.loc[df_pd["signal_short"] == 1, "prediction"] = -1  # Short

    # Statistics
    logging.info("")
    logging.info("=" * 80)
    logging.info("PREDICTION STATISTICS")
    logging.info("=" * 80)
    logging.info(f"Total bars: {len(df_pd):,}")
    logging.info(
        f"LONG signals: {(df_pd['prediction'] == 1).sum():,} ({(df_pd['prediction'] == 1).mean():.2%})"
    )
    logging.info(
        f"SHORT signals: {(df_pd['prediction'] == -1).sum():,} ({(df_pd['prediction'] == -1).mean():.2%})"
    )
    logging.info(
        f"Neutral: {(df_pd['prediction'] == 0).sum():,} ({(df_pd['prediction'] == 0).mean():.2%})"
    )

    # Filter to signals only
    signals = df_pd[df_pd["prediction"] != 0].copy()
    logging.info(f"\nTotal signals: {len(signals):,}")

    if len(signals) == 0:
        logging.error("No signals generated!")
        return

    # Backtest results
    logging.info("")
    logging.info("=" * 80)
    logging.info("BACKTEST RESULTS")
    logging.info("=" * 80)

    # LONG performance
    long_signals = signals[signals["prediction"] == 1]
    if len(long_signals) > 0:
        long_wins = (long_signals["forward_return"] > 0.015).sum()
        long_win_rate = long_wins / len(long_signals)
        long_avg_return = long_signals["forward_return"].mean()
        long_total_return = long_signals["forward_return"].sum()

        logging.info(f"LONG Signals: {len(long_signals):,}")
        logging.info(f"  Win rate: {long_win_rate:.2%}")
        logging.info(f"  Avg return: {long_avg_return:.2%}")
        logging.info(f"  Total return: {long_total_return:.2%}")

    # SHORT performance
    short_signals = signals[signals["prediction"] == -1]
    if len(short_signals) > 0:
        short_wins = (short_signals["forward_return"] < -0.015).sum()
        short_win_rate = short_wins / len(short_signals)
        short_avg_return = -short_signals["forward_return"].mean()  # Invert for short
        short_total_return = -short_signals["forward_return"].sum()

        logging.info(f"\nSHORT Signals: {len(short_signals):,}")
        logging.info(f"  Win rate: {short_win_rate:.2%}")
        logging.info(f"  Avg return: {short_avg_return:.2%}")
        logging.info(f"  Total return: {short_total_return:.2%}")

    # Combined
    combined_wins = (long_signals["forward_return"] > 0.015).sum() + (
        short_signals["forward_return"] < -0.015
    ).sum()
    combined_win_rate = combined_wins / len(signals)

    # Total P&L (assuming equal position sizing)
    total_pnl = (
        long_signals["forward_return"].sum() - short_signals["forward_return"].sum()
    )
    avg_pnl_per_signal = total_pnl / len(signals)

    logging.info("\nCOMBINED:")
    logging.info(f"  Total signals: {len(signals):,}")
    logging.info(f"  Win rate: {combined_win_rate:.2%}")
    logging.info(f"  Total P&L: {total_pnl:.2%}")
    logging.info(f"  Avg P&L per signal: {avg_pnl_per_signal:.2%}")

    # Daily statistics
    signals_by_date = signals.groupby("date").size()
    logging.info("\nDaily Signal Distribution:")
    logging.info(f"  Trading days: {len(signals_by_date)}")
    logging.info(f"  Avg signals/day: {signals_by_date.mean():.1f}")
    logging.info(f"  Min/Max: {signals_by_date.min()}/{signals_by_date.max()}")

    # Save predictions
    output_dir = Path("run/predictions_v4_intraday_sip")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save all predictions
    df_pred = pl.from_pandas(
        df_pd[
            [
                "timestamp",
                "symbol",
                "date",
                "close",
                "prob_long",
                "prob_short",
                "prediction",
                "forward_return",
            ]
        ]
    )
    df_pred.write_parquet(output_dir / "predictions.parquet")
    logging.info(f"\nSaved predictions to: {output_dir}/predictions.parquet")

    # Save signals only
    signals_pl = pl.from_pandas(
        signals[
            [
                "timestamp",
                "symbol",
                "date",
                "close",
                "prob_long",
                "prob_short",
                "prediction",
                "forward_return",
            ]
        ]
    )
    signals_pl.write_parquet(output_dir / "signals.parquet")
    logging.info(f"Saved signals to: {output_dir}/signals.parquet")

    logging.info("")
    logging.info("=" * 80)
    logging.info("BACKTEST COMPLETE")
    logging.info("=" * 80)


if __name__ == "__main__":
    main()
