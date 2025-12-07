#!/usr/bin/env python3
"""Simple backtest for v4 predictions."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")
LOGGER = logging.getLogger(__name__)


def main():
    LOGGER.info("=" * 80)
    LOGGER.info("Backtesting v4 Predictions")
    LOGGER.info("=" * 80)

    # Load predictions
    df = pd.read_parquet("run/predictions_v4_simple.parquet")
    
    # Filter to signals only
    signals = df[df["prediction"] != 0].copy()
    LOGGER.info(f"Total signals: {len(signals)}")
    LOGGER.info(f"  LONG: {(signals['prediction'] == 1).sum()}")
    LOGGER.info(f"  SHORT: {(signals['prediction'] == -1).sum()}")

    # Calculate forward returns (30 minutes)
    df = df.sort_values(["symbol", "ts"]).copy()
    df["forward_30min_return"] = df.groupby("symbol")["close"].pct_change(30).shift(-30)
    
    # Merge back to signals
    signals = signals.merge(
        df[["symbol", "ts", "forward_30min_return"]], 
        on=["symbol", "ts"], 
        how="left"
    )
    
    # Calculate P&L
    signals["pnl"] = signals["forward_30min_return"] * signals["prediction"]
    
    # Remove signals without forward data
    signals = signals.dropna(subset=["pnl"])
    
    # Stats
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Backtest Results")
    LOGGER.info("=" * 80)
    LOGGER.info(f"Tradeable signals: {len(signals)}")
    
    wins = (signals["pnl"] > 0).sum()
    losses = (signals["pnl"] < 0).sum()
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
    output_file = Path("run/backtest_v4_simple_results.txt")
    with open(output_file, "w") as f:
        f.write("v4 Simple Backtest Results\n")
        f.write("=" * 80 + "\n\n")
        f.write("Period: May 2024\n")
        f.write(f"Signals: {len(signals)}\n")
        f.write(f"Win rate: {win_rate*100:.1f}%\n")
        f.write(f"Avg P&L: {signals['pnl'].mean()*100:.2f}%\n")
        f.write(f"Total P&L: {signals['pnl'].sum()*100:.2f}%\n")
    
    LOGGER.info("")
    LOGGER.info(f"Results saved to: {output_file}")
    LOGGER.info("=" * 80)


if __name__ == "__main__":
    main()
