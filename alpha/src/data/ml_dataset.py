"""Unified ML dataset pipeline.

Loads L2 data from all sources (pre-computed features + raw), computes features
on raw data to match the pre-computed schema, and outputs a unified DataFrame.
"""

import logging
from collections import deque
from typing import Iterator, List, Optional

import numpy as np
import pandas as pd

from .l2_loader import L2Loader

logger = logging.getLogger(__name__)

# Canonical feature columns present in pre-computed data
FEATURE_COLS = [
    "mid",
    "spread",
    "microprice",
    "micro_off",
    "depth_bid_k",
    "depth_ask_k",
    "depth_imb_k",
    "pressure_k",
    "obi_1",
    "obi_2",
    "obi_3",
    "obi_5",
    "obi_10",
    "d_mid_5s",
    "d_spread_5s",
    "d_obi_1_5s",
    "d_micro_off_5s",
    "d_mid_15s",
    "d_spread_15s",
    "d_obi_1_15s",
    "d_micro_off_15s",
    "d_mid_30s",
    "d_spread_30s",
    "d_obi_1_30s",
    "d_micro_off_30s",
    "d_mid_60s",
    "d_spread_60s",
    "d_obi_1_60s",
    "d_micro_off_60s",
]

# Columns needed from raw data to compute features
RAW_BID_PX = [f"bid_px_{i}" for i in range(1, 6)]
RAW_BID_SZ = [f"bid_sz_{i}" for i in range(1, 6)]
RAW_ASK_PX = [f"ask_px_{i}" for i in range(1, 6)]
RAW_ASK_SZ = [f"ask_sz_{i}" for i in range(1, 6)]
RAW_METADATA_COLS = [
    "ts_utc",
    "ts_epoch",
    "date_et",
    "symbol",
    "exchange",
    "smart_depth",
    "has_depth",
    "l1_bid",
    "l1_ask",
    "l1_bid_size",
    "l1_ask_size",
]
RAW_REQUIRED_COLS = (
    RAW_METADATA_COLS + RAW_BID_PX + RAW_BID_SZ + RAW_ASK_PX + RAW_ASK_SZ
)


def optimize_memory(df: pd.DataFrame) -> pd.DataFrame:
    """Downcast numeric columns to reduce memory pressure."""
    optimized = df.copy()
    float_cols = optimized.select_dtypes(include=["float64"]).columns
    int_cols = optimized.select_dtypes(include=["int64"]).columns
    if len(float_cols) > 0:
        optimized[float_cols] = optimized[float_cols].astype(np.float32)
    if len(int_cols) > 0:
        optimized[int_cols] = optimized[int_cols].apply(
            pd.to_numeric, downcast="integer"
        )
    return optimized


