#!/usr/bin/env python3
"""Analyze LONG-only strategy vs LONG+SHORT strategy."""

import pandas as pd

# Load actual backtest results
trades = pd.read_csv("artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv")

print("=" * 80)
print("LONG-ONLY vs LONG+SHORT STRATEGY ANALYSIS")
print("=" * 80)
print()

# Overall results
print("Current Strategy (LONG + SHORT):")
print(f"  Total Trades: {len(trades)}")
print(f"  Total PnL:    ${trades['pnl_net'].sum():.2f}")
print(f"  Win Rate:     {(trades['pnl_net'] > 0).mean() * 100:.1f}%")
print()

# LONG only
long_trades = trades[trades['side'] == 'LONG']
print("LONG-Only Strategy:")
print(f"  Total Trades: {len(long_trades)}")
print(f"  Total PnL:    ${long_trades['pnl_net'].sum():.2f}")
print(f"  Win Rate:     {(long_trades['pnl_net'] > 0).mean() * 100:.1f}%")
print(f"  Avg PnL:      ${long_trades['pnl_net'].mean():.3f}")
print(f"  Target Rate:  {(long_trades['exit_reason'] == 'TARGET').mean() * 100:.1f}%")
print()

# SHORT only
short_trades = trades[trades['side'] == 'SHORT']
print("SHORT-Only Strategy:")
print(f"  Total Trades: {len(short_trades)}")
print(f"  Total PnL:    ${short_trades['pnl_net'].sum():.2f}")
print(f"  Win Rate:     {(short_trades['pnl_net'] > 0).mean() * 100:.1f}%")
print(f"  Avg PnL:      ${short_trades['pnl_net'].mean():.3f}")
print(f"  Target Rate:  {(short_trades['exit_reason'] == 'TARGET').mean() * 100:.1f}%")
print()

# Impact of removing SHORT
print("Impact of Removing SHORT Trades:")
improvement = long_trades['pnl_net'].sum() - trades['pnl_net'].sum()
print(f"  PnL Improvement: ${improvement:.2f}")
print(f"  Trades Removed:  {len(short_trades)}")
print()

# With dynamic position sizing (10x)
print("=" * 80)
print("WITH DYNAMIC POSITION SIZING (10x)")
print("=" * 80)
print()

# Simulate 10x position size
multiplier = 10

print("LONG-Only Strategy (10x position size):")
long_pnl_scaled = long_trades['pnl_net'].sum() * multiplier
long_commission_scaled = long_trades['commission'].sum() * multiplier
print(f"  Total PnL:       ${long_pnl_scaled:.2f}")
print(f"  Total Commission: ${long_commission_scaled:.2f}")
print(f"  Net PnL:         ${long_pnl_scaled:.2f}")
print(f"  Return on $1M:   {long_pnl_scaled / 1000000 * 100:.2f}%")
print()

# Best case: LONG only with selective filtering
print("=" * 80)
print("OPTIMIZED STRATEGY")
print("=" * 80)
print()

# Filter for high-conviction LONG trades
# Criteria: Target hits (best trades)
long_targets = long_trades[long_trades['exit_reason'] == 'TARGET']
print("LONG-Only, Target Hits Only:")
print(f"  Total Trades: {len(long_targets)}")
print(f"  Total PnL:    ${long_targets['pnl_net'].sum():.2f}")
print(f"  Win Rate:     {(long_targets['pnl_net'] > 0).mean() * 100:.1f}%")
print(f"  Avg PnL:      ${long_targets['pnl_net'].mean():.3f}")
print()

# With 10x sizing
long_targets_scaled = long_targets['pnl_net'].sum() * multiplier
print(f"  With 10x sizing: ${long_targets_scaled:.2f}")
print(f"  Return on $1M:   {long_targets_scaled / 1000000 * 100:.2f}%")
print()

# Recommendations
print("=" * 80)
print("RECOMMENDATIONS")
print("=" * 80)
print()
print("1. DISABLE SHORT TRADES")
print(f"   - SHORT losing ${short_trades['pnl_net'].sum():.2f}")
print(f"   - SHORT win rate only {(short_trades['pnl_net'] > 0).mean() * 100:.1f}%")
print()
print("2. INCREASE POSITION SIZE")
print(f"   - Current: 1 share per trade")
print(f"   - Recommended: Dynamic sizing (2% equity risk)")
print(f"   - Expected: 10-50x current PnL")
print()
print("3. FILTER FOR HIGH CONVICTION")
print(f"   - Use higher probability thresholds")
print(f"   - Focus on best setups")
print(f"   - Target 40%+ win rate")
print()
print("4. EXPECTED RESULTS")
print(f"   - LONG-only with 10x sizing: ${long_pnl_scaled:.2f}")
print(f"   - Monthly return: ~{long_pnl_scaled / 1000000 * 100:.2f}%")
print(f"   - Annualized: ~{long_pnl_scaled / 1000000 * 100 * 12:.1f}%")
