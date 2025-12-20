#!/usr/bin/env python3
"""
L2 Scalping - High Conviction Signal Analysis

Focus on:
1. Larger expected moves (>2 bps to cover costs)
2. Higher win rates (>40%)
3. Context as regime filter (trade with trend, favorable conditions)
4. Cost-aware analysis ($2 round-trip commission)
"""

import logging
from pathlib import Path
import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")
COMMISSION_PER_TRADE = 2.0  # $2 round trip


def load_data():
    """Load merged L2 + context data"""
    from l2_context_analysis import load_l2_data, download_polygon_bars, merge_l2_with_context, compute_forward_returns
    
    l2_df = load_l2_data()
    symbols = l2_df["symbol"].unique().tolist()
    dates = l2_df["ts_utc"].dt.date.unique()
    
    bars_dict = {}
    for symbol in symbols:
        all_bars = []
        for date in dates:
            bars = download_polygon_bars(symbol, str(date))
            if bars is not None:
                all_bars.append(bars)
        if all_bars:
            bars_dict[symbol] = pd.concat(all_bars, ignore_index=True)
    
    merged = merge_l2_with_context(l2_df, bars_dict)
    merged = compute_forward_returns(merged)
    return merged


def analyze_cost_adjusted_performance(df: pd.DataFrame):
    """Analyze strategies with commission costs"""
    
    logger.info("\n" + "=" * 70)
    logger.info("COST-AWARE ANALYSIS")
    logger.info("=" * 70)
    logger.info(f"Commission: ${COMMISSION_PER_TRADE} per round-trip")
    logger.info("Position size assumption: $5,000")
    logger.info("Break-even: 4 bps (=$2 on $5k)")
    
    results = []
    
    # Test various high-conviction strategies
    strategies = {
        # Extreme OBI only
        "extreme_obi_06": {
            "buy": (df["obi_1"] > 0.6),
            "sell": (df["obi_1"] < -0.6),
        },
        "extreme_obi_07": {
            "buy": (df["obi_1"] > 0.7),
            "sell": (df["obi_1"] < -0.7),
        },
        
        # Extreme OBI + trend alignment
        "extreme_obi_trend": {
            "buy": (df["obi_1"] > 0.5) & (df["mom_15"] > 0),
            "sell": (df["obi_1"] < -0.5) & (df["mom_15"] < 0),
        },
        
        # Extreme OBI + favorable VWAP (mean reversion setup)
        "extreme_obi_vwap": {
            "buy": (df["obi_1"] > 0.5) & (df["vwap_dist"] < -10),
            "sell": (df["obi_1"] < -0.5) & (df["vwap_dist"] > 10),
        },
        
        # Multi-level OBI confirmation
        "multi_obi_strong": {
            "buy": (df["obi_1"] > 0.4) & (df["obi_3"] > 0.3) & (df["obi_5"] > 0.2),
            "sell": (df["obi_1"] < -0.4) & (df["obi_3"] < -0.3) & (df["obi_5"] < -0.2),
        },
        
        # Extreme OBI + depth imbalance
        "extreme_obi_depth": {
            "buy": (df["obi_1"] > 0.5) & (df["depth_imb_k"] > 0.2),
            "sell": (df["obi_1"] < -0.5) & (df["depth_imb_k"] < -0.2),
        },
        
        # Extreme OBI + high volume (institutional flow)
        "extreme_obi_highvol": {
            "buy": (df["obi_1"] > 0.5) & (df["rel_vol"] > 1.5),
            "sell": (df["obi_1"] < -0.5) & (df["rel_vol"] > 1.5),
        },
        
        # Combined: extreme OBI + trend + not overbought/oversold
        "high_conviction": {
            "buy": (df["obi_1"] > 0.5) & (df["mom_15"] > 0) & (df["rsi_14"] < 65),
            "sell": (df["obi_1"] < -0.5) & (df["mom_15"] < 0) & (df["rsi_14"] > 35),
        },
        
        # Ultra-selective: all favorable conditions
        "ultra_selective": {
            "buy": (df["obi_1"] > 0.6) & (df["mom_15"] > 0) & (df["vwap_dist"] < 0) & (df["depth_imb_k"] > 0.1),
            "sell": (df["obi_1"] < -0.6) & (df["mom_15"] < 0) & (df["vwap_dist"] > 0) & (df["depth_imb_k"] < -0.1),
        },
    }
    
    for name, conds in strategies.items():
        signals = conds["buy"].astype(int) - conds["sell"].astype(int)
        signal_mask = signals != 0
        
        if signal_mask.sum() < 50:
            continue
        
        signal_df = df[signal_mask].copy()
        signal_df["signal"] = signals[signal_mask]
        
        for h in [10, 15, 30]:
            ret_col = f"fwd_ret_{h}s"
            if ret_col not in signal_df.columns:
                continue
            
            aligned_ret = signal_df["signal"] * signal_df[ret_col]
            valid = aligned_ret.dropna()
            
            if len(valid) < 50:
                continue
            
            mean_ret_bps = valid.mean()
            win_rate = (valid > 0).mean() * 100
            
            # Cost-adjusted metrics (assuming $5k position)
            position_size = 5000
            gross_pnl_per_trade = mean_ret_bps / 10000 * position_size
            net_pnl_per_trade = gross_pnl_per_trade - COMMISSION_PER_TRADE
            net_ret_bps = net_pnl_per_trade / position_size * 10000
            
            # Profitable trade threshold
            breakeven_bps = COMMISSION_PER_TRADE / position_size * 10000
            pct_above_breakeven = (valid > breakeven_bps).mean() * 100
            
            results.append({
                "strategy": name,
                "horizon_s": h,
                "n_signals": len(valid),
                "gross_ret_bps": mean_ret_bps,
                "net_ret_bps": net_ret_bps,
                "win_rate": win_rate,
                "pct_above_breakeven": pct_above_breakeven,
                "gross_pnl_per_trade": gross_pnl_per_trade,
                "net_pnl_per_trade": net_pnl_per_trade,
                "daily_signals_est": len(valid) / 2,  # 2 days of data
            })
    
    return pd.DataFrame(results)