def compute_features_from_raw(df: pd.DataFrame) -> pd.DataFrame:
    """Compute the canonical feature set from raw L2 book snapshots.

    Mirrors the pre-computed feature schema so raw and feature data
    can be concatenated into a single dataset.
    """
    out = pd.DataFrame(index=df.index)
    out["ts_utc"] = df["ts_utc"]

    # Copy metadata columns if present
    for col in (
        "ts_epoch",
        "date_et",
        "symbol",
        "exchange",
        "smart_depth",
        "has_depth",
    ):
        if col in df.columns:
            out[col] = df[col]

    # L1 best bid/ask. Raw data can contain missing or inverted best quotes, so sanitize
    # them before deriving the training schema fields.
    bid1 = pd.to_numeric(
        df.get("bid_px_1", df.get("l1_bid", pd.Series(np.nan, index=df.index))),
        errors="coerce",
    )
    ask1 = pd.to_numeric(
        df.get("ask_px_1", df.get("l1_ask", pd.Series(np.nan, index=df.index))),
        errors="coerce",
    )
    bid1 = bid1.fillna(
        pd.to_numeric(
            df.get("l1_bid", pd.Series(np.nan, index=df.index)), errors="coerce"
        )
    )
    ask1 = ask1.fillna(
        pd.to_numeric(
            df.get("l1_ask", pd.Series(np.nan, index=df.index)), errors="coerce"
        )
    )
    bid_sz1 = pd.to_numeric(
        df.get("bid_sz_1", df.get("l1_bid_size", pd.Series(0, index=df.index))),
        errors="coerce",
    ).fillna(0.0)
    ask_sz1 = pd.to_numeric(
        df.get("ask_sz_1", df.get("l1_ask_size", pd.Series(0, index=df.index))),
        errors="coerce",
    ).fillna(0.0)

    has_l1 = bid1.notna() & ask1.notna() & (bid1 > 0) & (ask1 > 0)
    inverted_l1 = has_l1 & (ask1 < bid1)
    clean_bid = bid1.where(~inverted_l1, ask1)
    clean_ask = ask1.where(~inverted_l1, bid1)
    derived_mid = (clean_bid + clean_ask) / 2.0
    derived_spread = clean_ask - clean_bid
    absurd_l1 = has_l1 & (
        (derived_mid <= 0)
        | (derived_spread <= 0)
        | ((derived_spread / np.maximum(np.abs(derived_mid), 1e-6)) > 0.50)
    )
    valid_l1 = has_l1 & ~absurd_l1

    out["mid"] = derived_mid.where(valid_l1)
    out["spread"] = derived_spread.where(valid_l1, 0.0)

    # Microprice
    total_l1 = bid_sz1 + ask_sz1
    out["microprice"] = np.where(
        total_l1 > 0,
        (clean_bid * ask_sz1 + clean_ask * bid_sz1) / total_l1,
        out["mid"],
    )
    out["microprice"] = pd.Series(out["microprice"], index=df.index).where(
        valid_l1, out["mid"]
    )
    out["micro_off"] = out["microprice"] - out["mid"]
    for column in ("mid", "spread", "microprice", "micro_off"):
        out[column] = (
            pd.to_numeric(out[column], errors="coerce")
            .replace([np.inf, -np.inf], np.nan)
            .ffill()
            .fillna(0.0)
        )

    # Depth aggregation (use available levels)
    bid_sz_cols = [c for c in RAW_BID_SZ if c in df.columns]
    ask_sz_cols = [c for c in RAW_ASK_SZ if c in df.columns]
    out["depth_bid_k"] = df[bid_sz_cols].sum(axis=1) if bid_sz_cols else 0
    out["depth_ask_k"] = df[ask_sz_cols].sum(axis=1) if ask_sz_cols else 0
    total_depth = out["depth_bid_k"] + out["depth_ask_k"]
    out["depth_imb_k"] = np.where(
        total_depth > 0,
        (out["depth_bid_k"] - out["depth_ask_k"]) / total_depth,
        0,
    )
    out["pressure_k"] = out["depth_bid_k"] - out["depth_ask_k"]

    # OBI at various levels
    for lvl in (1, 2, 3, 5, 10):
        n = min(lvl, len(bid_sz_cols))
        if n > 0:
            b = df[
                [f"bid_sz_{i}" for i in range(1, n + 1) if f"bid_sz_{i}" in df.columns]
            ].sum(axis=1)
            a = df[
                [f"ask_sz_{i}" for i in range(1, n + 1) if f"ask_sz_{i}" in df.columns]
            ].sum(axis=1)
            denom = b + a
            out[f"obi_{lvl}"] = np.where(denom > 0, (b - a) / denom, 0)
        else:
            out[f"obi_{lvl}"] = 0.0

    # Temporal deltas — need ts_epoch for time-based rolling
    if "ts_epoch" in df.columns:
        out = out.sort_values("ts_utc").reset_index(drop=True)
        ts = out["ts_epoch"] if "ts_epoch" in out.columns else df["ts_epoch"]
        for window_s, suffix in [(5, "5s"), (15, "15s"), (30, "30s"), (60, "60s")]:
            for base_col, delta_col in [
                ("mid", f"d_mid_{suffix}"),
                ("spread", f"d_spread_{suffix}"),
                ("obi_1", f"d_obi_1_{suffix}"),
                ("micro_off", f"d_micro_off_{suffix}"),
            ]:
                out[delta_col] = _time_delta(out[base_col], ts, window_s).fillna(0.0)
    else:
        # Fallback: fill deltas with 0
        for suffix in ("5s", "15s", "30s", "60s"):
            for prefix in ("d_mid", "d_spread", "d_obi_1", "d_micro_off"):
                out[f"{prefix}_{suffix}"] = 0.0

    return out


def _time_delta(series: pd.Series, ts_epoch: pd.Series, window_s: int) -> pd.Series:
    """Compute value change over a time window using searchsorted."""
    vals = series.values.astype(np.float64)
    ts = ts_epoch.values.astype(np.float64)
    target_ts = ts - window_s
    idx = np.searchsorted(ts, target_ts, side="left")
    idx = np.clip(idx, 0, len(vals) - 1)
    return pd.Series(vals - vals[idx], index=series.index)


