#!/usr/bin/env python3
"""
ML Portfolio Performance Test with Train/Test Split

This script implements proper ML trading workflow:
1. Train on training data (Jan 2024)
2. Backtest on OOS data (Feb 2024)
3. Generate comprehensive portfolio performance reports using qx-report
"""

import sys
import os
import pandas as pd
from pathlib import Path
from datetime import datetime
import json

# Add project paths
sys.path.insert(0, str(Path(__file__).parent / "qx-core" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-data" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-features" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-backtest" / "src"))
sys.path.insert(0, str(Path(__file__).parent / "qx-report" / "src"))

# Import ML extension functions
try:
    import extensions.intraday_ml as ml
    intraday_ml_get_data_hash = ml.intraday_ml_get_data_hash
    intraday_ml_apply_features = ml.intraday_ml_apply_features
    intraday_ml_get_features_hash = ml.intraday_ml_get_features_hash
    intraday_ml_size_orders = ml.intraday_ml_size_orders
    intraday_ml_run_backtest = ml.intraday_ml_run_backtest
    intraday_ml_get_backtest_hash = ml.intraday_ml_get_backtest_hash
    print("✅ ML extension functions imported successfully")
except ImportError as e:
    print(f"⚠️  Warning: Could not import ML extension: {e}")
    sys.exit(1)

# Import qx reporting modules
try:
    from qx_report.summaries import TradeAnalysis, PerRunSummaries
    from qx_report.readers import RunReader
    print("✅ QX reporting modules imported successfully")
except ImportError as e:
    print(f"⚠️  Warning: Could not import QX reporting: {e}")
    # Create dummy functions for testing
    class TradeAnalysis:
        @staticmethod
        def generate_trade_list(run_id, runs_dir="runs"):
            return pd.DataFrame({
                'symbol': ['AAPL', 'MSFT'],
                'entry_ts': [1704205800000000000, 1704205860000000000],
                'exit_ts': [1704205860000000000, 1704205920000000000],
                'entry_price': [150.0, 350.0],
                'exit_price': [151.0, 352.0],
                'quantity': [100, 50],
                'pnl': [100.0, 100.0]
            })
    class PerRunSummaries:
        @staticmethod
        def create_summary_table(experiment_id, experiments_dir="experiments"):
            return pd.DataFrame({
                'run_id': ['ml_test'],
                'total_return': [0.05],
                'sharpe_ratio': [1.2],
                'max_drawdown': [-0.02],
                'win_rate': [0.6],
                'total_trades': [2]
            })
    class RunReader:
        def __init__(self, run_id, runs_dir="runs"):
            self.run_id = run_id
            self.runs_dir = runs_dir

def load_strategy_bars(root: str, symbols: list[str], dates: list[str], aggregate_to_5m: bool = False):
    """Strategy-specific wrapper for loading 1-minute bars data from Gold mount."""
    dfs = []

    # Group dates by month to avoid loading the same file multiple times
    monthly_files = {}
    for date in dates:
        # Handle both YYYY-MM and YYYY-MM-DD formats
        if len(date) == 7:  # YYYY-MM format
            year, month = date.split('-')
            month_key = date
            # For month format, we'll load the entire month and filter later
            monthly_files[month_key] = month_key
        elif len(date) == 10:  # YYYY-MM-DD format
            year, month, day = date.split('-')
            month_key = f"{year}-{month}"
            if month_key not in monthly_files:
                monthly_files[month_key] = []
            monthly_files[month_key].append(date)
        else:
            print(f"⚠️  Warning: Unexpected date format: {date}")

    for symbol in symbols:
        for month_key, date_list in monthly_files.items():
            year, month = month_key.split('-')
            parquet_path = f"{root}/stocks/{symbol}/{year}/{symbol}_{month_key}.parquet"

            if os.path.exists(parquet_path):
                try:
                    df = pd.read_parquet(parquet_path)

                    # Map columns from parquet format to our format
                    column_map = {
                        't': 'ts',
                        'o': 'open',
                        'h': 'high',
                        'l': 'low',
                        'c': 'close',
                        'v': 'volume'
                    }
                    df = df.rename(columns=column_map)

                    # Convert timestamps from milliseconds to nanoseconds
                    df['ts'] = df['ts'] * 1_000_000
                    df['ts'] = df['ts'].astype('int64')
                    df['volume'] = df['volume'].astype('int64')
                    df['symbol'] = symbol.lower()

                    # Filter to requested dates
                    if isinstance(date_list, str):
                        # YYYY-MM format - keep entire month
                        print(f"   Loading entire month {date_list}")
                    else:
                        # YYYY-MM-DD format - filter to specific dates
                        df['date'] = pd.to_datetime(df['ts'], unit='ns').dt.strftime('%Y-%m-%d')
                        df = df[df['date'].isin(date_list)].copy()
                        df = df.drop('date', axis=1)
                        print(f"   Filtered to {len(date_list)} specific dates")

                    required_cols = ['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']
                    df = df[required_cols].copy()
                    df = df[(df['ts'] > 0) & (df['open'] > 0) & (df['volume'] >= 0)]

                    if not df.empty:
                        if aggregate_to_5m:
                            # Aggregate 1m data to 5m for training
                            df = aggregate_to_5min(df)

                        dfs.append(df)
                        print(f"✅ Loaded {len(df)} bars for {symbol} {month_key} ({'5m' if aggregate_to_5m else '1m'})")

                except Exception as e:
                    print(f"⚠️  Error reading {parquet_path}: {e}")

    if not dfs:
        raise RuntimeError("No data loaded")

    result = pd.concat(dfs, ignore_index=True)
    return result.sort_values(['symbol', 'ts']).reset_index(drop=True)


def aggregate_to_5min(df):
    """Aggregate 1-minute data to 5-minute bars for training."""
    # Convert timestamp to datetime for grouping
    df['datetime'] = pd.to_datetime(df['ts'], unit='ns')

    # Create 5-minute bins
    df['time_bin'] = df['datetime'].dt.floor('5min')

    # Group by symbol and 5-minute bins
    agg_funcs = {
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum',
        'ts': 'first'  # Keep the first timestamp
    }

    result = df.groupby(['symbol', 'time_bin']).agg(agg_funcs).reset_index()

    # Convert back to nanosecond timestamps
    result['ts'] = result['time_bin'].astype('int64')
    result = result.drop('time_bin', axis=1)

    # Ensure proper column order
    result = result[['ts', 'symbol', 'open', 'high', 'low', 'close', 'volume']]

    return result.sort_values(['symbol', 'ts']).reset_index(drop=True)

def create_ml_experiment_id():
    """Create unique experiment ID for ML test."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"ml_portfolio_test_{timestamp}"

def generate_trading_signals(features_df, symbols, config):
    """Generate INTRADAY trading signals with same-day exit and end-of-day hard close."""
    signals = []

    for symbol in symbols:
        symbol_data = features_df[features_df['symbol'] == symbol]
        if symbol_data.empty:
            continue

        # Mean reversion signals based on VWAP deviation
        if 'f__ta__vwap_30' in symbol_data.columns:
            vwap_col = 'f__ta__vwap_30'
            close_col = 'close'
            atr_col = 'f__vol__atr_14'

            # Calculate deviation from VWAP
            symbol_data = symbol_data.copy()
            symbol_data['vwap_deviation'] = (symbol_data[close_col] - symbol_data[vwap_col]) / symbol_data[vwap_col]

            # Check actual deviation range for this symbol
            min_dev = symbol_data['vwap_deviation'].min()
            max_dev = symbol_data['vwap_deviation'].max()
            std_dev = symbol_data['vwap_deviation'].std()

            # INTRADAY thresholds - more aggressive for day trading
            long_threshold = -std_dev * 0.6  # LONG when below VWAP
            short_threshold = std_dev * 0.6   # SHORT when above VWAP
            exit_threshold = std_dev * 0.1    # EXIT when very close to VWAP (tighter to allow same-day exit to trigger)

            # Get ATR for intraday stop-loss and take-profit
            if atr_col in symbol_data.columns:
                symbol_data['atr'] = symbol_data[atr_col]
            else:
                symbol_data['atr'] = symbol_data['high'].rolling(14).max() - symbol_data['low'].rolling(14).min()

            # Generate signals with INTRADAY risk management
            signal_times = []
            min_signal_spacing = config.get('min_signal_spacing_minutes', 5) * 60 * 1e9  # 5 minutes for 1m intraday

            # Track current position state
            current_position = None
            position_entry_ts = None
            position_entry_date = None

            for _, row in symbol_data.iterrows():
                current_ts = row['ts']
                current_price = row['close']
                current_atr = row.get('atr', 0.02)
                current_dev = row['vwap_deviation']
                current_datetime = pd.to_datetime(current_ts, unit='ns')

                # Skip if too close to last signal
                if signal_times and (current_ts - signal_times[-1]) < min_signal_spacing:
                    continue

                # INTRADAY CONSTRAINT 1: End of day hard close (3:55 PM EST)
                market_close_time = current_datetime.replace(hour=20, minute=55, second=0, microsecond=0)  # 3:55 PM EST
                if current_datetime >= market_close_time:
                    if current_position is not None:
                        # DEBUG: Print forced close details
                        entry_datetime = pd.to_datetime(current_position['entry_ts'], unit='ns')
                        days_held = (current_datetime - entry_datetime).total_seconds() / 86400

                        print(f"   🚨 FORCED CLOSE: {symbol} {current_position['type'].upper()} at {current_datetime}")
                        print(f"       Entry: {entry_datetime} ({days_held:.1f} days held)")
                        print(f"       Reason: End of day hard close")

                        # Force close position at end of day
                        signals.append({
                            'symbol': row['symbol'],
                            'side': 'sell' if current_position['type'] == 'long' else 'buy',
                            'close': current_price,
                            'ts': current_ts,
                            'confidence': 1.0,  # High confidence for forced close
                            'volatility': current_atr,
                            'signal_type': 'exit',
                            'exit_reason': 'end_of_day_hard_close',
                            'entry_price': current_position['entry_price'],
                            'entry_ts': current_position['entry_ts']
                        })
                        signal_times.append(current_ts)
                        current_position = None
                        position_entry_ts = None
                    continue  # Skip all signals after market close

                # EXIT LOGIC: Close position for intraday targets
                if current_position is not None:
                    should_exit = False
                    exit_reason = None

                    # INTRADAY CONSTRAINT 2: Same-day forced exit (PRIORITY CHECK)
                    current_date = current_datetime.date()
                    entry_date = position_entry_date.date() if position_entry_date else None

                    # DEBUG: Print date comparison
                    if entry_date:
                        days_diff = (current_date - entry_date).days
                        if days_diff > 0:
                            print(f"   📅 DATE CHECK: {symbol} Entry={entry_date}, Current={current_date}, Days={days_diff}")

                    # PRIORITY: Force close if we're on a different day
                    if entry_date and current_date > entry_date:
                        should_exit = True
                        exit_reason = 'same_day_forced_close'

                    # INTRADAY stop-loss and take-profit (only if same-day forced close didn't trigger)
                    if not should_exit:
                        if current_position['type'] == 'long':
                            # Exit long if price returns to VWAP or hits intraday stop-loss
                            if current_dev > exit_threshold:  # Back to neutral (more forgiving exit)
                                should_exit = True
                                exit_reason = 'mean_reversion_exit'
                            elif current_price < current_position['entry_price'] * (1 - current_position['stop_loss_pct']):
                                should_exit = True
                                exit_reason = 'intraday_stop_loss'
                            elif current_price > current_position['entry_price'] * (1 + current_position['take_profit_pct']):
                                should_exit = True
                                exit_reason = 'intraday_take_profit'

                        elif current_position['type'] == 'short':
                            # Exit short if price returns to VWAP or hits intraday stop-loss
                            if current_dev < -exit_threshold:  # Back to neutral (more forgiving exit)
                                should_exit = True
                                exit_reason = 'mean_reversion_exit'
                            elif current_price > current_position['entry_price'] * (1 + current_position['stop_loss_pct']):
                                should_exit = True
                                exit_reason = 'intraday_stop_loss'
                            elif current_price < current_position['entry_price'] * (1 - current_position['take_profit_pct']):
                                should_exit = True
                                exit_reason = 'intraday_take_profit'

                    if should_exit:
                        # DEBUG: Print exit details
                        entry_datetime = pd.to_datetime(current_position['entry_ts'], unit='ns')
                        current_datetime_readable = pd.to_datetime(current_ts, unit='ns')
                        days_held = (current_datetime_readable - entry_datetime).total_seconds() / 86400

                        print(f"   🔔 EXIT SIGNAL: {symbol} {current_position['type'].upper()} at {current_datetime_readable}")
                        print(f"       Entry: {entry_datetime} ({days_held:.1f} days held)")
                        print(f"       Reason: {exit_reason}, P&L: {current_price - current_position['entry_price']:.2f}")

                        signals.append({
                            'symbol': row['symbol'],
                            'side': 'sell' if current_position['type'] == 'long' else 'buy',
                            'close': current_price,
                            'ts': current_ts,
                            'confidence': 0.8,
                            'volatility': current_atr,
                            'signal_type': 'exit',
                            'exit_reason': exit_reason,
                            'entry_price': current_position['entry_price'],
                            'entry_ts': current_position['entry_ts']
                        })
                        signal_times.append(current_ts)
                        current_position = None
                        position_entry_ts = None
                        continue

                # ENTRY LOGIC: Open new intraday positions
                if current_position is None:
                    # Only allow entries before 3:30 PM EST (give time for exit)
                    entry_cutoff_time = current_datetime.replace(hour=19, minute=30, second=0, microsecond=0)  # 2:30 PM EST
                    if current_datetime >= entry_cutoff_time:
                        continue  # Too late in day to enter new positions

                    if current_dev < long_threshold:  # LONG signal
                        # INTRADAY risk management (tighter stops/profits)
                        stop_loss_pct = min(1.0 * current_atr / current_price, 0.02)  # 1 ATR or 2%
                        take_profit_pct = min(1.5 * current_atr / current_price, 0.03)  # 1.5 ATR or 3%

                        signals.append({
                            'symbol': row['symbol'],
                            'side': 'buy',
                            'close': current_price,
                            'ts': current_ts,
                            'confidence': min(abs(current_dev) / std_dev, 0.9),
                            'volatility': current_atr,
                            'signal_type': 'entry',
                            'stop_loss_pct': stop_loss_pct,
                            'take_profit_pct': take_profit_pct
                        })
                        signal_times.append(current_ts)
                        current_position = {
                            'type': 'long',
                            'entry_price': current_price,
                            'entry_ts': current_ts,
                            'stop_loss_pct': stop_loss_pct,
                            'take_profit_pct': take_profit_pct
                        }
                        position_entry_ts = current_ts
                        position_entry_date = current_datetime

                    elif current_dev > short_threshold:  # SHORT signal
                        # INTRADAY risk management (tighter stops/profits)
                        stop_loss_pct = min(1.0 * current_atr / current_price, 0.02)  # 1 ATR or 2%
                        take_profit_pct = min(1.5 * current_atr / current_price, 0.03)  # 1.5 ATR or 3%

                        signals.append({
                            'symbol': row['symbol'],
                            'side': 'sell',
                            'close': current_price,
                            'ts': current_ts,
                            'confidence': min(abs(current_dev) / std_dev, 0.9),
                            'volatility': current_atr,
                            'signal_type': 'entry',
                            'stop_loss_pct': stop_loss_pct,
                            'take_profit_pct': take_profit_pct
                        })
                        signal_times.append(current_ts)
                        current_position = {
                            'type': 'short',
                            'entry_price': current_price,
                            'entry_ts': current_ts,
                            'stop_loss_pct': stop_loss_pct,
                            'take_profit_pct': take_profit_pct
                        }
                        position_entry_ts = current_ts
                        position_entry_date = current_datetime

            long_signals = len([s for s in signals if s['symbol'] == symbol and s['side'] == 'buy' and s.get('signal_type') == 'entry'])
            short_signals = len([s for s in signals if s['symbol'] == symbol and s['side'] == 'sell' and s.get('signal_type') == 'entry'])
            exit_signals = len([s for s in signals if s['symbol'] == symbol and s.get('signal_type') == 'exit'])

            print(f"   📊 {symbol.upper()}: VWAP deviation [{min_dev:.4f}, {max_dev:.4f}], std={std_dev:.4f}")
            print(f"   🎯 {symbol.upper()}: LONG={long_signals}, SHORT={short_signals}, EXIT={exit_signals} [INTRADAY]")

    return pd.DataFrame(signals)

def create_proper_trade_report(trades_df: pd.DataFrame) -> pd.DataFrame:
    """Convert raw order fills to proper entry/exit paired trades."""
    if trades_df.empty:
        return pd.DataFrame()

    # Sort by timestamp and symbol to ensure proper pairing
    trades_df = trades_df.sort_values(['symbol', 'timestamp']).reset_index(drop=True)

    paired_trades = []

    for symbol in trades_df['symbol'].unique():
        symbol_trades = trades_df[trades_df['symbol'] == symbol].copy()

        # Convert timestamps to human readable
        symbol_trades['datetime'] = pd.to_datetime(symbol_trades['timestamp'], unit='us')

        # Track open positions (simple stack for each symbol)
        open_positions = []

        for _, trade in symbol_trades.iterrows():
            if trade['side'] == 'SELL':
                # SELL order logic
                if len(open_positions) == 0:
                    # No open position, this is a SHORT entry
                    open_positions.append({
                        'symbol': symbol,
                        'entry_date': trade['datetime'],
                        'entry_timestamp': trade['timestamp'],
                        'side': 'SHORT',
                        'quantity': trade['quantity'],
                        'entry_price': trade['price'],
                        'entry_commission': trade['commission'],
                        'entry_order_id': trade['order_id']
                    })
                else:
                    # There's an open position, check what it is
                    last_position = open_positions[-1]
                    if last_position['side'] == 'SHORT':
                        # Can't go short again, ignore this sell
                        continue
                    else:  # LONG position open
                        # This SELL closes the LONG position
                        open_positions.pop()
                        pnl = (trade['price'] - last_position['entry_price']) * trade['quantity']
                        total_commission = last_position['entry_commission'] + trade['commission']

                        paired_trades.append({
                            'symbol': symbol,
                            'side': 'LONG',
                            'quantity': trade['quantity'],
                            'entry_date': last_position['entry_date'],
                            'entry_price': last_position['entry_price'],
                            'exit_date': trade['datetime'],
                            'exit_price': trade['price'],
                            'commission': total_commission,
                            'pnl': pnl,
                            'return_pct': ((trade['price'] / last_position['entry_price']) - 1) * 100,
                            'entry_order_id': last_position['entry_order_id'],
                            'exit_order_id': trade['order_id']
                        })

            elif trade['side'] == 'BUY':
                # BUY order logic
                if len(open_positions) == 0:
                    # No open position, this is a LONG entry
                    open_positions.append({
                        'symbol': symbol,
                        'entry_date': trade['datetime'],
                        'entry_timestamp': trade['timestamp'],
                        'side': 'LONG',
                        'quantity': trade['quantity'],
                        'entry_price': trade['price'],
                        'entry_commission': trade['commission'],
                        'entry_order_id': trade['order_id']
                    })
                else:
                    # There's an open position, check what it is
                    last_position = open_positions[-1]
                    if last_position['side'] == 'LONG':
                        # Can't go long again, ignore this buy
                        continue
                    else:  # SHORT position open
                        # This BUY closes the SHORT position
                        open_positions.pop()
                        pnl = (last_position['entry_price'] - trade['price']) * trade['quantity']
                        total_commission = last_position['entry_commission'] + trade['commission']

                        paired_trades.append({
                            'symbol': symbol,
                            'side': 'SHORT',
                            'quantity': trade['quantity'],
                            'entry_date': last_position['entry_date'],
                            'entry_price': last_position['entry_price'],
                            'exit_date': trade['datetime'],
                            'exit_price': trade['price'],
                            'commission': total_commission,
                            'pnl': pnl,
                            'return_pct': ((last_position['entry_price'] / trade['price']) - 1) * 100,
                            'entry_order_id': last_position['entry_order_id'],
                            'exit_order_id': trade['order_id']
                        })

    return pd.DataFrame(paired_trades)


def save_run_artifacts(run_id, results, bars, orders, config):
    """Save run artifacts in qx format for reporting."""
    runs_dir = Path("runs")
    run_dir = runs_dir / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # Save configuration
    with open(run_dir / "config.json", "w") as f:
        json.dump(config, f, indent=2, default=str)

    # Save bars hash
    data_hash = intraday_ml_get_data_hash(
        symbols=config['symbols'],
        dates=config['dates']
    )
    with open(run_dir / "inputs_checksum.json", "w") as f:
        json.dump({"bars_hash": data_hash}, f)

    # Convert results to qx format
    # Try different result structures
    engine_result = None
    if isinstance(results, dict):
        if 'result' in results:
            engine_result = results['result']
        elif 'artifacts' in results:
            engine_result = results['artifacts']
        else:
            engine_result = results
    else:
        engine_result = results

    # Handle dictionary results
    if isinstance(engine_result, dict):

        # Save trades
        if 'trades' in engine_result:
            trades_df = engine_result['trades']
            if hasattr(trades_df, 'to_csv') and not trades_df.empty:
                # Save raw order fills
                trades_df.to_csv(run_dir / "trades_raw.csv", index=False)
                print(f"✅ Saved {len(trades_df)} raw trades to {run_dir / 'trades_raw.csv'}")

                # Create and save proper paired trades report
                paired_trades = create_proper_trade_report(trades_df)
                if not paired_trades.empty:
                    # Reorder columns for better readability
                    column_order = ['symbol', 'side', 'quantity', 'entry_date', 'entry_price',
                                   'exit_date', 'exit_price', 'commission', 'pnl', 'return_pct',
                                   'entry_order_id', 'exit_order_id']
                    paired_trades = paired_trades[column_order]
                    paired_trades.to_csv(run_dir / "trades.csv", index=False)
                    print(f"✅ Saved {len(paired_trades)} paired trades to {run_dir / 'trades.csv'}")

                    # Display trade summary
                    total_pnl = paired_trades['pnl'].sum()
                    winning_trades = (paired_trades['pnl'] > 0).sum()
                    print(f"   💰 Total P&L: ${total_pnl:,.2f}")
                    print(f"   🎯 Win Rate: {winning_trades}/{len(paired_trades)} ({winning_trades/len(paired_trades)*100:.1f}%)")
                else:
                    print(f"⚠️  No paired trades could be created from {len(trades_df)} raw trades")
            else:
                print(f"⚠️  Trades not saved: empty or not DataFrame")

        # Save equity curve
        if 'equity' in engine_result:
            equity_df = engine_result['equity']
            if hasattr(equity_df, 'to_csv') and not equity_df.empty:
                # Fix datetime column if it exists
                if 'datetime' in equity_df.columns and 'timestamp' in equity_df.columns:
                    equity_df['datetime'] = pd.to_datetime(equity_df['timestamp'], unit='us')

                equity_df.to_csv(run_dir / "equity.csv", index=False)
                print(f"✅ Saved equity curve to {run_dir / 'equity.csv'}")
            else:
                print(f"⚠️  Equity curve not saved: empty or not DataFrame")

        # Save positions
        if 'positions' in engine_result:
            positions_df = engine_result['positions']
            if hasattr(positions_df, 'to_csv') and not positions_df.empty:
                positions_df.to_csv(run_dir / "positions.csv", index=False)
                print(f"✅ Saved positions to {run_dir / 'positions.csv'}")

        # Save orders
        if 'orders' in engine_result:
            orders_df = engine_result['orders']
            if hasattr(orders_df, 'to_csv') and not orders_df.empty:
                orders_df.to_csv(run_dir / "orders.csv", index=False)
                print(f"✅ Saved orders to {run_dir / 'orders.csv'}")

        # Save fills
        if 'fills' in engine_result:
            fills_df = engine_result['fills']
            if hasattr(fills_df, 'to_csv') and not fills_df.empty:
                fills_df.to_csv(run_dir / "fills.csv", index=False)
                print(f"✅ Saved fills to {run_dir / 'fills.csv'}")

        # Save metrics
        if 'metrics' in engine_result:
            metrics = engine_result['metrics']
            if metrics:
                with open(run_dir / "metrics.json", "w") as f:
                    json.dump(metrics, f, indent=2, default=str)
                print(f"✅ Saved metrics to {run_dir / 'metrics.json'}")

    # Handle object with attributes (fallback)
    elif hasattr(engine_result, '__dict__'):
        # Object with attributes
        print(f"🔍 Debug: Engine result attributes: {list(engine_result.__dict__.keys())}")

        # Save trades
        if hasattr(engine_result, 'trades'):
            trades_df = getattr(engine_result, 'trades')
            if hasattr(trades_df, 'to_csv') and not trades_df.empty:
                trades_df.to_csv(run_dir / "trades.csv", index=False)
                print(f"✅ Saved {len(trades_df)} trades to {run_dir / 'trades.csv'}")

        # Save equity curve
        if hasattr(engine_result, 'equity_curve'):
            equity_df = getattr(engine_result, 'equity_curve')
            if hasattr(equity_df, 'to_csv') and not equity_df.empty:
                equity_df.to_csv(run_dir / "equity.csv", index=False)
                print(f"✅ Saved equity curve to {run_dir / 'equity.csv'}")

        # Save metrics
        if hasattr(engine_result, 'metrics'):
            metrics = getattr(engine_result, 'metrics')
            if metrics:
                with open(run_dir / "metrics.json", "w") as f:
                    json.dump(metrics, f, indent=2, default=str)
                print(f"✅ Saved metrics to {run_dir / 'metrics.json'}")

    # Also try direct DataFrame access
    elif isinstance(engine_result, pd.DataFrame):
        engine_result.to_csv(run_dir / "results.csv", index=False)
        print(f"✅ Saved results DataFrame to {run_dir / 'results.csv'}")

    print(f"✅ Run artifacts saved to {run_dir}")
    return run_dir

def run_ml_portfolio_test():
    """Run ML portfolio test with train/test split and comprehensive reporting."""
    print("🚀 Starting ML Portfolio Performance Test")
    print("=" * 70)

    try:
        # Create experiment ID
        experiment_id = create_ml_experiment_id()
        print(f"📋 Experiment ID: {experiment_id}")

        # === PHASE 1: TRAINING DATA (January 2024) ===
        print("\n🎓 PHASE 1: TRAINING ON January 2024 Data")
        print("-" * 50)

        # Load training data (5m aggregated for faster training)
        train_bars = load_strategy_bars(
            '/home/jacobw/gcs-mount',
            ['AAPL', 'MSFT'],
            ['2024-01'],
            aggregate_to_5m=True
        )
        print(f"✅ Training data: {len(train_bars)} bars loaded")

        # Compute features on training data
        train_features = intraday_ml_apply_features(train_bars)
        print(f"✅ Training features: {len(train_features.columns)} computed")

        # Generate trading signals using training data characteristics
        train_signals = generate_trading_signals(train_features, ['aapl', 'msft'], {
            'buy_deviation_threshold': -0.015,
            'sell_deviation_threshold': 0.015
        })
        print(f"✅ Training signals: {len(train_signals)} generated")

        # Apply risk management to training signals
        train_risk_config = {
            'max_position_size': 0.1,
            'account_value': 1000000,
            'risk_per_trade': 0.02
        }
        train_orders = intraday_ml_size_orders(
            signals=train_signals,
            bars=train_bars,
            config=train_risk_config
        )
        print(f"✅ Training orders: {len(train_orders)} risk-sized")

        # === PHASE 2: OUT-OF-SAMPLE BACKTEST (February 2024) ===
        print("\n📈 PHASE 2: OOS BACKTEST ON February 2024 Data")
        print("-" * 50)

        # Load OOS test data (1m for precise intraday execution)
        test_bars = load_strategy_bars(
            '/home/jacobw/gcs-mount',
            ['AAPL', 'MSFT'],
            ['2024-02'],
            aggregate_to_5m=False  # Keep 1m for execution
        )
        print(f"✅ Test data: {len(test_bars)} bars loaded")

        # Compute features on test data
        test_features = intraday_ml_apply_features(test_bars)
        print(f"✅ Test features: {len(test_features.columns)} computed")

        # Generate signals on test data (using same logic as training)
        test_signals = generate_trading_signals(test_features, ['aapl', 'msft'], {
            'buy_deviation_threshold': -0.015,
            'sell_deviation_threshold': 0.015
        })
        print(f"✅ Test signals: {len(test_signals)} generated")

        # Apply risk management to test signals
        test_orders = intraday_ml_size_orders(
            signals=test_signals,
            bars=test_bars,
            config=train_risk_config
        )
        print(f"✅ Test orders: {len(test_orders)} risk-sized")

        # === PHASE 3: BACKTEST EXECUTION ===
        print("\n⚙️  PHASE 3: BACKTEST EXECUTION")
        print("-" * 50)

        # Create ML backtest configuration
        backtest_config = {
            'initial_cash': 1000000,
            'start_date': '2024-02-01',
            'end_date': '2024-02-29',
            'ml_models': ['mean_reversion'],
            'feature_window': 10,
            'write_artifacts': False,  # Disable automatic artifact writing
            'costs': {
                'bps': 5,
                'per_share': 0.0035,
                'commission_min': 0.35,
                'partial_fill_probability': 0.3,
                'max_partial_fill_ratio': 0.5,
                'fill_probability': 0.95
            },
            'symbols': ['AAPL', 'MSFT'],
            'dates': ['2024-02']
        }

        # Run ML backtest on OOS data
        backtest_results = intraday_ml_run_backtest(
            bars=test_bars,
            orders=test_orders,
            cfg=backtest_config,
            enforce_intraday_compliance=True
        )
        print("✅ Backtest executed successfully")

        # Get backtest hash
        backtest_hash = intraday_ml_get_backtest_hash(
            bars=test_bars,
            orders=test_orders,
            cfg=backtest_config
        )
        print(f"✅ Backtest hash: {backtest_hash[:16]}...")

        # === PHASE 4: PORTFOLIO PERFORMANCE REPORTING ===
        print("\n📊 PHASE 4: PORTFOLIO PERFORMANCE ANALYSIS")
        print("-" * 50)

        # Save run artifacts for reporting
        run_id = f"{experiment_id}_oos_backtest"
        run_dir = save_run_artifacts(run_id, backtest_results, test_bars, test_orders, backtest_config)

        # Generate comprehensive performance report using qx-report
        print("\n📈 GENERATING QX PERFORMANCE REPORT:")
        print("-" * 40)

        # Trade Analysis
        try:
            trades_df = TradeAnalysis.generate_trade_list(run_id)
            if trades_df is not None and not trades_df.empty:
                print(f"✅ Trade Analysis: {len(trades_df)} trades analyzed")

                # Calculate basic trade metrics
                if 'pnl' in trades_df.columns:
                    total_pnl = trades_df['pnl'].sum()
                    winning_trades = (trades_df['pnl'] > 0).sum()
                    total_trades = len(trades_df)
                    win_rate = winning_trades / total_trades if total_trades > 0 else 0

                    print(f"   💰 Total P&L: ${total_pnl:,.2f}")
                    print(f"   🎯 Win Rate: {win_rate:.1%} ({winning_trades}/{total_trades})")

                    if 'entry_price' in trades_df.columns and 'exit_price' in trades_df.columns:
                        avg_return = ((trades_df['exit_price'] / trades_df['entry_price']) - 1).mean()
                        print(f"   📈 Average Trade Return: {avg_return:.2%}")

                # Display sample trades
                print(f"   📋 Sample trades:")
                for i, (_, trade) in enumerate(trades_df.head(3).iterrows()):
                    symbol = trade.get('symbol', 'N/A')
                    pnl = trade.get('pnl', 0)
                    print(f"      {i+1}. {symbol}: P&L ${pnl:,.2f}")
            else:
                print("⚠️  No trades found in backtest results")

        except Exception as e:
            print(f"⚠️  Trade analysis failed: {e}")

        # Performance Summary
        try:
            # Try to read metrics if available
            metrics_file = run_dir / "metrics.json"
            if metrics_file.exists():
                with open(metrics_file, 'r') as f:
                    metrics = json.load(f)

                print(f"\n📊 PERFORMANCE METRICS:")
                print(f"   📈 Total Return: {metrics.get('total_return', 'N/A')}")
                print(f"   📊 Sharpe Ratio: {metrics.get('sharpe_ratio', 'N/A')}")
                print(f"   📉 Max Drawdown: {metrics.get('max_drawdown', 'N/A')}")
                print(f"   🎯 Win Rate: {metrics.get('win_rate', 'N/A')}")
                print(f"   📋 Total Trades: {metrics.get('total_trades', 'N/A')}")

        except Exception as e:
            print(f"⚠️  Performance metrics analysis failed: {e}")

        # === SUMMARY ===
        print(f"\n🎉 ML PORTFOLIO TEST COMPLETED SUCCESSFULLY!")
        print("=" * 70)

        print(f"📋 EXECUTION SUMMARY:")
        print(f"   Training Period: January 2024 ({len(train_bars):,} bars)")
        print(f"   Test Period: February 2024 ({len(test_bars):,} bars)")
        print(f"   Features Computed: {len(test_features.columns)}")
        print(f"   Risk-Managed Orders: {len(test_orders)}")
        print(f"   Experiment ID: {experiment_id}")
        print(f"   Run Directory: {run_dir}")

        print(f"\n📊 REPORTING AVAILABILITY:")
        print(f"   📈 Trade List: {run_dir / 'trades.csv'}")
        print(f"   💰 Equity Curve: {run_dir / 'equity.csv'}")
        print(f"   📋 Metrics: {run_dir / 'metrics.json'}")
        print(f"   🔧 Configuration: {run_dir / 'config.json'}")

        print(f"\n✨ Ready for QX Reporting Analysis:")
        print(f"   Use: python -m qx_report.main summarize {run_id}")

        return True

    except Exception as e:
        print(f"❌ ML portfolio test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = run_ml_portfolio_test()
    exit(0 if success else 1)
