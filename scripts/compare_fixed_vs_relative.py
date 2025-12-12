#!/usr/bin/env python3
"""Compare fixed 1.5% labels vs ATR-relative 1.5x labels."""

import logging
from pathlib import Path
import pandas as pd
import polars as pl
import lightgbm as lgb
import numpy as np
from sklearn.metrics import roc_auc_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(message)s")

# Test periods
KNOWN_GOOD_PERIOD = ("2023-08-01", "2023-08-31")  # Aug 2023 - was profitable
RECENT_PERIOD = ("2025-07-01", "2025-09-30")      # Recent period

def compare_label_methods():
    """Compare fixed vs relative labeling on known good and recent periods."""
    
    logging.info("COMPARING FIXED vs RELATIVE LABELS")
    
    # Load improved features (has both original and ATR labels)
    df = pl.read_parquet("run/intraday_features_improved/features.parquet")
    
    # Feature columns
    exclude_cols = [
        "timestamp", "date", "symbol", "session_id", "bar_index",
        "entry_timestamp", "exit_timestamp", "entry_close", "exit_close",
        "forward_return", "label_long", "label_short", "label_long_atr", "label_short_atr",
        "atr_threshold", "open", "high", "low", "close", "volume", "atr", "tr", "prev_close",
        "vwap_session", "first_open", "prev_session_close", "cum_dollar_vol", "cum_volume"
    ]
    feature_cols = [c for c in df.columns if c not in exclude_cols]
    
    results = []
    
    # Test both periods
    for period_name, (start_date, end_date) in [("Known Good (Aug 2023)", KNOWN_GOOD_PERIOD), 
                                                ("Recent (Jul-Sep 2025)", RECENT_PERIOD)]:
        
        logging.info(f"\n{'='*60}")
        logging.info(f"TESTING PERIOD: {period_name}")
        logging.info(f"{'='*60}")
        
        # Filter to period
        period_df = df.filter(
            (pl.col("date") >= pl.lit(start_date).str.strptime(pl.Date)) &
            (pl.col("date") <= pl.lit(end_date).str.strptime(pl.Date))
        ).to_pandas()
        
        if len(period_df) < 1000:
            logging.warning(f"Insufficient data for {period_name}: {len(period_df)} rows")
            continue
        
        logging.info(f"Data: {len(period_df):,} rows")
        
        # Split chronologically
        split_idx = int(len(period_df) * 0.7)
        train_df = period_df.iloc[:split_idx]
        test_df = period_df.iloc[split_idx:]
        
        # Test both label methods
        for label_type in ["fixed", "relative"]:
            
            if label_type == "fixed":
                long_col, short_col = "label_long", "label_short"
                desc = "Fixed 1.5%"
            else:
                long_col, short_col = "label_long_atr", "label_short_atr"  
                desc = "ATR 1.5x"
            
            logging.info(f"\n--- {desc} Labels ---")
            
            # Label statistics
            long_rate = train_df[long_col].mean() * 100
            short_rate = train_df[short_col].mean() * 100
            logging.info(f"Label rates: Long {long_rate:.2f}%, Short {short_rate:.2f}%")
            
            # Train models
            model_results = train_and_test(train_df, test_df, feature_cols, long_col, short_col)
            
            if model_results:
                model_results.update({
                    'period': period_name,
                    'label_type': label_type,
                    'label_desc': desc,
                    'long_rate': long_rate,
                    'short_rate': short_rate
                })
                results.append(model_results)
                
                logging.info(f"AUC: Long {model_results['auc_long']:.3f}, Short {model_results['auc_short']:.3f}")
                logging.info(f"Backtest: {model_results['trades']} trades, {model_results['win_rate']:.1f}% win, ${model_results['pnl']:,.0f}")
    
    # Create comparison report
    if results:
        results_df = pd.DataFrame(results)
        results_df.to_csv("run/fixed_vs_relative_comparison.csv", index=False)
        
        generate_comparison_report(results_df)
    else:
        logging.error("No results generated")

def train_and_test(train_df, test_df, feature_cols, long_col, short_col):
    """Train models and run backtest."""
    
    X_train, X_test = train_df[feature_cols], test_df[feature_cols]
    
    params = {
        "objective": "binary", "metric": "auc", "boosting_type": "gbdt",
        "num_leaves": 31, "learning_rate": 0.05, "verbose": -1
    }
    
    # Train LONG model
    if train_df[long_col].sum() < 50:
        return None
    
    model_long = lgb.train(params, lgb.Dataset(X_train, train_df[long_col]), 100)
    pred_long = model_long.predict(X_test)
    auc_long = roc_auc_score(test_df[long_col], pred_long)
    
    # Train SHORT model
    if train_df[short_col].sum() < 50:
        model_short = None
        pred_short = np.zeros(len(X_test))
        auc_short = 0.5
    else:
        model_short = lgb.train(params, lgb.Dataset(X_train, train_df[short_col]), 100)
        pred_short = model_short.predict(X_test)
        auc_short = roc_auc_score(test_df[short_col], pred_short)
    
    # Simple backtest
    backtest_results = run_simple_backtest(test_df, pred_long, pred_short)
    
    return {
        'auc_long': auc_long,
        'auc_short': auc_short,
        **backtest_results
    }

