#!/usr/bin/env python3
"""Build 500+ features and analyze predictive value."""
import sys
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).parent))
from features_500.base_features import compute_base_features
from features_500.momentum_features import compute_momentum_features
from features_500.pattern_features import compute_pattern_features
from features_500.cross_sectional_features import compute_cross_sectional_features
from features_500.derivative_features import compute_derivative_features
from features_500.time_features import compute_time_features
from features_500.multi_timeframe_features import compute_multi_timeframe_features


def load_data() -> pd.DataFrame:
    """Load raw OHLCV data."""
    # Try predictions file with OHLCV
    pred_path = Path(__file__).parent.parent / "run" / "predictions_v4_simple.parquet"
    if pred_path.exists():
        df = pd.read_parquet(pred_path)
        # Rename ts to timestamp if needed
        if "ts" in df.columns and "timestamp" not in df.columns:
            df = df.rename(columns={"ts": "timestamp"})
        print(f"Loaded {len(df):,} rows from predictions_v4_simple.parquet")
        return df
    
    # Try gold data
    gold_path = Path(__file__).parent.parent / "data" / "gold"
    if gold_path.exists():
        dfs = []
        for f in gold_path.glob("*.parquet"):
            dfs.append(pd.read_parquet(f))
        if dfs:
            df = pd.concat(dfs, ignore_index=True)
            print(f"Loaded {len(df):,} rows from gold data")
            return df
    
    raise FileNotFoundError("No data found")


