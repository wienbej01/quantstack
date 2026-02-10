#!/usr/bin/env python3
"""End-of-Day Trade Performance Report

Unified report covering all systems and strategies with comprehensive analytics.

Usage:
    python eod_report.py                    # Today's report
    python eod_report.py --date 2026-01-28  # Specific date
    python eod_report.py --csv report.csv   # Export to CSV
"""

import argparse
from datetime import datetime, time
import psycopg2
import pandas as pd
import numpy as np


def load_trades(date_str: str = None) -> pd.DataFrame:
    """Load trades from PostgreSQL."""
    conn = psycopg2.connect(database='trading', user='jacobw')
    
    where = f"WHERE entry_time::date = '{date_str}'" if date_str else ""
    
    query = f"""
    SELECT 
        trade_id, symbol, system, strategy, direction,
        entry_time, entry_price, entry_qty,
        exit_time, exit_price, exit_qty, exit_reason,
        gross_pnl, commission, net_pnl,
        entry_slippage, exit_slippage,
        hold_time_seconds, status,
        signal_entry_price, signal_exit_price
    FROM trades 
    {where}
    ORDER BY entry_time
    """
    
    df = pd.read_sql_query(query, conn)
    conn.close()
    
    if df.empty:
        return df
    
    # Parse timestamps
    df['entry_time'] = pd.to_datetime(df['entry_time'])
    df['exit_time'] = pd.to_datetime(df['exit_time'], errors='coerce')
    
    # Add derived columns
    df['winner'] = df['net_pnl'] > 0
    df['hour'] = df['entry_time'].dt.hour
    df['period'] = df['hour'].apply(lambda h: 'Morning' if h < 12 else 'Afternoon')
    
    return df


def print_section(title: str):
    """Print section header."""
    print(f"\n{'='*80}")
    print(f"{title}")
    print('='*80)


def executive_summary(df: pd.DataFrame):
    """Print executive summary."""
    print_section("EXECUTIVE SUMMARY")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    total_pnl = closed['net_pnl'].sum()
    total_fees = closed['commission'].sum()
    winners = closed['winner'].sum()
    losers = len(closed) - winners
    win_rate = winners / len(closed) * 100
    avg_pnl = closed['net_pnl'].mean()
    avg_hold = closed['hold_time_seconds'].mean()
    
    print(f"Total Trades:      {len(closed)}")
    print(f"Total Net P&L:     ${total_pnl:,.2f}")
    print(f"Total Fees:        ${total_fees:,.2f}")
    print(f"Win Rate:          {win_rate:.1f}% ({winners}W/{losers}L)")
    print(f"Avg P&L per Trade: ${avg_pnl:,.2f}")
    print(f"Avg Hold Time:     {avg_hold:.1f}s")


def performance_by_system(df: pd.DataFrame):
    """Performance breakdown by system."""
    print_section("PERFORMANCE BY SYSTEM")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('system').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'commission': 'sum',
        'winner': 'sum',
        'hold_time_seconds': 'mean',
        'entry_slippage': 'mean',
        'exit_slippage': 'mean'
    }).round(2)
    
    agg.columns = ['Trades', 'Net_PnL', 'Avg_PnL', 'Fees', 'Winners', 'Avg_Hold_s', 'Avg_Entry_Slip', 'Avg_Exit_Slip']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Trades'] * 100).round(1)
    agg = agg[['Trades', 'Net_PnL', 'Avg_PnL', 'Fees', 'Win_Rate_%', 'Avg_Hold_s', 'Avg_Entry_Slip', 'Avg_Exit_Slip']]
    
    print(agg.to_string())


def performance_by_strategy(df: pd.DataFrame):
    """Performance breakdown by strategy."""
    print_section("PERFORMANCE BY STRATEGY")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('strategy').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'commission': 'sum',
        'winner': 'sum',
        'hold_time_seconds': 'mean',
        'entry_slippage': 'mean',
        'exit_slippage': 'mean'
    }).round(2)
    
    agg.columns = ['Trades', 'Net_PnL', 'Avg_PnL', 'Fees', 'Winners', 'Avg_Hold_s', 'Avg_Entry_Slip', 'Avg_Exit_Slip']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Trades'] * 100).round(1)
    agg = agg[['Trades', 'Net_PnL', 'Avg_PnL', 'Fees', 'Win_Rate_%', 'Avg_Hold_s', 'Avg_Entry_Slip', 'Avg_Exit_Slip']]
    
    print(agg.to_string())


