#!/usr/bin/env python3
"""
L2 Scalping Feature Analysis: L2-only vs L2+Context Features

Compares signal quality and estimated performance between:
1. L2-only features (OBI, depth, spread dynamics)
2. L2 + 1-minute OHLCV context features (VWAP, RSI, momentum)
"""

import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests  # type: ignore[import-untyped]

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Paths
L2_DATA_DIRS = [
    Path("/home/jacobw/quantstack/data/l2_maximum/features"),
    Path("/home/jacobw/quantstack/data/l2_maximum/features_v2"),
    Path("/home/jacobw/quantstack/data/live_l2"),
]
OUTPUT_DIR = Path("/home/jacobw/quantstack/l2_scalping/analysis/output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
GOLD_1M_ROOT = Path("/home/jacobw/gcs-mount/gold/stocks/1m")

POLYGON_API_KEY = os.getenv("POLYGON_API_KEY")

# Signal thresholds
OBI_L2_ONLY_THRESHOLD = 0.3
OBI_CONTEXT_THRESHOLD = 0.25
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30


def load_l2_data() -> pd.DataFrame:  # noqa: PLR0912
    """Load all available L2 feature data"""
    all_data = []

    # Load from l2_maximum
    max_dir = L2_DATA_DIRS[0]
    if max_dir.exists():
        for date_dir in max_dir.glob("date=*"):
            for sym_dir in date_dir.glob("symbol=*"):
                for f in sym_dir.glob("*.parquet"):
                    try:
                        df = pd.read_parquet(f)
                        all_data.append(df)
                    except Exception as e:
                        logger.warning(f"Error loading {f}: {e}")

    # Load from live_l2
    live_dir = L2_DATA_DIRS[2]
    if live_dir.exists():
        for run_dir in live_dir.glob("run_id=*"):
            feat_dir = run_dir / "feat"
            if feat_dir.exists():
                for date_dir in feat_dir.glob("date=*"):
                    for sym_dir in date_dir.glob("symbol=*"):
                        for f in sym_dir.glob("*.parquet"):
                            try:
                                df = pd.read_parquet(f)
                                all_data.append(df)
                            except Exception as e:
                                logger.warning(f"Error loading {f}: {e}")

    if not all_data:
        raise ValueError("No L2 data found")

    combined = pd.concat(all_data, ignore_index=True)
    combined["ts_utc"] = pd.to_datetime(combined["ts_utc"])
    combined = combined.sort_values(["symbol", "ts_utc"]).drop_duplicates(
        subset=["symbol", "ts_utc"], keep="first"
    )

    logger.info(f"Loaded {len(combined):,} L2 records")
    logger.info(f"Symbols: {combined['symbol'].unique().tolist()}")
    logger.info(f"Date range: {combined['ts_utc'].min()} to {combined['ts_utc'].max()}")

    return combined


def load_local_bars(symbol: str, date: str) -> pd.DataFrame | None:
    """Load 1-minute bars from local gold data (ET timestamps)."""
    if not GOLD_1M_ROOT.exists():
        return None

    year = date[:4]
    month = date[:7]
    monthly_path = GOLD_1M_ROOT / symbol / year / f"{month}.parquet"
    if not monthly_path.exists():
        return None

    try:
        df = pd.read_parquet(
            monthly_path, columns=["ts", "open", "high", "low", "close", "volume"]
        )
    except Exception as e:
        logger.warning(f"Error loading local bars {monthly_path}: {e}")
        return None

    day = pd.to_datetime(date).date()
    df = df[df["ts"].dt.date == day]
    if df.empty:
        return None

    try:
        ts_local = df["ts"].dt.tz_localize(
            "America/New_York", ambiguous="infer", nonexistent="shift_forward"
        )
    except Exception:
        ts_local = df["ts"].dt.tz_localize(
            "America/New_York", ambiguous="NaT", nonexistent="shift_forward"
        )

    df["timestamp"] = ts_local.dt.tz_convert("UTC")
    df["symbol"] = symbol
    return df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]]