def build_all_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build all 500+ features."""
    print("\n" + "=" * 70)
    print("BUILDING 500+ FEATURES")
    print("=" * 70)
    
    # Ensure required columns
    if "returns" not in df.columns:
        df["returns"] = df.groupby("symbol")["close"].pct_change()
    
    feature_dfs = []
    
    # 1. Base features (~80)
    print("\n[1/7] Computing base features...")
    try:
        base = compute_base_features(df)
        feature_dfs.append(base)
        print(f"  → {len(base.columns)} base features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 2. Momentum features (~60)
    print("[2/7] Computing momentum features...")
    try:
        momentum = compute_momentum_features(df)
        feature_dfs.append(momentum)
        print(f"  → {len(momentum.columns)} momentum features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 3. Pattern features (~70)
    print("[3/7] Computing pattern features...")
    try:
        patterns = compute_pattern_features(df)
        feature_dfs.append(patterns)
        print(f"  → {len(patterns.columns)} pattern features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 4. Cross-sectional features (~80)
    print("[4/7] Computing cross-sectional features...")
    try:
        cross = compute_cross_sectional_features(df)
        feature_dfs.append(cross)
        print(f"  → {len(cross.columns)} cross-sectional features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 5. Derivative features (~60)
    print("[5/7] Computing derivative features...")
    try:
        deriv = compute_derivative_features(df)
        feature_dfs.append(deriv)
        print(f"  → {len(deriv.columns)} derivative features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 6. Time features (~70)
    print("[6/7] Computing time features...")
    try:
        time_feats = compute_time_features(df)
        feature_dfs.append(time_feats)
        print(f"  → {len(time_feats.columns)} time features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # 7. Multi-timeframe features (~80)
    print("[7/7] Computing multi-timeframe features...")
    try:
        mtf = compute_multi_timeframe_features(df)
        feature_dfs.append(mtf)
        print(f"  → {len(mtf.columns)} multi-timeframe features")
    except Exception as e:
        print(f"  ⚠️ Error: {e}")
    
    # Combine all features
    all_features = pd.concat(feature_dfs, axis=1)
    
    # Remove duplicates
    all_features = all_features.loc[:, ~all_features.columns.duplicated()]
    
    print(f"\n✅ Total features: {len(all_features.columns)}")
    
    return all_features


def analyze_predictive_value(df: pd.DataFrame, features: pd.DataFrame, target_col: str = "return_30min") -> pd.DataFrame:
    """Score each feature for predictive value."""
    print("\n" + "=" * 70)
    print("ANALYZING PREDICTIVE VALUE")
    print("=" * 70)
    
    # Create forward return if not exists
    if target_col not in df.columns:
        df[target_col] = df.groupby("symbol")["close"].transform(lambda x: x.shift(-6) / x - 1)
    
    target = df[target_col]
    results = []
    
    print(f"\nAnalyzing {len(features.columns)} features against {target_col}...")
    
    for i, col in enumerate(features.columns):
        if (i + 1) % 50 == 0:
            print(f"  Progress: {i + 1}/{len(features.columns)}")
        
        feat = features[col]
        
        # Skip if too many NaNs
        valid = ~(feat.isna() | target.isna())
        if valid.sum() < 1000:
            continue
        
        try:
            # Spearman correlation
            corr, pval = spearmanr(feat[valid], target[valid])
            
            # Information coefficient (IC)
            ic = corr
            
            # IC stability (rolling IC std)
            # Simplified: just use correlation
            
            results.append({
                "feature": col,
                "correlation": corr,
                "abs_corr": abs(corr),
                "p_value": pval,
                "ic": ic,
                "n_valid": valid.sum(),
            })
        except Exception:
            continue
    
    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("abs_corr", ascending=False)
    
    return results_df


def print_analysis_report(results: pd.DataFrame):
    """Print analysis report."""
    print("\n" + "=" * 70)
    print("FEATURE IMPORTANCE RANKING")
    print("=" * 70)
    
    # Significance levels
    sig_001 = (results["p_value"] < 0.001).sum()
    sig_01 = (results["p_value"] < 0.01).sum()
    sig_05 = (results["p_value"] < 0.05).sum()
    
    print(f"\nStatistical Significance:")
    print(f"  p < 0.001: {sig_001} features")
    print(f"  p < 0.01:  {sig_01} features")
    print(f"  p < 0.05:  {sig_05} features")
    
    # Top features
    print(f"\n{'='*70}")
    print("TOP 50 PREDICTIVE FEATURES")
    print(f"{'='*70}")
    print(f"{'Feature':<45} {'Corr':>10} {'P-value':>12} {'Sig':>5}")
    print("-" * 70)
    
    for _, row in results.head(50).iterrows():
        sig = "***" if row["p_value"] < 0.001 else "**" if row["p_value"] < 0.01 else "*" if row["p_value"] < 0.05 else ""
        print(f"{row['feature']:<45} {row['correlation']:>+10.4f} {row['p_value']:>12.2e} {sig:>5}")
    
    # Feature categories
    print(f"\n{'='*70}")
    print("FEATURE CATEGORY ANALYSIS")
    print(f"{'='*70}")
    
    categories = {
        "Base/Price": ["ret_", "vol_ma", "price_ma", "volatility", "range_", "atr_", "body", "wick", "gap"],
        "Momentum": ["rsi_", "stoch_", "macd_", "roc_", "momentum_", "williams_", "cci_", "trend_strength"],
        "Pattern": ["dist_to_", "pivot", "triangle", "higher_", "lower_", "linreg_", "doji", "hammer", "engulf", "consec_"],
        "Cross-sectional": ["rank_", "market_", "rel_strength", "cross_", "sector_", "beta_", "alpha_", "zscore"],
        "Derivative": ["d1_", "d2_", "d3_", "mom_d", "vol_d", "curvature"],
        "Time": ["hour", "minute", "session", "vwap", "intraday", "from_open", "from_day"],
        "Multi-timeframe": ["ma_", "ema_", "mtf_", "bb_", "mom_align", "vol_regime"],
    }
    
    for cat_name, prefixes in categories.items():
        cat_features = results[results["feature"].str.contains("|".join(prefixes), case=False, na=False)]
        if len(cat_features) > 0:
            avg_corr = cat_features["abs_corr"].mean()
            top_feat = cat_features.iloc[0]["feature"] if len(cat_features) > 0 else "N/A"
            top_corr = cat_features.iloc[0]["correlation"] if len(cat_features) > 0 else 0
            print(f"\n{cat_name}:")
            print(f"  Features: {len(cat_features)}")
            print(f"  Avg |corr|: {avg_corr:.4f}")
            print(f"  Best: {top_feat} ({top_corr:+.4f})")
    
    # Actionable features
    print(f"\n{'='*70}")
    print("ACTIONABLE FEATURES (|corr| > 0.02, p < 0.01)")
    print(f"{'='*70}")
    
    actionable = results[(results["abs_corr"] > 0.02) & (results["p_value"] < 0.01)]
    print(f"\nFound {len(actionable)} actionable features:")
    for _, row in actionable.head(30).iterrows():
        direction = "↑" if row["correlation"] > 0 else "↓"
        print(f"  {direction} {row['feature']}: {row['correlation']:+.4f}")


def main():
    """Main entry point."""
    # Load data
    df = load_data()
    
    # Build features
    features = build_all_features(df)
    
    # Analyze predictive value
    results = analyze_predictive_value(df, features)
    
    # Print report
    print_analysis_report(results)
    
    # Save results
    output_dir = Path(__file__).parent.parent / "run" / "features_500"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    results.to_csv(output_dir / "feature_importance.csv", index=False)
    features.to_parquet(output_dir / "all_features.parquet")
    
    print(f"\n✅ Results saved to {output_dir}")
    print(f"  - feature_importance.csv")
    print(f"  - all_features.parquet")
    
    return results


if __name__ == "__main__":
    main()
