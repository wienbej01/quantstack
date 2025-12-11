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
    # Start: 2023-08 (train 2023-01 to 2023-06, val 2023-07)
    # End: 2025-09 (train 2025-02 to 2025-07, val 2025-08)

    start_year, start_month = 2023, 8
    end_year, end_month = 2025, 9

    current_year, current_month = start_year, start_month

    while (current_year < end_year) or (
        current_year == end_year and current_month <= end_month
    ):
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

        ranges.append(
            {
                "oos_month": f"{current_year}-{current_month:02d}",
                "train_start": train_start,
                "train_end": train_end,
                "val_start": val_start,
                "val_end": val_end,
                "oos_start": oos_start,
                "oos_end": oos_end,
            }
        )

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


def find_exit_with_stops(
    entry_idx,
    entry_price,
    stop_loss,
    take_profit,
    direction,
    bars_after_entry,
    max_bars=390,
):
    """Find exit based on stop/target/time on 1m bars."""
    for i, (idx, bar) in enumerate(bars_after_entry.iterrows()):
        if i >= max_bars:
            break

        if direction == 1:  # LONG
            if bar["low"] <= stop_loss:
                return stop_loss, bar["timestamp"], "stop_hit"
            if bar["high"] >= take_profit:
                return take_profit, bar["timestamp"], "target_hit"
        else:  # SHORT
            if bar["high"] >= stop_loss:
                return stop_loss, bar["timestamp"], "stop_hit"
            if bar["low"] <= take_profit:
                return take_profit, bar["timestamp"], "target_hit"

    # Time exit
    if len(bars_after_entry) > 0:
        last_bar = (
            bars_after_entry.iloc[-1]
            if len(bars_after_entry) > 1
            else bars_after_entry.iloc[0]
        )
        return last_bar["close"], last_bar["timestamp"], "time_exit"
    return None, None, "no_exit"


