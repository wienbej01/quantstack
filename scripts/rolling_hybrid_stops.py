#!/usr/bin/env python3
"""Full rolling backtest with hybrid approach: ML direction + ATR stops/targets.

Best config from matrix: thresh=0.60, atr_mult=2.0, r_target=2.0, max_hold=60
Position sizing: 2% equity at risk
"""

import logging
from datetime import datetime
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
import polars as pl
from dateutil.relativedelta import relativedelta
from sklearn.metrics import roc_auc_score

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s",
    handlers=[
        logging.FileHandler("/tmp/rolling_hybrid_stops.log"),
        logging.StreamHandler(),
    ],
)

# Best config from matrix optimization
THRESHOLD = 0.60
ATR_STOP_MULT = 2.0
R_TARGET = 2.0
MAX_HOLD_BARS = 60
RISK_PCT = 0.02  # 2% equity at risk


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


def backtest_hybrid(model_long, model_short, test_df, feature_cols, equity=10_000.0):
    """Hybrid backtest with ATR stops/targets."""
    X_test = test_df[feature_cols]
    test_df = test_df.copy()
    test_df["prob_long"] = model_long.predict(X_test)
    test_df["prob_short"] = model_short.predict(X_test)

    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= THRESHOLD, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= THRESHOLD, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0].copy()
    if len(signals) == 0:
        return None, equity

    trades = []
    current_equity = equity
    test_df_sorted = test_df.sort_values(["symbol", "timestamp"]).reset_index(drop=True)

    for _, signal in signals.iterrows():
        signal_ts = signal["timestamp"]
        symbol = signal["symbol"]
        direction = signal["prediction"]
        atr = signal.get("atr", 0.5)
        if pd.isna(atr) or atr <= 0:
            atr = 0.5

        # Get bars after signal
        symbol_bars = test_df_sorted[
            (test_df_sorted["symbol"] == symbol)
            & (test_df_sorted["timestamp"] > signal_ts)
        ]
        if len(symbol_bars) < 2:
            continue

        # Entry on NEXT bar
        entry_bar = symbol_bars.iloc[0]
        entry_price = entry_bar["close"]
        entry_ts = entry_bar["timestamp"]

        # Calculate stop/target
        stop_distance = atr * ATR_STOP_MULT
        if direction == 1:
            stop_loss = entry_price - stop_distance
            take_profit = entry_price + (stop_distance * R_TARGET)
        else:
            stop_loss = entry_price + stop_distance
            take_profit = entry_price - (stop_distance * R_TARGET)

        # Position sizing: 2% equity at risk
        risk_amount = current_equity * RISK_PCT
        shares = int(risk_amount / stop_distance) if stop_distance > 0 else 0
        if shares <= 0:
            continue

        # Monitor bars
        exit_price = None
        exit_ts = None
        exit_reason = None
        prev_close = entry_price
        prev_ts = entry_ts

        bars_after_entry = symbol_bars.iloc[1 : MAX_HOLD_BARS + 1]
        for _, bar in bars_after_entry.iterrows():
            # Same-day check
            if bar["timestamp"].date() != entry_ts.date():
                exit_price = prev_close
                exit_ts = prev_ts
                exit_reason = "eod"
                break

            if direction == 1:
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
            else:
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

        if exit_price is None and len(bars_after_entry) > 0:
            last_bar = bars_after_entry.iloc[-1]
            exit_price = last_bar["close"]
            exit_ts = last_bar["timestamp"]
            exit_reason = "time"

        if exit_price is None:
            continue

        # P&L
        if direction == 1:
            gross_pnl = (exit_price - entry_price) * shares
        else:
            gross_pnl = (entry_price - exit_price) * shares

        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = gross_pnl - fee - spread
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

    return pd.DataFrame(trades) if trades else None, current_equity


def calc_sharpe(trades_df):
    if trades_df is None or len(trades_df) == 0:
        return 0.0
    daily_pnl = trades_df.groupby(trades_df["entry_timestamp"].dt.date)["net_pnl"].sum()
    if len(daily_pnl) < 2 or daily_pnl.std() == 0:
        return 0.0
    return (daily_pnl.mean() / daily_pnl.std()) * np.sqrt(252)


