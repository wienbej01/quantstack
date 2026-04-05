"""Label generation and temporal train/val/test splitting for ML pipeline."""

import logging
from dataclasses import dataclass
from typing import List, Literal, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class SplitInfo:
    """Metadata for a train/val/test split."""

    train_dates: List[str]
    val_dates: List[str]
    test_dates: List[str]
    train_symbols: List[str]
    holdout_symbols: List[str]


@dataclass
class WalkForwardFold:
    """One fold of walk-forward CV."""

    fold_idx: int
    train_dates: List[str]
    val_dates: List[str]


BarrierOutcome = Literal["tp_first", "sl_first", "neither", "simultaneous"]


def classify_barrier_outcome(
    future_mid: np.ndarray,
    entry_mid: float,
    stop_bps: float,
    take_profit_bps: float,
    direction: Literal["long", "short"] = "long",
    tie_break_policy: Literal["worst_case", "best_case", "neutral"] = "worst_case",
) -> BarrierOutcome:
    """Classify which barrier is hit first from a full-resolution future path."""
    if future_mid.size == 0 or entry_mid <= 0:
        return "neither"

    move_bps = (future_mid - entry_mid) / entry_mid * 10000.0
    if direction == "short":
        favorable_bps = -move_bps
        adverse_bps = move_bps
    else:
        favorable_bps = move_bps
        adverse_bps = -move_bps

    tp_hits = np.flatnonzero(favorable_bps >= take_profit_bps)
    sl_hits = np.flatnonzero(adverse_bps >= stop_bps)
    tp_idx = int(tp_hits[0]) if tp_hits.size else None
    sl_idx = int(sl_hits[0]) if sl_hits.size else None

    if tp_idx is None and sl_idx is None:
        return "neither"
    if tp_idx is None:
        return "sl_first"
    if sl_idx is None:
        return "tp_first"
    if tp_idx < sl_idx:
        return "tp_first"
    if sl_idx < tp_idx:
        return "sl_first"
    if tie_break_policy == "best_case":
        return "tp_first"
    if tie_break_policy == "neutral":
        return "simultaneous"
    return "sl_first"


def generate_labels(
    df: pd.DataFrame,
    horizons_seconds: List[int] = (60, 180, 300),
    threshold_method: str = "fixed",
    fixed_bps: float = 10.0,
) -> pd.DataFrame:
    """Generate forward-return labels for each horizon.

    Adds columns: ret_fwd_{h}s, label_{h}s (0=down, 1=flat, 2=up) per horizon.
    Must be called per symbol-day (single symbol, sorted by ts_utc).
    """
    out = df.copy()
    if "ts_epoch" not in out.columns:
        out["ts_epoch"] = out["ts_utc"].astype(np.int64) / 1e9

    ts = out["ts_epoch"].values
    mid = out["mid"].values.astype(np.float64)

    for h in horizons_seconds:
        # Forward return: mid at t+h vs mid at t
        target_ts = ts + h
        fwd_idx = np.searchsorted(ts, target_ts, side="left")
        fwd_idx = np.clip(fwd_idx, 0, len(mid) - 1)
        fwd_mid = mid[fwd_idx]
        ret = np.where(mid > 0, (fwd_mid - mid) / mid, 0.0)

        # Mark rows where forward data is unavailable (near end of session)
        no_fwd = fwd_idx >= len(mid) - 1
        ret[no_fwd] = np.nan

        col_ret = f"ret_fwd_{h}s"
        col_label = f"label_{h}s"
        out[col_ret] = ret

        if threshold_method not in {"fixed", "quantile"}:
            raise ValueError(
                f"Unsupported threshold_method '{threshold_method}'. Expected 'fixed' or 'quantile'."
            )

        if threshold_method == "quantile":
            logger.warning(
                "generate_labels(threshold_method='quantile') uses same-day forward-return "
                "distribution statistics and is not temporally safe for production training."
            )
            valid = ret[~np.isnan(ret)]
            if len(valid) > 10:
                lo = np.percentile(valid, 33.3)
                hi = np.percentile(valid, 66.7)
            else:
                lo, hi = -fixed_bps / 10000, fixed_bps / 10000
        else:
            lo, hi = -fixed_bps / 10000, fixed_bps / 10000

        labels = np.full(len(ret), np.nan)
        labels[ret < lo] = 0  # down
        labels[(ret >= lo) & (ret <= hi)] = 1  # flat
        labels[ret > hi] = 2  # up
        out[col_label] = labels

    return out


