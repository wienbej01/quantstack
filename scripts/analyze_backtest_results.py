#!/usr/bin/env python3
"""Analyze backtest results in detail."""

import pandas as pd

# Load trade report
trades = pd.read_csv("artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv")

print("=" * 80)
print("BACKTEST ANALYSIS - MAY 2024")
print("=" * 80)
print()

# Basic stats
print(f"Total Trades: {len(trades)}")
print(f"Total PnL: ${trades['pnl_net'].sum():.2f}")
print(f"Win Rate: {(trades['pnl_net'] > 0).mean() * 100:.1f}%")
print()

# Exit reasons
print("Exit Reasons:")
exit_counts = trades['exit_reason'].value_counts()
for reason, count in exit_counts.items():
    pct = 100 * count / len(trades)
    print(f"  {reason:10s}: {count:4d} ({pct:5.1f}%)")
print()

# Performance by exit reason
print("Performance by Exit Reason:")
for reason in ['TARGET', 'STOP', 'EOD']:
    mask = trades['exit_reason'] == reason
    if mask.sum() > 0:
        avg_pnl = trades.loc[mask, 'pnl_net'].mean()
        total_pnl = trades.loc[mask, 'pnl_net'].sum()
        win_rate = (trades.loc[mask, 'pnl_net'] > 0).mean() * 100
        print(f"  {reason:10s}: avg=${avg_pnl:7.3f}  total=${total_pnl:8.2f}  win_rate={win_rate:5.1f}%")
print()

# Performance by side
print("Performance by Side:")
for side in ['LONG', 'SHORT']:
    mask = trades['side'] == side
    if mask.sum() > 0:
        count = mask.sum()
        avg_pnl = trades.loc[mask, 'pnl_net'].mean()
        total_pnl = trades.loc[mask, 'pnl_net'].sum()
        win_rate = (trades.loc[mask, 'pnl_net'] > 0).mean() * 100
        target_rate = (trades.loc[mask, 'exit_reason'] == 'TARGET').mean() * 100
        print(f"  {side:6s}: n={count:3d}  avg=${avg_pnl:7.3f}  total=${total_pnl:8.2f}  win={win_rate:5.1f}%  target={target_rate:5.1f}%")
print()

# Duration analysis
print("Duration Analysis:")
print(f"  Mean:   {trades['duration_minutes'].mean():.1f} minutes")
print(f"  Median: {trades['duration_minutes'].median():.1f} minutes")
print(f"  Max:    {trades['duration_minutes'].max():.0f} minutes ({trades['duration_minutes'].max()/60:.1f} hours)")
print(f"  Min:    {trades['duration_minutes'].min():.0f} minutes")
print()

# Duration by exit reason
print("Duration by Exit Reason:")
for reason in ['TARGET', 'STOP', 'EOD']:
    mask = trades['exit_reason'] == reason
    if mask.sum() > 0:
        mean_dur = trades.loc[mask, 'duration_minutes'].mean()
        median_dur = trades.loc[mask, 'duration_minutes'].median()
        print(f"  {reason:10s}: mean={mean_dur:6.1f}min  median={median_dur:5.1f}min")
print()

# Best and worst trades
print("Best 5 Trades:")
best = trades.nlargest(5, 'pnl_net')[['symbol', 'side', 'entry_time', 'pnl_net', 'exit_reason', 'duration_minutes']]
for idx, row in best.iterrows():
    print(f"  {row['symbol']:6s} {row['side']:5s} ${row['pnl_net']:7.3f}  {row['exit_reason']:6s}  {row['duration_minutes']:3.0f}min  {row['entry_time']}")
print()

print("Worst 5 Trades:")
worst = trades.nsmallest(5, 'pnl_net')[['symbol', 'side', 'entry_time', 'pnl_net', 'exit_reason', 'duration_minutes']]
for idx, row in worst.iterrows():
    print(f"  {row['symbol']:6s} {row['side']:5s} ${row['pnl_net']:7.3f}  {row['exit_reason']:6s}  {row['duration_minutes']:3.0f}min  {row['entry_time']}")
print()

