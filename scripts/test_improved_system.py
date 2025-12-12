#!/usr/bin/env python3
"""Test improved system with available data."""

import logging
import pandas as pd
import numpy as np
from pathlib import Path
import lightgbm as lgb
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

def main():
    logging.info("TESTING IMPROVED SYSTEM")
    
    # Load improved features
    features_path = Path("run/intraday_features_improved/features.parquet")
    if not features_path.exists():
        logging.error("No improved features found")
        return
    
    df = pd.read_parquet(features_path)
    logging.info(f"Loaded {len(df)} rows, {df['symbol'].nunique()} symbols")
    
    # Split data chronologically
    df = df.sort_values("timestamp")
    split_idx = int(len(df) * 0.7)  # 70% train, 30% test
    
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]
    
    logging.info(f"Train: {len(train_df)} rows, Test: {len(test_df)} rows")
    
    # Feature columns
    exclude_cols = [
        "timestamp", "date", "symbol", "session_id", "bar_index",
        "entry_timestamp", "exit_timestamp", "entry_close", "exit_close",
        "forward_return", "label_long", "label_short", "label_long_atr", "label_short_atr",
        "atr_threshold", "open", "high", "low", "close", "volume", "atr", "tr", "prev_close",
        # Remove raw price features
        "vwap_session", "first_open", "prev_session_close", "cum_dollar_vol", "cum_volume"
    ]
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    logging.info(f"Features: {len(feature_cols)}")
    
    # Compare label rates
    logging.info("\n--- LABEL COMPARISON ---")
    logging.info(f"Original labels - Long: {train_df['label_long'].mean()*100:.2f}%, Short: {train_df['label_short'].mean()*100:.2f}%")
    logging.info(f"ATR labels - Long: {train_df['label_long_atr'].mean()*100:.2f}%, Short: {train_df['label_short_atr'].mean()*100:.2f}%")
    
    # Train models on ATR labels
    X_train, X_test = train_df[feature_cols], test_df[feature_cols]
    
    params = {
        "objective": "binary",
        "metric": "auc", 
        "num_leaves": 31,
        "learning_rate": 0.05,
        "verbose": -1
    }
    
    # LONG model (ATR labels)
    y_train_long = train_df["label_long_atr"]
    y_test_long = test_df["label_long_atr"]
    
    if y_train_long.sum() > 50:
        model_long = lgb.train(params, lgb.Dataset(X_train, y_train_long), 100)
        pred_long = model_long.predict(X_test)
        auc_long = roc_auc_score(y_test_long, pred_long)
        logging.info(f"LONG AUC (ATR labels): {auc_long:.4f}")
    else:
        logging.info("Not enough LONG labels")
        model_long = None
    
    # SHORT model (ATR labels)  
    y_train_short = train_df["label_short_atr"]
    y_test_short = test_df["label_short_atr"]
    
    if y_train_short.sum() > 50:
        model_short = lgb.train(params, lgb.Dataset(X_train, y_train_short), 100)
        pred_short = model_short.predict(X_test)
        auc_short = roc_auc_score(y_test_short, pred_short)
        logging.info(f"SHORT AUC (ATR labels): {auc_short:.4f}")
    else:
        logging.info("Not enough SHORT labels")
        model_short = None
    
    # Simple backtest with improvements
    logging.info("\n--- BACKTEST WITH IMPROVEMENTS ---")
    
    test_df = test_df.copy()
    if model_long is not None:
        test_df["prob_long"] = model_long.predict(X_test)
    else:
        test_df["prob_long"] = 0
    
    if model_short is not None:
        test_df["prob_short"] = model_short.predict(X_test)
    else:
        test_df["prob_short"] = 0
    
    # Apply threshold and time filter
    threshold = 0.60
    test_df["prediction"] = 0
    test_df.loc[test_df["prob_long"] >= threshold, "prediction"] = 1
    test_df.loc[test_df["prob_short"] >= threshold, "prediction"] = -1
    
    # TIME FILTERING - Only morning trades
    test_df = test_df[test_df["is_morning"] == 1]
    
    signals = test_df[test_df["prediction"] != 0]
    logging.info(f"Signals after time filter: {len(signals)}")
    
    if len(signals) == 0:
        logging.info("No signals generated")
        return
    
    # DIVERSIFICATION - Max 3 trades per symbol per day
    signals["date"] = pd.to_datetime(signals["timestamp"]).dt.date
    
    filtered_signals = []
    for date, day_signals in signals.groupby("date"):
        symbol_counts = {}
        for _, signal in day_signals.iterrows():
            symbol = signal["symbol"]
            if symbol_counts.get(symbol, 0) < 3:  # Max 3 per symbol per day
                filtered_signals.append(signal)
                symbol_counts[symbol] = symbol_counts.get(symbol, 0) + 1
    
    if not filtered_signals:
        logging.info("No signals after diversification")
        return
    
    signals = pd.DataFrame(filtered_signals)
    logging.info(f"Signals after diversification: {len(signals)}")
    
    # Execute trades with FIXED position sizing
    trades = []
    equity = 10_000
    
    for _, signal in signals.iterrows():
        direction = signal["prediction"]
        entry_price = signal["close"]  # Use current close as proxy
        
        # Fixed $200 risk per trade
        atr_pct = signal.get("atr_pct", 0.02)
        shares = int(200 / (entry_price * atr_pct))
        
        if shares <= 0:
            continue
        
        # Simple 5-bar hold (use forward return)
        forward_return = signal.get("forward_return", 0)
        if pd.isna(forward_return):
            continue
        
        if direction == 1:  # LONG
            pnl = forward_return * shares * entry_price
        else:  # SHORT
            pnl = -forward_return * shares * entry_price
        
        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = pnl - fee - spread
        
        equity += net_pnl
        
        trades.append({
            "symbol": signal["symbol"],
            "side": "LONG" if direction == 1 else "SHORT",
            "shares": shares,
            "entry_price": entry_price,
            "forward_return": forward_return,
            "gross_pnl": pnl,
            "net_pnl": net_pnl,
            "hour": signal["hour"],
        })
    
    if not trades:
        logging.info("No trades executed")
        return
    
    trades_df = pd.DataFrame(trades)
    
    # Results
    logging.info("\n--- IMPROVED SYSTEM RESULTS ---")
    logging.info(f"Total trades: {len(trades_df)}")
    logging.info(f"Win rate: {(trades_df['net_pnl'] > 0).mean()*100:.1f}%")
    logging.info(f"Total PnL: ${trades_df['net_pnl'].sum():,.0f}")
    logging.info(f"Final equity: ${equity:,.0f}")
    logging.info(f"Return: {(equity - 10000) / 10000 * 100:.1f}%")
    
    # Diversification check
    symbol_counts = trades_df["symbol"].value_counts()
    logging.info(f"Unique symbols: {len(symbol_counts)}")
    logging.info(f"Max trades per symbol: {symbol_counts.max()}")
    
    # Time distribution
    hour_pnl = trades_df.groupby("hour")["net_pnl"].sum()
    logging.info(f"PnL by hour: {hour_pnl.to_dict()}")
    
    # Direction performance
    for side in ["LONG", "SHORT"]:
        side_trades = trades_df[trades_df["side"] == side]
        if len(side_trades) > 0:
            logging.info(f"{side}: {len(side_trades)} trades, ${side_trades['net_pnl'].sum():,.0f} PnL")


if __name__ == "__main__":
    main()