class MLDatasetBuilder:
    """Build unified ML dataset from all L2 sources."""

    def __init__(self, loader: Optional[L2Loader] = None, min_snapshots: int = 500):
        self.loader = loader or L2Loader()
        self.min_snapshots = min_snapshots

    def build(
        self,
        dates: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Build unified dataset across all available dates/symbols.

        Returns DataFrame with canonical feature columns + ts_utc, symbol, date.
        """
        if dates is None:
            dates = self.loader.get_available_dates(source_type="any")

        all_frames = [
            frame for frame in self.iter_symbol_days(dates=dates, symbols=symbols)
        ]

        if not all_frames:
            logger.warning("No data loaded")
            return pd.DataFrame()

        result = pd.concat(all_frames, ignore_index=True)
        result = result.sort_values(["symbol", "ts_utc"]).reset_index(drop=True)
        logger.info(
            f"Built ML dataset: {len(result)} rows, "
            f"{result['symbol'].nunique()} symbols, "
            f"{result['date'].nunique()} dates"
        )
        return result

    def iter_symbol_days(
        self,
        dates: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        balanced_by_date: bool = False,
    ) -> Iterator[pd.DataFrame]:
        """Yield one normalized symbol-day at a time."""
        if dates is None:
            dates = self.loader.get_available_dates(source_type="any")

        if balanced_by_date:
            yield from self._iter_symbol_days_balanced(dates=dates, symbols=symbols)
            return

        quality_log = []

        for date in sorted(dates):
            avail_symbols = self.loader.get_available_symbols(date, source_type="any")
            if symbols:
                avail_symbols = [s for s in avail_symbols if s in symbols]

            for sym in avail_symbols:
                try:
                    df = self._load_one(sym, date)
                    if df is not None and len(df) >= self.min_snapshots:
                        quality_log.append(
                            {
                                "date": date,
                                "symbol": sym,
                                "rows": len(df),
                                "status": "ok",
                            }
                        )
                        yield optimize_memory(df)
                    else:
                        n = len(df) if df is not None else 0
                        quality_log.append(
                            {
                                "date": date,
                                "symbol": sym,
                                "rows": n,
                                "status": f"skipped (<{self.min_snapshots})",
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed {sym}/{date}: {e}")
                    quality_log.append(
                        {
                            "date": date,
                            "symbol": sym,
                            "rows": 0,
                            "status": f"error: {e}",
                        }
                    )

        self._quality_log = pd.DataFrame(quality_log)

    def _iter_symbol_days_balanced(
        self,
        dates: List[str],
        symbols: Optional[List[str]] = None,
    ) -> Iterator[pd.DataFrame]:
        """Yield symbol-days in round-robin date order to preserve temporal breadth."""
        quality_log = []
        per_date_symbols = {}

        for date in sorted(dates):
            avail_symbols = self.loader.get_available_symbols(date, source_type="any")
            if symbols:
                avail_symbols = [s for s in avail_symbols if s in symbols]
            if avail_symbols:
                per_date_symbols[date] = deque(sorted(avail_symbols))

        while per_date_symbols:
            exhausted_dates = []
            for date in sorted(per_date_symbols):
                queue = per_date_symbols[date]
                if not queue:
                    exhausted_dates.append(date)
                    continue

                sym = queue.popleft()
                try:
                    df = self._load_one(sym, date)
                    if df is not None and len(df) >= self.min_snapshots:
                        quality_log.append(
                            {
                                "date": date,
                                "symbol": sym,
                                "rows": len(df),
                                "status": "ok",
                            }
                        )
                        yield optimize_memory(df)
                    else:
                        n = len(df) if df is not None else 0
                        quality_log.append(
                            {
                                "date": date,
                                "symbol": sym,
                                "rows": n,
                                "status": f"skipped (<{self.min_snapshots})",
                            }
                        )
                except Exception as e:
                    logger.warning(f"Failed {sym}/{date}: {e}")
                    quality_log.append(
                        {
                            "date": date,
                            "symbol": sym,
                            "rows": 0,
                            "status": f"error: {e}",
                        }
                    )

                if not queue:
                    exhausted_dates.append(date)

            for date in exhausted_dates:
                per_date_symbols.pop(date, None)

        self._quality_log = pd.DataFrame(quality_log)

    def _load_one(self, symbol: str, date: str) -> Optional[pd.DataFrame]:
        """Load and normalize one symbol-day."""
        # Try features first
        try:
            df = self.loader.load_snapshots(
                symbol,
                date,
                source_type="features",
                columns=["ts_utc", "symbol", *FEATURE_COLS],
            )
            df["date"] = date
            df["source_type"] = df.attrs.get("source_type", "features")
            if "symbol" not in df.columns:
                df["symbol"] = symbol
            # Ensure canonical columns exist
            missing = [c for c in FEATURE_COLS if c not in df.columns]
            for c in missing:
                df[c] = 0.0
            return df[["ts_utc", "symbol", "date", "source_type"] + FEATURE_COLS]
        except FileNotFoundError:
            pass

        # Fall back to raw
        try:
            df = self.loader.load_snapshots(
                symbol,
                date,
                source_type="raw",
                columns=RAW_REQUIRED_COLS,
            )
            computed = compute_features_from_raw(df)
            computed["date"] = date
            computed["source_type"] = df.attrs.get("source_type", "raw")
            if "symbol" not in computed.columns:
                computed["symbol"] = symbol
            missing = [c for c in FEATURE_COLS if c not in computed.columns]
            for c in missing:
                computed[c] = 0.0
            return computed[["ts_utc", "symbol", "date", "source_type"] + FEATURE_COLS]
        except FileNotFoundError:
            return None

    @property
    def quality_report(self) -> pd.DataFrame:
        return getattr(self, "_quality_log", pd.DataFrame())
