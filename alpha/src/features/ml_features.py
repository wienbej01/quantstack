"""ML feature engineering — temporal aggregations and cross-features.

Extends the base L2 feature set with rolling statistics, interaction terms,
and time-of-day encoding for ML model consumption.
"""

import numpy as np
import pandas as pd

from .price_features import compute_all_price_features

# Base columns from the pre-computed feature set that we build on
_ROLL_COLS = [
    "obi_1",
    "obi_5",
    "spread",
    "pressure_k",
    "mid",
    "micro_off",
    "depth_imb_k",
]
_WINDOWS = [10, 30, 60, 300]
_PRICE_RETURN_PERIODS = [1, 3, 5, 10]
_CONTEXT_COLS = {
    "minutes_since_open",
    "seconds_since_open",
    "seconds_since_first_snapshot",
    "session_progress",
    "session_bucket",
    "session_is_open",
    "session_is_morning",
    "session_is_midday",
    "session_is_close",
    "source_is_features",
    "source_is_raw",
    "source_is_unknown",
    "depth_imb_positive_10s",
    "depth_imb_negative_10s",
    "depth_imb_positive_60s",
    "depth_imb_negative_60s",
    "micro_off_positive_30s",
    "micro_off_negative_30s",
    "micro_off_positive_60s",
    "micro_off_negative_60s",
    "open_x_depth_imb_positive_10s",
    "open_x_depth_imb_negative_10s",
    "midday_x_depth_imb_positive_10s",
    "midday_x_depth_imb_negative_10s",
    "open_x_micro_off_positive_30s",
    "open_x_micro_off_negative_30s",
    "midday_x_micro_off_positive_30s",
    "midday_x_micro_off_negative_30s",
}

_SIDE_AWARE_CONTEXT_ONLY_COLS = {
    "session_is_open",
    "session_is_morning",
    "session_is_midday",
    "session_is_close",
    "depth_imb_positive_10s",
    "depth_imb_negative_10s",
    "depth_imb_positive_60s",
    "depth_imb_negative_60s",
    "micro_off_positive_30s",
    "micro_off_negative_30s",
    "micro_off_positive_60s",
    "micro_off_negative_60s",
    "open_x_depth_imb_positive_10s",
    "open_x_depth_imb_negative_10s",
    "midday_x_depth_imb_positive_10s",
    "midday_x_depth_imb_negative_10s",
    "open_x_micro_off_positive_30s",
    "open_x_micro_off_negative_30s",
    "midday_x_micro_off_positive_30s",
    "midday_x_micro_off_negative_30s",
}


