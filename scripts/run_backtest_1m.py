"""Run backtest on 1-minute execution data with 10m decision signals."""

import sys
from pathlib import Path
import pandas as pd

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from extensions.intraday_ml.backtest_bt_detailed import run_backtest_detailed


def load_1m_bars(symbols, start_date, end_date):
    """Load 1-minute bars from gold data."""
    gold_path = Path.home() / 'gcs-mount/gold/stocks/1m'
    
    all_bars = []
    for symbol in symbols:
        symbol_upper = symbol.upper()
        
        # Load May 2024
        may_path = gold_path / symbol_upper / '2024' / '2024-05.parquet'
        if may_path.exists():
            df = pd.read_parquet(may_path)
            df['symbol'] = symbol.lower()
            
            # Filter to date range
            df['date'] = pd.to_datetime(df['ts']).dt.date
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            # Select OHLCV columns
            df = df[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']].copy()
            
            # Convert ts to nanoseconds if needed
            if df['ts'].dtype == 'datetime64[ns]':
                df['ts'] = df['ts'].astype('int64')
            
            all_bars.append(df)
            print(f"  {symbol}: {len(df):,} bars")
    
    if not all_bars:
        raise ValueError("No 1-minute data loaded")
    
    return pd.concat(all_bars, ignore_index=True)


def main():
    """Run backtest on May 2024 with 1-minute execution."""
    
    artifacts_dir = project_root / "artefacts/extensions/intraday_ml/phaseA_full_sip"
    
    print("="*80)
    print("MAY 2024 BACKTEST - 1-MINUTE EXECUTION DATA")
    print("="*80)
    
    # Load orders (10m decisions)
    print("\nLoading orders...")
    orders = pd.read_parquet(artifacts_dir / "oos_orders.parquet")
    symbols = sorted(orders['symbol'].unique())
    
    print(f"Orders: {len(orders)}")
    print(f"Symbols: {len(symbols)} - {', '.join(symbols[:10])}...")
    
    # Load 1-minute bars
    print("\nLoading 1-minute bars from gold data...")
    import datetime
    start_date = datetime.date(2024, 5, 1)
    end_date = datetime.date(2024, 5, 31)
    
    bars_1m = load_1m_bars(symbols, start_date, end_date)
    
    print(f"\nTotal 1m bars: {len(bars_1m):,}")
    print(f"Date range: {pd.to_datetime(bars_1m['ts'], unit='ns').min()} to {pd.to_datetime(bars_1m['ts'], unit='ns').max()}")
    
    # Configuration
    config = {
        'initial_cash': 1_000_000.0,
        'costs': {
            'per_share': 0.0035,
            'commission_min': 0.35,
            'bps': 5,
        }
    }
    
    print("\n" + "="*80)
    print("RUNNING BACKTEST WITH 1-MINUTE BARS")
    print("="*80 + "\n")
    
    # Run backtest
    results, trades_df = run_backtest_detailed(bars_1m, orders, config)
    
    # Save
    output_path = project_root / "artefacts/extensions/intraday_ml/trade_report_may2024_1m.csv"
    trades_df.to_csv(output_path, index=False)
    print(f"\nTrade report saved to: {output_path}")
    
    # Analysis
    print("\n" + "="*80)
    print("RESULTS")
    print("="*80)
    print(f"\nInitial Cash:    ${results['initial_cash']:,.2f}")
    print(f"Final Value:     ${results['final_value']:,.2f}")
    print(f"Total PnL:       ${results['pnl']:,.2f}")
    print(f"Return:          {results['return_pct']:.2f}%")
    print(f"Total Trades:    {results.get('total_trades', 0)}")
    print(f"Win Rate:        {results.get('win_rate', 0.0):.1f}%")
    
    if not trades_df.empty:
        print("\n--- Exit Reasons ---")
        for reason in sorted(trades_df['exit_reason'].unique()):
            count = (trades_df['exit_reason'] == reason).sum()
            pct = count / len(trades_df) * 100
            print(f"{reason:10} {count:4} ({pct:5.1f}%)")
        
        print("\n--- Duration ---")
        print(f"Max:    {trades_df['duration_minutes'].max():.0f} minutes")
        print(f"Mean:   {trades_df['duration_minutes'].mean():.0f} minutes")
        print(f"Median: {trades_df['duration_minutes'].median():.0f} minutes")
        
        print("\n--- Stop/Target Distances ---")
        trades_df['stop_dist'] = abs(trades_df['entry_price'] - trades_df['stop_price'])
        trades_df['target_dist'] = abs(trades_df['entry_price'] - trades_df['target_price'])
        trades_df['actual_move'] = abs(trades_df['exit_price'] - trades_df['entry_price'])
        
        print(f"Stop distance:   ${trades_df['stop_dist'].mean():.3f} (median: ${trades_df['stop_dist'].median():.3f})")
        print(f"Target distance: ${trades_df['target_dist'].mean():.3f} (median: ${trades_df['target_dist'].median():.3f})")
        print(f"Actual move:     ${trades_df['actual_move'].mean():.3f} (median: ${trades_df['actual_move'].median():.3f})")
        
        print("\n--- Transaction Costs ---")
        print(f"Total commission: ${trades_df['commission'].sum():.2f}")
        print(f"Avg commission:   ${trades_df['commission'].mean():.2f}")
        print(f"Commission vs move: {(trades_df['commission'].mean() / trades_df['actual_move'].mean() * 100):.0f}%")
        
        print("\n--- Validation ---")
        print(f"Max duration < 400m (EOD working): {'PASS' if trades_df['duration_minutes'].max() < 400 else 'FAIL'}")
        print(f"Target hits > 10%: {'PASS' if (trades_df['exit_reason'] == 'TARGET').sum() / len(trades_df) > 0.1 else 'FAIL'}")
        print(f"Win rate > 40%: {'PASS' if results.get('win_rate', 0) > 40 else 'FAIL'}")


if __name__ == "__main__":
    main()
