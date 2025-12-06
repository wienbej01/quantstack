"""Backtrader integration for intraday ML strategy."""

from typing import Any

import backtrader as bt
import pandas as pd


class MLStrategy(bt.Strategy):
    """Backtrader strategy that executes ML-generated orders with stop/target."""
    
    params = (
        ('orders_df', None),
        ('commission_per_share', 0.0035),
        ('commission_min', 0.35),
        ('slippage_bps', 5),
    )
    
    def __init__(self):
        self.orders_by_ts = {}
        self.active_orders = {}
        self.positions_tracker = {}
        
        if self.params.orders_df is not None and not self.params.orders_df.empty:
            # Convert orders to dict keyed by datetime
            for _, order in self.params.orders_df.iterrows():
                ts_ns = int(order['ts'])
                dt = pd.to_datetime(ts_ns, unit='ns', utc=True)
                # Round to minute for matching
                dt_key = dt.floor('1min')
                
                symbol = order['symbol']
                if dt_key not in self.orders_by_ts:
                    self.orders_by_ts[dt_key] = []
                self.orders_by_ts[dt_key].append(order)
    
    def next(self):
        """Execute on each bar."""
        # Get current datetime from first data feed
        current_dt = self.datas[0].datetime.datetime(0)
        if current_dt.tzinfo is None:
            current_dt = pd.Timestamp(current_dt, tz='UTC')
        else:
            current_dt = pd.Timestamp(current_dt)
        
        # Round to minute for matching
        dt_key = current_dt.floor('1min')
        
        # Check for orders at this timestamp
        if dt_key not in self.orders_by_ts:
            return
        
        for order_data in self.orders_by_ts[dt_key]:
            symbol = order_data['symbol']
            side = order_data['side'].lower()
            qty = int(order_data['qty'])
            
            # Get data feed for this symbol
            data = self._get_data_by_symbol(symbol)
            if data is None:
                continue
            
            # Check if we already have a position
            position = self.getposition(data)
            if position.size != 0:
                continue  # Skip if already in position
            
            # Calculate stop and target prices
            current_price = data.close[0]
            stop_pct = order_data.get('stop_loss_pct', 0.01)
            target_pct = order_data.get('take_profit_pct', 0.02)
            
            if side == 'long':
                stop_price = current_price * (1 - stop_pct)
                target_price = current_price * (1 + target_pct)
                
                # Submit bracket order
                self.buy_bracket(
                    data=data,
                    size=qty,
                    stopprice=stop_price,
                    limitprice=target_price,
                )
            else:  # short
                stop_price = current_price * (1 + stop_pct)
                target_price = current_price * (1 - target_pct)
                
                # Submit bracket order
                self.sell_bracket(
                    data=data,
                    size=qty,
                    stopprice=stop_price,
                    limitprice=target_price,
                )
    
    def _get_data_by_symbol(self, symbol: str):
        """Find data feed by symbol name."""
        for data in self.datas:
            if data._name == symbol:
                return data
        return None
    
    def notify_order(self, order):
        """Track order status."""
        if order.status in [order.Completed]:
            if order.isbuy():
                action = 'BUY'
            else:
                action = 'SELL'
            
            print(f'{action} EXECUTED: {order.data._name} @ {order.executed.price:.2f}, '
                  f'Size: {order.executed.size}, Cost: {order.executed.value:.2f}, '
                  f'Comm: {order.executed.comm:.2f}')
    
    def notify_trade(self, trade):
        """Track completed trades."""
        if trade.isclosed:
            print(f'TRADE CLOSED: {trade.data._name}, PnL: ${trade.pnl:.2f}, '
                  f'Net: ${trade.pnlcomm:.2f}')


def run_backtest_bt(
    bars: pd.DataFrame,
    orders: pd.DataFrame,
    cfg: dict[str, Any],
) -> dict[str, Any]:
    """Run backtest using Backtrader with stop/target support.
    
    Args:
        bars: OHLCV data with columns [ts, symbol, open, high, low, close, volume]
        orders: ML orders with columns [ts, symbol, side, qty, stop_loss_pct, take_profit_pct]
        cfg: Configuration dict with initial_cash, costs, etc.
    
    Returns:
        Dictionary with fills, trades, and performance metrics
    """
    cerebro = bt.Cerebro()
    
    # Set initial cash
    initial_cash = cfg.get('initial_cash', 1_000_000.0)
    cerebro.broker.setcash(initial_cash)
    
    # Set commission
    costs = cfg.get('costs', {})
    commission_per_share = costs.get('per_share', 0.0035)
    commission_min = costs.get('commission_min', 0.35)
    cerebro.broker.setcommission(
        commission=commission_per_share,
        commtype=bt.CommInfoBase.COMM_FIXED,
        percabs=True,
    )
    
    # Add data feeds for each symbol
    symbols = bars['symbol'].unique()
    for symbol in symbols:
        symbol_data = bars[bars['symbol'] == symbol].copy()
        symbol_data['datetime'] = pd.to_datetime(symbol_data['ts'], unit='ns', utc=True)
        symbol_data = symbol_data.set_index('datetime')
        symbol_data = symbol_data[['open', 'high', 'low', 'close', 'volume']]
        
        data = bt.feeds.PandasData(
            dataname=symbol_data,
            name=symbol,
        )
        cerebro.adddata(data)
    
    # Add strategy with orders
    cerebro.addstrategy(
        MLStrategy,
        orders_df=orders,
        commission_per_share=commission_per_share,
        commission_min=commission_min,
        slippage_bps=costs.get('bps', 5),
    )
    
    # Add analyzers
    cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name='sharpe')
    cerebro.addanalyzer(bt.analyzers.DrawDown, _name='drawdown')
    cerebro.addanalyzer(bt.analyzers.Returns, _name='returns')
    cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name='trades')
    
    # Run backtest
    print(f'Starting Portfolio Value: ${cerebro.broker.getvalue():,.2f}')
    results = cerebro.run()
    final_value = cerebro.broker.getvalue()
    print(f'Final Portfolio Value: ${final_value:,.2f}')
    
    # Extract results
    strat = results[0]
    
    # Build artifacts
    artifacts = {
        'initial_cash': initial_cash,
        'final_value': final_value,
        'pnl': final_value - initial_cash,
        'return_pct': ((final_value - initial_cash) / initial_cash) * 100,
    }
    
    # Add analyzer results
    if hasattr(strat.analyzers.sharpe, 'get_analysis'):
        sharpe_analysis = strat.analyzers.sharpe.get_analysis()
        artifacts['sharpe_ratio'] = sharpe_analysis.get('sharperatio', 0.0)
    
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
    
    return artifacts