def generate_barrier_labels(
    df: pd.DataFrame,
    horizons_seconds: List[int] = (60, 180, 300),
    stop_bps: float = 10.0,
    take_profit_bps: float = 10.0,
    direction: Literal["long", "short"] = "long",
    tie_break_policy: Literal["worst_case", "best_case", "neutral"] = "worst_case",
) -> pd.DataFrame:
    """Generate full-path barrier labels without compressing away event ordering.

    Adds columns:
    - barrier_outcome_{h}s: tp_first | sl_first | neither | simultaneous
    - barrier_label_{h}s: 2=tp_first, 1=neither/simultaneous, 0=sl_first
    """
    out = df.copy()
    if "ts_epoch" not in out.columns:
        out["ts_epoch"] = out["ts_utc"].astype(np.int64) / 1e9

    ts = out["ts_epoch"].to_numpy(dtype=np.float64)
    mid = out["mid"].to_numpy(dtype=np.float64)

    for horizon in horizons_seconds:
        outcomes: list[str | float] = []
        labels = np.full(len(out), np.nan)
        for idx, (ts_now, mid_now) in enumerate(zip(ts, mid)):
            if mid_now <= 0:
                outcomes.append(np.nan)
                continue
            end_ts = ts_now + horizon
            end_idx = int(np.searchsorted(ts, end_ts, side="right"))
            if end_idx <= idx + 1:
                outcomes.append(np.nan)
                continue
            outcome = classify_barrier_outcome(
                future_mid=mid[idx + 1 : end_idx],
                entry_mid=float(mid_now),
                stop_bps=stop_bps,
                take_profit_bps=take_profit_bps,
                direction=direction,
                tie_break_policy=tie_break_policy,
            )
            outcomes.append(outcome)
            if outcome == "tp_first":
                labels[idx] = 2
            elif outcome == "sl_first":
                labels[idx] = 0
            else:
                labels[idx] = 1

        out[f"barrier_outcome_{horizon}s"] = outcomes
        out[f"barrier_label_{horizon}s"] = labels

    return out


def temporal_split(
    df: pd.DataFrame,
    train_pct: float = 0.65,
    val_pct: float = 0.20,
    symbol_holdout_pct: float = 0.20,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, SplitInfo]:
    """Split dataset temporally into train/val/test with optional symbol holdout.

    Returns (train_df, val_df, test_df, split_info).
    """
    dates = sorted(df["date"].unique())
    n = len(dates)
    train_end = int(n * train_pct)
    val_end = int(n * (train_pct + val_pct))

    train_dates = dates[:train_end]
    val_dates = dates[train_end:val_end]
    test_dates = dates[val_end:]

    # Symbol holdout
    symbols = sorted(df["symbol"].unique())
    n_holdout = max(1, int(len(symbols) * symbol_holdout_pct))
    rng = np.random.RandomState(42)
    rng.shuffle(symbols)
    holdout_symbols = list(symbols[:n_holdout])
    train_symbols = list(symbols[n_holdout:])

    train_df = df[df["date"].isin(train_dates) & df["symbol"].isin(train_symbols)]
    val_df = df[df["date"].isin(val_dates)]
    test_df = df[df["date"].isin(test_dates)]

    info = SplitInfo(
        train_dates=list(train_dates),
        val_dates=list(val_dates),
        test_dates=list(test_dates),
        train_symbols=train_symbols,
        holdout_symbols=holdout_symbols,
    )
    logger.info(
        f"Split: train={len(train_dates)} dates, val={len(val_dates)}, "
        f"test={len(test_dates)}, holdout_symbols={holdout_symbols}"
    )
    return train_df, val_df, test_df, info


def walk_forward_folds(
    dates: List[str],
    n_folds: int = 5,
    min_train: int = 3,
) -> List[WalkForwardFold]:
    """Generate expanding-window walk-forward CV folds.

    Each fold trains on an expanding window and validates on the next chunk.
    """
    dates = sorted(dates)
    n = len(dates)
    if n < min_train + n_folds:
        # Not enough dates — single fold
        mid = max(min_train, n - 1)
        return [WalkForwardFold(0, dates[:mid], dates[mid:])]

    val_size = max(1, (n - min_train) // n_folds)
    folds = []
    for i in range(n_folds):
        val_start = min_train + i * val_size
        val_end = min(val_start + val_size, n)
        if val_start >= n:
            break
        folds.append(
            WalkForwardFold(
                fold_idx=i,
                train_dates=dates[:val_start],
                val_dates=dates[val_start:val_end],
            )
        )
    return folds
