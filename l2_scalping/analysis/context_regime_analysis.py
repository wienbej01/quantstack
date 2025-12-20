#!/usr/bin/env python3
"""
L2 Scalping Context Analysis - Market Regime & Environment Filtering

Context features used for:
1. Market regime detection (trending vs ranging)
2. Support/resistance awareness
3. Favorable trading conditions (not signal generation)
"""

import logging
from pathlib import Path

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")


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
            from l2_context_analysis import download_polygon_bars
            bars = download_polygon_bars(symbol, str(date))
            if bars is not None:
                all_bars.append(bars)
        if all_bars:
            bars_dict[symbol] = pd.concat(all_bars, ignore_index=True)
    
    merged = merge_l2_with_context(l2_df, bars_dict)
    merged = compute_forward_returns(merged)
    return merged


def analyze_regime_performance(df: pd.DataFrame) -> dict:
    """Analyze L2 signal performance across different market regimes"""
    
    # Generate base L2 signal (OBI > 0.3)
    df["l2_signal"] = (df["obi_1"] > 0.3).astype(int) - (df["obi_1"] < -0.3).astype(int)
    signals = df[df["l2_signal"] != 0].copy()
    signals["aligned_ret_10s"] = signals["l2_signal"] * signals["fwd_ret_10s"]
    
    results = {}
    
    # 1. TREND REGIME: Trading with vs against trend
    logger.info("\n" + "=" * 60)
    logger.info("1. TREND ALIGNMENT (mom_15 = 15-bar momentum)")
    logger.info("=" * 60)
    
    # With trend: L2 signal matches momentum direction
    with_trend = signals[
        ((signals["l2_signal"] == 1) & (signals["mom_15"] > 0)) |
        ((signals["l2_signal"] == -1) & (signals["mom_15"] < 0))
    ]
    against_trend = signals[
        ((signals["l2_signal"] == 1) & (signals["mom_15"] < 0)) |
        ((signals["l2_signal"] == -1) & (signals["mom_15"] > 0))
    ]
    
    results["with_trend"] = {
        "n": len(with_trend),
        "mean_ret": with_trend["aligned_ret_10s"].mean(),
        "win_rate": (with_trend["aligned_ret_10s"] > 0).mean() * 100,
    }
    results["against_trend"] = {
        "n": len(against_trend),
        "mean_ret": against_trend["aligned_ret_10s"].mean(),
        "win_rate": (against_trend["aligned_ret_10s"] > 0).mean() * 100,
    }
    
    logger.info(f"WITH TREND:    {results['with_trend']['n']:,} signals, "
                f"{results['with_trend']['mean_ret']:.2f} bps, "
                f"{results['with_trend']['win_rate']:.1f}% win rate")
    logger.info(f"AGAINST TREND: {results['against_trend']['n']:,} signals, "
                f"{results['against_trend']['mean_ret']:.2f} bps, "
                f"{results['against_trend']['win_rate']:.1f}% win rate")
    
    # 2. VWAP POSITION: Above vs below VWAP
    logger.info("\n" + "=" * 60)
    logger.info("2. VWAP POSITION (support/resistance proxy)")
    logger.info("=" * 60)
    
    # Buy signals when price below VWAP (support), sell when above (resistance)
    favorable_vwap = signals[
        ((signals["l2_signal"] == 1) & (signals["vwap_dist"] < 0)) |
        ((signals["l2_signal"] == -1) & (signals["vwap_dist"] > 0))
    ]
    unfavorable_vwap = signals[
        ((signals["l2_signal"] == 1) & (signals["vwap_dist"] > 0)) |
        ((signals["l2_signal"] == -1) & (signals["vwap_dist"] < 0))
    ]
    
    results["favorable_vwap"] = {
        "n": len(favorable_vwap),
        "mean_ret": favorable_vwap["aligned_ret_10s"].mean(),
        "win_rate": (favorable_vwap["aligned_ret_10s"] > 0).mean() * 100,
    }
    results["unfavorable_vwap"] = {
        "n": len(unfavorable_vwap),
        "mean_ret": unfavorable_vwap["aligned_ret_10s"].mean(),
        "win_rate": (unfavorable_vwap["aligned_ret_10s"] > 0).mean() * 100,
    }
    
    logger.info(f"FAVORABLE VWAP (buy<VWAP, sell>VWAP): {results['favorable_vwap']['n']:,} signals, "
                f"{results['favorable_vwap']['mean_ret']:.2f} bps, "
                f"{results['favorable_vwap']['win_rate']:.1f}% win rate")
    logger.info(f"UNFAVORABLE VWAP:                     {results['unfavorable_vwap']['n']:,} signals, "
                f"{results['unfavorable_vwap']['mean_ret']:.2f} bps, "
                f"{results['unfavorable_vwap']['win_rate']:.1f}% win rate")
    
    # 3. VOLATILITY REGIME: High vs low ATR
    logger.info("\n" + "=" * 60)
    logger.info("3. VOLATILITY REGIME (ATR percentile)")
    logger.info("=" * 60)
    
    atr_median = signals["atr_pct"].median()
    high_vol = signals[signals["atr_pct"] > atr_median]
    low_vol = signals[signals["atr_pct"] <= atr_median]
    
    results["high_volatility"] = {
        "n": len(high_vol),
        "mean_ret": high_vol["aligned_ret_10s"].mean(),
        "win_rate": (high_vol["aligned_ret_10s"] > 0).mean() * 100,
    }
    results["low_volatility"] = {
        "n": len(low_vol),
        "mean_ret": low_vol["aligned_ret_10s"].mean(),
        "win_rate": (low_vol["aligned_ret_10s"] > 0).mean() * 100,
    }
    
    logger.info(f"HIGH VOLATILITY: {results['high_volatility']['n']:,} signals, "
                f"{results['high_volatility']['mean_ret']:.2f} bps, "
                f"{results['high_volatility']['win_rate']:.1f}% win rate")
    logger.info(f"LOW VOLATILITY:  {results['low_volatility']['n']:,} signals, "
                f"{results['low_volatility']['mean_ret']:.2f} bps, "
                f"{results['low_volatility']['win_rate']:.1f}% win rate")
    
    # 4. RSI REGIME: Overbought/oversold awareness
    logger.info("\n" + "=" * 60)
    logger.info("4. RSI REGIME (overbought/oversold awareness)")
    logger.info("=" * 60)
    
    # Avoid buying when overbought, avoid selling when oversold
    rsi_favorable = signals[
        ((signals["l2_signal"] == 1) & (signals["rsi_14"] < 70)) |
        ((signals["l2_signal"] == -1) & (signals["rsi_14"] > 30))
    ]
    rsi_unfavorable = signals[
        ((signals["l2_signal"] == 1) & (signals["rsi_14"] >= 70)) |
        ((signals["l2_signal"] == -1) & (signals["rsi_14"] <= 30))
    ]
    
    results["rsi_favorable"] = {
        "n": len(rsi_favorable),
        "mean_ret": rsi_favorable["aligned_ret_10s"].mean(),
        "win_rate": (rsi_favorable["aligned_ret_10s"] > 0).mean() * 100,
    }
    results["rsi_unfavorable"] = {
        "n": len(rsi_unfavorable),
        "mean_ret": rsi_unfavorable["aligned_ret_10s"].mean() if len(rsi_unfavorable) > 0 else 0,
        "win_rate": (rsi_unfavorable["aligned_ret_10s"] > 0).mean() * 100 if len(rsi_unfavorable) > 0 else 0,
    }
    
    logger.info(f"RSI FAVORABLE (not extreme): {results['rsi_favorable']['n']:,} signals, "
                f"{results['rsi_favorable']['mean_ret']:.2f} bps, "
                f"{results['rsi_favorable']['win_rate']:.1f}% win rate")
    logger.info(f"RSI UNFAVORABLE (extreme):   {results['rsi_unfavorable']['n']:,} signals, "
                f"{results['rsi_unfavorable']['mean_ret']:.2f} bps, "
                f"{results['rsi_unfavorable']['win_rate']:.1f}% win rate")
    
    # 5. VOLUME REGIME: High vs normal volume
    logger.info("\n" + "=" * 60)
    logger.info("5. VOLUME REGIME (relative volume)")
    logger.info("=" * 60)
    
    high_volume = signals[signals["rel_vol"] > 1.5]
    normal_volume = signals[(signals["rel_vol"] >= 0.5) & (signals["rel_vol"] <= 1.5)]
    low_volume = signals[signals["rel_vol"] < 0.5]
    
    results["high_volume"] = {
        "n": len(high_volume),
        "mean_ret": high_volume["aligned_ret_10s"].mean() if len(high_volume) > 0 else 0,
        "win_rate": (high_volume["aligned_ret_10s"] > 0).mean() * 100 if len(high_volume) > 0 else 0,
    }
    results["normal_volume"] = {
        "n": len(normal_volume),
        "mean_ret": normal_volume["aligned_ret_10s"].mean(),
        "win_rate": (normal_volume["aligned_ret_10s"] > 0).mean() * 100,
    }
    results["low_volume"] = {
        "n": len(low_volume),
        "mean_ret": low_volume["aligned_ret_10s"].mean() if len(low_volume) > 0 else 0,
        "win_rate": (low_volume["aligned_ret_10s"] > 0).mean() * 100 if len(low_volume) > 0 else 0,
    }
    
    logger.info(f"HIGH VOLUME (>1.5x):   {results['high_volume']['n']:,} signals, "
                f"{results['high_volume']['mean_ret']:.2f} bps, "
                f"{results['high_volume']['win_rate']:.1f}% win rate")
    logger.info(f"NORMAL VOLUME:         {results['normal_volume']['n']:,} signals, "
                f"{results['normal_volume']['mean_ret']:.2f} bps, "
                f"{results['normal_volume']['win_rate']:.1f}% win rate")
    logger.info(f"LOW VOLUME (<0.5x):    {results['low_volume']['n']:,} signals, "
                f"{results['low_volume']['mean_ret']:.2f} bps, "
                f"{results['low_volume']['win_rate']:.1f}% win rate")
    
    # 6. COMBINED FAVORABLE CONDITIONS
    logger.info("\n" + "=" * 60)
    logger.info("6. COMBINED FAVORABLE CONDITIONS")
    logger.info("=" * 60)
    
    # All favorable: with trend + favorable VWAP + not extreme RSI
    all_favorable = signals[
        (
            ((signals["l2_signal"] == 1) & (signals["mom_15"] > 0)) |
            ((signals["l2_signal"] == -1) & (signals["mom_15"] < 0))
        ) &
        (
            ((signals["l2_signal"] == 1) & (signals["vwap_dist"] < 0)) |
            ((signals["l2_signal"] == -1) & (signals["vwap_dist"] > 0))
        ) &
        (
            ((signals["l2_signal"] == 1) & (signals["rsi_14"] < 70)) |
            ((signals["l2_signal"] == -1) & (signals["rsi_14"] > 30))
        )
    ]
    
    all_unfavorable = signals[
        (
            ((signals["l2_signal"] == 1) & (signals["mom_15"] < 0)) |
            ((signals["l2_signal"] == -1) & (signals["mom_15"] > 0))
        ) &
        (
            ((signals["l2_signal"] == 1) & (signals["vwap_dist"] > 0)) |
            ((signals["l2_signal"] == -1) & (signals["vwap_dist"] < 0))
        )
    ]
    
    results["all_favorable"] = {
        "n": len(all_favorable),
        "mean_ret": all_favorable["aligned_ret_10s"].mean() if len(all_favorable) > 0 else 0,
        "win_rate": (all_favorable["aligned_ret_10s"] > 0).mean() * 100 if len(all_favorable) > 0 else 0,
    }
    results["all_unfavorable"] = {
        "n": len(all_unfavorable),
        "mean_ret": all_unfavorable["aligned_ret_10s"].mean() if len(all_unfavorable) > 0 else 0,
        "win_rate": (all_unfavorable["aligned_ret_10s"] > 0).mean() * 100 if len(all_unfavorable) > 0 else 0,
    }
    
    baseline_ret = signals["aligned_ret_10s"].mean()
    baseline_wr = (signals["aligned_ret_10s"] > 0).mean() * 100
    
    logger.info(f"BASELINE (all L2 signals):  {len(signals):,} signals, "
                f"{baseline_ret:.2f} bps, {baseline_wr:.1f}% win rate")
    logger.info(f"ALL FAVORABLE CONDITIONS:   {results['all_favorable']['n']:,} signals, "
                f"{results['all_favorable']['mean_ret']:.2f} bps, "
                f"{results['all_favorable']['win_rate']:.1f}% win rate")
    logger.info(f"ALL UNFAVORABLE CONDITIONS: {results['all_unfavorable']['n']:,} signals, "
                f"{results['all_unfavorable']['mean_ret']:.2f} bps, "
                f"{results['all_unfavorable']['win_rate']:.1f}% win rate")
    
    return results