def backtest(
    model_long,
    model_short,
    test_df,
    feature_cols,
    threshold=0.50,
    equity=10_000.0,
    risk_fraction=0.005,
    atr_stop_multiple=2.5,
    r_target=2.0,
    max_hold_bars=120,
):
    """Backtest with entry delay, ATR stops, and full trade tracking."""
    X_test = test_df[feature_cols]

    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)

    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0].copy()
    signals = signals.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    if len(signals) == 0:
        return None

    start_equity = equity
    trades = []

    # Group by symbol for efficient bar lookup
    test_df_sorted = test_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    for idx, signal in signals.iterrows():
        signal_ts = signal["timestamp"]
        symbol = signal["symbol"]
        direction = signal["prediction"]
        atr = signal.get("atr", signal["close"] * 0.02)  # Fallback to 2% if no ATR

        # Get bars after signal for this symbol
        symbol_bars = test_df_sorted[
            (test_df_sorted["symbol"] == symbol)
            & (test_df_sorted["timestamp"] > signal_ts)
        ]

        if len(symbol_bars) == 0:
            continue

        # Entry on NEXT bar after signal
        entry_bar = symbol_bars.iloc[0]
        entry_price = entry_bar["close"]
        entry_ts = entry_bar["timestamp"]

        # Calculate stop and target using ATR
        stop_distance = atr * atr_stop_multiple

        if direction == 1:  # LONG
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + (stop_distance * r_target)
        else:  # SHORT
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - (stop_distance * r_target)

        # Position sizing: 1% equity risk
        per_trade_risk = equity * risk_fraction
        shares = int(per_trade_risk / stop_distance)

        if shares <= 0:
            continue

        # Find exit
        bars_after_entry = symbol_bars.iloc[1:]  # Bars after entry bar
        exit_price, exit_ts, exit_reason = find_exit_with_stops(
            idx,
            entry_price,
            stop_loss,
            take_profit,
            direction,
            bars_after_entry,
            max_bars=max_hold_bars,
        )

        if exit_price is None:
            continue

        # Calculate P&L
        gross_pnl = shares * (exit_price - entry_price) * direction

        # Costs
        commission_per_share = 0.0035
        commission_min = 0.35
        fee = max(shares * commission_per_share * 2, commission_min * 2)  # Entry + exit
        spread = shares * entry_price * 0.0005  # 5 bps
        net_pnl = gross_pnl - fee - spread

        equity += net_pnl

        # R-multiple
        r_multiple = (exit_price - entry_price) / stop_distance * direction

        trades.append(
            {
                "signal_timestamp": signal_ts,
                "entry_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "symbol": symbol,
                "side": "LONG" if direction == 1 else "SHORT",
                "shares": shares,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "stop_distance": stop_distance,
                "atr": atr,
                "gross_pnl": gross_pnl,
                "fee": fee,
                "spread": spread,
                "net_pnl": net_pnl,
                "r_multiple": r_multiple,
            }
        )

    if len(trades) == 0:
        return None

    wins = sum(1 for t in trades if t["net_pnl"] > 0)

    return {
        "total_signals": len(trades),
        "combined_win_rate": wins / len(trades),
        "total_pnl": (equity - start_equity) / start_equity,
        "equity_start": start_equity,
        "equity_end": equity,
        "trades": trades,
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
    df_pd["date"] = pd.to_datetime(df_pd["date"])

    logging.info(f"Data: {len(df_pd):,} bars")

    # Feature columns
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
        "atr",
        "time_since_open",
        "time_to_close",
        "price_position",
        "fvg_up",
        "fvg_down",
        "fvg_size_pct",
        "displacement_up",
        "displacement_down",
        "order_block_bull",
        "order_block_bear",
        "liquidity_grab_high",
        "liquidity_grab_low",
        "bos_up",
        "bos_down",
        "pressure_ratio",
        "distance_from_vwap",
        "volume_momentum",
        "pv_divergence",
    ]

    # Get date ranges
    ranges = get_date_ranges()
    logging.info(f"Rolling iterations: {len(ranges)}")

    # Output directories
    models_dir = Path("run/rolling_results/models")
    models_dir.mkdir(parents=True, exist_ok=True)

    results = []
    all_trades = []
    equity = 10_000.0

    for i, range_info in enumerate(ranges, 1):
        oos_month = range_info["oos_month"]
        logging.info("")
        logging.info("=" * 80)
        logging.info(f"ITERATION {i}/{len(ranges)}: OOS {oos_month}")
        logging.info("=" * 80)
        logging.info(f"Train: {range_info['train_start']} to {range_info['train_end']}")
        logging.info(f"Val: {range_info['val_start']} to {range_info['val_end']}")
        logging.info(f"OOS: {range_info['oos_start']} to {range_info['oos_end']}")

        train_start = pd.Timestamp(range_info["train_start"])
        train_end = pd.Timestamp(range_info["train_end"])
        val_start = pd.Timestamp(range_info["val_start"])
        val_end = pd.Timestamp(range_info["val_end"])
        oos_start = pd.Timestamp(range_info["oos_start"])
        oos_end = pd.Timestamp(range_info["oos_end"])

        # Split data
        train_df = df_pd[(df_pd["date"] >= train_start) & (df_pd["date"] < train_end)]
        val_df = df_pd[(df_pd["date"] >= val_start) & (df_pd["date"] < val_end)]
        test_df = df_pd[(df_pd["date"] >= oos_start) & (df_pd["date"] < oos_end)]

        logging.info(f"Train: {len(train_df):,} bars")
        logging.info(f"Val: {len(val_df):,} bars")
        logging.info(f"OOS: {len(test_df):,} bars")

        if len(train_df) == 0 or len(val_df) == 0 or len(test_df) == 0:
            logging.warning("Insufficient data, skipping")
            continue

        # Train
        logging.info("Training models...")
        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, feature_cols
        )
        logging.info(f"LONG AUC: {auc_long:.4f}, SHORT AUC: {auc_short:.4f}")

        # Save models
        model_long.save_model(str(models_dir / f"{oos_month}_long.txt"))
        model_short.save_model(str(models_dir / f"{oos_month}_short.txt"))

        # Backtest
        logging.info("Backtesting...")
        metrics = backtest(
            model_long,
            model_short,
            test_df.copy(),
            feature_cols,
            equity=equity,
        )

        if metrics:
            logging.info(f"Signals: {metrics['total_signals']}")
            logging.info(f"Win Rate: {metrics['combined_win_rate']:.2%}")
            logging.info(f"Total P&L: {metrics['total_pnl']:.2%}")

            # Calculate exit reason breakdown
            trades_list = metrics.get("trades", [])
            if trades_list:
                exit_reasons = {}
                for t in trades_list:
                    reason = t.get("exit_reason", "unknown")
                    exit_reasons[reason] = exit_reasons.get(reason, 0) + 1
                logging.info(f"Exit reasons: {exit_reasons}")

            equity = metrics["equity_end"]
            all_trades.extend(
                [
                    {**trade, "oos_month": oos_month}
                    for trade in metrics.get("trades", [])
                ]
            )

            results.append(
                {
                    "oos_month": oos_month,
                    "auc_long": auc_long,
                    "auc_short": auc_short,
                    **metrics,
                }
            )
        else:
            logging.warning("No signals generated")

    # Save results
    results_df = pd.DataFrame(results)
    results_file = Path("run/rolling_results/metrics.csv")
    results_df.to_csv(results_file, index=False)

    # Save trades
    trades_file = Path("run/rolling_results/trades.csv")
    trades_df = pd.DataFrame(all_trades)
    trades_df.to_csv(trades_file, index=False)

    logging.info("")
    logging.info("=" * 80)
    logging.info("ROLLING BACKTEST COMPLETE")
    logging.info("=" * 80)
    logging.info(f"Results saved to: {results_file}")
    logging.info(f"Final equity: ${equity:,.2f}")

    # Summary
    logging.info("")
    logging.info("SUMMARY:")
    logging.info(f"Total iterations: {len(results)}")
    logging.info(f"Avg win rate: {results_df['combined_win_rate'].mean():.2%}")
    logging.info(f"Total P&L: {(equity - 10_000) / 10_000:.2%}")
    logging.info(f"Total signals: {results_df['total_signals'].sum()}")


if __name__ == "__main__":
    main()