def compute_ml_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add rolling stats, cross-features, and time encoding to a symbol-day DataFrame.

    Expects df sorted by ts_utc within a single symbol-day.
    Returns df with new columns appended (original columns preserved).
    """
    out = df.copy()

    # Ensure ts_utc is timezone-aware UTC before converting to New York session time.
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)

    # Use exchange-local time so DST transitions do not distort session features.
    ts_et = out["ts_utc"].dt.tz_convert("America/New_York")
    minutes_since_open = (ts_et.dt.hour * 60 + ts_et.dt.minute) - (9 * 60 + 30)
    out["minutes_since_open"] = minutes_since_open.clip(lower=0)
    out["seconds_since_open"] = out["minutes_since_open"] * 60.0
    out["session_bucket"] = (
        pd.cut(
            minutes_since_open,
            bins=[-1, 30, 180, 360, 999],
            labels=[0, 1, 2, 3],  # open, morning, midday, close
        )
        .astype(float)
        .fillna(1)
    )
    first_ts = out["ts_utc"].iloc[0]
    out["seconds_since_first_snapshot"] = (
        (out["ts_utc"] - first_ts).dt.total_seconds().clip(lower=0.0)
    )
    out["session_progress"] = (out["seconds_since_open"] / (6.5 * 60.0 * 60.0)).clip(
        lower=0.0, upper=1.0
    )
    source_type = out.get("source_type", pd.Series("unknown", index=out.index)).fillna(
        "unknown"
    )
    source_type = source_type.astype(str)
    out["source_is_features"] = (source_type == "features").astype(float)
    out["source_is_raw"] = (source_type == "raw").astype(float)
    out["source_is_unknown"] = (~(source_type.isin(["features", "raw"]))).astype(float)

    out = add_causal_price_features(out)

    # Rolling statistics per window
    if "ts_epoch" in out.columns:
        ts = out["ts_epoch"].values
    else:
        ts = out["ts_utc"].astype(np.int64) / 1e9

    for w in _WINDOWS:
        suffix = f"_{w}s"
        for col in _ROLL_COLS:
            if col not in out.columns:
                continue
            vals = out[col].values.astype(np.float64)
            rm, rs = _rolling_mean_std(vals, ts, w)
            out[f"{col}_mean{suffix}"] = rm
            out[f"{col}_std{suffix}"] = rs
            out[f"{col}_delta{suffix}"] = vals - rm

    # Cross-features
    if "obi_1" in out.columns and "pressure_k" in out.columns:
        out["obi1_x_pressure"] = out["obi_1"] * out["pressure_k"]
    if "spread" in out.columns and "d_mid_30s" in out.columns:
        out["spread_x_dmid30"] = out["spread"] * out["d_mid_30s"]
    if "depth_bid_k" in out.columns and "depth_ask_k" in out.columns:
        denom = out["depth_ask_k"].replace(0, np.nan)
        out["depth_ratio"] = (out["depth_bid_k"] / denom).fillna(1.0)
        if "depth_ratio_mean_30s" not in out.columns:
            vals = out["depth_ratio"].values.astype(np.float64)
            rm, _ = _rolling_mean_std(vals, ts, 30)
            out["depth_ratio_delta_30s"] = vals - rm

    return add_side_aware_context_features(out)


def add_causal_price_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add causal OHLCV-derived features when minute-bar columns are available."""
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        return df

    out = df.copy()
    bars = out.copy()
    if "ts" not in bars.columns and "ts_utc" in bars.columns:
        bars["ts"] = pd.to_datetime(bars["ts_utc"], utc=True)

    enriched = compute_all_price_features(
        bars,
        return_periods=_PRICE_RETURN_PERIODS,
        atr_period=14,
        rsi_period=14,
        bb_period=20,
    )
    close = pd.to_numeric(enriched["close"], errors="coerce").replace(0.0, np.nan)
    open_px = pd.to_numeric(enriched["open"], errors="coerce").replace(0.0, np.nan)
    volume = pd.to_numeric(enriched["volume"], errors="coerce")
    volume_mean_20 = (
        volume.rolling(window=20, min_periods=1).mean().replace(0.0, np.nan)
    )

    out["vwap"] = pd.to_numeric(enriched["vwap"], errors="coerce")
    out["dist_vwap_bps"] = ((close - out["vwap"]) / close).replace(
        [np.inf, -np.inf], np.nan
    ) * 10000.0
    out["hl_range_pct"] = (
        (
            pd.to_numeric(enriched["high"], errors="coerce")
            - pd.to_numeric(enriched["low"], errors="coerce")
        )
        / close
    ).replace([np.inf, -np.inf], np.nan)
    out["oc_change_pct"] = (
        (pd.to_numeric(enriched["close"], errors="coerce") - open_px) / open_px
    ).replace([np.inf, -np.inf], np.nan)
    out["volume_rel_20"] = (volume / volume_mean_20).replace([np.inf, -np.inf], np.nan)

    for column in (
        "atr_pct",
        "position_in_range",
        "rsi",
        "bb_width",
        "bb_position",
        "session_range",
    ):
        out[column] = pd.to_numeric(enriched[column], errors="coerce")

    for period in _PRICE_RETURN_PERIODS:
        out[f"ret_{period}"] = pd.to_numeric(enriched[f"ret_{period}"], errors="coerce")
        out[f"log_log_ret_{period}"] = pd.to_numeric(
            enriched[f"log_log_ret_{period}"], errors="coerce"
        )

    causal_price_cols = [
        "vwap",
        "dist_vwap_bps",
        "hl_range_pct",
        "oc_change_pct",
        "volume_rel_20",
        "atr_pct",
        "position_in_range",
        "rsi",
        "bb_width",
        "bb_position",
        "session_range",
        *(f"ret_{period}" for period in _PRICE_RETURN_PERIODS),
        *(f"log_log_ret_{period}" for period in _PRICE_RETURN_PERIODS),
    ]
    out[causal_price_cols] = (
        out[causal_price_cols]
        .astype(np.float32)
        .replace([np.inf, -np.inf], np.nan)
        .fillna(0.0)
    )
    return out


