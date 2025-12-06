"""Analyze predictive power of ML features and parameters."""


import pandas as pd

# Load data
predictions = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_full_sip/oos_predictions_bigmove.parquet')
orders = pd.read_parquet('artefacts/extensions/intraday_ml/phaseA_full_sip/oos_orders.parquet')
trades = pd.read_csv('artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv')

print('='*80)
print('PREDICTIVE POWER ANALYSIS')
print('='*80)

# Convert timestamps for merging
predictions['ts_ns'] = pd.to_datetime(predictions['ts']).astype('int64')
orders['ts_ns'] = orders['ts'].astype('int64')

# Merge predictions with orders
merged = orders.merge(
    predictions[['ts_ns', 'symbol', 'prob_bigmove', 'prob_long', 'prob_short', 
                 'prob_bigmove_long', 'prob_bigmove_short']],
    left_on=['ts_ns', 'symbol'],
    right_on=['ts_ns', 'symbol'],
    how='left'
)

print('\n=== DATA LOADED ===')
print(f'Predictions: {len(predictions):,}')
print(f'Orders: {len(orders):,}')
print(f'Trades executed: {len(trades):,}')
print(f'Merged orders with predictions: {len(merged):,}')

# Merge trades with orders to get outcomes
trades['entry_time_ns'] = pd.to_datetime(trades['entry_time']).astype('int64')
merged_trades = merged.merge(
    trades[['symbol', 'entry_time_ns', 'exit_reason', 'pnl_net', 'duration_minutes']],
    left_on=['symbol', 'ts_ns'],
    right_on=['symbol', 'entry_time_ns'],
    how='inner'
)

print(f'Trades with predictions: {len(merged_trades):,}')

# Analyze by prediction strength
print('\n' + '='*80)
print('PREDICTION STRENGTH vs OUTCOME')
print('='*80)

# Bin by probability
merged_trades['prob_bin'] = pd.cut(merged_trades['prob_bigmove'], bins=[0, 0.4, 0.5, 0.6, 0.7, 1.0], 
                                     labels=['<0.4', '0.4-0.5', '0.5-0.6', '0.6-0.7', '>0.7'])

print('\n--- By Bigmove Probability ---')
for prob_bin in merged_trades['prob_bin'].cat.categories:
    bin_trades = merged_trades[merged_trades['prob_bin'] == prob_bin]
    if len(bin_trades) > 0:
        target_rate = (bin_trades['exit_reason'] == 'TARGET').sum() / len(bin_trades) * 100
        avg_pnl = bin_trades['pnl_net'].mean()
        print(f'{prob_bin:10} {len(bin_trades):4} trades, {target_rate:5.1f}% targets, avg PnL: ${avg_pnl:7.3f}')

# By expected R (from orders, not predictions)
if 'risk_r_multiple' in merged_trades.columns:
    merged_trades['expected_r_bin'] = pd.cut(merged_trades['risk_r_multiple'], 
                                              bins=[0, 1.2, 1.4, 1.6, 1.8, 10], 
                                              labels=['<1.2', '1.2-1.4', '1.4-1.6', '1.6-1.8', '>1.8'])

    print('\n--- By Expected R-Multiple ---')
    for r_bin in merged_trades['expected_r_bin'].cat.categories:
        bin_trades = merged_trades[merged_trades['expected_r_bin'] == r_bin]
        if len(bin_trades) > 0:
            target_rate = (bin_trades['exit_reason'] == 'TARGET').sum() / len(bin_trades) * 100
            avg_pnl = bin_trades['pnl_net'].mean()
            print(f'{r_bin:10} {len(bin_trades):4} trades, {target_rate:5.1f}% targets, avg PnL: ${avg_pnl:7.3f}')

# By direction probability
print('\n--- By Direction Confidence ---')
for side in ['LONG', 'SHORT']:
    side_trades = merged_trades[merged_trades['side'] == side]
    if len(side_trades) > 0:
        prob_col = 'prob_long' if side == 'LONG' else 'prob_short'
        
        # Bin by directional probability
        side_trades['dir_prob_bin'] = pd.cut(side_trades[prob_col], 
                                              bins=[0, 0.5, 0.6, 0.7, 0.8, 1.0],
                                              labels=['<0.5', '0.5-0.6', '0.6-0.7', '0.7-0.8', '>0.8'])
        
        print(f'\n{side}:')
        for prob_bin in side_trades['dir_prob_bin'].cat.categories:
            bin_trades = side_trades[side_trades['dir_prob_bin'] == prob_bin]
            if len(bin_trades) > 0:
                target_rate = (bin_trades['exit_reason'] == 'TARGET').sum() / len(bin_trades) * 100
                avg_pnl = bin_trades['pnl_net'].mean()
                print(f'  {prob_bin:10} {len(bin_trades):4} trades, {target_rate:5.1f}% targets, avg PnL: ${avg_pnl:7.3f}')

# Analyze risk parameters
print('\n' + '='*80)
print('RISK PARAMETER ANALYSIS')
print('='*80)

# Stop distance
merged_trades['stop_pct_bin'] = pd.cut(merged_trades['stop_loss_pct'] * 100,
                                        bins=[0, 0.2, 0.3, 0.4, 0.5, 10],
                                        labels=['<0.2%', '0.2-0.3%', '0.3-0.4%', '0.4-0.5%', '>0.5%'])

