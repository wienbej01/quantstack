#!/usr/bin/env python3
"""
Grid search for VWAP reversion settings on AAPL (April 1-5, 2024).

Explores:
    - Timeframes: 5m, 15m, 30m, 60m (aggregated from 1m bars)
    - Entry thresholds: rvol_min, min_deviation_pct
    - Risk sizing: position_size_pct, max_risk_frac, atr_mult
    - SIP screening: original top-5 using relative volume

Outputs the combinations that produce ~3-5 trades per day (15-25 trades total).
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import numpy as np
import pandas as pd

from qx_backtest.engine import BacktestConfig, BacktestEngine
from qx_backtest.fill import DefaultFiller
from qx_backtest.policies.vwap_revert import VwapRevertPolicy
from qx_data.gold_loader import load_bars
from qx_features.core_basics import compute_all_core_features
from qx_screener.sip import screen

START_DATE = pd.to_datetime("2024-04-01").date()
END_DATE = pd.to_datetime("2024-04-05").date()
SYMBOLS = ["AAPL"]
ROOT = "/home/jacobw/gcs-mount"
FAMILY = "stocks"


@dataclass
class SearchConfig:
    freq_label: str
    minutes: int
    vwap_window: int
    atr_window: int
    params: dict[str, float]
    total_trades: int
    trades_per_day: float
    total_return: float
    win_rate: float
    avg_trade_pnl: float


def resample_bars(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Aggregate 1m bars to the requested timeframe."""
    df = df.copy()
    df["datetime"] = pd.to_datetime(df["ts"], unit="ns", utc=True)
    resampled_frames: list[pd.DataFrame] = []

    rule = f"{minutes}T"

    for symbol, group in df.groupby("symbol", sort=False):
        agg = (
            group.set_index("datetime")
            .resample(rule)
            .agg(
                {
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                }
            )
        )
        agg = agg.dropna(subset=["open", "high", "low", "close"])
        if agg.empty:
            continue
        agg["symbol"] = symbol
        resampled_frames.append(agg.reset_index())

    if not resampled_frames:
        return pd.DataFrame()

    out = pd.concat(resampled_frames, ignore_index=True)
    out["ts"] = out["datetime"].astype("int64")
    out["date_et"] = out["datetime"].dt.tz_convert("America/New_York").dt.date
    mask = (out["date_et"] >= START_DATE) & (out["date_et"] <= END_DATE)
    out = out[mask].copy()
    return out.drop(columns=["date_et"])


def prepare_feature_dataframe(raw_df: pd.DataFrame, minutes: int) -> tuple[pd.DataFrame, int, int]:
    """Compute features with scaled windows."""
    if raw_df.empty:
        return raw_df, 0, 0

    vwap_window = max(2, int(np.ceil(30 / minutes))) if minutes else 30
    atr_window = max(5, int(np.ceil(14 / minutes))) if minutes else 14

    feature_df = compute_all_core_features(
        raw_df,
        vwap_window=vwap_window,
        rvol_window=vwap_window,
        atr_window=atr_window,
    )
    feature_df = feature_df.sort_values(["ts", "symbol"]).reset_index(drop=True)
    return feature_df, vwap_window, atr_window


def filter_by_sip(feature_df: pd.DataFrame, rvol_col: str, top_n: int = 5) -> pd.DataFrame:
    """Apply original SIP top-N filter."""
    universe_map = screen(feature_df, rvol_col, top_n=top_n, whitelist=None)
    if not universe_map:
        return feature_df

    allowed = feature_df["ts"].map(lambda ts: universe_map.get(int(ts), set()))
    mask = [
        symbol in allowed_set if isinstance(allowed_set, set) else False
        for symbol, allowed_set in zip(feature_df["symbol"], allowed, strict=False)
    ]
    filtered = feature_df.loc[mask].reset_index(drop=True)
    return filtered