def performance_by_symbol(df: pd.DataFrame):
    """Performance breakdown by symbol."""
    print_section("PERFORMANCE BY SYMBOL")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('symbol').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'winner': 'sum'
    }).round(2)
    
    agg.columns = ['Trades', 'Net_PnL', 'Avg_PnL', 'Winners']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Trades'] * 100).round(1)
    agg = agg[['Trades', 'Net_PnL', 'Avg_PnL', 'Win_Rate_%']]
    agg = agg.sort_values('Net_PnL', ascending=False)
    
    print(agg.to_string())


def performance_by_direction(df: pd.DataFrame):
    """Performance breakdown by direction."""
    print_section("PERFORMANCE BY DIRECTION")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('direction').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'winner': 'sum'
    }).round(2)
    
    agg.columns = ['Trades', 'Net_PnL', 'Avg_PnL', 'Winners']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Trades'] * 100).round(1)
    agg = agg[['Trades', 'Net_PnL', 'Avg_PnL', 'Win_Rate_%']]
    
    print(agg.to_string())


def exit_reason_analysis(df: pd.DataFrame):
    """Exit reason breakdown."""
    print_section("EXIT REASON ANALYSIS")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('exit_reason').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'winner': 'sum'
    }).round(2)
    
    agg.columns = ['Count', 'Net_PnL', 'Avg_PnL', 'Winners']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Count'] * 100).round(1)
    agg = agg[['Count', 'Net_PnL', 'Avg_PnL', 'Win_Rate_%']]
    agg = agg.sort_values('Count', ascending=False)
    
    print(agg.to_string())


def intraday_time_analysis(df: pd.DataFrame):
    """Performance by time of day."""
    print_section("INTRADAY TIME ANALYSIS")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    agg = closed.groupby('period').agg({
        'trade_id': 'count',
        'net_pnl': ['sum', 'mean'],
        'winner': 'sum',
        'hold_time_seconds': 'mean'
    }).round(2)
    
    agg.columns = ['Trades', 'Net_PnL', 'Avg_PnL', 'Winners', 'Avg_Hold_s']
    agg['Win_Rate_%'] = (agg['Winners'] / agg['Trades'] * 100).round(1)
    agg = agg[['Trades', 'Net_PnL', 'Avg_PnL', 'Win_Rate_%', 'Avg_Hold_s']]
    
    print(agg.to_string())