def main():
    logging.info("=" * 80)
    logging.info("ROLLING HYBRID BACKTEST: ML + ATR Stops/Targets")
    logging.info(
        f"Config: thresh={THRESHOLD}, atr_mult={ATR_STOP_MULT}, r_target={R_TARGET}, max_hold={MAX_HOLD_BARS}"
    )
    logging.info("=" * 80)

    features_path = Path("run/intraday_features_rolling/features.parquet")
    output_dir = Path("run/rolling_hybrid_results")
    output_dir.mkdir(parents=True, exist_ok=True)

    df = pl.read_parquet(features_path)

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

    # Rolling schedule
    train_months = 6
    end_date = datetime(2025, 10, 1)
    current = datetime(2023, 8, 1)

    all_trades = []
    all_metrics = []
    equity = 10_000.0
    iteration = 0

    while current < end_date:
        iteration += 1
        oos_start = current
        oos_end = oos_start + relativedelta(months=1)
        val_start = oos_start - relativedelta(months=1)
        train_end = val_start
        train_start = train_end - relativedelta(months=train_months)

        logging.info(f"\n{'='*60}")
        logging.info(f"ITERATION {iteration}: OOS {oos_start.strftime('%Y-%m')}")

        train_df = df.filter(
            (pl.col("date") >= train_start.date()) & (pl.col("date") < train_end.date())
        ).to_pandas()
        val_df = df.filter(
            (pl.col("date") >= val_start.date()) & (pl.col("date") < oos_start.date())
        ).to_pandas()
        test_df = df.filter(
            (pl.col("date") >= oos_start.date()) & (pl.col("date") < oos_end.date())
        ).to_pandas()

        logging.info(
            f"Train: {len(train_df):,} | Val: {len(val_df):,} | OOS: {len(test_df):,}"
        )

        if len(train_df) < 1000 or len(val_df) < 100 or len(test_df) < 100:
            logging.warning("Insufficient data, skipping")
            current = oos_end
            continue

        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, feature_cols
        )
        logging.info(f"AUC - Long: {auc_long:.4f} | Short: {auc_short:.4f}")

        trades_df, equity = backtest_hybrid(
            model_long, model_short, test_df, feature_cols, equity
        )

        if trades_df is not None and len(trades_df) > 0:
            n_trades = len(trades_df)
            win_rate = (trades_df["net_pnl"] > 0).mean() * 100
            total_pnl = trades_df["net_pnl"].sum()
            sharpe = calc_sharpe(trades_df)
            avg_r = trades_df["r_multiple"].mean()

            stop_pct = (trades_df["exit_reason"] == "stop").mean() * 100
            target_pct = (trades_df["exit_reason"] == "target").mean() * 100
            time_pct = (trades_df["exit_reason"] == "time").mean() * 100

            logging.info(
                f"Trades: {n_trades} | Win: {win_rate:.1f}% | PnL: ${total_pnl:,.0f} | Sharpe: {sharpe:.2f}"
            )
            logging.info(
                f"Exits - Stop: {stop_pct:.0f}% | Target: {target_pct:.0f}% | Time: {time_pct:.0f}%"
            )

            trades_df["oos_month"] = oos_start.strftime("%Y-%m")
            all_trades.append(trades_df)

            all_metrics.append(
                {
                    "oos_month": oos_start.strftime("%Y-%m"),
                    "trades": n_trades,
                    "win_rate": win_rate,
                    "total_pnl": total_pnl,
                    "sharpe": sharpe,
                    "avg_r": avg_r,
                    "stop_pct": stop_pct,
                    "target_pct": target_pct,
                    "time_pct": time_pct,
                    "equity": equity,
                    "auc_long": auc_long,
                    "auc_short": auc_short,
                }
            )

        current = oos_end

    # Save results
    if all_trades:
        trades_all = pd.concat(all_trades, ignore_index=True)
        trades_all.to_csv(output_dir / "trades.csv", index=False)

        metrics_df = pd.DataFrame(all_metrics)
        metrics_df.to_csv(output_dir / "metrics.csv", index=False)

        # Summary
        logging.info("\n" + "=" * 80)
        logging.info("FINAL RESULTS")
        logging.info("=" * 80)
        logging.info(f"Total trades: {len(trades_all)}")
        logging.info(f"Win rate: {(trades_all['net_pnl'] > 0).mean()*100:.1f}%")
        logging.info(f"Total PnL: ${trades_all['net_pnl'].sum():,.0f}")
        logging.info(f"Final equity: ${equity:,.0f}")
        logging.info(f"Return: {(equity - 10000) / 10000 * 100:.1f}%")
        logging.info(f"Sharpe: {calc_sharpe(trades_all):.2f}")
        logging.info(f"Avg R: {trades_all['r_multiple'].mean():.3f}")

        # Exit breakdown
        logging.info("\n--- Exit Reason Breakdown ---")
        for reason in trades_all["exit_reason"].unique():
            subset = trades_all[trades_all["exit_reason"] == reason]
            logging.info(
                f"{reason:6s}: {len(subset):4d} ({len(subset)/len(trades_all)*100:5.1f}%) | "
                f"Win: {(subset['net_pnl']>0).mean()*100:5.1f}% | "
                f"PnL: ${subset['net_pnl'].sum():+,.0f}"
            )

        # Direction breakdown
        logging.info("\n--- By Direction ---")
        for side in ["LONG", "SHORT"]:
            subset = trades_all[trades_all["side"] == side]
            logging.info(
                f"{side:5s}: {len(subset):4d} trades | "
                f"Win: {(subset['net_pnl']>0).mean()*100:5.1f}% | "
                f"PnL: ${subset['net_pnl'].sum():+,.0f}"
            )

        logging.info(f"\nResults saved to: {output_dir}")


if __name__ == "__main__":
    main()
