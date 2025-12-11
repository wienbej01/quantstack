#!/usr/bin/env python3
"""Hybrid approach: ML for direction/timing, backtest applies ATR stops/targets.

Matrix optimization over:
- threshold: ML probability threshold
- atr_stop_mult: Stop distance as ATR multiple
- r_target: Take profit as R multiple (min 1.5)
- max_hold_bars: Maximum hold duration (backup exit)

Position sizing: 2% equity at risk (entry to stop distance)
Unlimited concurrent positions
3-month test period for fast iteration
"""

import logging
from datetime import datetime
from itertools import product
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl
from sklearn.metrics import roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/matrix_hybrid_stops.log"),
        logging.StreamHandler(),
    ],
)


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


def backtest_hybrid(
    model_long,
    model_short,
    test_df,
    feature_cols,
    all_bars_df,
    threshold=0.50,
    atr_stop_mult=1.5,
    r_target=2.0,
    max_hold_bars=30,
    equity=10_000.0,
    risk_pct=0.02,  # 2% equity at risk per trade
):
    """Hybrid backtest: ML signals + ATR stops/targets + max hold."""
    X_test = test_df[feature_cols]
    test_df = test_df.copy()
    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)

    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return None

    trades = []
    current_equity = equity

    for _, signal in signals.iterrows():
        signal_ts = signal["timestamp"]
        symbol = signal["symbol"]
        direction = signal["prediction"]
        atr = signal.get("atr", 0.5)

        if pd.isna(atr) or atr <= 0:
            atr = 0.5

        # Get bars after signal for this symbol
        symbol_bars = all_bars_df[
            (all_bars_df["symbol"] == symbol) & (all_bars_df["timestamp"] > signal_ts)
        ].sort_values("timestamp")

        if len(symbol_bars) < 2:
            continue

        # Entry on NEXT bar after signal
        entry_bar = symbol_bars.iloc[0]
        entry_price = entry_bar["close"]
        entry_ts = entry_bar["timestamp"]

        # Calculate stop/target
        stop_distance = atr * atr_stop_mult
        if direction == 1:  # LONG
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + (stop_distance * r_target)
        else:  # SHORT
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - (stop_distance * r_target)

        # Position sizing: 2% equity at risk
        risk_amount = current_equity * risk_pct
        shares = int(risk_amount / stop_distance) if stop_distance > 0 else 0
        if shares <= 0:
            continue

        # Monitor bars for stop/target/time exit
        exit_price = None
        exit_ts = None
        exit_reason = None

        bars_after_entry = symbol_bars.iloc[1 : max_hold_bars + 1]
        prev_close = entry_price
        prev_ts = entry_ts
        for _, bar in bars_after_entry.iterrows():
            # Same-day check
            if bar["timestamp"].date() != entry_ts.date():
                exit_price = prev_close
                exit_ts = prev_ts
                exit_reason = "eod"
                break

            if direction == 1:  # LONG
                if bar["low"] <= stop_loss:
                    exit_price = stop_loss
                    exit_ts = bar["timestamp"]
                    exit_reason = "stop"
                    break
                if bar["high"] >= take_profit:
                    exit_price = take_profit
                    exit_ts = bar["timestamp"]
                    exit_reason = "target"
                    break
            else:  # SHORT
                if bar["high"] >= stop_loss:
                    exit_price = stop_loss
                    exit_ts = bar["timestamp"]
                    exit_reason = "stop"
                    break
                if bar["low"] <= take_profit:
                    exit_price = take_profit
                    exit_ts = bar["timestamp"]
                    exit_reason = "target"
                    break

            prev_close = bar["close"]
            prev_ts = bar["timestamp"]

        # Time exit if no stop/target hit
        if exit_price is None and len(bars_after_entry) > 0:
            last_bar = bars_after_entry.iloc[-1]
            exit_price = last_bar["close"]
            exit_ts = last_bar["timestamp"]
            exit_reason = "time"

        if exit_price is None:
            continue

        # Calculate P&L
        if direction == 1:
            gross_pnl = (exit_price - entry_price) * shares
        else:
            gross_pnl = (entry_price - exit_price) * shares

        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread

        # R-multiple
        r_mult = (
            (exit_price - entry_price) / stop_distance
            if direction == 1
            else (entry_price - exit_price) / stop_distance
        )

        current_equity += net_pnl

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
                "atr": atr,
                "stop_distance": stop_distance,
                "gross_pnl": gross_pnl,
                "fee": fee,
                "spread": spread,
                "net_pnl": net_pnl,
                "r_multiple": r_mult,
            }
        )

    return pd.DataFrame(trades) if trades else None


def calc_sharpe(trades_df):
    """Calculate Sharpe ratio from trades."""
    if trades_df is None or len(trades_df) == 0:
        return 0.0
    daily_pnl = trades_df.groupby(trades_df["entry_timestamp"].dt.date)["net_pnl"].sum()
    if len(daily_pnl) < 2 or daily_pnl.std() == 0:
        return 0.0
    return (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252)


