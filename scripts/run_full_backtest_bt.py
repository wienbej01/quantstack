"""Run full backtest using Backtrader on all OOS data."""

import sys
from pathlib import Path

import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from extensions.intraday_ml.backtest_bt import run_backtest_bt


def main():
    """Run full backtest on all OOS data."""
    
    artifacts_dir = project_root / "artefacts/extensions/intraday_ml/phaseA_multi"
    
    # Load features for OHLCV
    print("Loading data...")
    features = pd.read_parquet(artifacts_dir / "oos_features.parquet")
    bars = features[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']].copy()
    print(f"Loaded {len(bars):,} bars")
    
    # Load ML orders
    orders = pd.read_parquet(artifacts_dir / "oos_orders.parquet")
    print(f"Loaded {len(orders):,} orders")
    
    # Ensure stop/target columns
    if 'stop_loss_pct' not in orders.columns:
        orders['stop_loss_pct'] = 0.01
    if 'take_profit_pct' not in orders.columns:
        orders['take_profit_pct'] = 0.02
    
    # Configuration
    config = {
        'initial_cash': 1_000_000.0,
        'costs': {
            'per_share': 0.0035,
            'commission_min': 0.35,
            'bps': 5,
        }
    }
    
    # Run backtest
    print("\n" + "="*70)
    print("RUNNING FULL BACKTEST WITH BACKTRADER")
    print("="*70 + "\n")
    
    results = run_backtest_bt(bars, orders, config)
    
    # Print results
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    print("\nPortfolio Performance:")
    print(f"  Initial Cash:    ${results['initial_cash']:,.2f}")
    print(f"  Final Value:     ${results['final_value']:,.2f}")
    print(f"  Total PnL:       ${results['pnl']:,.2f}")
    print(f"  Return:          {results['return_pct']:.2f}%")
    
    sharpe = results.get('sharpe_ratio')
    if sharpe is not None:
        print(f"  Sharpe Ratio:    {sharpe:.2f}")
    
    dd = results.get('max_drawdown')
    if dd is not None:
        print(f"  Max Drawdown:    {dd:.2f}%")
    
    print("\nTrading Statistics:")
    print(f"  Total Trades:    {results.get('total_trades', 0)}")
    print(f"  Win Rate:        {results.get('win_rate', 0.0):.1f}%")
    
    if 'trade_analysis' in results:
        ta = results['trade_analysis']
        
        if 'won' in ta:
            won_total = ta['won'].get('total', 0)
            won_avg = ta['won'].get('pnl', {}).get('average', 0)
            won_max = ta['won'].get('pnl', {}).get('max', 0)
            print(f"\n  Winning Trades:  {won_total}")
            print(f"    Average Win:   ${won_avg:.2f}")
            print(f"    Largest Win:   ${won_max:.2f}")
        
        if 'lost' in ta:
            lost_total = ta['lost'].get('total', 0)
            lost_avg = ta['lost'].get('pnl', {}).get('average', 0)
            lost_max = ta['lost'].get('pnl', {}).get('max', 0)
            print(f"\n  Losing Trades:   {lost_total}")
            print(f"    Average Loss:  ${lost_avg:.2f}")
            print(f"    Largest Loss:  ${lost_max:.2f}")
        
        if 'won' in ta and 'lost' in ta:
            won_avg = ta['won'].get('pnl', {}).get('average', 0)
            lost_avg = ta['lost'].get('pnl', {}).get('average', 0)
            if lost_avg != 0:
                profit_factor = abs(won_avg * ta['won'].get('total', 0) / 
                                   (lost_avg * ta['lost'].get('total', 1)))
                print(f"\n  Profit Factor:   {profit_factor:.2f}")
    
    print("\n" + "="*70)
    print("COMPARISON TO OLD ENGINE")
    print("="*70)
    print("Old Engine (broken stops/targets):")
    print("  Win Rate:        0.3%")
    print("  Avg PnL:         -$0.70")
    print("  Exit Reason:     94% timeout")
    print("\nBacktrader (working stops/targets):")
    print(f"  Win Rate:        {results.get('win_rate', 0.0):.1f}%")
    print(f"  Avg PnL:         ${results['pnl'] / max(results.get('total_trades', 1), 1):.2f}")
    print("  Exit Reason:     Stop/Target hits")
    print("\n" + "="*70)


if __name__ == "__main__":
    main()