def download_polygon_bars(symbol: str, date: str) -> pd.DataFrame | None:
    """Download 1-minute bars from Polygon or load from local gold data."""
    local = load_local_bars(symbol, date)
    if local is not None:
        return local

    if not POLYGON_API_KEY:
        logger.warning("No Polygon API key found")
        return None

    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}"
    params = {"apiKey": POLYGON_API_KEY, "limit": 50000}

    try:
        resp = requests.get(url, params=params, timeout=30)
        data = resp.json()

        if data.get("resultsCount", 0) == 0:
            return None

        df = pd.DataFrame(data["results"])
        df["timestamp"] = pd.to_datetime(df["t"], unit="ms", utc=True)
        df = df.rename(
            columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}
        )
        df["symbol"] = symbol

        return df[["timestamp", "symbol", "open", "high", "low", "close", "volume"]]

    except Exception as e:
        logger.error(f"Error downloading {symbol} {date}: {e}")
        return None


def compute_context_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Compute context features from 1-minute OHLCV bars"""
    df = bars.copy()

    # VWAP
    df["cum_vol"] = df["volume"].cumsum()
    df["cum_vwap"] = (df["close"] * df["volume"]).cumsum()
    df["vwap"] = df["cum_vwap"] / df["cum_vol"]
    df["vwap_dist"] = (df["close"] - df["vwap"]) / df["vwap"] * 10000  # bps

    # RSI (14-period)
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi_14"] = 100 - (100 / (1 + rs))

    # Momentum
    df["mom_5"] = df["close"].pct_change(5) * 10000  # bps
    df["mom_15"] = df["close"].pct_change(15) * 10000

    # Volatility (ATR proxy)
    df["range"] = df["high"] - df["low"]
    df["atr_14"] = df["range"].rolling(14).mean()
    df["atr_pct"] = df["atr_14"] / df["close"] * 10000  # bps

    # Volume profile
    df["vol_ma_20"] = df["volume"].rolling(20).mean()
    df["rel_vol"] = df["volume"] / df["vol_ma_20"]

    return df


def merge_l2_with_context(l2_df: pd.DataFrame, bars_dict: dict) -> pd.DataFrame:
    """Merge L2 data with context features (asof join by minute)"""
    merged_data = []
    context_cols = ["vwap_dist", "rsi_14", "mom_5", "mom_15", "atr_pct", "rel_vol"]

    for symbol in l2_df["symbol"].unique():
        l2_sym = l2_df[l2_df["symbol"] == symbol].copy()

        if symbol not in bars_dict or bars_dict[symbol] is None:
            # No context data - use L2 only
            l2_sym["has_context"] = False
            for col in context_cols:
                l2_sym[col] = np.nan
            merged_data.append(l2_sym)
            continue

        bars = bars_dict[symbol].copy()
        bars = compute_context_features(bars)
        bars["minute"] = bars["timestamp"].dt.floor("min")

        l2_sym["minute"] = l2_sym["ts_utc"].dt.floor("min")

        # Merge on minute
        merged = pd.merge_asof(
            l2_sym.sort_values("ts_utc"),
            bars[
                [
                    "minute",
                    "vwap_dist",
                    "rsi_14",
                    "mom_5",
                    "mom_15",
                    "atr_pct",
                    "rel_vol",
                ]
            ].sort_values("minute"),
            on="minute",
            direction="backward",
        )
        merged["has_context"] = merged["vwap_dist"].notna()
        merged_data.append(merged)

    return pd.concat(merged_data, ignore_index=True)


def compute_forward_returns(
    df: pd.DataFrame, horizons: list[int] | None = None
) -> pd.DataFrame:
    """Compute forward returns at various horizons (in seconds)"""
    result = df.copy()
    if horizons is None:
        horizons = [5, 10, 15, 30]

    for symbol in result["symbol"].unique():
        mask = result["symbol"] == symbol
        sym_data = result.loc[mask].copy()

        for h in horizons:
            # Approximate: each row ~0.5s, so h seconds = h*2 rows
            shift = h * 2
            result.loc[mask, f"fwd_ret_{h}s"] = (
                sym_data["mid"].shift(-shift) / sym_data["mid"] - 1
            ) * 10000  # bps

    return result


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """Generate trading signals using L2 and context features"""
    result = df.copy()

    # L2-only signal: OBI momentum
    result["signal_l2_only"] = 0
    result.loc[result["obi_1"] > OBI_L2_ONLY_THRESHOLD, "signal_l2_only"] = 1  # Buy
    result.loc[result["obi_1"] < -OBI_L2_ONLY_THRESHOLD, "signal_l2_only"] = -1  # Sell

    # L2 + Context signal: OBI + VWAP + RSI confirmation
    result["signal_l2_context"] = 0

    # Buy: OBI bullish + price below VWAP + RSI not overbought
    buy_cond = (
        (result["obi_1"] > OBI_CONTEXT_THRESHOLD)
        & (result["vwap_dist"] < 0)
        & (result["rsi_14"] < RSI_OVERBOUGHT)
        & (result["has_context"])
    )
    result.loc[buy_cond, "signal_l2_context"] = 1

    # Sell: OBI bearish + price above VWAP + RSI not oversold
    sell_cond = (
        (result["obi_1"] < -OBI_CONTEXT_THRESHOLD)
        & (result["vwap_dist"] > 0)
        & (result["rsi_14"] > RSI_OVERSOLD)
        & (result["has_context"])
    )
    result.loc[sell_cond, "signal_l2_context"] = -1

    # Fallback to L2-only when no context
    no_context = ~result["has_context"]
    result.loc[no_context, "signal_l2_context"] = result.loc[
        no_context, "signal_l2_only"
    ]

    return result


def analyze_signal_performance(df: pd.DataFrame) -> dict:
    """Analyze performance of different signal types"""
    results = {}

    for signal_col in ["signal_l2_only", "signal_l2_context"]:
        signal_name = signal_col.replace("signal_", "")

        # Filter to signal rows only
        signals = df[df[signal_col] != 0].copy()

        if len(signals) == 0:
            continue

        # Compute returns aligned with signal direction
        for h in [5, 10, 15, 30]:
            ret_col = f"fwd_ret_{h}s"
            if ret_col not in signals.columns:
                continue

            signals[f"aligned_ret_{h}s"] = signals[signal_col] * signals[ret_col]

        # Compute metrics
        metrics = {
            "total_signals": len(signals),
            "buy_signals": (signals[signal_col] == 1).sum(),
            "sell_signals": (signals[signal_col] == -1).sum(),
        }

        for h in [5, 10, 15, 30]:
            ret_col = f"aligned_ret_{h}s"
            if ret_col not in signals.columns:
                continue

            valid = signals[ret_col].dropna()
            if len(valid) == 0:
                continue

            metrics[f"mean_ret_{h}s_bps"] = valid.mean()
            metrics[f"win_rate_{h}s"] = (valid > 0).mean() * 100
            metrics[f"sharpe_{h}s"] = (
                valid.mean() / valid.std() * np.sqrt(len(valid))
                if valid.std() > 0
                else 0
            )

        results[signal_name] = metrics

    return results


def run_analysis():  # noqa: PLR0915
    """Main analysis pipeline"""
    logger.info("=" * 60)
    logger.info("L2 SCALPING FEATURE ANALYSIS")
    logger.info("=" * 60)

    # 1. Load L2 data
    logger.info("\n1. Loading L2 data...")
    l2_df = load_l2_data()

    # 2. Get unique symbols and dates
    symbols = l2_df["symbol"].unique().tolist()
    dates = l2_df["ts_utc"].dt.date.unique()
    logger.info(f"\nSymbols: {symbols}")
    logger.info(f"Dates: {[str(d) for d in dates]}")

    # 3. Download 1-minute bars from Polygon
    logger.info("\n2. Downloading 1-minute OHLCV bars from Polygon...")
    bars_dict = {}

    for symbol in symbols:
        all_bars = []
        for date in dates:
            date_str = str(date)
            bars = download_polygon_bars(symbol, date_str)
            if bars is not None:
                all_bars.append(bars)
                logger.info(f"  {symbol} {date_str}: {len(bars)} bars")

        if all_bars:
            bars_dict[symbol] = pd.concat(all_bars, ignore_index=True)
        else:
            bars_dict[symbol] = None
            logger.warning(f"  {symbol}: No bars downloaded")

    # 4. Merge L2 with context features
    logger.info("\n3. Merging L2 data with context features...")
    merged_df = merge_l2_with_context(l2_df, bars_dict)

    context_pct = merged_df["has_context"].mean() * 100
    logger.info(f"  Records with context: {context_pct:.1f}%")

    # 5. Compute forward returns
    logger.info("\n4. Computing forward returns...")
    merged_df = compute_forward_returns(merged_df)

    # 6. Generate signals
    logger.info("\n5. Generating trading signals...")
    merged_df = generate_signals(merged_df)

    l2_only_signals = (merged_df["signal_l2_only"] != 0).sum()
    l2_context_signals = (merged_df["signal_l2_context"] != 0).sum()
    logger.info(f"  L2-only signals: {l2_only_signals:,}")
    logger.info(f"  L2+Context signals: {l2_context_signals:,}")

    # 7. Analyze performance
    logger.info("\n6. Analyzing signal performance...")
    results = analyze_signal_performance(merged_df)

    # 8. Print results
    logger.info("\n" + "=" * 60)
    logger.info("RESULTS: L2-ONLY vs L2+CONTEXT SIGNALS")
    logger.info("=" * 60)

    for signal_name, metrics in results.items():
        logger.info(f"\n{signal_name.upper()}:")
        logger.info(f"  Total signals: {metrics['total_signals']:,}")
        logger.info(
            f"  Buy/Sell: {metrics['buy_signals']:,} / {metrics['sell_signals']:,}"
        )

        for h in [5, 10, 15]:
            if f"mean_ret_{h}s_bps" in metrics:
                logger.info(f"  {h}s horizon:")
                logger.info(f"    Mean return: {metrics[f'mean_ret_{h}s_bps']:.2f} bps")
                logger.info(f"    Win rate: {metrics[f'win_rate_{h}s']:.1f}%")
                logger.info(f"    Sharpe: {metrics[f'sharpe_{h}s']:.2f}")

    # 9. Save results
    output_file = (
        OUTPUT_DIR / f"analysis_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    )

    # Convert to DataFrame for saving
    results_df = pd.DataFrame(results).T
    results_df.to_csv(output_file)
    logger.info(f"\nResults saved to: {output_file}")

    # 10. Summary comparison
    logger.info("\n" + "=" * 60)
    logger.info("SUMMARY COMPARISON")
    logger.info("=" * 60)

    if "l2_only" in results and "l2_context" in results:
        l2_only = results["l2_only"]
        l2_ctx = results["l2_context"]

        for h in [10, 15]:
            if f"mean_ret_{h}s_bps" in l2_only and f"mean_ret_{h}s_bps" in l2_ctx:
                improvement = (
                    l2_ctx[f"mean_ret_{h}s_bps"] - l2_only[f"mean_ret_{h}s_bps"]
                )
                logger.info(f"\n{h}s Horizon:")
                logger.info(
                    f"  L2-only mean return: {l2_only[f'mean_ret_{h}s_bps']:.2f} bps"
                )
                logger.info(
                    f"  L2+Context mean return: {l2_ctx[f'mean_ret_{h}s_bps']:.2f} bps"
                )
                logger.info(f"  Improvement: {improvement:+.2f} bps")

                wr_improvement = l2_ctx[f"win_rate_{h}s"] - l2_only[f"win_rate_{h}s"]
                logger.info(f"  Win rate improvement: {wr_improvement:+.1f}%")

    return results, merged_df


if __name__ == "__main__":
    results, data = run_analysis()
