#!/usr/bin/env python3
"""
Extended L2 Feature Analysis - Multiple Signal Strategies

Tests various combinations of L2 and context features to find optimal signal generation.
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Load the merged data from previous analysis
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")


def load_merged_data() -> pd.DataFrame:
    """Load merged L2 + context data"""
    # Re-run the data loading from the main analysis
    from l2_context_analysis import load_l2_data, download_polygon_bars, merge_l2_with_context, compute_forward_returns
    
    l2_df = load_l2_data()
    symbols = l2_df["symbol"].unique().tolist()
    dates = l2_df["ts_utc"].dt.date.unique()
    
    # Download bars
    bars_dict = {}
    for symbol in symbols:
        all_bars = []
        for date in dates:
            bars = download_polygon_bars(symbol, str(date))
            if bars is not None:
                all_bars.append(bars)
        if all_bars:
            bars_dict[symbol] = pd.concat(all_bars, ignore_index=True)
    
    # Merge and compute returns
    merged = merge_l2_with_context(l2_df, bars_dict)
    merged = compute_forward_returns(merged)
    
    return merged


def test_signal_strategies(df: pd.DataFrame) -> pd.DataFrame:
    """Test multiple signal generation strategies"""
    results = []
    
    strategies = {
        # L2-only strategies
        "l2_obi_03": lambda d: (d["obi_1"] > 0.3).astype(int) - (d["obi_1"] < -0.3).astype(int),
        "l2_obi_025": lambda d: (d["obi_1"] > 0.25).astype(int) - (d["obi_1"] < -0.25).astype(int),
        "l2_obi_02": lambda d: (d["obi_1"] > 0.2).astype(int) - (d["obi_1"] < -0.2).astype(int),
        
        # L2 + momentum
        "l2_obi_mom5": lambda d: (
            ((d["obi_1"] > 0.25) & (d["d_mid_5s"] > 0)).astype(int) -
            ((d["obi_1"] < -0.25) & (d["d_mid_5s"] < 0)).astype(int)
        ),
        
        # L2 + depth imbalance
        "l2_obi_depth": lambda d: (
            ((d["obi_1"] > 0.25) & (d["depth_imb_k"] > 0.1)).astype(int) -
            ((d["obi_1"] < -0.25) & (d["depth_imb_k"] < -0.1)).astype(int)
        ),
        
        # L2 + spread filter (tight spreads only)
        "l2_obi_spread": lambda d: (
            ((d["obi_1"] > 0.25) & (d["spread"] < d["spread"].quantile(0.5))).astype(int) -
            ((d["obi_1"] < -0.25) & (d["spread"] < d["spread"].quantile(0.5))).astype(int)
        ),
        
        # L2 + VWAP (context)
        "l2_vwap_mean_rev": lambda d: (
            ((d["obi_1"] > 0.2) & (d["vwap_dist"] < -5) & d["has_context"]).astype(int) -
            ((d["obi_1"] < -0.2) & (d["vwap_dist"] > 5) & d["has_context"]).astype(int)
        ),
        
        # L2 + RSI (context)
        "l2_rsi_filter": lambda d: (
            ((d["obi_1"] > 0.25) & (d["rsi_14"] < 60) & d["has_context"]).astype(int) -
            ((d["obi_1"] < -0.25) & (d["rsi_14"] > 40) & d["has_context"]).astype(int)
        ),
        
        # L2 + volume (context)
        "l2_high_vol": lambda d: (
            ((d["obi_1"] > 0.25) & (d["rel_vol"] > 1.2) & d["has_context"]).astype(int) -
            ((d["obi_1"] < -0.25) & (d["rel_vol"] > 1.2) & d["has_context"]).astype(int)
        ),
        
        # Combined: L2 + momentum + VWAP
        "l2_mom_vwap": lambda d: (
            ((d["obi_1"] > 0.2) & (d["d_mid_5s"] > 0) & (d["vwap_dist"] < 0) & d["has_context"]).astype(int) -
            ((d["obi_1"] < -0.2) & (d["d_mid_5s"] < 0) & (d["vwap_dist"] > 0) & d["has_context"]).astype(int)
        ),
        
        # Extreme OBI only
        "l2_extreme_obi": lambda d: (d["obi_1"] > 0.5).astype(int) - (d["obi_1"] < -0.5).astype(int),
        
        # Multi-level OBI confirmation
        "l2_multi_obi": lambda d: (
            ((d["obi_1"] > 0.2) & (d["obi_3"] > 0.15) & (d["obi_5"] > 0.1)).astype(int) -
            ((d["obi_1"] < -0.2) & (d["obi_3"] < -0.15) & (d["obi_5"] < -0.1)).astype(int)
        ),
    }
    
    for name, signal_fn in strategies.items():
        try:
            signals = signal_fn(df)
            signal_mask = signals != 0
            
            if signal_mask.sum() == 0:
                continue
            
            signal_df = df[signal_mask].copy()
            signal_df["signal"] = signals[signal_mask]
            
            for h in [5, 10, 15]:
                ret_col = f"fwd_ret_{h}s"
                if ret_col not in signal_df.columns:
                    continue
                
                aligned_ret = signal_df["signal"] * signal_df[ret_col]
                valid = aligned_ret.dropna()
                
                if len(valid) < 100:
                    continue
                
                results.append({
                    "strategy": name,
                    "horizon_s": h,
                    "n_signals": len(valid),
                    "mean_ret_bps": valid.mean(),
                    "std_ret_bps": valid.std(),
                    "win_rate": (valid > 0).mean() * 100,
                    "sharpe": valid.mean() / valid.std() * np.sqrt(len(valid)) if valid.std() > 0 else 0,
                    "buy_signals": (signal_df["signal"] == 1).sum(),
                    "sell_signals": (signal_df["signal"] == -1).sum(),
                })
        except Exception as e:
            logger.warning(f"Error with strategy {name}: {e}")
    
    return pd.DataFrame(results)


def main():
    logger.info("=" * 70)
    logger.info("EXTENDED L2 FEATURE ANALYSIS - MULTIPLE STRATEGIES")
    logger.info("=" * 70)
    
    # Load data
    logger.info("\nLoading merged L2 + context data...")
    df = load_merged_data()
    logger.info(f"Loaded {len(df):,} records")
    
    # Test strategies
    logger.info("\nTesting signal strategies...")
    results = test_signal_strategies(df)
    
    # Sort by mean return at 10s horizon
    results_10s = results[results["horizon_s"] == 10].sort_values("mean_ret_bps", ascending=False)
    
    logger.info("\n" + "=" * 70)
    logger.info("STRATEGY COMPARISON (10s horizon, sorted by mean return)")
    logger.info("=" * 70)
    
    for _, row in results_10s.iterrows():
        logger.info(f"\n{row['strategy']}:")
        logger.info(f"  Signals: {row['n_signals']:,} (Buy: {row['buy_signals']:,}, Sell: {row['sell_signals']:,})")
        logger.info(f"  Mean return: {row['mean_ret_bps']:.2f} bps")
        logger.info(f"  Win rate: {row['win_rate']:.1f}%")
        logger.info(f"  Sharpe: {row['sharpe']:.2f}")
    
    # Save results
    output_file = OUTPUT_DIR / "strategy_comparison.csv"
    results.to_csv(output_file, index=False)
    logger.info(f"\nResults saved to: {output_file}")
    
    # Best strategy summary
    logger.info("\n" + "=" * 70)
    logger.info("BEST STRATEGIES BY METRIC")
    logger.info("=" * 70)
    
    for h in [5, 10, 15]:
        h_results = results[results["horizon_s"] == h]
        if len(h_results) == 0:
            continue
        
        best_ret = h_results.loc[h_results["mean_ret_bps"].idxmax()]
        best_wr = h_results.loc[h_results["win_rate"].idxmax()]
        best_sharpe = h_results.loc[h_results["sharpe"].idxmax()]
        
        logger.info(f"\n{h}s Horizon:")
        logger.info(f"  Best return: {best_ret['strategy']} ({best_ret['mean_ret_bps']:.2f} bps)")
        logger.info(f"  Best win rate: {best_wr['strategy']} ({best_wr['win_rate']:.1f}%)")
        logger.info(f"  Best Sharpe: {best_sharpe['strategy']} ({best_sharpe['sharpe']:.2f})")


if __name__ == "__main__":
    main()