print('\n--- By Stop Distance (% of price) ---')
for stop_bin in merged_trades['stop_pct_bin'].cat.categories:
    bin_trades = merged_trades[merged_trades['stop_pct_bin'] == stop_bin]
    if len(bin_trades) > 0:
        target_rate = (bin_trades['exit_reason'] == 'TARGET').sum() / len(bin_trades) * 100
        stop_rate = (bin_trades['exit_reason'] == 'STOP').sum() / len(bin_trades) * 100
        avg_pnl = bin_trades['pnl_net'].mean()
        print(f'{stop_bin:10} {len(bin_trades):4} trades, {target_rate:5.1f}% targets, {stop_rate:5.1f}% stops, avg PnL: ${avg_pnl:7.3f}')

# ATR multiple
merged_trades['atr_mult_bin'] = pd.cut(merged_trades['risk_atr_multiple_stop'],
                                        bins=[0, 0.5, 0.7, 0.9, 1.1, 10],
                                        labels=['<0.5', '0.5-0.7', '0.7-0.9', '0.9-1.1', '>1.1'])

print('\n--- By Stop as ATR Multiple ---')
for atr_bin in merged_trades['atr_mult_bin'].cat.categories:
    bin_trades = merged_trades[merged_trades['atr_mult_bin'] == atr_bin]
    if len(bin_trades) > 0:
        target_rate = (bin_trades['exit_reason'] == 'TARGET').sum() / len(bin_trades) * 100
        avg_pnl = bin_trades['pnl_net'].mean()
        print(f'{atr_bin:10} {len(bin_trades):4} trades, {target_rate:5.1f}% targets, avg PnL: ${avg_pnl:7.3f}')

# Correlation analysis
print('\n' + '='*80)
print('CORRELATION ANALYSIS')
print('='*80)

# Create binary outcome
merged_trades['hit_target'] = (merged_trades['exit_reason'] == 'TARGET').astype(int)
merged_trades['profitable'] = (merged_trades['pnl_net'] > 0).astype(int)

# Calculate correlations
correlations = []
for col in ['prob_bigmove', 'prob_long', 'prob_short', 'prob_bigmove_long', 'prob_bigmove_short',
            'stop_loss_pct', 'take_profit_pct', 'risk_atr_multiple_stop', 'risk_r_multiple']:
    if col in merged_trades.columns:
        corr_target = merged_trades[col].corr(merged_trades['hit_target'])
        corr_profit = merged_trades[col].corr(merged_trades['profitable'])
        corr_pnl = merged_trades[col].corr(merged_trades['pnl_net'])
        correlations.append({
            'parameter': col,
            'vs_target_hit': corr_target,
            'vs_profitable': corr_profit,
            'vs_pnl': corr_pnl
        })

corr_df = pd.DataFrame(correlations).sort_values('vs_target_hit', ascending=False)
print('\nCorrelation with outcomes:')
print(corr_df.to_string(index=False))

# Summary statistics
print('\n' + '='*80)
print('SUMMARY STATISTICS')
print('='*80)

print('\nPrediction ranges:')
print(f'  prob_bigmove: {merged_trades["prob_bigmove"].min():.3f} to {merged_trades["prob_bigmove"].max():.3f}')
print(f'  prob_long: {merged_trades["prob_long"].min():.3f} to {merged_trades["prob_long"].max():.3f}')
print(f'  prob_short: {merged_trades["prob_short"].min():.3f} to {merged_trades["prob_short"].max():.3f}')

print('\nRisk parameter ranges:')
print(f'  stop_loss_pct: {merged_trades["stop_loss_pct"].min()*100:.3f}% to {merged_trades["stop_loss_pct"].max()*100:.3f}%')
print(f'  take_profit_pct: {merged_trades["take_profit_pct"].min()*100:.3f}% to {merged_trades["take_profit_pct"].max()*100:.3f}%')
print(f'  atr_multiple: {merged_trades["risk_atr_multiple_stop"].min():.3f} to {merged_trades["risk_atr_multiple_stop"].max():.3f}')

# Key findings
print('\n' + '='*80)
print('KEY FINDINGS')
print('='*80)

# Find best performing segments
best_prob = corr_df[corr_df['parameter'] == 'prob_bigmove']['vs_target_hit'].values[0]

print('\n1. Prediction Quality:')
if abs(best_prob) < 0.05:
    print(f'   ❌ prob_bigmove has WEAK correlation ({best_prob:.3f}) with target hits')
    print('   → ML model has minimal predictive power')
else:
    print(f'   ✓ prob_bigmove has correlation {best_prob:.3f} with target hits')

# Direction analysis
long_target_rate = (merged_trades[merged_trades['side'] == 'LONG']['exit_reason'] == 'TARGET').sum() / len(merged_trades[merged_trades['side'] == 'LONG']) * 100
short_target_rate = (merged_trades[merged_trades['side'] == 'SHORT']['exit_reason'] == 'TARGET').sum() / len(merged_trades[merged_trades['side'] == 'SHORT']) * 100

print('\n2. Directional Performance:')
print(f'   LONG target rate: {long_target_rate:.1f}% (expected: 38.5%)')
print(f'   SHORT target rate: {short_target_rate:.1f}% (expected: 38.5%)')
if long_target_rate > 40:
    print('   ✓ LONG trades show edge')
else:
    print('   ⚠️ LONG trades marginal')
if short_target_rate < 35:
    print('   ❌ SHORT trades FAILING - consider disabling')

print('\n' + '='*80)