def add_side_aware_context_features(df: pd.DataFrame) -> pd.DataFrame:
    """Add lightweight side-aware regime/context interactions.

    These are symmetric context features designed to help direction models learn when
    long-leaning or short-leaning setups are acceptable without hardcoding a prior.
    """
    out = df.copy()
    session_bucket = pd.to_numeric(out.get("session_bucket"), errors="coerce").fillna(
        1.0
    )
    out["session_is_open"] = (session_bucket == 0.0).astype(float)
    out["session_is_morning"] = (session_bucket == 1.0).astype(float)
    out["session_is_midday"] = (session_bucket == 2.0).astype(float)
    out["session_is_close"] = (session_bucket == 3.0).astype(float)

    def _split_signed(column: str, pos_name: str, neg_name: str) -> None:
        source = (
            out[column] if column in out.columns else pd.Series(np.nan, index=out.index)
        )
        values = pd.to_numeric(source, errors="coerce").fillna(0.0)
        out[pos_name] = values.clip(lower=0.0)
        out[neg_name] = (-values).clip(lower=0.0)

    _split_signed(
        "depth_imb_k_mean_10s", "depth_imb_positive_10s", "depth_imb_negative_10s"
    )
    _split_signed(
        "depth_imb_k_mean_60s", "depth_imb_positive_60s", "depth_imb_negative_60s"
    )
    _split_signed(
        "micro_off_mean_30s", "micro_off_positive_30s", "micro_off_negative_30s"
    )
    _split_signed(
        "micro_off_mean_60s", "micro_off_positive_60s", "micro_off_negative_60s"
    )

    out["open_x_depth_imb_positive_10s"] = (
        out["session_is_open"] * out["depth_imb_positive_10s"]
    )
    out["open_x_depth_imb_negative_10s"] = (
        out["session_is_open"] * out["depth_imb_negative_10s"]
    )
    out["midday_x_depth_imb_positive_10s"] = (
        out["session_is_midday"] * out["depth_imb_positive_10s"]
    )
    out["midday_x_depth_imb_negative_10s"] = (
        out["session_is_midday"] * out["depth_imb_negative_10s"]
    )
    out["open_x_micro_off_positive_30s"] = (
        out["session_is_open"] * out["micro_off_positive_30s"]
    )
    out["open_x_micro_off_negative_30s"] = (
        out["session_is_open"] * out["micro_off_negative_30s"]
    )
    out["midday_x_micro_off_positive_30s"] = (
        out["session_is_midday"] * out["micro_off_positive_30s"]
    )
    out["midday_x_micro_off_negative_30s"] = (
        out["session_is_midday"] * out["micro_off_negative_30s"]
    )
    return out