def main():
    logger.info("=" * 70)
    logger.info("L2 SCALPING - CONTEXT AS REGIME/ENVIRONMENT FILTER")
    logger.info("=" * 70)
    logger.info("\nContext features used for AWARENESS, not signal generation:")
    logger.info("- Trend alignment (trade with market direction)")
    logger.info("- VWAP position (support/resistance awareness)")
    logger.info("- Volatility regime (adjust expectations)")
    logger.info("- RSI extremes (avoid overbought/oversold)")
    logger.info("- Volume regime (liquidity awareness)")
    
    logger.info("\nLoading data...")
    df = load_data()
    
    results = analyze_regime_performance(df)
    
    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("SUMMARY: CONTEXT AS FILTER EFFECTIVENESS")
    logger.info("=" * 70)
    
    improvements = []
    baseline = 0.55  # baseline L2 signal return
    
    for regime, data in results.items():
        if "favorable" in regime or regime == "with_trend" or regime == "high_volume":
            if data["n"] > 100:
                improvement = data["mean_ret"] - baseline
                improvements.append((regime, improvement, data["mean_ret"], data["win_rate"], data["n"]))
    
    improvements.sort(key=lambda x: x[1], reverse=True)
    
    logger.info("\nFavorable conditions ranked by improvement over baseline:")
    for regime, imp, ret, wr, n in improvements:
        logger.info(f"  {regime}: {ret:.2f} bps ({imp:+.2f} vs baseline), {wr:.1f}% WR, {n:,} signals")
    
    # Save results
    results_df = pd.DataFrame(results).T
    results_df.to_csv(OUTPUT_DIR / "context_regime_analysis.csv")
    logger.info(f"\nResults saved to: {OUTPUT_DIR / 'context_regime_analysis.csv'}")


if __name__ == "__main__":
    main()