# Symbol performance
print("Top 5 Symbols by PnL:")
symbol_pnl = trades.groupby('symbol')['pnl_net'].agg(['sum', 'count', 'mean'])
symbol_pnl = symbol_pnl.sort_values('sum', ascending=False)
for symbol, row in symbol_pnl.head(5).iterrows():
    print(f"  {symbol:6s}: ${row['sum']:8.2f}  (n={row['count']:3.0f}  avg=${row['mean']:6.3f})")
print()

print("Bottom 5 Symbols by PnL:")
for symbol, row in symbol_pnl.tail(5).iterrows():
    print(f"  {symbol:6s}: ${row['sum']:8.2f}  (n={row['count']:3.0f}  avg=${row['mean']:6.3f})")
print()

# Risk metrics
print("Risk Metrics:")
print(f"  Avg Stop Distance:   ${trades['stop_pct'].abs().mean() * trades['entry_price'].mean():.3f} ({trades['stop_pct'].abs().mean() * 100:.2f}%)")
print(f"  Avg Target Distance: ${trades['target_pct'].abs().mean() * trades['entry_price'].mean():.3f} ({trades['target_pct'].abs().mean() * 100:.2f}%)")
print(f"  Avg R-multiple:      {(trades['target_pct'].abs() / trades['stop_pct'].abs()).mean():.2f}")
print()

# Commission impact
total_commission = trades['commission'].sum()
total_gross_pnl = trades['pnl_gross'].sum()
print("Commission Impact:")
print(f"  Total Commission: ${total_commission:.2f}")
print(f"  Gross PnL:        ${total_gross_pnl:.2f}")
print(f"  Net PnL:          ${trades['pnl_net'].sum():.2f}")
print(f"  Commission %:     {100 * total_commission / abs(total_gross_pnl):.1f}% of gross PnL")
print()

# Win/Loss distribution
wins = trades[trades['pnl_net'] > 0]['pnl_net']
losses = trades[trades['pnl_net'] < 0]['pnl_net']
print("Win/Loss Distribution:")
print(f"  Wins:   n={len(wins):3d}  avg=${wins.mean():6.3f}  total=${wins.sum():8.2f}")
print(f"  Losses: n={len(losses):3d}  avg=${losses.mean():6.3f}  total=${losses.sum():8.2f}")
print(f"  Profit Factor: {abs(wins.sum() / losses.sum()):.3f}")
print()

# Target hit rate analysis
target_hits = (trades['exit_reason'] == 'TARGET').sum()
stop_hits = (trades['exit_reason'] == 'STOP').sum()
total_resolved = target_hits + stop_hits
if total_resolved > 0:
    target_rate = 100 * target_hits / total_resolved
    print("Target Hit Rate (excluding EOD):")
    print(f"  Target hits: {target_hits} / {total_resolved} = {target_rate:.1f}%")
    print("  Expected (random walk): 38.5%")
    print(f"  Improvement: {target_rate - 38.5:+.1f} percentage points")
    print()

print("=" * 80)
print("ASSESSMENT")
print("=" * 80)
print()

# Check success criteria
print("Success Criteria:")
print(f"  ✓ EOD close working: {trades['duration_minutes'].max() < 400}")
print(f"  ✓ Target hits > 10%: {(trades['exit_reason'] == 'TARGET').mean() > 0.10}")
print(f"  {'✓' if (trades['pnl_net'] > 0).mean() > 0.40 else '✗'} Win rate > 40%: {(trades['pnl_net'] > 0).mean() * 100:.1f}%")
print(f"  {'✓' if target_rate > 40 else '✗'} Target rate > 40%: {target_rate:.1f}%")
print(f"  {'✓' if trades['pnl_net'].sum() > 0 else '✗'} Positive PnL: ${trades['pnl_net'].sum():.2f}")
print()

if trades['pnl_net'].sum() < 0:
    print("⚠️  Model is not profitable yet. Issues:")
    print(f"   - Win rate too low: {(trades['pnl_net'] > 0).mean() * 100:.1f}% (need >42%)")
    print(f"   - Target rate: {target_rate:.1f}% (need >40%)")
    print(f"   - Commission impact: {100 * total_commission / abs(total_gross_pnl):.1f}% of gross PnL")
    print()
    print("Recommendations:")
    print("   1. Lower probability thresholds to get more selective trades")
    print("   2. Increase position size to overcome commission drag")
    print("   3. Filter for higher conviction signals")
    print("   4. Consider wider stops to reduce stop-outs")
else:
    print("✓ Model is profitable!")
