#!/usr/bin/env python3
"""Analyze why stops are being hit immediately on every trade."""

from pathlib import Path

import pandas as pd


def load_matched_trades():
    """Load the matched trades from previous analysis."""
    path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/matched_trades.parquet")
    if not path.exists():
        raise FileNotFoundError(f"Run match_fills_to_trades.py first: {path}")
    return pd.read_parquet(path)

def load_fills():
    """Load raw fills to get stop distances."""
    path = Path("artefacts/extensions/intraday_ml/phaseA_full_sip/fills.parquet")
    if not path.exists():
        raise FileNotFoundError(f"Fills not found: {path}")
    return pd.read_parquet(path)

def analyze_stop_patterns(matched_trades, fills):
    """Analyze the stop-hitting patterns."""
    
    print("=" * 80)
    print("STOP HIT ANALYSIS")
    print("=" * 80)
    
    # Basic stats
    print(f"\nTotal Trades: {len(matched_trades)}")
    print(f"Winners: {(matched_trades['pnl'] > 0).sum()} ({(matched_trades['pnl'] > 0).mean()*100:.1f}%)")
    print(f"Losers: {(matched_trades['pnl'] < 0).sum()} ({(matched_trades['pnl'] < 0).mean()*100:.1f}%)")
    print(f"Avg PnL: ${matched_trades['pnl'].mean():.2f}")
    print(f"Avg Duration: {matched_trades['duration_minutes'].mean():.1f} minutes")
    
    # Get stop distances from fills
    if 'stop_dist_ps' in fills.columns:
        print("\n--- Stop Distance Stats ---")
        print(f"Avg Stop Distance: ${fills['stop_dist_ps'].mean():.3f}")
        print(f"Median Stop Distance: ${fills['stop_dist_ps'].median():.3f}")
        print(f"Min Stop Distance: ${fills['stop_dist_ps'].min():.3f}")
        print(f"Max Stop Distance: ${fills['stop_dist_ps'].max():.3f}")
    
    # Analyze move sizes vs stop distances
    print("\n--- Move Analysis ---")
    matched_trades['abs_move'] = abs(matched_trades['exit_price'] - matched_trades['entry_price'])
    print(f"Avg Absolute Move: ${matched_trades['abs_move'].mean():.3f}")
    print(f"Median Absolute Move: ${matched_trades['abs_move'].median():.3f}")
    
    # Sample trades
    print("\n--- Sample Losing Trades (First 10) ---")
    losers = matched_trades[matched_trades['pnl'] < 0].head(10)
    
    for idx, trade in losers.iterrows():
        print(f"\n{trade['symbol']} | {trade['side']}")
        print(f"  Entry: ${trade['entry_price']:.2f}")
        print(f"  Exit:  ${trade['exit_price']:.2f}")
        print(f"  Move:  ${trade['abs_move']:.3f}")
        print(f"  PnL:   ${trade['pnl']:.2f}")
        print(f"  Duration: {trade['duration_minutes']:.0f} min")
        
        # Try to get stop distance for this trade
        entry_fills = fills[
            (fills['symbol'] == trade['symbol']) & 
            (fills['timestamp'] == trade['entry_time'])
        ]
        if not entry_fills.empty and 'stop_dist_ps' in entry_fills.columns:
            stop_dist = entry_fills.iloc[0]['stop_dist_ps']
            print(f"  Stop Distance: ${stop_dist:.3f}")
            print(f"  Move/Stop Ratio: {trade['abs_move']/stop_dist:.2f}x")
    
    # Duration analysis
    print("\n--- Duration Analysis ---")
    print(f"Trades < 10 min: {(matched_trades['duration_minutes'] < 10).sum()}")
    print(f"Trades 10-20 min: {((matched_trades['duration_minutes'] >= 10) & (matched_trades['duration_minutes'] < 20)).sum()}")
    print(f"Trades 20-30 min: {((matched_trades['duration_minutes'] >= 20) & (matched_trades['duration_minutes'] < 30)).sum()}")
    print(f"Trades > 30 min: {(matched_trades['duration_minutes'] >= 30).sum()}")
    
    # PnL distribution
    print("\n--- PnL Distribution ---")
    print(f"PnL < -$1.00: {(matched_trades['pnl'] < -1.0).sum()}")
    print(f"PnL -$1.00 to -$0.50: {((matched_trades['pnl'] >= -1.0) & (matched_trades['pnl'] < -0.5)).sum()}")
    print(f"PnL -$0.50 to $0.00: {((matched_trades['pnl'] >= -0.5) & (matched_trades['pnl'] < 0)).sum()}")
    print(f"PnL $0.00 to $0.50: {((matched_trades['pnl'] >= 0) & (matched_trades['pnl'] < 0.5)).sum()}")
    print(f"PnL > $0.50: {(matched_trades['pnl'] >= 0.5).sum()}")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    matched_trades = load_matched_trades()
    fills = load_fills()
    analyze_stop_patterns(matched_trades, fills)
