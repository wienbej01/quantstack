#!/usr/bin/env python3
"""Generate predictions and backtest on OOS data."""

import logging
from pathlib import Path

import lightgbm as lgb
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def engineer_features(df):
    """Create features from OHLCV."""
    df = df.sort_values(['symbol', 'ts']).copy()
    
    df['returns'] = df.groupby('symbol')['close'].pct_change()
    df['range_pct'] = (df['high'] - df['low']) / df['close']
    df['volume_ma5'] = df.groupby('symbol')['volume'].transform(lambda x: x.rolling(5, min_periods=1).mean())
    df['volume_ratio'] = df['volume'] / df['volume_ma5']
    df['returns_5'] = df.groupby('symbol')['close'].pct_change(5)
    df['returns_10'] = df.groupby('symbol')['close'].pct_change(10)
    
    df = df.fillna(0)
    return df


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("OOS Backtest - 3 MONTHS")
    LOGGER.info("=" * 80)
    
    # Load models
    model_long = lgb.Booster(model_file="models/v4_3months_long.txt")
    model_short = lgb.Booster(model_file="models/v4_3months_short.txt")
    LOGGER.info("Models loaded")
    
    # Load OOS data
    oos_df = pd.read_parquet("artefacts/extensions/intraday_ml/v4_3months/oos.parquet")
    LOGGER.info(f"OOS data: {len(oos_df):,} rows (May 2024)")
    
    # Engineer features
    oos_df = engineer_features(oos_df)
    
    feature_cols = ['returns', 'range_pct', 'volume_ratio', 'returns_5', 'returns_10']
    X = oos_df[feature_cols]
    
    # Predict
    LOGGER.info("Generating predictions...")
    oos_df['prob_long'] = model_long.predict(X)
    oos_df['prob_short'] = model_short.predict(X)
    
    # Apply threshold
    threshold = 0.50
    oos_df['prediction'] = 0
    oos_df.loc[oos_df['prob_long'] >= threshold, 'prediction'] = 1
    oos_df.loc[oos_df['prob_short'] >= threshold, 'prediction'] = -1
    
    # Filter to signals
    signals = oos_df[oos_df['prediction'] != 0].copy()
    LOGGER.info(f"Signals: {len(signals)} ({len(signals)/len(oos_df)*100:.2f}%)")
    LOGGER.info(f"  LONG: {(signals['prediction'] == 1).sum()}")
    LOGGER.info(f"  SHORT: {(signals['prediction'] == -1).sum()}")
    
    # Calculate forward returns
    oos_df['forward_30min_return'] = oos_df.groupby('symbol')['close'].pct_change(30).shift(-30)
    signals = signals.merge(
        oos_df[['symbol', 'ts', 'forward_30min_return']], 
        on=['symbol', 'ts'], 
        how='left'
    )
    
    # Calculate P&L
    signals['pnl'] = signals['forward_30min_return'] * signals['prediction']
    signals = signals.dropna(subset=['pnl'])
    
    # Stats
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("OOS Backtest Results")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Tradeable signals: {len(signals)}")
    
    wins = (signals['pnl'] > 0).sum()
    losses = (signals['pnl'] < 0).sum()
    win_rate = wins / len(signals) if len(signals) > 0 else 0
    
    LOGGER.info(f"Wins: {wins}")
    LOGGER.info(f"Losses: {losses}")
    LOGGER.info(f"Win rate: {win_rate*100:.1f}%")
    LOGGER.info(f"Avg P&L: {signals['pnl'].mean()*100:.2f}%")
    LOGGER.info(f"Total P&L: {signals['pnl'].sum()*100:.2f}%")
    LOGGER.info(f"Sharpe (approx): {signals['pnl'].mean() / signals['pnl'].std():.2f}")
    
    # By direction
    LOGGER.info("")
    LOGGER.info("By Direction:")
    for direction, name in [(1, "LONG"), (-1, "SHORT")]:
        dir_signals = signals[signals["prediction"] == direction]
        if len(dir_signals) > 0:
            dir_wins = (dir_signals["pnl"] > 0).sum()
            dir_win_rate = dir_wins / len(dir_signals)
            LOGGER.info(f"  {name}: {len(dir_signals)} trades, {dir_win_rate*100:.1f}% win rate, {dir_signals['pnl'].mean()*100:.2f}% avg")
    
    # Save results
    output_file = Path("run/backtest_v4_3months_oos_results.txt")
    with open(output_file, "w") as f:
        f.write("v4 3-Month OOS Backtest Results\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Period: May 2024 (OOS)\n")
        f.write(f"Signals: {len(signals)}\n")
        f.write(f"Win rate: {win_rate*100:.1f}%\n")
        f.write(f"Avg P&L: {signals['pnl'].mean()*100:.2f}%\n")
        f.write(f"Total P&L: {signals['pnl'].sum()*100:.2f}%\n")
    
    LOGGER.info("")
    LOGGER.info(f"Results saved to: {output_file}")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
