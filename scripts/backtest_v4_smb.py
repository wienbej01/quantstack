#!/usr/bin/env python3
"""Backtest v4 SMB strategy with high selectivity."""

import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s"
)
LOGGER = logging.getLogger(__name__)


def calculate_atr_from_bars(bars: pd.DataFrame, window: int = 14) -> float:
    """Calculate ATR from intraday bars."""
    if len(bars) < 2:
        return 0.0

    # Calculate true range
    bars = bars.sort_values("ts")
    high = bars["high"].values
    low = bars["low"].values
    close = bars["close"].values

    tr = []
    for i in range(1, len(bars)):
        tr.append(
            max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
        )

    if not tr:
        return 0.0

    return sum(tr[-window:]) / min(len(tr), window)


def backtest_v4_smb(
    predictions: pd.DataFrame,
    gold_path: str = "/home/jacobw/gcs-mount/gold/stocks/1m",
    initial_capital: float = 10000.0,
    risk_per_trade: float = 0.02,
    target_atr_multiple: float = 2.5,
    stop_atr_multiple: float = 1.0,
    max_positions: int = 5,
) -> dict:
    """
    Backtest v4 SMB strategy.

    Args:
        predictions: DataFrame with predictions
        gold_path: Path to gold data
        initial_capital: Starting capital
        risk_per_trade: Risk per trade (2% = 0.02)
        target_atr_multiple: Target in ATR multiples
        stop_atr_multiple: Stop in ATR multiples
        max_positions: Maximum concurrent positions

    Returns:
        Dictionary with backtest results
    """

    # Filter to signals only
    signals = predictions[predictions["prediction"] != 0].copy()
    signals = signals.sort_values("ts")

    LOGGER.info("Processing %d signals...", len(signals))

    # Track state
    capital = initial_capital
    positions = []
    trades = []
    equity_curve = [{"ts": signals["ts"].min(), "equity": capital}]

    for idx, row in signals.iterrows():
        symbol = row["symbol"]
        ts = row["ts"]
        direction = row["prediction"]  # 1 = LONG, -1 = SHORT
        prob = row["prob_max"]

        # Check if we can open new position
        if len(positions) >= max_positions:
            continue

        # Load bars for this symbol/date
        date_str = pd.to_datetime(ts).strftime("%Y-%m-%d")
        symbol_path = Path(gold_path) / symbol / f"{date_str}.parquet"

        if not symbol_path.exists():
            continue

        try:
            bars = pd.read_parquet(symbol_path)
            bars["ts"] = pd.to_datetime(bars["ts"])
        except Exception as e:
            LOGGER.warning("Error loading %s: %s", symbol_path, e)
            continue

        # Get entry bar
        entry_bars = bars[bars["ts"] == ts]
        if len(entry_bars) == 0:
            continue

        entry_bar = entry_bars.iloc[0]
        entry_price = entry_bar["close"]

        # Calculate ATR
        atr = calculate_atr_from_bars(bars)
        if atr == 0:
            continue

        # Calculate position size (2% risk)
        risk_amount = capital * risk_per_trade
        stop_distance = atr * stop_atr_multiple
        shares = int(risk_amount / stop_distance)

        if shares == 0:
            continue

        # Set targets
        if direction == 1:  # LONG
            stop_price = entry_price - stop_distance
            target_price = entry_price + (atr * target_atr_multiple)
        else:  # SHORT
            stop_price = entry_price + stop_distance
            target_price = entry_price - (atr * target_atr_multiple)

        # Track position
        position = {
            "symbol": symbol,
            "direction": direction,
            "entry_ts": ts,
            "entry_price": entry_price,
            "shares": shares,
            "stop_price": stop_price,
            "target_price": target_price,
            "atr": atr,
            "prob": prob,
        }

        # Simulate exit (simplified: check remaining bars)
        future_bars = bars[bars["ts"] > ts]

        exit_price = None
        exit_ts = None
        exit_reason = "EOD"

        for _, future_bar in future_bars.iterrows():
            if direction == 1:  # LONG
                if future_bar["low"] <= stop_price:
                    exit_price = stop_price
                    exit_ts = future_bar["ts"]
                    exit_reason = "STOP"
                    break
                elif future_bar["high"] >= target_price:
                    exit_price = target_price
                    exit_ts = future_bar["ts"]
                    exit_reason = "TARGET"
                    break
            elif future_bar["high"] >= stop_price:
                exit_price = stop_price
                exit_ts = future_bar["ts"]
                exit_reason = "STOP"
                break
            elif future_bar["low"] <= target_price:
                exit_price = target_price
                exit_ts = future_bar["ts"]
                exit_reason = "TARGET"
                break

        # If no exit, use last bar
        if exit_price is None:
            exit_price = (
                future_bars.iloc[-1]["close"] if len(future_bars) > 0 else entry_price
            )
            exit_ts = future_bars.iloc[-1]["ts"] if len(future_bars) > 0 else ts
            exit_reason = "EOD"

        # Calculate P&L
        if direction == 1:
            pnl = (exit_price - entry_price) * shares
        else:
            pnl = (entry_price - exit_price) * shares

        capital += pnl

        # Record trade
        trades.append(
            {
                "symbol": symbol,
                "direction": "LONG" if direction == 1 else "SHORT",
                "entry_ts": ts,
                "entry_price": entry_price,
                "exit_ts": exit_ts,
                "exit_price": exit_price,
                "shares": shares,
                "pnl": pnl,
                "pnl_pct": pnl / (entry_price * shares),
                "exit_reason": exit_reason,
                "atr": atr,
                "r_multiple": pnl / risk_amount,
                "prob": prob,
            }
        )

        equity_curve.append({"ts": exit_ts, "equity": capital})

    # Calculate metrics
    trades_df = pd.DataFrame(trades)

    if len(trades_df) == 0:
        LOGGER.warning("No trades executed!")
        return {
            "total_trades": 0,
            "win_rate": 0,
            "avg_r_multiple": 0,
            "total_pnl": 0,
            "final_capital": initial_capital,
            "return_pct": 0,
        }

    total_trades = len(trades_df)
    winners = (trades_df["pnl"] > 0).sum()
    win_rate = winners / total_trades
    avg_r_multiple = trades_df["r_multiple"].mean()
    total_pnl = trades_df["pnl"].sum()
    final_capital = capital
    return_pct = (final_capital - initial_capital) / initial_capital

    # Trades per day
    trades_df["date"] = pd.to_datetime(trades_df["entry_ts"]).dt.date
    trading_days = trades_df["date"].nunique()
    trades_per_day = total_trades / trading_days if trading_days > 0 else 0

    results = {
        "total_trades": total_trades,
        "trading_days": trading_days,
        "trades_per_day": trades_per_day,
        "winners": winners,
        "losers": total_trades - winners,
        "win_rate": win_rate,
        "avg_r_multiple": avg_r_multiple,
        "total_pnl": total_pnl,
        "initial_capital": initial_capital,
        "final_capital": final_capital,
        "return_pct": return_pct,
        "avg_pnl_per_trade": total_pnl / total_trades,
        "trades_df": trades_df,
        "equity_curve": pd.DataFrame(equity_curve),
    }

    return results


