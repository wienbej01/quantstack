"""Backtrader integration with detailed trade logging."""

import backtrader as bt
import pandas as pd
from typing import Any
from datetime import datetime


class MLStrategyDetailed(bt.Strategy):
    """Strategy with detailed trade tracking."""
    
    params = (
        ('orders_df', None),
        ('commission_per_share', 0.0035),
    )
    
    def __init__(self):
        self.orders_by_ts = {}
        self.pending_entries = {}  # Track entry details by symbol
        self.trade_log = []
        
        if self.params.orders_df is not None and not self.params.orders_df.empty:
            for _, order in self.params.orders_df.iterrows():
                ts_ns = int(order['ts'])
                dt = pd.to_datetime(ts_ns, unit='ns', utc=True)
                dt_key = dt.floor('1min')
                
                if dt_key not in self.orders_by_ts:
                    self.orders_by_ts[dt_key] = []
                self.orders_by_ts[dt_key].append(order)
    
    def next(self):
        """Execute on each bar."""
        current_dt = pd.Timestamp(self.datas[0].datetime.datetime(0))
        if current_dt.tzinfo is None:
            current_dt = current_dt.replace(tzinfo=pd.Timestamp('now', tz='UTC').tzinfo)
        
        # Force close all positions at 15:55 ET
        current_et = current_dt.tz_convert('America/New_York')
        if current_et.time() >= pd.Timestamp('15:55').time():
            for data in self.datas:
                position = self.getposition(data)
                if position.size != 0:
                    self.close(data)
            return
        
        dt_key = current_dt.floor('1min')
        
        if dt_key not in self.orders_by_ts:
            return
        
        for order_data in self.orders_by_ts[dt_key]:
            symbol = order_data['symbol']
            side = order_data['side'].lower()
            qty = int(order_data['qty'])
            
            data = self._get_data_by_symbol(symbol)
            if data is None:
                continue
            
            position = self.getposition(data)
            if position.size != 0:
                continue
            
            current_price = data.close[0]
            stop_pct = order_data.get('stop_loss_pct', 0.01)
            target_pct = order_data.get('take_profit_pct', 0.02)
            
            if side == 'long':
                stop_price = current_price * (1 - stop_pct)
                target_price = current_price * (1 + target_pct)
                
                self.buy_bracket(
                    data=data,
                    size=qty,
                    stopprice=stop_price,
                    limitprice=target_price,
                )
                
                # Store entry details
                self.pending_entries[symbol] = {
                    'side': 'LONG',
                    'entry_time': current_dt,
                    'entry_price': current_price,
                    'qty': qty,
                    'stop_price': stop_price,
                    'target_price': target_price,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                }
            else:
                stop_price = current_price * (1 + stop_pct)
                target_price = current_price * (1 - target_pct)
                
                self.sell_bracket(
                    data=data,
                    size=qty,
                    stopprice=stop_price,
                    limitprice=target_price,
                )
                
                self.pending_entries[symbol] = {
                    'side': 'SHORT',
                    'entry_time': current_dt,
                    'entry_price': current_price,
                    'qty': qty,
                    'stop_price': stop_price,
                    'target_price': target_price,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                }
    
    def _get_data_by_symbol(self, symbol: str):
        """Find data feed by symbol name."""
        for data in self.datas:
            if data._name == symbol:
                return data
        return None
    
    def notify_trade(self, trade):
        """Log completed trades."""
        if trade.isclosed:
            symbol = trade.data._name
            
            # Get entry details
            if symbol not in self.pending_entries:
                return
            
            entry = self.pending_entries[symbol]
            exit_time = self.datas[0].datetime.datetime(0)
            
            # Calculate duration
            entry_dt = entry['entry_time']
            if isinstance(entry_dt, pd.Timestamp):
                entry_dt = entry_dt.to_pydatetime()
            if hasattr(exit_time, 'tzinfo') and exit_time.tzinfo is None:
                exit_time = pd.Timestamp(exit_time, tz='UTC').to_pydatetime()
            if hasattr(entry_dt, 'tzinfo') and entry_dt.tzinfo is None:
                entry_dt = pd.Timestamp(entry_dt, tz='UTC').to_pydatetime()
            
            duration_minutes = (exit_time - entry_dt).total_seconds() / 60
            
            # Determine exit reason based on price
            exit_price = trade.price
            if entry['side'] == 'LONG':
                if exit_price <= entry['stop_price'] * 1.002:
                    exit_reason = 'STOP'
                elif exit_price >= entry['target_price'] * 0.998:
                    exit_reason = 'TARGET'
                else:
                    exit_reason = 'OTHER'
            else:  # SHORT
                if exit_price >= entry['stop_price'] * 0.998:
                    exit_reason = 'STOP'
                elif exit_price <= entry['target_price'] * 1.002:
                    exit_reason = 'TARGET'
                else:
                    exit_reason = 'OTHER'
            
            # Log trade
            self.trade_log.append({
                'symbol': symbol,
                'side': entry['side'],
                'entry_time': entry['entry_time'],
                'entry_price': entry['entry_price'],
                'stop_price': entry['stop_price'],
                'target_price': entry['target_price'],
                'stop_pct': entry['stop_pct'],
                'target_pct': entry['target_pct'],
                'exit_time': exit_time,
                'exit_price': exit_price,
                'exit_reason': exit_reason,
                'qty': entry['qty'],
                'pnl_gross': trade.pnl,
                'pnl_net': trade.pnlcomm,
                'commission': abs(trade.pnlcomm - trade.pnl),
                'duration_minutes': duration_minutes,
            })
            
            # Clear entry
            del self.pending_entries[symbol]