def risk_metrics(df: pd.DataFrame):
    """Calculate risk metrics."""
    print_section("RISK METRICS")
    
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No closed trades.")
        return
    
    pnl_series = closed['net_pnl']
    
    # Cumulative P&L for drawdown
    cum_pnl = pnl_series.cumsum()
    running_max = cum_pnl.cummax()
    drawdown = running_max - cum_pnl
    max_dd = drawdown.max()
    
    # Sharpe (assuming 252 trading days, 6.5 hour day, trades per hour)
    if len(pnl_series) > 1:
        sharpe = pnl_series.mean() / pnl_series.std() * np.sqrt(252) if pnl_series.std() > 0 else 0
    else:
        sharpe = 0
    
    # Profit factor
    gross_profit = pnl_series[pnl_series > 0].sum()
    gross_loss = abs(pnl_series[pnl_series < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
    
    # Expectancy
    expectancy = pnl_series.mean()
    
    print(f"Max Drawdown:      ${max_dd:,.2f}")
    print(f"Sharpe Ratio:      {sharpe:.2f}")
    print(f"Profit Factor:     {profit_factor:.2f}")
    print(f"Expectancy:        ${expectancy:,.2f}")
    print(f"Best Trade:        ${pnl_series.max():,.2f}")
    print(f"Worst Trade:       ${pnl_series.min():,.2f}")


def signal_execution_analysis(df: pd.DataFrame):
    """Analyze signal vs execution prices."""
    print_section("SIGNAL VS EXECUTION ANALYSIS")
    
    closed = df[df['status'] == 'CLOSED'].copy()
    
    if closed.empty:
        print("No closed trades.")
        return
    
    # Filter trades with signal prices
    has_signal = closed['signal_entry_price'].notna()
    
    if not has_signal.any():
        print("No signal price data available.")
        return
    
    signal_df = closed[has_signal].copy()
    
    # Calculate signal slippage (actual - signal)
    signal_df['signal_entry_slip'] = signal_df['entry_price'] - signal_df['signal_entry_price']
    
    # For shorts, negative slippage is bad (paid more)
    signal_df['signal_entry_slip_adj'] = signal_df.apply(
        lambda x: -x['signal_entry_slip'] if x['direction'] == 'SHORT' else x['signal_entry_slip'],
        axis=1
    )
    
    avg_signal_slip = signal_df['signal_entry_slip_adj'].mean()
    
    print(f"Trades with Signal Data: {len(signal_df)}")
    print(f"Avg Signal Slippage:     ${avg_signal_slip:.4f}")
    print(f"Min Signal Slippage:     ${signal_df['signal_entry_slip_adj'].min():.4f}")
    print(f"Max Signal Slippage:     ${signal_df['signal_entry_slip_adj'].max():.4f}")


def trade_details(df: pd.DataFrame):
    """Print trade-by-trade details."""
    print_section("TRADE DETAILS")
    
    closed = df[df['status'] == 'CLOSED'].copy()
    
    if closed.empty:
        print("No closed trades.")
        return
    
    # Format for display
    display = closed[[
        'entry_time', 'symbol', 'system', 'strategy', 'direction',
        'entry_price', 'exit_price', 'net_pnl', 'exit_reason', 'hold_time_seconds'
    ]].copy()
    
    display['entry_time'] = display['entry_time'].dt.strftime('%H:%M:%S')
    display['entry_price'] = display['entry_price'].round(2)
    display['exit_price'] = display['exit_price'].round(2)
    display['net_pnl'] = display['net_pnl'].round(2)
    display['hold_time_seconds'] = display['hold_time_seconds'].round(0)
    
    display.columns = ['Time', 'Symbol', 'System', 'Strategy', 'Dir', 'Entry', 'Exit', 'P&L', 'Reason', 'Hold_s']
    
    print(display.to_string(index=False))


def export_csv(df: pd.DataFrame, filepath: str):
    """Export full data to CSV."""
    closed = df[df['status'] == 'CLOSED']
    
    if closed.empty:
        print("No trades to export.")
        return
    
    closed.to_csv(filepath, index=False)
    print(f"\nExported {len(closed)} trades to: {filepath}")


def main():
    parser = argparse.ArgumentParser(description="End-of-Day Trade Performance Report")
    parser.add_argument("--date", help="Date (YYYY-MM-DD), default: today")
    parser.add_argument("--csv", help="Export to CSV file")
    args = parser.parse_args()
    
    # Determine date
    if args.date:
        report_date = args.date
        date_obj = datetime.strptime(args.date, "%Y-%m-%d")
    else:
        date_obj = datetime.now()
        report_date = date_obj.strftime("%Y-%m-%d")
    
    # Load data
    df = load_trades(report_date)
    
    if df.empty:
        print(f"No trades found for {report_date}")
        return
    
    # Print header
    print("\n" + "="*80)
    print(f"END-OF-DAY TRADE PERFORMANCE REPORT")
    print(f"Date: {report_date}")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*80)
    
    # Generate all sections
    executive_summary(df)
    performance_by_system(df)
    performance_by_strategy(df)
    performance_by_symbol(df)
    performance_by_direction(df)
    exit_reason_analysis(df)
    intraday_time_analysis(df)
    risk_metrics(df)
    signal_execution_analysis(df)
    trade_details(df)
    
    # Export if requested
    if args.csv:
        export_csv(df, args.csv)
    
    print("\n" + "="*80)


if __name__ == "__main__":
    main()