def run_backtest(
    df: pd.DataFrame,
    vwap_window: int,
    params: dict[str, float],
    atr_col: str,
) -> tuple[int, float, float, float]:
    """Execute backtest with the provided parameters."""
    if df.empty:
        return 0, 0.0, 0.0, 0.0

    filler = DefaultFiller(
        commission_per_share=0.01,
        commission_min=0.0,
        slippage_bps=5,
    )
    backtest_cfg = BacktestConfig(initial_cash=1_000_000, filler=filler)
    engine = BacktestEngine(backtest_cfg, {"sip_method": "none"})

    policy = VwapRevertPolicy(
        vwap_window=vwap_window,
        min_rvol=params["rvol_min"],
        max_position_bars=50,
        position_size_pct=params["position_size_pct"],
        max_positions=3,
        min_deviation_pct=params["min_deviation_pct"],
        risk_params={
            "max_risk_frac": params["max_risk_frac"],
            "atr_mult": params["atr_mult"],
        },
        atr_col=atr_col,
    )
    policy.engine = engine
    engine.policy = policy
    policy.on_start()

    def strategy_func(engine_ref, bar):
        policy.process_bar(bar)

    result = engine.run(df, strategy_func)
    policy.on_end()

    total_trades = result.total_trades
    total_return = result.total_return
    win_rate = result.win_rate
    avg_pnl = result.avg_trade_pnl
    return total_trades, total_return, win_rate, avg_pnl


def main():
    base_df = load_bars(
        root=ROOT,
        family=FAMILY,
        symbols=SYMBOLS,
        dates=["2024-04-01", "2024-04-02", "2024-04-03", "2024-04-04", "2024-04-05"],
        validate=False,
        sort=True,
    )
    base_df = base_df.drop_duplicates(subset=["symbol", "ts"]).reset_index(drop=True)

    timeframe_specs = [
        ("15T", 15),
    ]
    rvol_min_opts = [0.6, 0.8, 1.0]
    min_dev_opts = [0.2, 0.3]
    pos_pct_opts = [0.02]
    risk_frac_opts = [0.003, 0.004, 0.005]
    atr_mult_opts = [0.75, 1.0, 1.5]

    results: list[SearchConfig] = []

    for freq_label, minutes in timeframe_specs:
        resampled = resample_bars(base_df, minutes)
        features_df, vwap_window, atr_window = prepare_feature_dataframe(resampled, minutes)
        if vwap_window == 0 or features_df.empty:
            continue

        rvol_col = f"f__vol__rel_volume_{vwap_window}"
        atr_col = f"f__vol__atr_{atr_window}"

        filtered_df = filter_by_sip(features_df, rvol_col, top_n=5)
        run_df = filtered_df.sort_values(["ts", "symbol"]).reset_index(drop=True)
        if run_df.empty:
            continue

        for rvol_min, min_dev, pos_pct, risk_frac, atr_mult in product(
            rvol_min_opts, min_dev_opts, pos_pct_opts, risk_frac_opts, atr_mult_opts
        ):
            params = {
                "rvol_min": rvol_min,
                "min_deviation_pct": min_dev,
                "position_size_pct": pos_pct,
                "max_risk_frac": risk_frac,
                "atr_mult": atr_mult,
            }
            total_trades, total_return, win_rate, avg_pnl = run_backtest(
                run_df, vwap_window, params, atr_col
            )
            trades_per_day = total_trades / 5 if total_trades else 0.0

            results.append(
                SearchConfig(
                    freq_label=freq_label,
                    minutes=minutes,
                    vwap_window=vwap_window,
                    atr_window=atr_window,
                    params=params,
                    total_trades=total_trades,
                    trades_per_day=trades_per_day,
                    total_return=total_return,
                    win_rate=win_rate,
                    avg_trade_pnl=avg_pnl,
                )
            )

    if not results:
        print("No valid combinations evaluated.")
        return

    # Focus on trade count near 3-5 per day.
    target = 4.0
    results.sort(key=lambda cfg: (abs(cfg.trades_per_day - target), -cfg.total_return))

    non_zero = [cfg for cfg in results if 0 < cfg.trades_per_day <= 10]
    non_zero.sort(key=lambda cfg: (abs(cfg.trades_per_day - target), -cfg.total_return))

    print("\nTop combinations near 3-5 trades/day:")
    for cfg in non_zero[:15]:
        print(
            f"Freq={cfg.freq_label} (vw={cfg.vwap_window}, atr={cfg.atr_window}) | "
            f"Trades/day={cfg.trades_per_day:.2f} (total={cfg.total_trades}) | "
            f"Return={cfg.total_return:.2%} | WinRate={cfg.win_rate:.2%} | "
            f"AvgPnL={cfg.avg_trade_pnl:.2f} | Params={cfg.params}"
        )

    if not non_zero:
        print(
            "No parameter combinations produced trades in this range. "
            "Consider relaxing thresholds or evaluating broader settings."
        )


if __name__ == "__main__":
    main()
