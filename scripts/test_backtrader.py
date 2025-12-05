"""Test Backtrader integration with ML orders."""

import sys
from pathlib import Path

import pandas as pd

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from extensions.intraday_ml.backtest_bt import run_backtest_bt


def main():
    """Run simple test with Backtrader."""
    
    # Load existing data
    artifacts_dir = project_root / "artefacts/extensions/intraday_ml/phaseA_multi"
    
    # Load features to extract OHLCV bars
    features_path = artifacts_dir / "oos_features.parquet"
    if not features_path.exists():
        print(f"ERROR: Features file not found at {features_path}")
        return
    
    features = pd.read_parquet(features_path)
    print(f"Loaded {len(features):,} feature rows")
    
    # Extract OHLCV columns
    bars = features[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']].copy()
    print(f"Extracted {len(bars):,} bars")
    
    # Load orders (use oos_orders which has ML signals)
    orders_path = artifacts_dir / "oos_orders.parquet"
    if not orders_path.exists():
        print(f"ERROR: Orders file not found at {orders_path}")
        return
    
    orders = pd.read_parquet(orders_path)
    print(f"Loaded {len(orders):,} orders")
    
    # Ensure required columns exist
    if 'stop_loss_pct' not in orders.columns:
        orders['stop_loss_pct'] = 0.01  # Default 1%
    if 'take_profit_pct' not in orders.columns:
        orders['take_profit_pct'] = 0.02  # Default 2%
    
    # Filter to first 5 days for quick test
    if not bars.empty:
        bars['date'] = pd.to_datetime(bars['ts'], unit='ns').dt.date
        unique_dates = sorted(bars['date'].unique())
        test_dates = unique_dates[:5]
        bars = bars[bars['date'].isin(test_dates)].copy()
        bars = bars.drop(columns=['date'])
        print(f"Testing with {len(test_dates)} days: {test_dates[0]} to {test_dates[-1]}")
    
    # Filter orders to match
    if not orders.empty:
        orders['date'] = pd.to_datetime(orders['ts'], unit='ns').dt.date
        orders = orders[orders['date'].isin(test_dates)].copy()
        orders = orders.drop(columns=['date'])
        print(f"Testing with {len(orders)} orders")
    
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
    print("\n" + "="*60)
    print("RUNNING BACKTRADER BACKTEST")
    print("="*60 + "\n")
    
    results = run_backtest_bt(bars, orders, config)
    
    # Print results
    print("\n" + "="*60)
    print("RESULTS")
    print("="*60)
    print(f"Initial Cash:    ${results['initial_cash']:,.2f}")
    print(f"Final Value:     ${results['final_value']:,.2f}")
    print(f"PnL:             ${results['pnl']:,.2f}")
    print(f"Return:          {results['return_pct']:.2f}%")
    
    sharpe = results.get('sharpe_ratio')
    sharpe_str = f"{sharpe:.2f}" if sharpe is not None else "N/A"
    print(f"Sharpe Ratio:    {sharpe_str}")
    
    dd = results.get('max_drawdown')
    dd_str = f"{dd:.2f}%" if dd is not None else "N/A"
    print(f"Max Drawdown:    {dd_str}")
    
    print(f"Total Trades:    {results.get('total_trades', 0)}")
    print(f"Win Rate:        {results.get('win_rate', 0.0):.1f}%")
    
    if 'trade_analysis' in results:
        ta = results['trade_analysis']
        print("\nTrade Analysis:")
        if 'won' in ta:
            print(f"  Won:  {ta['won'].get('total', 0)} trades, "
                  f"Avg: ${ta['won'].get('pnl', {}).get('average', 0):.2f}")
        if 'lost' in ta:
            print(f"  Lost: {ta['lost'].get('total', 0)} trades, "
                  f"Avg: ${ta['lost'].get('pnl', {}).get('average', 0):.2f}")


if __name__ == "__main__":
    main()
