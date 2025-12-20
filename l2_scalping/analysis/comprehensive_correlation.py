#!/usr/bin/env python3
"""
Comprehensive L2 Scalping Context Feature Correlation Analysis

Analyzes correlation between L2 signals and:
1. Technical indicators (RSI, MACD, Bollinger, etc.)
2. Volume Profile Analysis (VPA)
3. ICT concepts (liquidity, order blocks, FVG)
4. Cross-sectional/market features
5. Multi-timeframe alignment
6. Time-of-day effects
"""

import logging
from pathlib import Path
import numpy as np
import pandas as pd
from scipy.stats import spearmanr, pearsonr

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")


def load_l2_data():
    """Load L2 data"""
    from l2_context_analysis import load_l2_data as _load
    return _load()


def download_bars(symbol, date):
    """Download 1-min bars"""
    from l2_context_analysis import download_polygon_bars
    return download_polygon_bars(symbol, date)


def compute_comprehensive_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute 100+ context features from 1-min OHLCV"""
    df = bars.copy()
    
    # === 1. BASIC PRICE FEATURES ===
    df["returns"] = df["close"].pct_change()
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))
    df["range"] = df["high"] - df["low"]
    df["body"] = df["close"] - df["open"]
    df["body_pct"] = df["body"] / (df["range"] + 1e-8)
    
    # === 2. MOVING AVERAGES ===
    for lb in [5, 10, 20, 50]:
        df[f"sma_{lb}"] = df["close"].rolling(lb, min_periods=1).mean()
        df[f"ema_{lb}"] = df["close"].ewm(span=lb, adjust=False).mean()
        df[f"price_vs_sma_{lb}"] = (df["close"] - df[f"sma_{lb}"]) / df[f"sma_{lb}"] * 10000  # bps
        df[f"price_vs_ema_{lb}"] = (df["close"] - df[f"ema_{lb}"]) / df[f"ema_{lb}"] * 10000
    
    # MA alignment
    df["ma_align_short"] = (np.sign(df["price_vs_sma_5"]) + np.sign(df["price_vs_sma_10"]) + np.sign(df["price_vs_sma_20"])) / 3
    
    # === 3. MOMENTUM ===
    for lb in [1, 3, 5, 10, 14, 15, 20, 30]:
        df[f"mom_{lb}"] = df["close"].pct_change(lb) * 10000  # bps
    
    df["mom_accel"] = df["mom_5"] - df["mom_5"].shift(5)
    
    # === 4. RSI ===
    delta = df["close"].diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    for lb in [5, 9, 14, 21]:
        avg_gain = gain.rolling(lb, min_periods=1).mean()
        avg_loss = loss.rolling(lb, min_periods=1).mean()
        rs = avg_gain / (avg_loss + 1e-8)
        df[f"rsi_{lb}"] = 100 - (100 / (1 + rs))
    
    df["rsi_divergence"] = df["rsi_5"] - df["rsi_14"]
    df["rsi_extreme"] = ((df["rsi_14"] > 70) | (df["rsi_14"] < 30)).astype(int)
    df["rsi_overbought"] = (df["rsi_14"] > 70).astype(int)
    df["rsi_oversold"] = (df["rsi_14"] < 30).astype(int)
    
    # === 5. MACD ===
    ema_12 = df["close"].ewm(span=12, adjust=False).mean()
    ema_26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = (ema_12 - ema_26) / df["close"] * 10000
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_signal"]
    df["macd_cross_up"] = ((df["macd"] > df["macd_signal"]) & (df["macd"].shift(1) <= df["macd_signal"].shift(1))).astype(int)
    df["macd_cross_down"] = ((df["macd"] < df["macd_signal"]) & (df["macd"].shift(1) >= df["macd_signal"].shift(1))).astype(int)
    
    # === 6. BOLLINGER BANDS ===
    for lb in [10, 20]:
        ma = df["close"].rolling(lb, min_periods=1).mean()
        std = df["close"].rolling(lb, min_periods=1).std()
        df[f"bb_upper_{lb}"] = ma + 2 * std
        df[f"bb_lower_{lb}"] = ma - 2 * std
        df[f"bb_width_{lb}"] = 4 * std / (ma + 1e-8) * 10000
        df[f"bb_position_{lb}"] = (df["close"] - df[f"bb_lower_{lb}"]) / (4 * std + 1e-8)
        df[f"bb_squeeze_{lb}"] = (df[f"bb_width_{lb}"] < df[f"bb_width_{lb}"].rolling(20).mean() * 0.8).astype(int)
    
    # === 7. STOCHASTIC ===
    for lb in [5, 14]:
        low_min = df["low"].rolling(lb, min_periods=1).min()
        high_max = df["high"].rolling(lb, min_periods=1).max()
        df[f"stoch_k_{lb}"] = 100 * (df["close"] - low_min) / (high_max - low_min + 1e-8)
        df[f"stoch_d_{lb}"] = df[f"stoch_k_{lb}"].rolling(3, min_periods=1).mean()
    
    # === 8. ATR / VOLATILITY ===
    tr = pd.concat([
        df["high"] - df["low"],
        abs(df["high"] - df["close"].shift(1)),
        abs(df["low"] - df["close"].shift(1))
    ], axis=1).max(axis=1)
    
    for lb in [5, 14, 20]:
        df[f"atr_{lb}"] = tr.rolling(lb, min_periods=1).mean()
        df[f"atr_pct_{lb}"] = df[f"atr_{lb}"] / df["close"] * 10000
        df[f"volatility_{lb}"] = df["returns"].rolling(lb, min_periods=1).std() * 10000
    
    df["vol_regime"] = df["volatility_5"] / (df["volatility_20"] + 1e-8)
    df["vol_expansion"] = (df["vol_regime"] > 1.5).astype(int)
    df["vol_contraction"] = (df["vol_regime"] < 0.5).astype(int)
    
    # === 9. VWAP ===
    typical = (df["high"] + df["low"] + df["close"]) / 3
    df["cum_vol"] = df["volume"].cumsum()
    df["cum_vwap"] = (typical * df["volume"]).cumsum()
    df["vwap"] = df["cum_vwap"] / df["cum_vol"]
    df["vwap_dist"] = (df["close"] - df["vwap"]) / df["vwap"] * 10000
    df["above_vwap"] = (df["close"] > df["vwap"]).astype(int)
    
    # === 10. VOLUME PROFILE ANALYSIS (VPA) ===
    df["vol_ma_20"] = df["volume"].rolling(20, min_periods=1).mean()
    df["rel_vol"] = df["volume"] / (df["vol_ma_20"] + 1)
    df["high_vol"] = (df["rel_vol"] > 2.0).astype(int)
    df["low_vol"] = (df["rel_vol"] < 0.5).astype(int)
    
    # Volume-price relationship
    df["vol_up"] = ((df["returns"] > 0) & (df["rel_vol"] > 1.2)).astype(int)
    df["vol_down"] = ((df["returns"] < 0) & (df["rel_vol"] > 1.2)).astype(int)
    df["vol_price_confirm"] = ((df["returns"] > 0) & (df["rel_vol"] > 1)) | ((df["returns"] < 0) & (df["rel_vol"] > 1))
    
    # Climax detection
    df["buying_climax"] = ((df["returns"] > df["returns"].rolling(20).quantile(0.9)) & (df["rel_vol"] > 2)).astype(int)
    df["selling_climax"] = ((df["returns"] < df["returns"].rolling(20).quantile(0.1)) & (df["rel_vol"] > 2)).astype(int)
    
    # === 11. ICT CONCEPTS ===
    # Liquidity levels (swing highs/lows)
    df["swing_high"] = ((df["high"] > df["high"].shift(1)) & (df["high"] > df["high"].shift(-1))).astype(int)
    df["swing_low"] = ((df["low"] < df["low"].shift(1)) & (df["low"] < df["low"].shift(-1))).astype(int)
    
    # Distance to recent swing
    df["dist_to_swing_high"] = (df["high"].rolling(20).max() - df["close"]) / df["close"] * 10000
    df["dist_to_swing_low"] = (df["close"] - df["low"].rolling(20).min()) / df["close"] * 10000
    
    # Fair Value Gap (FVG) proxy
    df["gap_up"] = (df["low"] > df["high"].shift(2)).astype(int)
    df["gap_down"] = (df["high"] < df["low"].shift(2)).astype(int)
    
    # Order block proxy (large candle followed by reversal)
    large_candle = abs(df["body"]) > df["range"].rolling(20).mean() * 1.5
    df["bull_ob"] = (large_candle & (df["body"] > 0) & (df["returns"].shift(-1) < 0)).astype(int)
    df["bear_ob"] = (large_candle & (df["body"] < 0) & (df["returns"].shift(-1) > 0)).astype(int)
    
    # Displacement (strong move)
    df["displacement_up"] = (df["returns"] > df["returns"].rolling(20).std() * 2).astype(int)
    df["displacement_down"] = (df["returns"] < -df["returns"].rolling(20).std() * 2).astype(int)
    
    # === 12. SUPPORT/RESISTANCE ===
    for lb in [10, 20, 50]:
        df[f"resistance_{lb}"] = df["high"].rolling(lb, min_periods=1).max()
        df[f"support_{lb}"] = df["low"].rolling(lb, min_periods=1).min()
        df[f"range_position_{lb}"] = (df["close"] - df[f"support_{lb}"]) / (df[f"resistance_{lb}"] - df[f"support_{lb}"] + 1e-8)
        df[f"near_resistance_{lb}"] = (df["close"] > df[f"resistance_{lb}"] * 0.995).astype(int)
        df[f"near_support_{lb}"] = (df["close"] < df[f"support_{lb}"] * 1.005).astype(int)
    
    # === 13. CANDLESTICK PATTERNS ===
    df["doji"] = (abs(df["body"]) / (df["range"] + 1e-8) < 0.1).astype(int)
    df["hammer"] = ((df["body"] > 0) & ((df["open"] - df["low"]) > 2 * abs(df["body"]))).astype(int)
    df["shooting_star"] = ((df["body"] < 0) & ((df["high"] - df["open"]) > 2 * abs(df["body"]))).astype(int)
    df["engulfing_bull"] = ((df["body"] > 0) & (df["body"].shift(1) < 0) & (abs(df["body"]) > abs(df["body"].shift(1)))).astype(int)
    df["engulfing_bear"] = ((df["body"] < 0) & (df["body"].shift(1) > 0) & (abs(df["body"]) > abs(df["body"].shift(1)))).astype(int)
    
    # === 14. TREND STRENGTH ===
    df["adx_proxy"] = abs(df["mom_14"]) / (df["volatility_14"] + 1e-8)
    df["trend_strength"] = abs(df["price_vs_sma_20"]) / (df["bb_width_20"] + 1e-8)
    df["trending"] = (df["adx_proxy"] > df["adx_proxy"].rolling(20).quantile(0.7)).astype(int)
    df["ranging"] = (df["adx_proxy"] < df["adx_proxy"].rolling(20).quantile(0.3)).astype(int)
    
    # === 15. TIME OF DAY ===
    if "timestamp" in df.columns:
        ts = pd.to_datetime(df["timestamp"])
        hour = ts.dt.hour + ts.dt.minute / 60
        df["hour"] = hour
        df["market_open"] = ((hour >= 9.5) & (hour < 10.5)).astype(int)
        df["mid_day"] = ((hour >= 11) & (hour < 14)).astype(int)
        df["power_hour"] = (hour >= 15).astype(int)
        df["first_30min"] = (hour < 10).astype(int)
        df["last_30min"] = (hour >= 15.5).astype(int)
    
    # === 16. CONSECUTIVE MOVES ===
    df["consec_up"] = (df["returns"] > 0).rolling(5, min_periods=1).sum()
    df["consec_down"] = (df["returns"] < 0).rolling(5, min_periods=1).sum()
    
    return df


def run_correlation_analysis():
    """Run comprehensive correlation analysis"""
    logger.info("=" * 70)
    logger.info("COMPREHENSIVE L2 SCALPING CONTEXT CORRELATION ANALYSIS")
    logger.info("=" * 70)
    
    # Load L2 data
    logger.info("\nLoading L2 data...")
    l2_df = load_l2_data()
    
    # Filter to symbols with substantial data (>10k records)
    symbol_counts = l2_df.groupby("symbol").size()
    good_symbols = symbol_counts[symbol_counts > 10000].index.tolist()
    l2_df = l2_df[l2_df["symbol"].isin(good_symbols)]
    
    symbols = l2_df["symbol"].unique().tolist()
    dates = l2_df["ts_utc"].dt.date.unique()
    
    logger.info(f"Symbols with >10k records: {symbols}")
    logger.info(f"Dates: {len(dates)}")
    
    # Download and compute features for each symbol
    logger.info("\nDownloading bars and computing features...")
    all_merged = []
    
    for symbol in symbols:
        bars_list = []
        for date in dates:
            bars = download_bars(symbol, str(date))
            if bars is not None:
                bars_list.append(bars)
        
        if not bars_list:
            continue
        
        bars = pd.concat(bars_list, ignore_index=True)
        bars = compute_comprehensive_features(bars)
        bars["minute"] = pd.to_datetime(bars["timestamp"]).dt.floor("min")
        
        # Get L2 data for this symbol
        l2_sym = l2_df[l2_df["symbol"] == symbol].copy().sort_values("ts_utc").reset_index(drop=True)
        l2_sym["minute"] = l2_sym["ts_utc"].dt.floor("min")
        
        # Compute forward returns using time-based lookup (more robust)
        l2_sym["ts_epoch_s"] = l2_sym["ts_utc"].astype(np.int64) // 10**9
        for h in [60, 300]:
            target_time = l2_sym["ts_epoch_s"] + h
            # Find closest future price
            fwd_prices = []
            mid_arr = l2_sym["mid"].values
            ts_arr = l2_sym["ts_epoch_s"].values
            for i, t in enumerate(target_time):
                # Find index where ts >= target
                future_idx = np.searchsorted(ts_arr, t)
                if future_idx < len(mid_arr):
                    fwd_prices.append(mid_arr[future_idx])
                else:
                    fwd_prices.append(np.nan)
            l2_sym[f"fwd_ret_{h}s"] = (np.array(fwd_prices) / l2_sym["mid"].values - 1) * 10000
        
        logger.info(f"{symbol}: {len(l2_sym):,} L2 records, {l2_sym['fwd_ret_300s'].notna().sum():,} valid fwd returns")
        
        # Merge
        merged = pd.merge_asof(
            l2_sym.sort_values("ts_utc"),
            bars.sort_values("minute"),
            left_on="minute",
            right_on="minute",
            direction="backward"
        )
        all_merged.append(merged)
    
    df = pd.concat(all_merged, ignore_index=True)
    logger.info(f"Merged data: {len(df):,} rows")
    
    # Generate L2 signal
    df["l2_signal"] = (df["obi_1"] > 0.5).astype(int) - (df["obi_1"] < -0.5).astype(int)
    df["aligned_ret_300s"] = df["l2_signal"] * df["fwd_ret_300s"]
    
    # Get feature columns
    l2_features = ["obi_1", "obi_3", "obi_5", "depth_imb_k", "pressure_k", "spread", "d_mid_5s", "d_mid_15s"]
    
    context_features = [c for c in df.columns if any(x in c for x in [
        "sma", "ema", "mom_", "rsi", "macd", "bb_", "stoch", "atr", "volatility",
        "vwap", "vol_", "rel_vol", "high_vol", "swing", "dist_to", "gap", "ob",
        "displacement", "resistance", "support", "range_position", "near_",
        "doji", "hammer", "engulfing", "adx", "trend", "ranging", "hour",
        "market_open", "power_hour", "consec", "climax"
    ]) and c in df.columns and df[c].dtype in [np.float64, np.int64, float, int]]
    
    context_features = list(set(context_features))[:80]  # Limit
    
    logger.info(f"\nAnalyzing {len(l2_features)} L2 features and {len(context_features)} context features")
    
    # Compute correlations with forward return
    logger.info("\n" + "=" * 70)
    logger.info("CORRELATION WITH 5-MINUTE FORWARD RETURN")
    logger.info("=" * 70)
    
    correlations = []
    
    for feat in l2_features + context_features:
        if feat not in df.columns:
            continue
        
        valid = df[feat].notna() & df["fwd_ret_300s"].notna()
        if valid.sum() < 100:
            continue
        
        try:
            corr, pval = spearmanr(df.loc[valid, feat], df.loc[valid, "fwd_ret_300s"])
            if not np.isnan(corr):
                correlations.append({
                    "feature": feat,
                    "type": "L2" if feat in l2_features else "Context",
                    "correlation": corr,
                    "p_value": pval,
                    "abs_corr": abs(corr),
                })
        except:
            pass
    
    if not correlations:
        logger.error("No valid correlations computed! Check data.")
        return pd.DataFrame(), pd.DataFrame()
    
    corr_df = pd.DataFrame(correlations).sort_values("abs_corr", ascending=False)
    
    # Print top correlations
    logger.info("\nTOP 30 FEATURES BY CORRELATION WITH FORWARD RETURN:")
    logger.info("-" * 70)
    for _, row in corr_df.head(30).iterrows():
        sig = "***" if row["p_value"] < 0.001 else "**" if row["p_value"] < 0.01 else "*" if row["p_value"] < 0.05 else ""
        logger.info(f"{row['type']:8} {row['feature']:30} {row['correlation']:+.4f} {sig}")
    
    # Analyze by category
    logger.info("\n" + "=" * 70)
    logger.info("CORRELATION BY FEATURE CATEGORY")
    logger.info("=" * 70)
    
    categories = {
        "L2 Order Book": ["obi", "depth", "pressure", "spread"],
        "Momentum": ["mom_", "ret_"],
        "RSI": ["rsi"],
        "MACD": ["macd"],
        "Bollinger": ["bb_"],
        "Volatility/ATR": ["atr", "volatility", "vol_regime"],
        "VWAP": ["vwap"],
        "Volume": ["vol_", "rel_vol", "high_vol", "climax"],
        "ICT/Liquidity": ["swing", "gap", "ob", "displacement", "dist_to"],
        "Support/Resistance": ["resistance", "support", "range_position", "near_"],
        "Candlestick": ["doji", "hammer", "engulfing"],
        "Trend": ["adx", "trend", "ranging", "ma_align"],
        "Time": ["hour", "market_open", "power_hour"],
    }
    
    for cat_name, keywords in categories.items():
        cat_feats = corr_df[corr_df["feature"].apply(lambda x: any(k in x for k in keywords))]
        if len(cat_feats) > 0:
            best = cat_feats.iloc[0]
            avg_corr = cat_feats["abs_corr"].mean()
            logger.info(f"\n{cat_name}:")
            logger.info(f"  Best: {best['feature']} ({best['correlation']:+.4f})")
            logger.info(f"  Avg |corr|: {avg_corr:.4f}")
    
    # Conditional analysis: L2 signal performance by context
    logger.info("\n" + "=" * 70)
    logger.info("L2 SIGNAL PERFORMANCE BY CONTEXT REGIME")
    logger.info("=" * 70)
    
    signals = df[df["l2_signal"] != 0].copy()
    baseline_ret = signals["aligned_ret_300s"].mean()
    baseline_wr = (signals["aligned_ret_300s"] > 0).mean() * 100
    
    logger.info(f"\nBaseline (all L2 signals): {baseline_ret:.2f} bps, {baseline_wr:.1f}% WR, {len(signals):,} signals")
    
    # Test each context condition
    conditions = {
        "RSI < 30 (oversold)": signals["rsi_14"] < 30,
        "RSI > 70 (overbought)": signals["rsi_14"] > 70,
        "RSI 40-60 (neutral)": (signals["rsi_14"] >= 40) & (signals["rsi_14"] <= 60),
        "Above VWAP": signals["above_vwap"] == 1,
        "Below VWAP": signals["above_vwap"] == 0,
        "High volume (>2x)": signals["rel_vol"] > 2.0,
        "Low volume (<0.5x)": signals["rel_vol"] < 0.5,
        "Trending (ADX high)": signals["trending"] == 1,
        "Ranging (ADX low)": signals["ranging"] == 1,
        "Vol expansion": signals["vol_expansion"] == 1,
        "Vol contraction": signals["vol_contraction"] == 1,
        "Near resistance": signals["near_resistance_20"] == 1,
        "Near support": signals["near_support_20"] == 1,
        "Market open (9:30-10:30)": signals["market_open"] == 1,
        "Power hour (15:00+)": signals["power_hour"] == 1,
        "BB squeeze": signals["bb_squeeze_20"] == 1,
        "Displacement up": signals["displacement_up"] == 1,
        "Displacement down": signals["displacement_down"] == 1,
        "With momentum (mom_15 aligned)": ((signals["l2_signal"] == 1) & (signals["mom_15"] > 0)) | ((signals["l2_signal"] == -1) & (signals["mom_15"] < 0)),
        "Against momentum": ((signals["l2_signal"] == 1) & (signals["mom_15"] < 0)) | ((signals["l2_signal"] == -1) & (signals["mom_15"] > 0)),
    }
    
    regime_results = []
    for name, cond in conditions.items():
        if cond.sum() < 50:
            continue
        
        subset = signals[cond]
        ret = subset["aligned_ret_300s"].mean()
        wr = (subset["aligned_ret_300s"] > 0).mean() * 100
        n = len(subset)
        improvement = ret - baseline_ret
        
        regime_results.append({
            "condition": name,
            "n_signals": n,
            "mean_ret_bps": ret,
            "win_rate": wr,
            "improvement_bps": improvement,
        })
    
    regime_df = pd.DataFrame(regime_results).sort_values("improvement_bps", ascending=False)
    
    logger.info("\nContext conditions ranked by improvement over baseline:")
    logger.info("-" * 70)
    for _, row in regime_df.iterrows():
        sign = "+" if row["improvement_bps"] > 0 else ""
        logger.info(f"{row['condition']:35} {row['mean_ret_bps']:+.2f} bps ({sign}{row['improvement_bps']:.2f}), {row['win_rate']:.1f}% WR, n={row['n_signals']}")
    
    # Save results
    corr_df.to_csv(OUTPUT_DIR / "feature_correlations.csv", index=False)
    regime_df.to_csv(OUTPUT_DIR / "regime_performance.csv", index=False)
    
    logger.info(f"\nResults saved to {OUTPUT_DIR}")
    
    return corr_df, regime_df


if __name__ == "__main__":
    corr_df, regime_df = run_correlation_analysis()