def run_simple_backtest(test_df, pred_long, pred_short, threshold=0.40):
    """Run simple backtest with fixed parameters."""
    
    test_df = test_df.copy()
    test_df['prob_long'] = pred_long
    test_df['prob_short'] = pred_short
    test_df['prediction'] = 0
    test_df.loc[test_df['prob_long'] >= threshold, 'prediction'] = 1
    test_df.loc[test_df['prob_short'] >= threshold, 'prediction'] = -1
    
    signals = test_df[test_df['prediction'] != 0]
    
    if len(signals) < 5:
        return {'trades': 0, 'win_rate': 0, 'pnl': 0, 'symbols': 0}
    
    # Execute trades
    trades = []
    for _, signal in signals.iterrows():
        direction = signal['prediction']
        entry_price = signal.get('entry_close', signal['close'])
        exit_price = signal.get('exit_close', signal['close'])
        
        if pd.isna(entry_price) or pd.isna(exit_price):
            continue
        
        # Fixed $200 risk
        atr_pct = signal.get('atr_pct', 0.02)
        if atr_pct <= 0 or pd.isna(atr_pct):
            atr_pct = 0.02
        
        shares = int(200 / (entry_price * atr_pct))
        if shares <= 0:
            continue
        
        # P&L
        if direction == 1:
            pnl = (exit_price - entry_price) * shares
        else:
            pnl = (entry_price - exit_price) * shares
        
        # Costs
        fee = max(shares * 0.0035, 0.35) * 2
        spread = shares * entry_price * 0.0005
        net_pnl = pnl - fee - spread
        
        trades.append({
            'symbol': signal['symbol'],
            'net_pnl': net_pnl
        })
    
    if not trades:
        return {'trades': 0, 'win_rate': 0, 'pnl': 0, 'symbols': 0}
    
    trades_df = pd.DataFrame(trades)
    
    return {
        'trades': len(trades_df),
        'win_rate': (trades_df['net_pnl'] > 0).mean() * 100,
        'pnl': trades_df['net_pnl'].sum(),
        'symbols': trades_df['symbol'].nunique()
    }

def generate_comparison_report(results_df):
    """Generate comprehensive comparison report."""
    
    logging.info("\n" + "=" * 80)
    logging.info("COMPREHENSIVE COMPARISON REPORT")
    logging.info("=" * 80)
    
    # Group by period
    for period in results_df['period'].unique():
        period_data = results_df[results_df['period'] == period]
        
        logging.info(f"\n{period}")
        logging.info("-" * 60)
        
        for _, row in period_data.iterrows():
            logging.info(f"{row['label_desc']:12s}: "
                        f"AUC L/S {row['auc_long']:.3f}/{row['auc_short']:.3f} | "
                        f"Labels {row['long_rate']:.1f}%/{row['short_rate']:.1f}% | "
                        f"{row['trades']:3d} trades | "
                        f"{row['win_rate']:5.1f}% win | "
                        f"${row['pnl']:+8,.0f}")
    
    # Direct comparison
    logging.info("\n" + "=" * 80)
    logging.info("DIRECT COMPARISON")
    logging.info("=" * 80)
    
    for period in results_df['period'].unique():
        period_data = results_df[results_df['period'] == period]
        
        if len(period_data) == 2:
            fixed = period_data[period_data['label_type'] == 'fixed'].iloc[0]
            relative = period_data[period_data['label_type'] == 'relative'].iloc[0]
            
            logging.info(f"\n{period}:")
            logging.info(f"  Model Quality (AUC Long):")
            logging.info(f"    Fixed:    {fixed['auc_long']:.3f}")
            logging.info(f"    Relative: {relative['auc_long']:.3f}")
            logging.info(f"    Winner:   {'Fixed' if fixed['auc_long'] > relative['auc_long'] else 'Relative'}")
            
            logging.info(f"  Performance (PnL):")
            logging.info(f"    Fixed:    ${fixed['pnl']:+,.0f}")
            logging.info(f"    Relative: ${relative['pnl']:+,.0f}")
            logging.info(f"    Winner:   {'Fixed' if fixed['pnl'] > relative['pnl'] else 'Relative'}")
            
            logging.info(f"  Label Rates (Long):")
            logging.info(f"    Fixed:    {fixed['long_rate']:.1f}%")
            logging.info(f"    Relative: {relative['long_rate']:.1f}%")
    
    # Overall recommendation
    logging.info("\n" + "=" * 80)
    logging.info("RECOMMENDATION")
    logging.info("=" * 80)
    
    # Count wins
    fixed_wins = 0
    relative_wins = 0
    
    for period in results_df['period'].unique():
        period_data = results_df[results_df['period'] == period]
        if len(period_data) == 2:
            fixed_pnl = period_data[period_data['label_type'] == 'fixed']['pnl'].iloc[0]
            relative_pnl = period_data[period_data['label_type'] == 'relative']['pnl'].iloc[0]
            
            if fixed_pnl > relative_pnl:
                fixed_wins += 1
            else:
                relative_wins += 1
    
    if fixed_wins > relative_wins:
        logging.info("RECOMMENDATION: Use FIXED 1.5% labels")
        logging.info("Fixed labels outperform ATR-relative labels")
    elif relative_wins > fixed_wins:
        logging.info("RECOMMENDATION: Use RELATIVE ATR 1.5x labels")  
        logging.info("ATR-relative labels outperform fixed labels")
    else:
        logging.info("RECOMMENDATION: No clear winner")
        logging.info("Both methods perform similarly")

if __name__ == "__main__":
    compare_label_methods()
