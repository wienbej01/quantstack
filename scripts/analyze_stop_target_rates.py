"""Analyze stop vs target hit rates."""

import pandas as pd
import numpy as np

trades = pd.read_csv('artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv')

print('=== STOP VS TARGET ANALYSIS ===')
print(f'\nTotal trades: {len(trades)}')

# Exit reason breakdown
stop_trades = trades[trades['exit_reason'] == 'STOP']
target_trades = trades[trades['exit_reason'] == 'TARGET']
eod_trades = trades[trades['exit_reason'] == 'EOD']

print(f'\nSTOP hits:   {len(stop_trades)} ({len(stop_trades)/len(trades)*100:.1f}%)')
print(f'TARGET hits: {len(target_trades)} ({len(target_trades)/len(trades)*100:.1f}%)')
print(f'EOD exits:   {len(eod_trades)} ({len(eod_trades)/len(trades)*100:.1f}%)')

# Calculate expected vs actual
r_multiple = 1.6
expected_target_rate = 1 / (1 + r_multiple)  # For random walk
expected_stop_rate = r_multiple / (1 + r_multiple)

print(f'\n=== EXPECTED (RANDOM WALK) ===')
print(f'R-multiple: {r_multiple}')
print(f'Expected TARGET rate: {expected_target_rate*100:.1f}%')
print(f'Expected STOP rate:   {expected_stop_rate*100:.1f}%')

actual_target_rate = len(target_trades) / (len(stop_trades) + len(target_trades))
actual_stop_rate = len(stop_trades) / (len(stop_trades) + len(target_trades))

print(f'\n=== ACTUAL (EXCLUDING EOD) ===')
print(f'Actual TARGET rate: {actual_target_rate*100:.1f}%')
print(f'Actual STOP rate:   {actual_stop_rate*100:.1f}%')

print(f'\n=== PERFORMANCE VS RANDOM ===')
print(f'Target rate: {actual_target_rate*100:.1f}% vs {expected_target_rate*100:.1f}% expected')
print(f'Difference: {(actual_target_rate - expected_target_rate)*100:.1f} percentage points')

if actual_target_rate < expected_target_rate:
    print(f'⚠️ WORSE than random walk by {(expected_target_rate - actual_target_rate)*100:.1f} pp')
else:
    print(f'✓ BETTER than random walk by {(actual_target_rate - expected_target_rate)*100:.1f} pp')

# PnL analysis
print(f'\n=== PNL ANALYSIS ===')
print(f'Avg STOP loss:   ${stop_trades["pnl_net"].mean():.3f}')
print(f'Avg TARGET win:  ${target_trades["pnl_net"].mean():.3f}')
print(f'Avg EOD:         ${eod_trades["pnl_net"].mean():.3f}')

# Calculate R-achieved
trades['stop_dist'] = abs(trades['entry_price'] - trades['stop_price'])
trades['target_dist'] = abs(trades['entry_price'] - trades['target_price'])
trades['actual_r'] = trades['target_dist'] / trades['stop_dist']

print(f'\n=== R-MULTIPLE ===')
print(f'Configured R: {r_multiple}')
print(f'Actual R (mean): {trades["actual_r"].mean():.2f}')
print(f'Actual R (median): {trades["actual_r"].median():.2f}')

# Expected PnL
expected_pnl = (expected_target_rate * target_trades['pnl_net'].mean() + 
                expected_stop_rate * stop_trades['pnl_net'].mean())
actual_pnl = trades[trades['exit_reason'].isin(['STOP', 'TARGET'])]['pnl_net'].mean()

print(f'\n=== EXPECTED VS ACTUAL PNL ===')
print(f'Expected PnL/trade (random): ${expected_pnl:.3f}')
print(f'Actual PnL/trade:            ${actual_pnl:.3f}')
print(f'Difference:                  ${actual_pnl - expected_pnl:.3f}')

# By direction
print(f'\n=== BY DIRECTION ===')
for side in ['LONG', 'SHORT']:
    side_trades = trades[trades['side'] == side]
    if len(side_trades) > 0:
        side_stops = side_trades[side_trades['exit_reason'] == 'STOP']
        side_targets = side_trades[side_trades['exit_reason'] == 'TARGET']
        
        if len(side_stops) + len(side_targets) > 0:
            target_rate = len(side_targets) / (len(side_stops) + len(side_targets))
            print(f'\n{side}:')
            print(f'  Total: {len(side_trades)}')
            print(f'  STOP: {len(side_stops)} ({len(side_stops)/len(side_trades)*100:.1f}%)')
            print(f'  TARGET: {len(side_targets)} ({len(side_targets)/len(side_trades)*100:.1f}%)')
            print(f'  Target rate: {target_rate*100:.1f}% (expected: {expected_target_rate*100:.1f}%)')
            print(f'  Avg PnL: ${side_trades["pnl_net"].mean():.3f}')

print(f'\n=== CONCLUSION ===')
if actual_target_rate < expected_target_rate - 0.02:
    print('❌ System is WORSE than random - ML predictions have NO edge')
    print('   Recommendation: Do not trade this system')
elif actual_target_rate < expected_target_rate + 0.02:
    print('⚠️ System is BREAKEVEN - ML predictions have MINIMAL edge')
    print('   Recommendation: Optimize or abandon')
else:
    print('✓ System has EDGE - ML predictions are working')
    print('   Recommendation: Optimize position sizing and costs')
