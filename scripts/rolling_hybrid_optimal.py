#!/usr/bin/env python3
"""Production hybrid backtest with optimal configuration.

Best config from matrix optimization:
- threshold: 0.60
- atr_stop_mult: 3.0 (wider stops reduce stop-outs)
- r_target: 2.0
- max_hold_bars: 60
- risk_pct: 2% equity at risk per trade
- unlimited concurrent positions
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
        logging.FileHandler("/tmp/rolling_hybrid_optimal.log"),
        logging.StreamHandler(),
    ],
)

# OPTIMAL CONFIG
THRESHOLD = 0.60
ATR_STOP_MULT = 3.0  # Wider stops
R_TARGET = 2.0
MAX_HOLD_BARS = 60
RISK_PCT = 0.02


def train_models(train_df, val_df, feature_cols):
    X_train, X_val = train_df[feature_cols], val_df[feature_cols]
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

    model_long = lgb.train(
        params,
        lgb.Dataset(X_train, train_df["label_long"]),
        500,
        valid_sets=[lgb.Dataset(X_val, val_df["label_long"])],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    model_short = lgb.train(
        params,
        lgb.Dataset(X_train, train_df["label_short"]),
        500,
        valid_sets=[lgb.Dataset(X_val, val_df["label_short"])],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )

    auc_long = roc_auc_score(val_df["label_long"], model_long.predict(X_val))
    auc_short = roc_auc_score(val_df["label_short"], model_short.predict(X_val))
    return model_long, model_short, auc_long, auc_short


def backtest(model_long, model_short, test_df, feature_cols, equity):
    test_df = test_df.copy()
    test_df["prob_long"] = model_long.predict(test_df[feature_cols])
    test_df["prob_short"] = model_short.predict(test_df[feature_cols])
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= THRESHOLD, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= THRESHOLD, "prediction"] = -1

    signals = test_df[test_df["prediction"] != 0]
    trades = []

    for _, sig in signals.iterrows():
        symbol, direction = sig["symbol"], sig["prediction"]
        atr = sig.get("atr", 0.5)
        if pd.isna(atr) or atr <= 0:
            atr = 0.5

        bars = test_df[
            (test_df["symbol"] == symbol) & (test_df["timestamp"] > sig["timestamp"])
        ].sort_values("timestamp")
        if len(bars) < 2:
            continue

        entry_bar = bars.iloc[0]
        entry_price, entry_ts = entry_bar["close"], entry_bar["timestamp"]
        stop_dist = atr * ATR_STOP_MULT

        if direction == 1:
            stop, target = entry_price - stop_dist, entry_price + stop_dist * R_TARGET
        else:
            stop, target = entry_price + stop_dist, entry_price - stop_dist * R_TARGET

        shares = int(equity * RISK_PCT / stop_dist) if stop_dist > 0 else 0
        if shares <= 0:
            continue

        exit_price, exit_ts, exit_reason = None, None, None
        prev_close, prev_ts = entry_price, entry_ts

        for _, bar in bars.iloc[1 : MAX_HOLD_BARS + 1].iterrows():
            if bar["timestamp"].date() != entry_ts.date():
                exit_price, exit_ts, exit_reason = prev_close, prev_ts, "eod"
                break
            if direction == 1:
                if bar["low"] <= stop:
                    exit_price, exit_ts, exit_reason = stop, bar["timestamp"], "stop"
                    break
                if bar["high"] >= target:
                    exit_price, exit_ts, exit_reason = (
                        target,
                        bar["timestamp"],
                        "target",
                    )
                    break
            else:
                if bar["high"] >= stop:
                    exit_price, exit_ts, exit_reason = stop, bar["timestamp"], "stop"
                    break
                if bar["low"] <= target:
                    exit_price, exit_ts, exit_reason = (
                        target,
                        bar["timestamp"],
                        "target",
                    )
                    break
            prev_close, prev_ts = bar["close"], bar["timestamp"]

        if exit_price is None and len(bars) > MAX_HOLD_BARS:
            last = bars.iloc[MAX_HOLD_BARS]
            exit_price, exit_ts, exit_reason = last["close"], last["timestamp"], "time"
        if exit_price is None:
            continue

        pnl = (
            (exit_price - entry_price) * shares
            if direction == 1
            else (entry_price - exit_price) * shares
        )
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = pnl - fee - spread
        r_mult = (
            (exit_price - entry_price) / stop_dist
            if direction == 1
            else (entry_price - exit_price) / stop_dist
        )

        equity += net_pnl
        trades.append(
            {
                "signal_timestamp": sig["timestamp"],
                "entry_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "symbol": symbol,
                "side": "LONG" if direction == 1 else "SHORT",
                "shares": shares,
                "entry_price": entry_price,
                "stop_loss": stop,
                "take_profit": target,
                "exit_price": exit_price,
                "exit_reason": exit_reason,
                "atr": atr,
                "stop_distance": stop_dist,
                "gross_pnl": pnl,
                "fee": fee,
                "spread": spread,
                "net_pnl": net_pnl,
                "r_multiple": r_mult,
            }
        )

    return pd.DataFrame(trades) if trades else None, equity


def main():
    logging.info("=" * 80)
    logging.info("HYBRID OPTIMAL: thresh=0.60, atr=3.0, R=2.0, hold=60")
    logging.info("=" * 80)

    df = pl.read_parquet("run/intraday_features_rolling/features.parquet")
    output_dir = Path("run/rolling_hybrid_optimal")
    output_dir.mkdir(parents=True, exist_ok=True)

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

    all_trades, all_metrics = [], []
    equity = 10_000.0
    current = datetime(2023, 8, 1)

    while current < datetime(2025, 10, 1):
        oos_start = current
        oos_end = oos_start + relativedelta(months=1)
        val_start = oos_start - relativedelta(months=1)
        train_start = val_start - relativedelta(months=6)

        train_df = df.filter(
            (pl.col("date") >= train_start.date()) & (pl.col("date") < val_start.date())
        ).to_pandas()
        val_df = df.filter(
            (pl.col("date") >= val_start.date()) & (pl.col("date") < oos_start.date())
        ).to_pandas()
        test_df = df.filter(
            (pl.col("date") >= oos_start.date()) & (pl.col("date") < oos_end.date())
        ).to_pandas()

        if len(train_df) < 1000 or len(val_df) < 100 or len(test_df) < 100:
            current = oos_end
            continue

        logging.info(
            f"\n{'='*60}\nOOS {oos_start.strftime('%Y-%m')}: Train {len(train_df):,} | Val {len(val_df):,} | Test {len(test_df):,}"
        )

        model_long, model_short, auc_long, auc_short = train_models(
            train_df, val_df, feature_cols
        )
        trades_df, equity = backtest(
            model_long, model_short, test_df, feature_cols, equity
        )

        if trades_df is not None and len(trades_df) > 0:
            n = len(trades_df)
            win = (trades_df["net_pnl"] > 0).mean() * 100
            pnl = trades_df["net_pnl"].sum()
            stop_pct = (trades_df["exit_reason"] == "stop").mean() * 100
            target_pct = (trades_df["exit_reason"] == "target").mean() * 100

            logging.info(
                f"Trades: {n} | Win: {win:.1f}% | PnL: ${pnl:,.0f} | Equity: ${equity:,.0f}"
            )
            logging.info(f"Stop: {stop_pct:.0f}% | Target: {target_pct:.0f}%")

            trades_df["oos_month"] = oos_start.strftime("%Y-%m")
            all_trades.append(trades_df)
            all_metrics.append(
                {
                    "oos_month": oos_start.strftime("%Y-%m"),
                    "trades": n,
                    "win_rate": win,
                    "pnl": pnl,
                    "equity": equity,
                    "stop_pct": stop_pct,
                    "target_pct": target_pct,
                }
            )

        current = oos_end

    # Save and summarize
    if all_trades:
        trades_all = pd.concat(all_trades, ignore_index=True)
        trades_all.to_csv(output_dir / "trades.csv", index=False)
        pd.DataFrame(all_metrics).to_csv(output_dir / "metrics.csv", index=False)

        logging.info("\n" + "=" * 80)
        logging.info("FINAL RESULTS - HYBRID OPTIMAL")
        logging.info("=" * 80)
        logging.info(f"Total trades: {len(trades_all)}")
        logging.info(f"Win rate: {(trades_all['net_pnl'] > 0).mean()*100:.1f}%")
        logging.info(f"Total PnL: ${trades_all['net_pnl'].sum():,.0f}")
        logging.info(f"Final equity: ${equity:,.0f}")
        logging.info(f"Return: {(equity - 10000) / 10000 * 100:.1f}%")

        daily = trades_all.groupby(
            pd.to_datetime(trades_all["entry_timestamp"]).dt.date
        )["net_pnl"].sum()
        sharpe = (daily.mean() / daily.std()) * np.sqrt(252) if len(daily) > 1 else 0
        logging.info(f"Sharpe: {sharpe:.2f}")

        logging.info("\n--- Exit Breakdown ---")
        for reason in ["stop", "target", "time", "eod"]:
            sub = trades_all[trades_all["exit_reason"] == reason]
            if len(sub) > 0:
                logging.info(
                    f"{reason:6s}: {len(sub):4d} ({len(sub)/len(trades_all)*100:5.1f}%) | "
                    f"Win: {(sub['net_pnl']>0).mean()*100:5.1f}% | PnL: ${sub['net_pnl'].sum():+,.0f}"
                )

        logging.info("\n--- By Direction ---")
        for side in ["LONG", "SHORT"]:
            sub = trades_all[trades_all["side"] == side]
            logging.info(
                f"{side:5s}: {len(sub):4d} | Win: {(sub['net_pnl']>0).mean()*100:5.1f}% | PnL: ${sub['net_pnl'].sum():+,.0f}"
            )

        logging.info(f"\nResults saved to: {output_dir}")


if __name__ == "__main__":
    main()