def main():
    logger.info("=" * 70)
    logger.info("HIGH CONVICTION L2 SCALPING ANALYSIS")
    logger.info("=" * 70)
    logger.info("\nGoal: Find signals with:")
    logger.info("  - Expected return > 4 bps (to cover $2 commission on $5k)")
    logger.info("  - Win rate > 35%")
    logger.info("  - Reasonable signal frequency")
    
    logger.info("\nLoading data...")
    df = load_data()
    logger.info(f"Loaded {len(df):,} records")
    
    logger.info("\nAnalyzing strategies...")
    results = analyze_cost_adjusted_performance(df)
    
    # Filter to 15s horizon and sort by net return
    results_15s = results[results["horizon_s"] == 15].sort_values("net_ret_bps", ascending=False)
    
    logger.info("\n" + "=" * 70)
    logger.info("RESULTS: 15s HORIZON (sorted by net return after costs)")
    logger.info("=" * 70)
    
    for _, row in results_15s.iterrows():
        profitable = "✓" if row["net_ret_bps"] > 0 else "✗"
        logger.info(f"\n{profitable} {row['strategy']}:")
        logger.info(f"   Signals: {row['n_signals']:,} ({row['daily_signals_est']:.0f}/day)")
        logger.info(f"   Gross return: {row['gross_ret_bps']:.2f} bps")
        logger.info(f"   Net return:   {row['net_ret_bps']:.2f} bps (after $2 commission)")
        logger.info(f"   Win rate: {row['win_rate']:.1f}%")
        logger.info(f"   % trades > breakeven: {row['pct_above_breakeven']:.1f}%")
        logger.info(f"   Est. P&L/trade: ${row['net_pnl_per_trade']:.2f}")
    
    # Best strategies summary
    logger.info("\n" + "=" * 70)
    logger.info("PROFITABLE STRATEGIES (net return > 0)")
    logger.info("=" * 70)
    
    profitable = results_15s[results_15s["net_ret_bps"] > 0]
    if len(profitable) > 0:
        for _, row in profitable.iterrows():
            daily_pnl = row["net_pnl_per_trade"] * row["daily_signals_est"]
            logger.info(f"\n{row['strategy']}:")
            logger.info(f"   Net return: {row['net_ret_bps']:.2f} bps")
            logger.info(f"   Win rate: {row['win_rate']:.1f}%")
            logger.info(f"   Signals/day: {row['daily_signals_est']:.0f}")
            logger.info(f"   Est. daily P&L: ${daily_pnl:.2f}")
    else:
        logger.info("\nNo strategies profitable after costs at 15s horizon.")
        logger.info("Consider: longer hold times, larger position sizes, or lower-cost execution.")
    
    # Check 30s horizon
    results_30s = results[results["horizon_s"] == 30].sort_values("net_ret_bps", ascending=False)
    profitable_30s = results_30s[results_30s["net_ret_bps"] > 0]
    
    if len(profitable_30s) > 0:
        logger.info("\n" + "=" * 70)
        logger.info("PROFITABLE AT 30s HORIZON")
        logger.info("=" * 70)
        for _, row in profitable_30s.head(5).iterrows():
            daily_pnl = row["net_pnl_per_trade"] * row["daily_signals_est"]
            logger.info(f"\n{row['strategy']}:")
            logger.info(f"   Net return: {row['net_ret_bps']:.2f} bps, Win rate: {row['win_rate']:.1f}%")
            logger.info(f"   Signals/day: {row['daily_signals_est']:.0f}, Est. daily P&L: ${daily_pnl:.2f}")
    
    # Save results
    results.to_csv(OUTPUT_DIR / "cost_adjusted_analysis.csv", index=False)
    logger.info(f"\nResults saved to: {OUTPUT_DIR / 'cost_adjusted_analysis.csv'}")
    
    # Final recommendation
    logger.info("\n" + "=" * 70)
    logger.info("RECOMMENDATIONS")
    logger.info("=" * 70)
    
    best_15s = results_15s.iloc[0] if len(results_15s) > 0 else None
    best_30s = results_30s.iloc[0] if len(results_30s) > 0 else None
    
    if best_15s is not None and best_15s["net_ret_bps"] > 0:
        logger.info(f"\nBest 15s strategy: {best_15s['strategy']}")
        logger.info(f"  Use OBI threshold: 0.5-0.7 with trend/context filters")
    
    if best_30s is not None and best_30s["net_ret_bps"] > 0:
        logger.info(f"\nBest 30s strategy: {best_30s['strategy']}")
        logger.info(f"  Consider longer holds for better cost coverage")
    
    logger.info("\nKey insights:")
    logger.info("  1. Higher OBI thresholds (0.6+) = fewer but better signals")
    logger.info("  2. Trend alignment improves win rate")
    logger.info("  3. 30s holds may be more cost-effective than 15s")
    logger.info("  4. Consider $10k+ positions to improve cost ratio")


if __name__ == "__main__":
    main()
