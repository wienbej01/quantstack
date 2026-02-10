#!/usr/bin/env python3
"""
Backtest top-10 LLM-selected patterns with proper identifiers and horizons.
"""

from pathlib import Path
import pandas as pd
import numpy as np
from src.validation_backtest import backtest_pattern_on_period

# Top-10 patterns from LLM analysis with identifiers
TOP_10_PATTERNS = [
    {
        "id": "P130_VWAP_ATR_120m",
        "rule": "vwap_cross_up_bin == True AND atr_14_bin == 0",
        "rule_type": "double",
        "rule_col1": "vwap_cross_up_bin",
        "rule_val1": True,
        "rule_col2": "atr_14_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_120m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P131_RET15M_ATR_120m",
        "rule": "ret_15m_turned_positive_bin == True AND atr_14_bin == 0",
        "rule_type": "double",
        "rule_col1": "ret_15m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "atr_14_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_120m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P132_RET5M_ATR_120m",
        "rule": "ret_5m_turned_positive_bin == True AND atr_14_bin == 0",
        "rule_type": "double",
        "rule_col1": "ret_5m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "atr_14_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_120m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P221_VWAP_RVOL_180m",
        "rule": "vwap_cross_up_bin == True AND rvol_bin == 0",
        "rule_type": "double",
        "rule_col1": "vwap_cross_up_bin",
        "rule_val1": True,
        "rule_col2": "rvol_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P222_RET30M_RVOL_180m",
        "rule": "ret_30m_turned_positive_bin == True AND rvol_bin == 0",
        "rule_type": "double",
        "rule_col1": "ret_30m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "rvol_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P223_RET15M_RVOL_180m",
        "rule": "ret_15m_turned_positive_bin == True AND rvol_bin == 0",
        "rule_type": "double",
        "rule_col1": "ret_15m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "rvol_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P224_RET5M_RVOL_180m",
        "rule": "ret_5m_turned_positive_bin == True AND rvol_bin == 0",
        "rule_type": "double",
        "rule_col1": "ret_5m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "rvol_bin",
        "rule_val2": 0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P225_RET15M_RET15MBIN_180m",
        "rule": "ret_15m_turned_positive_bin == True AND ret_15m_bin == 2.0",
        "rule_type": "double",
        "rule_col1": "ret_15m_turned_positive_bin",
        "rule_val1": True,
        "rule_col2": "ret_15m_bin",
        "rule_val2": 2.0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P226_VWAP_RET15MBIN_180m",
        "rule": "vwap_cross_up_bin == True AND ret_15m_bin == 2.0",
        "rule_type": "double",
        "rule_col1": "vwap_cross_up_bin",
        "rule_val1": True,
        "rule_col2": "ret_15m_bin",
        "rule_val2": 2.0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
    {
        "id": "P227_VWAP_RET5MBIN_180m",
        "rule": "vwap_cross_up_bin == True AND ret_5m_bin == 2.0",
        "rule_type": "double",
        "rule_col1": "vwap_cross_up_bin",
        "rule_val1": True,
        "rule_col2": "ret_5m_bin",
        "rule_val2": 2.0,
        "direction": "LONG",
        "horizon": "fwd_ret_180m",
        "regime": "bull_low_vol",
    },
]


def load_monthly_cache_with_bins(monthly_cache_dir: str = "output_aaa/monthly_cache") -> pd.DataFrame:
    """Load monthly cache and compute binned features."""
    cache_path = Path(monthly_cache_dir)
    files = sorted(cache_path.glob("features_targets_*.parquet"))
    
    if not files:
        raise FileNotFoundError(f"No monthly cache files found in {monthly_cache_dir}")
    
    print(f"Loading {len(files)} monthly cache files...")
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    
    print(f"Loaded {len(df):,} rows")
    print("Computing binned features...")
    
    # Compute quantile bins for continuous features
    for col in ['ret_5m', 'ret_15m', 'ret_30m', 'ret_60m']:
        if col in df.columns:
            df[f'{col}_bin'] = pd.qcut(df[col], q=5, labels=False, duplicates='drop')
    
    if 'atr_14' in df.columns:
        df['atr_14_bin'] = pd.qcut(df['atr_14'], q=5, labels=False, duplicates='drop')
    
    if 'rvol' in df.columns:
        df['rvol_bin'] = pd.qcut(df['rvol'], q=5, labels=False, duplicates='drop')
    
    # Boolean features - just copy with _bin suffix
    for col in ['vwap_cross_up', 'ret_5m_turned_positive', 'ret_15m_turned_positive', 
                'ret_30m_turned_positive', 'ret_60m_turned_positive']:
        if col in df.columns:
            df[f'{col}_bin'] = df[col]
    
    print(f"Computed binned features. Total columns: {len(df.columns)}")
    return df


def backtest_top10(
    monthly_cache_dir: str = "output_aaa/monthly_cache",
    output_path: str = "output_aaa/backtest_top10_results.csv",
    dedupe_by_symbol_day: bool = True,
):
    """
    Backtest top-10 patterns on monthly cache data.
    
    Args:
        monthly_cache_dir: Path to monthly cache directory
        output_path: Where to save results
        dedupe_by_symbol_day: One signal per symbol/day
    """
    df = load_monthly_cache_with_bins(monthly_cache_dir)
    
    results = []
    
    for pattern in TOP_10_PATTERNS:
        print(f"\n{'='*80}")
        print(f"Testing {pattern['id']}")
        print(f"Rule: {pattern['rule']}")
        print(f"Horizon: {pattern['horizon']} ({pattern['horizon'].replace('fwd_ret_', '')})")
        print(f"Regime: {pattern['regime']}")
        
        metrics, reason = backtest_pattern_on_period(
            pattern=pattern,
            df=df,
            return_col=pattern["horizon"],
            dedupe_by_symbol_day=dedupe_by_symbol_day,
            dedupe_policy="first",
        )
        
        if metrics is None:
            print(f"❌ FAILED: {reason}")
            results.append({
                "pattern_id": pattern["id"],
                "rule": pattern["rule"],
                "horizon": pattern["horizon"],
                "regime": pattern["regime"],
                "status": "FAILED",
                "reason": reason,
            })
        else:
            print(f"✅ SUCCESS")
            print(f"   Trades: {metrics['n_trades']:,}")
            print(f"   Expectancy: {metrics['expectancy']:.4%}")
            print(f"   Win Rate: {metrics['win_rate']:.2%}")
            print(f"   Sharpe: {metrics['sharpe']:.2f}")
            print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
            
            results.append({
                "pattern_id": pattern["id"],
                "rule": pattern["rule"],
                "horizon": pattern["horizon"],
                "regime": pattern["regime"],
                "status": "SUCCESS",
                "n_trades": metrics["n_trades"],
                "expectancy": metrics["expectancy"],
                "win_rate": metrics["win_rate"],
                "sharpe": metrics["sharpe"],
                "profit_factor": metrics["profit_factor"],
                "avg_win": metrics["avg_win"],
                "avg_loss": metrics["avg_loss"],
            })
    
    # Save results
    results_df = pd.DataFrame(results)
    results_df.to_csv(output_path, index=False)
    print(f"\n{'='*80}")
    print(f"Results saved to {output_path}")
    
    # Summary
    success = results_df[results_df["status"] == "SUCCESS"]
    if not success.empty:
        print(f"\n{'='*80}")
        print("SUMMARY - Top Performers:")
        print(f"{'='*80}")
        summary = success.sort_values("expectancy", ascending=False).head(5)
        for _, row in summary.iterrows():
            print(f"{row['pattern_id']:30s} | Exp: {row['expectancy']:.4%} | "
                  f"WR: {row['win_rate']:.2%} | Trades: {row['n_trades']:,}")
    
    return results_df


if __name__ == "__main__":
    import sys
    
    monthly_cache_dir = sys.argv[1] if len(sys.argv) > 1 else "output_aaa/monthly_cache"
    output_path = sys.argv[2] if len(sys.argv) > 2 else "output_aaa/backtest_top10_results.csv"
    
    backtest_top10(monthly_cache_dir, output_path)
