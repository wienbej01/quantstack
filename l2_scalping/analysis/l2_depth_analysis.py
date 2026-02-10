#!/usr/bin/env python3
"""
L2 Depth Statistical Analysis Tool

Comprehensive analysis of order book depth and its predictive power:
1. Size-return correlation by depth level
2. Depth percentile analysis (dynamic thresholds)
3. Support/resistance detection via repeated large orders
4. Depth imbalance vs absolute size comparison
5. Time decay analysis of signals
6. Time-of-day effects (broad buckets to avoid overfitting)
7. OBI level comparison
"""

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Data paths
L2_FEATURES_DIR = Path("/home/jacobw/quantstack/data/l2/l2_maximum/features")
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output/depth_analysis")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Time-of-day buckets (ET) - economically meaningful, not data-mined
TOD_BUCKETS = {
    "opening": (9, 30, 10, 0),    # 9:30-10:00 - high vol, gaps
    "mid_morning": (10, 0, 11, 30),  # 10:00-11:30 - institutional
    "midday": (11, 30, 14, 0),    # 11:30-14:00 - lunch lull
    "afternoon": (14, 0, 15, 30),  # 14:00-15:30 - volume pickup
    "closing": (15, 30, 16, 0),   # 15:30-16:00 - MOC, high vol
}


@dataclass
class AnalysisResult:
    name: str
    description: str
    data: pd.DataFrame
    summary: str


def load_all_data() -> pd.DataFrame:
    """Load all L2 features data."""
    logger.info("Loading L2 features data...")
    dfs = []
    for pq in L2_FEATURES_DIR.rglob("*.parquet"):
        df = pd.read_parquet(pq)
        symbol = None
        for part in pq.parts:
            if part.startswith("symbol="):
                symbol = part.split("=", 1)[1]
                break
        if symbol:
            if "symbol" not in df.columns:
                df["symbol"] = symbol
            else:
                df["symbol"] = df["symbol"].fillna(symbol)
        dfs.append(df)
    
    data = pd.concat(dfs, ignore_index=True)
    data["ts"] = pd.to_datetime(data["ts_utc"])
    data = data.sort_values(["symbol", "ts"]).reset_index(drop=True)
    
    # Add time-of-day bucket
    data["hour"] = data["ts"].dt.hour
    data["minute"] = data["ts"].dt.minute
    data["time_minutes"] = data["hour"] * 60 + data["minute"]
    
    def get_tod_bucket(row):
        t = row["time_minutes"]
        for name, (h1, m1, h2, m2) in TOD_BUCKETS.items():
            start = h1 * 60 + m1
            end = h2 * 60 + m2
            if start <= t < end:
                return name
        return "other"
    
    data["tod_bucket"] = data.apply(get_tod_bucket, axis=1)
    
    logger.info(f"Loaded {len(data):,} rows, {data['symbol'].nunique()} symbols")
    return data


def compute_forward_returns(df: pd.DataFrame, horizons: list[int]) -> pd.DataFrame:
    """Compute forward returns for each horizon (in rows, ~1 row/sec)."""
    for h in horizons:
        df[f"fwd_ret_{h}s"] = df.groupby("symbol")["mid"].transform(
            lambda x: (x.shift(-h) / x - 1) * 10000
        )
    return df


def compute_signal_stats(returns: np.ndarray, min_n: int = 30) -> dict | None:
    """Compute statistics for a set of returns."""
    returns = returns[~np.isnan(returns)]
    n = len(returns)
    if n < min_n:
        return None
    
    mean_ret = float(np.mean(returns))
    std_ret = float(np.std(returns))
    t_stat = mean_ret / (std_ret / np.sqrt(n)) if std_ret > 0 else 0
    p_value = 2 * (1 - stats.t.cdf(abs(t_stat), df=n - 1)) if n > 1 else 1.0
    sharpe = mean_ret / std_ret * np.sqrt(252 * 6.5 * 3600) if std_ret > 0 else 0
    
    return {
        "mean_ret_bps": mean_ret,
        "std_ret_bps": std_ret,
        "t_stat": t_stat,
        "p_value": p_value,
        "sharpe": sharpe,
        "n_obs": n,
        "win_rate": float((returns > 0).mean()),
    }