def _rolling_mean_std(vals: np.ndarray, ts: np.ndarray, window_s: int):
    """Compute rolling mean and std over a time window.

    This is called many times over second-level L2 frames during replay. A
    vectorized prefix-sum implementation keeps the same inclusive time-window
    semantics as the original loop without repeatedly walking rows in Python.
    """
    vals = np.asarray(vals, dtype=np.float64)
    ts = np.asarray(ts, dtype=np.float64)
    n = len(vals)
    if n == 0:
        return np.array([], dtype=np.float64), np.array([], dtype=np.float64)

    valid = np.isfinite(vals)
    clean_vals = np.where(valid, vals, 0.0)
    starts = np.searchsorted(ts, ts - float(window_s), side="left")
    ends = np.arange(n, dtype=np.int64) + 1

    prefix_sum = np.concatenate(([0.0], np.cumsum(clean_vals)))
    prefix_sum2 = np.concatenate(([0.0], np.cumsum(clean_vals * clean_vals)))
    prefix_count = np.concatenate(([0], np.cumsum(valid.astype(np.int64))))

    counts = prefix_count[ends] - prefix_count[starts]
    sums = prefix_sum[ends] - prefix_sum[starts]
    sums2 = prefix_sum2[ends] - prefix_sum2[starts]

    means = np.divide(
        sums,
        counts,
        out=np.zeros(n, dtype=np.float64),
        where=counts > 0,
    )
    variances = np.divide(
        sums2,
        counts,
        out=np.zeros(n, dtype=np.float64),
        where=counts > 0,
    ) - (means * means)
    stds = np.where(counts > 1, np.sqrt(np.maximum(variances, 0.0)), 0.0)

    # Preserve the historical behavior for rows whose current value is NaN:
    # carry forward the previous rolling value instead of emitting the window's
    # numeric aggregate at that timestamp.
    for idx in np.flatnonzero(~valid):
        if idx > 0:
            means[idx] = means[idx - 1]
            stds[idx] = stds[idx - 1]
        else:
            means[idx] = 0.0
            stds[idx] = 0.0
    return means, stds


def _base_ml_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return list of ML feature column names (excludes metadata/label cols)."""
    exclude = {
        "ts_utc",
        "ts_epoch",
        "date_et",
        "symbol",
        "date",
        "exchange",
        "smart_depth",
        "has_depth",
        "label",
        "ret_fwd",
        "ret_realized",
        "event_score",
        "event_flag",
    }
    return [
        c
        for c in df.columns
        if c not in exclude and df[c].dtype in (np.float64, np.float32, float, int)
    ]


def _is_stage1_feature(column: str) -> bool:
    if column in _CONTEXT_COLS:
        return True
    if column.startswith(("d_", "obi1_x_pressure", "spread_x_dmid30")):
        return False
    return any(
        token in column
        for token in (
            "_std_",
            "_mean_",
            "spread",
            "micro_off",
            "depth_imb",
            "pressure",
            "depth_ratio",
            "mid",
        )
    )


def _is_stage2_feature(column: str) -> bool:
    if column in _CONTEXT_COLS:
        return True
    return (
        column.startswith("d_")
        or "obi" in column
        or "pressure" in column
        or "micro_off" in column
        or "depth_imb" in column
        or "spread_x" in column
        or "depth_ratio" in column
        or column in {"mid", "spread", "microprice", "depth_bid_k", "depth_ask_k"}
    )


def get_ml_feature_columns(df: pd.DataFrame, stage: str | None = None) -> list[str]:
    """Return ML feature columns, optionally filtered for a specific 2-stage task layer."""
    cols = _base_ml_feature_columns(df)
    if stage is None:
        return cols
    if stage == "stage1":
        return [column for column in cols if _is_stage1_feature(column)]
    if stage == "stage2":
        return [column for column in cols if _is_stage2_feature(column)]
    raise ValueError(
        f"Unsupported stage '{stage}'. Expected None, 'stage1', or 'stage2'."
    )


def get_side_aware_context_columns() -> list[str]:
    """Return side-aware context interaction columns added for direction-sensitive modeling."""
    return sorted(_SIDE_AWARE_CONTEXT_ONLY_COLS)
