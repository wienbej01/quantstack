"""Test OHLC-based stop/target monitoring."""

import sys
from pathlib import Path
import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from extensions.intraday_ml.backtest_bt_ohlc import run_backtest_ohlc


def main():
    """Test with first 5 days of May 2024."""
    
    artifacts_dir = project_root / "artefacts/extensions/intraday_ml/phaseA_full_sip"
    
    print("="*80)
    print("TESTING OHLC STOP/TARGET MONITORING")
    print("="*80)
    
    # Load data
    features = pd.read_parquet(artifacts_dir / "oos_features.parquet")
    bars = features[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']].copy()
    
    # Filter to first 5 days
    bars['date'] = pd.to_datetime(bars['ts']).dt.date
    unique_dates = sorted(bars['date'].unique())
    test_dates = unique_dates[:5]
    bars = bars[bars['date'].isin(test_dates)].drop(columns=['date'])
    
    orders = pd.read_parquet(artifacts_dir / "oos_orders.parquet")
    orders['date'] = pd.to_datetime(orders['ts'], unit='ns').dt.date
    orders = orders[orders['date'].isin(test_dates)].drop(columns=['date'])
    
    print(f"\nTest period: {test_dates[0]} to {test_dates[-1]}")
    print(f"Bars: {len(bars):,}")
    print(f"Orders: {len(orders)}")
    
    config = {
        'initial_cash': 1_000_000.0,
        'costs': {'per_share': 0.0035},
        'eod_close_time': '15:55',
    }
    
    print("\n" + "="*80)
    print("RUNNING BACKTEST")
    print("="*80 + "\n")
    
    results, trades_df = run_backtest_ohlc(bars, orders, config)
    
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    print(f"\nTotal PnL:       ${results['pnl']:,.2f}")
    print(f"Total Trades:    {results.get('total_trades', 0)}")
    print(f"Win Rate:        {results.get('win_rate', 0.0):.1f}%")
    
    if not trades_df.empty:
        print("\n--- Exit Reasons ---")
        print(trades_df['exit_reason'].value_counts())
        
        print("\n--- Duration ---")
        print(f"Max: {trades_df['duration_minutes'].max():.0f}m")
        print(f"Mean: {trades_df['duration_minutes'].mean():.0f}m")
        print(f"Median: {trades_df['duration_minutes'].median():.0f}m")
        
        print("\n--- Price Movement ---")
        trades_df['price_diff'] = abs(trades_df['exit_price'] - trades_df['entry_price'])
        print(f"Mean move: ${trades_df['price_diff'].mean():.3f}")
        print(f"Median move: ${trades_df['price_diff'].median():.3f}")
        print(f"Zero moves: {(trades_df['price_diff'] == 0).sum()}")
        
        print("\n--- Sample Trades ---")
        print(trades_df[['symbol', 'side', 'entry_price', 'exit_price', 'exit_reason', 'pnl_net', 'duration_minutes']].head(10))


if __name__ == "__main__":
    main()