def analyze_depth_size_correlation(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 1: Correlation between depth size and forward returns."""
    logger.info("Running depth-size correlation analysis...")
    
    results = []
    for side in ["bid", "ask"]:
        depth_col = f"depth_{side}_k"
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            valid = df[[depth_col, ret_col]].dropna()
            if len(valid) < 100:
                continue
            
            pearson_r, pearson_p = stats.pearsonr(valid[depth_col], valid[ret_col])
            spearman_r, spearman_p = stats.spearmanr(valid[depth_col], valid[ret_col])
            
            results.append({
                "side": side, "horizon_sec": h,
                "pearson_r": pearson_r, "pearson_p": pearson_p,
                "spearman_r": spearman_r, "spearman_p": spearman_p,
                "n_obs": len(valid),
            })
    
    results_df = pd.DataFrame(results)
    summary = "DEPTH-SIZE CORRELATION:\n"
    summary += "Bid depth positive r = large bids → price UP\n"
    summary += "Ask depth negative r = large asks → price DOWN\n\n"
    
    for _, row in results_df.iterrows():
        sig = "***" if row["pearson_p"] < 0.01 else "**" if row["pearson_p"] < 0.05 else ""
        summary += f"{row['side'].upper()} @ {row['horizon_sec']}s: r={row['pearson_r']:+.4f} {sig}\n"
    
    return AnalysisResult("depth_size_correlation", "Correlation between depth and returns", results_df, summary)


def analyze_depth_percentiles(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 2: Forward returns by depth percentile buckets."""
    logger.info("Running depth percentile analysis...")
    
    pct_bins = [0, 50, 75, 90, 95, 99, 100]
    pct_labels = ["0-50%", "50-75%", "75-90%", "90-95%", "95-99%", "99%+"]
    
    results = []
    for side in ["bid", "ask"]:
        depth_col = f"depth_{side}_k"
        
        # Compute percentile buckets per symbol with duplicate handling
        def safe_cut(x):
            try:
                bins = x.quantile(np.array(pct_bins)/100).values
                # Check for duplicates
                if len(np.unique(bins)) < len(bins):
                    # Use rank-based bucketing instead
                    return pd.qcut(x, q=len(pct_labels), labels=pct_labels, duplicates='drop')
                return pd.cut(x, bins=bins, labels=pct_labels, include_lowest=True, duplicates='drop')
            except:
                # Fallback: return None for symbols with insufficient variation
                return pd.Series([None] * len(x), index=x.index)
        
        df[f"{side}_pct"] = df.groupby("symbol")[depth_col].transform(safe_cut)
        
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            for bucket in pct_labels:
                mask = df[f"{side}_pct"] == bucket
                returns = df.loc[mask, ret_col].dropna().values
                if side == "ask":
                    returns = -returns
                
                stats_dict = compute_signal_stats(returns)
                if stats_dict:
                    results.append({"side": side, "percentile": bucket, "horizon_sec": h, **stats_dict})
    
    results_df = pd.DataFrame(results)
    summary = "DEPTH PERCENTILE ANALYSIS:\n"
    summary += "Per-symbol percentiles (dynamic threshold)\n\n"
    
    for h in horizons:
        summary += f"--- {h}s ---\n"
        for side in ["bid", "ask"]:
            subset = results_df[(results_df["horizon_sec"] == h) & (results_df["side"] == side)]
            for _, row in subset.iterrows():
                sig = "***" if abs(row["t_stat"]) >= 2 else ""
                summary += f"  {side} {row['percentile']:>8}: {row['mean_ret_bps']:+.2f} bps (t={row['t_stat']:+.2f}) {sig}\n"
    
    return AnalysisResult("depth_percentiles", "Returns by depth percentile", results_df, summary)


def analyze_time_of_day(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """
    Analysis 3: Time-of-day effects on signal quality.
    Uses broad economically-meaningful buckets to avoid overfitting.
    """
    logger.info("Running time-of-day analysis...")
    
    results = []
    
    # Use 90th percentile as threshold (consistent across TOD)
    for side in ["bid", "ask"]:
        depth_col = f"depth_{side}_k"
        thresh = df[depth_col].quantile(0.90)
        large_mask = df[depth_col] >= thresh
        
        for tod in TOD_BUCKETS.keys():
            tod_mask = df["tod_bucket"] == tod
            combined_mask = large_mask & tod_mask
            
            for h in horizons:
                ret_col = f"fwd_ret_{h}s"
                returns = df.loc[combined_mask, ret_col].dropna().values
                if side == "ask":
                    returns = -returns
                
                stats_dict = compute_signal_stats(returns)
                if stats_dict:
                    results.append({
                        "side": side, "tod_bucket": tod, "horizon_sec": h,
                        "threshold_k": thresh, **stats_dict
                    })
    
    results_df = pd.DataFrame(results)
    
    # Test if TOD differences are significant (ANOVA-like comparison)
    summary = "TIME-OF-DAY ANALYSIS:\n"
    summary += "Signal quality by market session (90th pct threshold)\n"
    summary += "Buckets: opening(9:30-10), mid_morning(10-11:30), midday(11:30-14), afternoon(14-15:30), closing(15:30-16)\n\n"
    
    for h in horizons:
        summary += f"--- {h}s Horizon ---\n"
        for side in ["bid", "ask"]:
            subset = results_df[(results_df["horizon_sec"] == h) & (results_df["side"] == side)]
            if len(subset) == 0:
                continue
            
            summary += f"  {side.upper()}:\n"
            best_tod = subset.loc[subset["t_stat"].abs().idxmax(), "tod_bucket"]
            
            for _, row in subset.sort_values("t_stat", ascending=False).iterrows():
                marker = " ← BEST" if row["tod_bucket"] == best_tod else ""
                sig = "***" if abs(row["t_stat"]) >= 2 else ""
                summary += f"    {row['tod_bucket']:>12}: {row['mean_ret_bps']:+.2f} bps "
                summary += f"(t={row['t_stat']:+.2f}, n={row['n_obs']:,}) {sig}{marker}\n"
    
    # Add statistical test for TOD differences
    summary += "\nSTATISTICAL TEST (Kruskal-Wallis):\n"
    summary += "Tests if TOD differences are significant vs random variation\n"
    
    for side in ["bid", "ask"]:
        depth_col = f"depth_{side}_k"
        thresh = df[depth_col].quantile(0.90)
        large_mask = df[depth_col] >= thresh
        
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            groups = []
            for tod in TOD_BUCKETS.keys():
                tod_mask = df["tod_bucket"] == tod
                returns = df.loc[large_mask & tod_mask, ret_col].dropna().values
                if side == "ask":
                    returns = -returns
                if len(returns) >= 20:
                    groups.append(returns)
            
            if len(groups) >= 2:
                stat, p = stats.kruskal(*groups)
                sig = "***" if p < 0.01 else "**" if p < 0.05 else "ns"
                summary += f"  {side} @ {h}s: H={stat:.2f}, p={p:.4f} {sig}\n"
    
    return AnalysisResult("time_of_day", "Time-of-day effects on signal quality", results_df, summary)


def analyze_obi_levels(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 4: Compare OBI at different levels."""
    logger.info("Running OBI level comparison...")
    
    obi_cols = [c for c in df.columns if c.startswith("obi_") and c[4:].isdigit()]
    
    results = []
    for obi_col in obi_cols:
        level = int(obi_col.split("_")[1])
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            valid = df[[obi_col, ret_col]].dropna()
            if len(valid) < 100:
                continue
            r, p = stats.pearsonr(valid[obi_col], valid[ret_col])
            results.append({"obi_level": level, "horizon_sec": h, "correlation_r": r, "p_value": p, "n_obs": len(valid)})
    
    results_df = pd.DataFrame(results)
    summary = "OBI LEVEL COMPARISON:\n"
    summary += "Which book level is most predictive?\n\n"
    
    for h in horizons:
        summary += f"--- {h}s ---\n"
        subset = results_df[results_df["horizon_sec"] == h].sort_values("obi_level")
        best_level = subset.loc[subset["correlation_r"].abs().idxmax(), "obi_level"]
        for _, row in subset.iterrows():
            marker = " ← BEST" if row["obi_level"] == best_level else ""
            sig = "***" if row["p_value"] < 0.01 else ""
            summary += f"  OBI_{row['obi_level']:>2}: r={row['correlation_r']:+.4f} {sig}{marker}\n"
    
    return AnalysisResult("obi_levels", "OBI predictive power by level", results_df, summary)


def analyze_imbalance_vs_size(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 5: Compare imbalance vs absolute size."""
    logger.info("Running imbalance vs size comparison...")
    
    df["depth_imbalance"] = (df["depth_bid_k"] - df["depth_ask_k"]) / (df["depth_bid_k"] + df["depth_ask_k"] + 1e-9)
    
    results = []
    for h in horizons:
        ret_col = f"fwd_ret_{h}s"
        valid = df[["depth_imbalance", "depth_bid_k", "depth_ask_k", ret_col]].dropna()
        if len(valid) < 100:
            continue
        
        imb_r, imb_p = stats.pearsonr(valid["depth_imbalance"], valid[ret_col])
        bid_r, bid_p = stats.pearsonr(valid["depth_bid_k"], valid[ret_col])
        ask_r, ask_p = stats.pearsonr(valid["depth_ask_k"], valid[ret_col])
        
        results.append({
            "horizon_sec": h,
            "imbalance_r": imb_r, "imbalance_p": imb_p,
            "bid_depth_r": bid_r, "bid_depth_p": bid_p,
            "ask_depth_r": ask_r, "ask_depth_p": ask_p,
            "n_obs": len(valid),
        })
    
    results_df = pd.DataFrame(results)
    summary = "IMBALANCE VS SIZE:\n"
    summary += "Which metric is more predictive?\n\n"
    
    for _, row in results_df.iterrows():
        summary += f"--- {row['horizon_sec']}s ---\n"
        summary += f"  Imbalance: r={row['imbalance_r']:+.4f}\n"
        summary += f"  Bid Depth: r={row['bid_depth_r']:+.4f}\n"
        summary += f"  Ask Depth: r={row['ask_depth_r']:+.4f}\n"
    
    return AnalysisResult("imbalance_vs_size", "Imbalance vs absolute size comparison", results_df, summary)


def analyze_threshold_sensitivity(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 6: Find optimal fixed threshold."""
    logger.info("Running threshold sensitivity analysis...")
    
    thresholds = [5, 10, 15, 20, 25, 30, 40, 50]
    
    results = []
    for thresh in thresholds:
        for side in ["bid", "ask"]:
            depth_col = f"depth_{side}_k"
            large_mask = df[depth_col] >= thresh
            
            for h in horizons:
                ret_col = f"fwd_ret_{h}s"
                returns = df.loc[large_mask, ret_col].dropna().values
                if side == "ask":
                    returns = -returns
                
                stats_dict = compute_signal_stats(returns)
                if stats_dict:
                    results.append({
                        "threshold_k": thresh, "side": side, "horizon_sec": h,
                        "signal_rate": large_mask.mean(), **stats_dict
                    })
    
    results_df = pd.DataFrame(results)
    summary = "THRESHOLD SENSITIVITY:\n\n"
    
    for side in ["bid", "ask"]:
        summary += f"{side.upper()} DEPTH:\n"
        for h in horizons:
            subset = results_df[(results_df["side"] == side) & (results_df["horizon_sec"] == h)]
            if len(subset) == 0:
                continue
            best = subset.loc[subset["t_stat"].abs().idxmax()]
            summary += f"  {h}s: Best=${best['threshold_k']}k (t={best['t_stat']:+.2f}, {best['mean_ret_bps']:+.2f} bps)\n"
    
    return AnalysisResult("threshold_sensitivity", "Optimal threshold analysis", results_df, summary)


def analyze_time_decay(df: pd.DataFrame) -> AnalysisResult:
    """Analysis 7: Signal time decay."""
    logger.info("Running time decay analysis...")
    
    horizons = [5, 10, 15, 30, 60, 120, 180, 300, 600]
    df = compute_forward_returns(df, horizons)
    
    results = []
    for side in ["bid", "ask"]:
        depth_col = f"depth_{side}_k"
        thresh = df[depth_col].quantile(0.90)
        large_mask = df[depth_col] >= thresh
        
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            returns = df.loc[large_mask, ret_col].dropna().values
            if side == "ask":
                returns = -returns
            
            stats_dict = compute_signal_stats(returns)
            if stats_dict:
                results.append({"side": side, "horizon_sec": h, **stats_dict})
    
    results_df = pd.DataFrame(results)
    summary = "TIME DECAY ANALYSIS:\n"
    summary += "How quickly does signal alpha decay?\n\n"
    
    for side in ["bid", "ask"]:
        summary += f"{side.upper()} (90th pct threshold):\n"
        subset = results_df[results_df["side"] == side].sort_values("horizon_sec")
        for _, row in subset.iterrows():
            bar = "█" * max(1, int(abs(row["t_stat"])))
            summary += f"  {row['horizon_sec']:>3}s: {row['mean_ret_bps']:+.2f} bps (t={row['t_stat']:+.2f}) {bar}\n"
    
    return AnalysisResult("time_decay", "Signal time decay", results_df, summary)


def analyze_support_resistance(df: pd.DataFrame, horizons: list[int]) -> AnalysisResult:
    """Analysis 8: Support/resistance via repeated large orders."""
    logger.info("Running support/resistance analysis...")
    
    results = []
    for symbol in df["symbol"].unique():
        sym_df = df[df["symbol"] == symbol].copy()
        if len(sym_df) < 1000:
            continue
        
        # Price levels (5 ticks or 5 cents)
        tick = max(sym_df["spread"].median() * 5, 0.05)
        sym_df["level"] = (sym_df["mid"] / tick).round() * tick
        
        # Large order threshold (90th pct)
        sym_df["bid_large"] = sym_df["depth_bid_k"] >= sym_df["depth_bid_k"].quantile(0.90)
        sym_df["ask_large"] = sym_df["depth_ask_k"] >= sym_df["depth_ask_k"].quantile(0.90)
        
        # Level stats
        level_stats = sym_df.groupby("level").agg({
            "mid": "count", "bid_large": "sum", "ask_large": "sum"
        }).rename(columns={"mid": "touches"})
        level_stats = level_stats[level_stats["touches"] >= 10]
        
        if len(level_stats) == 0:
            continue
        
        level_stats["bid_ratio"] = level_stats["bid_large"] / level_stats["touches"]
        level_stats["ask_ratio"] = level_stats["ask_large"] / level_stats["touches"]
        
        support_levels = level_stats[level_stats["bid_ratio"] >= 0.3].index
        resist_levels = level_stats[level_stats["ask_ratio"] >= 0.3].index
        
        for h in horizons:
            ret_col = f"fwd_ret_{h}s"
            
            # Support
            mask = sym_df["level"].isin(support_levels) & sym_df["bid_large"]
            returns = sym_df.loc[mask, ret_col].dropna().values
            stats_dict = compute_signal_stats(returns, min_n=20)
            if stats_dict:
                results.append({"symbol": symbol, "type": "support", "horizon_sec": h, "n_levels": len(support_levels), **stats_dict})
            
            # Resistance
            mask = sym_df["level"].isin(resist_levels) & sym_df["ask_large"]
            returns = -sym_df.loc[mask, ret_col].dropna().values
            stats_dict = compute_signal_stats(returns, min_n=20)
            if stats_dict:
                results.append({"symbol": symbol, "type": "resistance", "horizon_sec": h, "n_levels": len(resist_levels), **stats_dict})
    
    results_df = pd.DataFrame(results) if results else pd.DataFrame()
    
    summary = "SUPPORT/RESISTANCE ANALYSIS:\n"
    summary += "Levels with 30%+ large order occurrence rate\n\n"
    
    if len(results_df) > 0:
        agg = results_df.groupby(["type", "horizon_sec"]).agg({
            "mean_ret_bps": "mean", "n_obs": "sum", "n_levels": "sum"
        }).reset_index()
        for _, row in agg.iterrows():
            summary += f"{row['type'].upper()} @ {row['horizon_sec']}s: {row['mean_ret_bps']:+.2f} bps (n={row['n_obs']:,})\n"
    
    return AnalysisResult("support_resistance", "Support/resistance detection", results_df, summary)


def main():
    parser = argparse.ArgumentParser(description="L2 Depth Statistical Analysis")
    parser.add_argument("--horizons", type=int, nargs="+", default=[30, 60, 120, 300])
    args = parser.parse_args()
    
    print("=" * 80)
    print("L2 DEPTH STATISTICAL ANALYSIS")
    print("=" * 80)
    
    df = load_all_data()
    df = compute_forward_returns(df, args.horizons)
    
    analyses = [
        analyze_depth_size_correlation(df, args.horizons),
        analyze_depth_percentiles(df, args.horizons),
        analyze_time_of_day(df, args.horizons),
        analyze_obi_levels(df, args.horizons),
        analyze_imbalance_vs_size(df, args.horizons),
        analyze_threshold_sensitivity(df, args.horizons),
        analyze_time_decay(df),
        analyze_support_resistance(df, args.horizons),
    ]
    
    print("\n" + "=" * 80)
    print("RESULTS")
    print("=" * 80)
    
    for analysis in analyses:
        print(f"\n{'='*80}")
        print(f"[{analysis.name.upper()}]")
        print("=" * 80)
        print(analysis.summary)
        
        if len(analysis.data) > 0:
            output_file = OUTPUT_DIR / f"{analysis.name}.csv"
            analysis.data.to_csv(output_file, index=False)
            print(f"Saved: {output_file}")
    
    # Save summary
    summary_file = OUTPUT_DIR / "analysis_summary.txt"
    with open(summary_file, "w") as f:
        for analysis in analyses:
            f.write(f"\n{'='*80}\n[{analysis.name.upper()}]\n{'='*80}\n")
            f.write(analysis.summary + "\n")
    print(f"\nFull summary: {summary_file}")


if __name__ == "__main__":
    main()