def main():
    predictions_path = Path(
        "artefacts/extensions/intraday_ml/v4_smb/predictions.parquet"
    )
    output_path = Path("artefacts/extensions/intraday_ml/v4_smb/backtest_results.txt")

    LOGGER.info("=" * 80)
    LOGGER.info("v4 SMB Backtest")
    LOGGER.info("=" * 80)

    # Load predictions
    LOGGER.info("Loading predictions from: %s", predictions_path)
    predictions = pd.read_parquet(predictions_path)
    LOGGER.info("Loaded %d predictions", len(predictions))

    # Run backtest
    LOGGER.info("Running backtest...")
    results = backtest_v4_smb(predictions)

    # Display results
    LOGGER.info("")
    LOGGER.info("=" * 80)
    LOGGER.info("Backtest Results")
    LOGGER.info("=" * 80)
    LOGGER.info("Total trades: %d", results["total_trades"])
    LOGGER.info("Trading days: %d", results["trading_days"])
    LOGGER.info("Trades/day: %.2f", results["trades_per_day"])
    LOGGER.info("")
    LOGGER.info("Winners: %d", results["winners"])
    LOGGER.info("Losers: %d", results["losers"])
    LOGGER.info("Win rate: %.2f%%", results["win_rate"] * 100)
    LOGGER.info("")
    LOGGER.info("Avg R-multiple: %.2f", results["avg_r_multiple"])
    LOGGER.info("Avg PnL/trade: $%.2f", results["avg_pnl_per_trade"])
    LOGGER.info("")
    LOGGER.info("Initial capital: $%.2f", results["initial_capital"])
    LOGGER.info("Final capital: $%.2f", results["final_capital"])
    LOGGER.info("Total PnL: $%.2f", results["total_pnl"])
    LOGGER.info("Return: %.2f%%", results["return_pct"] * 100)
    LOGGER.info("=" * 80)

    # Save results
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        f.write("v4 SMB Backtest Results\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"Total trades: {results['total_trades']}\n")
        f.write(f"Trading days: {results['trading_days']}\n")
        f.write(f"Trades/day: {results['trades_per_day']:.2f}\n\n")
        f.write(f"Winners: {results['winners']}\n")
        f.write(f"Losers: {results['losers']}\n")
        f.write(f"Win rate: {results['win_rate']*100:.2f}%\n\n")
        f.write(f"Avg R-multiple: {results['avg_r_multiple']:.2f}\n")
        f.write(f"Avg PnL/trade: ${results['avg_pnl_per_trade']:.2f}\n\n")
        f.write(f"Initial capital: ${results['initial_capital']:.2f}\n")
        f.write(f"Final capital: ${results['final_capital']:.2f}\n")
        f.write(f"Total PnL: ${results['total_pnl']:.2f}\n")
        f.write(f"Return: {results['return_pct']*100:.2f}%\n")

    LOGGER.info("Results saved to: %s", output_path)

    # Save trades
    trades_path = output_path.parent / "trades.parquet"
    results["trades_df"].to_parquet(trades_path, index=False)
    LOGGER.info("Trades saved to: %s", trades_path)


if __name__ == "__main__":
    main()