def main():
    logging.info("=" * 80)
    logging.info("HYBRID MATRIX: ML Direction + ATR Stops/Targets")
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_rolling/features.parquet")
    output_dir = Path("run/matrix_hybrid_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.info(f"Loading: {features_path}")
    df = pl.read_parquet(features_path)

    # Feature columns
    exclude_cols = [
        "timestamp",
        "date",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "entry_close",
        "entry_timestamp",
        "exit_close",
        "exit_timestamp",
        "forward_return",
        "label_long",
        "label_short",
        "atr",
        "tr",
        "prev_close",
        "candle_top",
        "candle_bottom",
        "prev_high",
        "prev_low",
        "next_low",
        "next_high",
        "prev_bearish",
        "prev_bullish",
        "prev_high_5",
        "prev_low_5",
        "up_volume",
        "down_volume",
        "typical_price",
        "vwap_num",
        "vwap_den",
    ]
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    logging.info(f"Features: {len(feature_cols)}")

    # 3-month test period: 2025-07 to 2025-09
    # Train: 2025-01 to 2025-05 (5 months)
    # Val: 2025-06
    # OOS: 2025-07 to 2025-09 (3 months)

    train_start = datetime(2025, 1, 1)
    train_end = datetime(2025, 6, 1)
    val_start = datetime(2025, 6, 1)
    val_end = datetime(2025, 7, 1)
    oos_start = datetime(2025, 7, 1)
    oos_end = datetime(2025, 10, 1)

    logging.info(f"Train: {train_start.date()} to {train_end.date()}")
    logging.info(f"Val: {val_start.date()} to {val_end.date()}")
    logging.info(f"OOS: {oos_start.date()} to {oos_end.date()}")

    train_df = df.filter(
        (pl.col("date") >= train_start.date()) & (pl.col("date") < train_end.date())
    ).to_pandas()
    val_df = df.filter(
        (pl.col("date") >= val_start.date()) & (pl.col("date") < val_end.date())
    ).to_pandas()
    test_df = df.filter(
        (pl.col("date") >= oos_start.date()) & (pl.col("date") < oos_end.date())
    ).to_pandas()

    logging.info(
        f"Train: {len(train_df):,} | Val: {len(val_df):,} | OOS: {len(test_df):,}"
    )

    # Train models once
    logging.info("Training models...")
    model_long, model_short, auc_long, auc_short = train_models(
        train_df, val_df, feature_cols
    )
    logging.info(f"AUC - Long: {auc_long:.4f} | Short: {auc_short:.4f}")

    # Matrix parameters
    thresholds = [0.40, 0.50, 0.60]
    atr_stop_mults = [1.0, 1.5, 2.0]
    r_targets = [1.5, 2.0, 2.5, 3.0]
    max_hold_bars_list = [10, 20, 30, 60]

    all_combos = list(
        product(thresholds, atr_stop_mults, r_targets, max_hold_bars_list)
    )
    logging.info(f"Testing {len(all_combos)} parameter combinations...")

    results = []
    best_sharpe = -999
    best_config = None

    for i, (thresh, atr_mult, r_tgt, max_hold) in enumerate(all_combos):
        trades_df = backtest_hybrid(
            model_long,
            model_short,
            test_df,
            feature_cols,
            test_df,
            threshold=thresh,
            atr_stop_mult=atr_mult,
            r_target=r_tgt,
            max_hold_bars=max_hold,
            equity=10_000.0,
            risk_pct=0.02,
        )

        if trades_df is None or len(trades_df) == 0:
            continue

        n_trades = len(trades_df)
        win_rate = (trades_df["net_pnl"] > 0).mean() * 100
        total_pnl = trades_df["net_pnl"].sum()
        sharpe = calc_sharpe(trades_df)

        # Exit reason breakdown
        stop_pct = (trades_df["exit_reason"] == "stop").mean() * 100
        target_pct = (trades_df["exit_reason"] == "target").mean() * 100
        time_pct = (trades_df["exit_reason"] == "time").mean() * 100

        avg_r = trades_df["r_multiple"].mean()
        max_dd = trades_df["net_pnl"].cumsum().min()

        results.append(
            {
                "threshold": thresh,
                "atr_stop_mult": atr_mult,
                "r_target": r_tgt,
                "max_hold_bars": max_hold,
                "trades": n_trades,
                "win_rate": win_rate,
                "total_pnl": total_pnl,
                "sharpe": sharpe,
                "avg_r": avg_r,
                "stop_pct": stop_pct,
                "target_pct": target_pct,
                "time_pct": time_pct,
                "max_dd": max_dd,
            }
        )

        if sharpe > best_sharpe:
            best_sharpe = sharpe
            best_config = (thresh, atr_mult, r_tgt, max_hold)
            trades_df.to_csv(output_dir / "best_trades.csv", index=False)

        if (i + 1) % 10 == 0:
            logging.info(f"Progress: {i+1}/{len(all_combos)}")

    # Save results
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("sharpe", ascending=False)
    results_df.to_csv(output_dir / "matrix_results.csv", index=False)

    logging.info("\n" + "=" * 80)
    logging.info("TOP 10 CONFIGURATIONS BY SHARPE")
    logging.info("=" * 80)
    print(results_df.head(10).to_string(index=False))

    logging.info("\n" + "=" * 80)
    logging.info("TOP 10 CONFIGURATIONS BY PNL")
    logging.info("=" * 80)
    print(
        results_df.sort_values("total_pnl", ascending=False)
        .head(10)
        .to_string(index=False)
    )

    if best_config:
        logging.info(
            f"\nBest config: thresh={best_config[0]}, atr_mult={best_config[1]}, "
            f"r_target={best_config[2]}, max_hold={best_config[3]}"
        )
        logging.info(f"Best Sharpe: {best_sharpe:.2f}")

    logging.info(f"\nResults saved to: {output_dir}")


if __name__ == "__main__":
    main()
