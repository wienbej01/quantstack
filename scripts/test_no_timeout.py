#!/usr/bin/env python3
"""Test policy with timeouts disabled to validate hypothesis."""

import json
import sys
from pathlib import Path

import pandas as pd

# Add project to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from extensions.intraday_ml.backtest import intraday_ml_run_backtest
from extensions.intraday_ml.experiments.policy_sweep import (
    _ensure_required_columns,
    _prepare_signals_for_policy_mode,
)
from extensions.intraday_ml_policies.intraday_ml_decision_policy import IntradayMLDecisionPolicy


def load_data():
    """Load signals and bars."""
    base_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip")
    
    signals = pd.read_parquet(base_path / "oos_predictions_bigmove.parquet")
    bars = pd.read_parquet(base_path / "oos_features.parquet")
    
    return signals, bars

def run_test():
    """Run single backtest with no-timeout config."""
    print("=" * 80)
    print("TESTING NO-TIMEOUT CONFIGURATION")
    print("=" * 80)
    
    # Load data
    print("\n1. Loading data...")
    signals, bars = load_data()
    print(f"   Signals: {len(signals)} rows")
    print(f"   Bars: {len(bars)} rows")
    
    # Load config
    print("\n2. Loading no-timeout config...")
    config_path = Path("configs/extensions/intraday_ml/policy_config_no_timeout.json")
    with open(config_path) as f:
        policy_config = json.load(f)
    
    print(f"   Early cut: {policy_config['lifecycle']['early_loss_cut_minutes']} min")
    print(f"   Dead trade: {policy_config['lifecycle']['dead_trade_exit_minutes']} min")
    print(f"   Max hold: {policy_config['lifecycle']['max_hold_minutes_flat_or_loser']} min")
    
    # Create policy
    print("\n3. Creating policy...")
    policy = IntradayMLDecisionPolicy(policy_config)
    
    # Prepare signals
    print("\n4. Preparing signals...")
    policy_mode = policy_config.get("policy_mode", "bigmove")
    prepared_signals = _prepare_signals_for_policy_mode(signals, policy_mode)
    
    required_columns = (
        policy.get_required_feature_columns()
        if hasattr(policy, "get_required_feature_columns")
        else set()
    )
    prepared_signals = _ensure_required_columns(prepared_signals, bars, required_columns=required_columns)
    print(f"   Prepared signals: {len(prepared_signals)} rows")
    print(f"   Columns: {len(prepared_signals.columns)}")
    
    # Generate orders
    print("\n5. Generating orders...")
    orders, rejections = policy.process_signals(prepared_signals)
    print(f"   Orders: {len(orders)}")
    print(f"   Rejections: {len(rejections)}")
    
    if len(orders) == 0:
        print("❌ No orders generated")
        rejection_counts = policy.get_rejection_reason_counts()
        print(f"   Rejection reasons: {dict(rejection_counts)}")
        return
    
    # Run backtest
    print("\n6. Running backtest...")
    backtest_config = {}
    
    result = intraday_ml_run_backtest(
        bars=bars,
        orders=orders,
        cfg=backtest_config,
    )
    
    # Analyze results
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    trades = result.get('trades')
    if trades is None or trades.empty:
        print("❌ No trades generated")
        return
    
    print(f"\nTrade Count: {len(trades)}")
    print(f"Final Equity: ${result.get('final_equity', 0):,.2f}")
    print(f"Total Return: {result.get('total_return_pct', 0):.2f}%")
    print(f"Sharpe Ratio: {result.get('sharpe_ratio', 0):.2f}")
    
    # Match fills to trades
    print("\n--- Matching Fills to Trades ---")
    from scripts.match_fills_to_trades import match_fills_to_trades
    
    matched = match_fills_to_trades(trades)
    
    if not matched.empty:
        print(f"\nCompleted Trades: {len(matched)}")
        print(f"Win Rate: {(matched['pnl'] > 0).mean():.1%}")
        print(f"Avg PnL: ${matched['pnl'].mean():.2f}")
        print(f"Total PnL: ${matched['pnl'].sum():.2f}")
        print(f"Avg Duration: {matched['duration_minutes'].mean():.1f} minutes")
        
        # Duration distribution
        print("\n--- Duration Distribution ---")
        print(f"< 10 min: {(matched['duration_minutes'] < 10).sum()}")
        print(f"10-20 min: {((matched['duration_minutes'] >= 10) & (matched['duration_minutes'] < 20)).sum()}")
        print(f"20-30 min: {((matched['duration_minutes'] >= 20) & (matched['duration_minutes'] < 30)).sum()}")
        print(f"30-60 min: {((matched['duration_minutes'] >= 30) & (matched['duration_minutes'] < 60)).sum()}")
        print(f"> 60 min: {(matched['duration_minutes'] >= 60).sum()}")
        
        # PnL distribution
        print("\n--- PnL Distribution ---")
        print(f"< -$1.00: {(matched['pnl'] < -1.0).sum()}")
        print(f"-$1.00 to -$0.50: {((matched['pnl'] >= -1.0) & (matched['pnl'] < -0.5)).sum()}")
        print(f"-$0.50 to $0.00: {((matched['pnl'] >= -0.5) & (matched['pnl'] < 0)).sum()}")
        print(f"$0.00 to $0.50: {((matched['pnl'] >= 0) & (matched['pnl'] < 0.5)).sum()}")
        print(f"> $0.50: {(matched['pnl'] >= 0.5).sum()}")
        
        # Sample winners
        winners = matched[matched['pnl'] > 0]
        if len(winners) > 0:
            print("\n--- Sample Winners (First 5) ---")
            for idx, trade in winners.head(5).iterrows():
                print(f"{trade['symbol']} {trade['side']}: ${trade['entry_price']:.2f} → ${trade['exit_price']:.2f} | PnL: ${trade['pnl']:.2f} | {trade['duration_minutes']:.0f} min")
        
        # Save results
        output_path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/matched_trades_no_timeout.parquet")
        matched.to_parquet(output_path, index=False)
        print(f"\n✅ Saved to {output_path}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    run_test()