def run_backtest_detailed(
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    cfg: dict[str, Any],
) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run backtest with detailed trade logging."""
    
    cerebro = bt.Cerebro()
    
    initial_cash = cfg.get('initial_cash', 1_000_000.0)
    cerebro.broker.setcash(initial_cash)
    
    costs = cfg.get('costs', {})
    commission_per_share = costs.get('per_share', 0.0035)
    cerebro.broker.setcommission(
        commission=commission_per_share,
        commtype=bt.CommInfoBase.COMM_FIXED,
        percabs=True,
    )
    
    # Add data feeds
    symbols = bars['symbol'].unique()
    for symbol in symbols:
        symbol_data = bars[bars['symbol'] == symbol].copy()
        symbol_data['datetime'] = pd.to_datetime(symbol_data['ts'], unit='ns', utc=True)
        symbol_data = symbol_data.set_index('datetime')
        symbol_data = symbol_data[['open', 'high', 'low', 'close', 'volume']]
        
        data = bt.feeds.PandasData(dataname=symbol_data, name=symbol)
        cerebro.adddata(data)
    
    # Add strategy
    cerebro.addstrategy(
        MLStrategyDetailed,
        orders_df=orders,
        commission_per_share=commission_per_share,
    )
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # Run
    print(f'Starting Portfolio Value: ${cerebro.broker.getvalue():,.2f}')
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f'Final Portfolio Value: ${final_value:,.2f}')
    
    strat = results[0]
    
    # Build artifacts
    artifacts = {
        'initial_cash': initial_cash,
        'final_value': final_value,
        'pnl': final_value - initial_cash,
        'return_pct': ((final_value - initial_cash) / initial_cash) * 100,
    }
    
    if hasattr(strat.analyzers.sharpe, 'get_analysis'):
        sharpe_analysis = strat.analyzers.sharpe.get_analysis()
        artifacts['sharpe_ratio'] = sharpe_analysis.get('sharperatio', None)
    
    if hasattr(strat.analyzers.drawdown, 'get_analysis'):
        dd_analysis = strat.analyzers.drawdown.get_analysis()
        artifacts['max_drawdown'] = dd_analysis.get('max', {}).get('drawdown', 0.0)
    
    if hasattr(strat.analyzers.trades, 'get_analysis'):
        trade_analysis = strat.analyzers.trades.get_analysis()
        artifacts['trade_analysis'] = trade_analysis
        
        total_trades = trade_analysis.get('total', {}).get('total', 0)
        won_trades = trade_analysis.get('won', {}).get('total', 0)
        artifacts['total_trades'] = total_trades
        artifacts['win_rate'] = (won_trades / total_trades * 100) if total_trades > 0 else 0.0
    
    # Convert trade log to DataFrame
    trade_df = pd.DataFrame(strat.trade_log)
    
    return artifacts, trade_df
