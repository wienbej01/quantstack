"""Backtrader strategy for 1-minute execution with proper EOD close."""

from datetime import time
from typing import Any

import backtrader as bt
import pandas as pd


class MLStrategy1m(bt.Strategy):
    """Strategy for 1-minute bars with EOD close."""
    
    params = (
        ('orders_df', None),
        ('commission_per_share', 0.0035),
    )
    
    def __init__(self):
        self.orders_by_ts = {}
        self.active_positions = {}
        self.trade_log = []
        self.eod_time = time(15, 55)  # 15:55 ET
        
        if self.params.orders_df is not None and not self.params.orders_df.empty:
            for _, order in self.params.orders_df.iterrows():
                ts_ns = int(order['ts'])
                dt = pd.to_datetime(ts_ns, unit='ns', utc=True)
                dt_key = dt.floor('1min')
                
                if dt_key not in self.orders_by_ts:
                    self.orders_by_ts[dt_key] = []
                self.orders_by_ts[dt_key].append(order)
    
    def next(self):
        """Execute on each 1-minute bar."""
        # Get current time in ET
        current_dt_utc = pd.Timestamp(self.datas[0].datetime.datetime(0), tz='UTC')
        current_dt_et = current_dt_utc.tz_convert('America/New_York')
        current_time_et = current_dt_et.time()
        
        # Force close all positions at EOD
        if current_time_et >= self.eod_time:
            for symbol in list(self.active_positions.keys()):
                data = self._get_data_by_symbol(symbol)
                if data and self.getposition(data).size != 0:
                    self.close(data)
                    self.active_positions[symbol]['exit_reason'] = 'EOD'
            return
        
        # Check existing positions for stop/target
        for symbol in list(self.active_positions.keys()):
            pos_info = self.active_positions[symbol]
            data = self._get_data_by_symbol(symbol)
            
            if not data:
                continue
            
            position = self.getposition(data)
            if position.size == 0:
                del self.active_positions[symbol]
                continue
            
            current_price = data.close[0]
            
            if pos_info['side'] == 'LONG':
                if current_price <= pos_info['stop_price']:
                    self.close(data)
                    pos_info['exit_reason'] = 'STOP'
                elif current_price >= pos_info['target_price']:
                    self.close(data)
                    pos_info['exit_reason'] = 'TARGET'
            elif current_price >= pos_info['stop_price']:
                self.close(data)
                pos_info['exit_reason'] = 'STOP'
            elif current_price <= pos_info['target_price']:
                self.close(data)
                pos_info['exit_reason'] = 'TARGET'
        
        # Process new orders
        dt_key = current_dt_utc.floor('1min')
        
        if dt_key not in self.orders_by_ts:
            return
        
        for order_data in self.orders_by_ts[dt_key]:
            symbol = order_data['symbol']
            
            if symbol in self.active_positions:
                continue
            
            data = self._get_data_by_symbol(symbol)
            if not data or self.getposition(data).size != 0:
                continue
            
            side = order_data['side'].lower()
            qty = int(order_data['qty'])
            current_price = data.close[0]
            
            stop_pct = order_data.get('stop_loss_pct', 0.01)
            target_pct = order_data.get('take_profit_pct', 0.02)
            
            if side == 'long':
                stop_price = current_price * (1 - stop_pct)
                target_price = current_price * (1 + target_pct)
                self.buy(data=data, size=qty)
                
                self.active_positions[symbol] = {
                    'side': 'LONG',
                    'entry_time': current_dt_utc,
                    'entry_price': current_price,
                    'qty': qty,
                    'stop_price': stop_price,
                    'target_price': target_price,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                    'exit_reason': None,
                }
            else:
                stop_price = current_price * (1 + stop_pct)
                target_price = current_price * (1 - target_pct)
                self.sell(data=data, size=qty)
                
                self.active_positions[symbol] = {
                    'side': 'SHORT',
                    'entry_time': current_dt_utc,
                    'entry_price': current_price,
                    'qty': qty,
                    'stop_price': stop_price,
                    'target_price': target_price,
                    'stop_pct': stop_pct,
                    'target_pct': target_pct,
                    'exit_reason': None,
                }
    
    def _get_data_by_symbol(self, symbol: str):
        for data in self.datas:
            if data._name == symbol:
                return data
        return None
    
    def notify_trade(self, trade):
        if trade.isclosed:
            symbol = trade.data._name
            
            if symbol not in self.active_positions:
                return
            
            entry = self.active_positions[symbol]
            exit_time = pd.Timestamp(self.datas[0].datetime.datetime(0), tz='UTC')
            
            duration_minutes = (exit_time - entry['entry_time']).total_seconds() / 60
            
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
                'exit_price': trade.price,
                'exit_reason': entry.get('exit_reason', 'OTHER'),
                'qty': entry['qty'],
                'pnl_gross': trade.pnl,
                'pnl_net': trade.pnlcomm,
                'commission': abs(trade.pnlcomm - trade.pnl),
                'duration_minutes': duration_minutes,
            })
            
            del self.active_positions[symbol]


def run_backtest_1m(bars: pd.DataFrame, orders: pd.DataFrame, cfg: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    """Run backtest on 1-minute bars."""
    
    cerebro = bt.Cerebro()
    
    initial_cash = cfg.get('initial_cash', 1_000_000.0)
    cerebro.broker.setcash(initial_cash)
    
    costs = cfg.get('costs', {})
    cerebro.broker.setcommission(
        commission=costs.get('per_share', 0.0035),
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
    
    cerebro.addstrategy(MLStrategy1m, orders_df=orders, commission_per_share=costs.get('per_share', 0.0035))
    
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    print(f'Starting Portfolio Value: ${cerebro.broker.getvalue():,.2f}')
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f'Final Portfolio Value: ${final_value:,.2f}')
    
    strat = results[0]
    
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
    
    trade_df = pd.DataFrame(strat.trade_log)
    
    return artifacts, trade_df
