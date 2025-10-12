"""Backtest engine v0."""

from typing import Dict, List

import pandas as pd

from qx_risk.atr_stop import set_stops, size_order


def run_backtest(df: pd.DataFrame, signals_df: pd.DataFrame, params: Dict) -> Dict:
    """Run backtest simulation.

    Args:
        df: DataFrame with bars and features
        signals_df: DataFrame with signals
        params: Backtest params

    Returns:
        Dict with artifacts
    """
    initial_equity = params.get('initial_equity', 100000.0)
    cost_bps = params.get('cost_bps', 0.0)
    cost_per_share = params.get('cost_per_share', 0.0)

    # Ensure sorted
    df = df.sort_values(['ts', 'symbol']).reset_index(drop=True)
    signals_df = signals_df.sort_values(['ts', 'symbol']).reset_index(drop=True)

    # Artifacts
    orders = []
    fills = []
    positions = []
    equity_curve = []
    trades = []
    risk_rejects = []
    allocation_log = []

    # State
    current_positions = {}  # symbol -> {'qty': int, 'entry_px': float, 'entry_ts': pd.Timestamp}
    pending_orders = []  # List of order dicts with 'fill_ts'
    cum_pnl = 0.0
    equity = initial_equity

    # Get unique ts
    all_ts = sorted(df['ts'].unique())

    for ts in all_ts:
        bars_ts = df[df['ts'] == ts]
        signals_ts = signals_df[signals_df['ts'] == ts]

        # Fill pending orders
        to_remove = []
        for order in pending_orders:
            if order['fill_ts'] <= ts:
                symbol = order['symbol']
                bar = bars_ts[bars_ts['symbol'] == symbol]
                if not bar.empty:
                    fill_px = bar['open'].iloc[0]  # Next open
                    fees = calculate_fees(order['qty'], fill_px, cost_bps, cost_per_share)
                    fill = {
                        'ts': ts,
                        'symbol': symbol,
                        'side': order['side'],
                        'qty': order['qty'],
                        'px': fill_px,
                        'fees': fees
                    }
                    fills.append(fill)

                    if order['side'] == 'BUY':
                        current_positions[symbol] = {
                            'qty': order['qty'],
                            'entry_px': fill_px,
                            'entry_ts': ts
                        }
                    elif order['side'] == 'SELL':
                        if symbol in current_positions:
                            pos = current_positions[symbol]
                            pnl = (fill_px - pos['entry_px']) * order['qty'] - fees
                            cum_pnl += pnl
                            trade = {
                                'entry_ts': pos['entry_ts'],
                                'exit_ts': ts,
                                'symbol': symbol,
                                'side': 'BUY',
                                'qty': order['qty'],
                                'entry_px': pos['entry_px'],
                                'exit_px': fill_px,
                                'pnl': pnl,
                                'r_multiple': pnl / (pos['entry_px'] * order['qty'] * 0.01) if pos['entry_px'] > 0 else 0,
                                'mfe': 0.0,  # Stub
                                'mae': 0.0,  # Stub
                                'duration_s': (ts - pos['entry_ts']).total_seconds(),
                                'policy_tag': 'vwap_revert',
                                'risk_tag': 'atr_stop'
                            }
                            trades.append(trade)
                            del current_positions[symbol]
                to_remove.append(order)
        for o in to_remove:
            pending_orders.remove(o)

        # Process signals
        for _, signal in signals_ts.iterrows():
            symbol = signal['symbol']
            side = signal['side']

            if side == 'BUY' and symbol not in current_positions:
                # Size order
                bar = bars_ts[bars_ts['symbol'] == symbol]
                if not bar.empty:
                    atr = bar['f__vol__atr_m'].iloc[0]
                    qty = size_order(signal.to_dict(), equity, atr, params)
                    if qty is None:
                        # Reject
                        risk_rejects.append({
                            'reason_code': 'sizing_failed',
                            'limit_name': 'atr_too_small_or_notional',
                            'value': atr,
                            'threshold': 0.0
                        })
                        continue

                    order = {
                        'ts': ts,
                        'symbol': symbol,
                        'side': 'BUY',
                        'qty': qty,
                        'type': 'MKT',
                        'tif': 'DAY'
                    }
                    orders.append(order)
                    # Fill at next ts
                    next_ts = all_ts[min(all_ts.index(ts) + 1, len(all_ts) - 1)] if ts in all_ts else ts
                    order['fill_ts'] = next_ts
                    pending_orders.append(order)

            elif side == 'SELL' and symbol in current_positions:
                qty = current_positions[symbol]['qty']
                order = {
                    'ts': ts,
                    'symbol': symbol,
                    'side': 'SELL',
                    'qty': qty,
                    'type': 'MKT',
                    'tif': 'DAY'
                }
                orders.append(order)
                next_ts = all_ts[min(all_ts.index(ts) + 1, len(all_ts) - 1)] if ts in all_ts else ts
                order['fill_ts'] = next_ts
                pending_orders.append(order)

        # Update positions snapshot
        for symbol, pos in current_positions.items():
            positions.append({
                'ts': ts,
                'symbol': symbol,
                'qty': pos['qty'],
                'entry_px': pos['entry_px']
            })

        # Update equity
        unrealized = 0.0
        for symbol, pos in current_positions.items():
            bar = bars_ts[bars_ts['symbol'] == symbol]
            if not bar.empty:
                current_px = bar['close'].iloc[0]
                unrealized += (current_px - pos['entry_px']) * pos['qty']

        equity = initial_equity + cum_pnl + unrealized
        equity_curve.append({'ts': ts, 'equity': equity})

        # Allocation log (stub)
        allocation_log.append({'ts': ts, 'allocation': len(current_positions)})

    # Metrics
    if trades:
        avg_r = sum(t['r_multiple'] for t in trades) / len(trades)
        es_95 = sorted([t['r_multiple'] for t in trades])[int(len(trades) * 0.05)]
        pvalue_u = 0.5  # Stub
        sharpe_ci_low = avg_r - 0.1  # Stub
        sharpe_ci_high = avg_r + 0.1  # Stub
        capacity_bps = 50.0  # Stub
    else:
        avg_r = 0.0
        es_95 = 0.0
        pvalue_u = 1.0
        sharpe_ci_low = 0.0
        sharpe_ci_high = 0.0
        capacity_bps = 0.0

    metrics = {
        'trades': len(trades),
        'avg_R': avg_r,
        'ES_95': es_95,
        'pvalue_u': pvalue_u,
        'sharpe_CI_low': sharpe_ci_low,
        'sharpe_CI_high': sharpe_ci_high,
        'capacity_break_even_bps': capacity_bps
    }

    return {
        'signals': signals_df,
        'orders': pd.DataFrame(orders),
        'fills': pd.DataFrame(fills),
        'positions': pd.DataFrame(positions),
        'equity': pd.DataFrame(equity_curve),
        'trades': pd.DataFrame(trades),
        'risk_rejects': pd.DataFrame(risk_rejects),
        'allocation_log': pd.DataFrame(allocation_log),
        'metrics': metrics
    }


def calculate_fees(qty: int, px: float, bps: float, per_share: float) -> float:
    """Calculate trading fees."""
    return qty * (px * bps / 10000 + per_share)