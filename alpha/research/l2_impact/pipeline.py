"""Pipeline for deep L2 liquidity impact experiment."""

from __future__ import annotations

import json
import logging
import math
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import requests
import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class L2Group:
    date: str
    symbol: str
    files: Tuple[Path, ...]


@dataclass(frozen=True)
class EventDefinition:
    key: str
    name: str
    persistence_seconds: int
    percentile: Optional[float] = None
    percentile_ratio: Optional[float] = None
    percentile_deep: Optional[float] = None


@dataclass(frozen=True)
class EventRecord:
    symbol: str
    date: str
    definition: str
    threshold: float
    event_ts: pd.Timestamp
    event_minute: pd.Timestamp
    deep_total: float
    ratio: float


def load_config(config_path: Path) -> dict:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("Config must be a mapping")
    return config


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def parse_date(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y-%m-%d")


def has_snapshot_columns(columns: Sequence[str]) -> bool:
    ts_candidates = {"ts_utc", "ts_epoch", "timestamp", "ts"}
    if not ts_candidates.intersection(columns):
        return False
    has_bid = any(col.startswith("bid_sz_") for col in columns)
    has_ask = any(col.startswith("ask_sz_") for col in columns)
    return has_bid and has_ask


def discover_l2_groups(
    l2_root: Path,
    start_date: Optional[str],
    end_date: Optional[str],
    symbols: Optional[Sequence[str]],
) -> List[L2Group]:
    l2_root = l2_root.expanduser()
    if not l2_root.exists():
        raise FileNotFoundError(f"L2 root not found: {l2_root}")

    symbol_set = set(symbols) if symbols else None
    groups: Dict[Tuple[str, str], List[Path]] = {}

    for date_dir in sorted(l2_root.rglob("date=*")):
        if not date_dir.is_dir():
            continue
        date_str = date_dir.name.replace("date=", "")
        try:
            parse_date(date_str)
        except ValueError:
            continue
        if start_date and date_str < start_date:
            continue
        if end_date and date_str > end_date:
            continue

        for symbol_dir in sorted(date_dir.glob("symbol=*")):
            if not symbol_dir.is_dir():
                continue
            symbol = symbol_dir.name.replace("symbol=", "")
            if symbol_set and symbol not in symbol_set:
                continue
            files = sorted(symbol_dir.glob("*.parquet"))
            if not files:
                continue
            try:
                schema_cols = pq.ParquetFile(files[0]).schema.names
            except Exception:
                continue
            if not has_snapshot_columns(schema_cols):
                continue
            key = (date_str, symbol)
            groups.setdefault(key, []).extend(files)

    if not groups:
        raise RuntimeError(f"No L2 parquet files found under {l2_root}")

    l2_groups = [
        L2Group(date=key[0], symbol=key[1], files=tuple(sorted(paths)))
        for key, paths in sorted(groups.items())
    ]
    return l2_groups


def infer_l2_columns(columns: Sequence[str]) -> Tuple[str, List[int], List[int]]:
    ts_candidates = ["ts_utc", "ts_epoch", "timestamp", "ts"]
    ts_col = next((col for col in ts_candidates if col in columns), None)
    if ts_col is None:
        raise RuntimeError("No timestamp column found in L2 data")

    bid_levels: List[int] = []
    ask_levels: List[int] = []
    bid_pattern = re.compile(r"^bid_sz_(\d+)$")
    ask_pattern = re.compile(r"^ask_sz_(\d+)$")

    for col in columns:
        bid_match = bid_pattern.match(col)
        if bid_match:
            bid_levels.append(int(bid_match.group(1)))
        ask_match = ask_pattern.match(col)
        if ask_match:
            ask_levels.append(int(ask_match.group(1)))

    if not bid_levels or not ask_levels:
        raise RuntimeError("Missing bid/ask size columns in L2 data")

    bid_levels = sorted(bid_levels)
    ask_levels = sorted(ask_levels)

    return ts_col, bid_levels, ask_levels


def load_l2_seconds(
    group: L2Group,
    config: dict,
    tz: str,
) -> Tuple[pd.DataFrame, Dict[str, int]]:
    import pyarrow.parquet as pq

    valid_files: List[Tuple[Path, Sequence[str]]] = []
    schema_union: set[str] = set()
    for file_path in group.files:
        try:
            schema_cols = pq.ParquetFile(file_path).schema.names
        except Exception:
            continue
        if not has_snapshot_columns(schema_cols):
            continue
        valid_files.append((file_path, schema_cols))
        schema_union.update(schema_cols)

    if not valid_files:
        raise RuntimeError(f"No L2 data read for {group.symbol} on {group.date}")

    ts_col, bid_levels, ask_levels = infer_l2_columns(sorted(schema_union))

    max_level = min(max(bid_levels), max(ask_levels))
    deep_min = config["deep_level_min"]
    near_max = config["near_level_max"]

    if max_level < deep_min or max_level < near_max:
        raise RuntimeError(
            f"Insufficient depth levels (max {max_level}) in L2 data for {group.symbol}"
        )

    deep_max = min(config["deep_level_max"], max_level)
    deep_levels = list(range(deep_min, deep_max + 1))
    near_levels = list(range(1, min(near_max, max_level) + 1))

    bid_sz_cols = [f"bid_sz_{lvl}" for lvl in range(1, deep_max + 1)]
    ask_sz_cols = [f"ask_sz_{lvl}" for lvl in range(1, deep_max + 1)]
    optional_cols = [
        col for col in ["bid_px_1", "ask_px_1", "has_depth"] if col in schema_union
    ]

    frames = []
    for file_path, schema_cols in valid_files:
        if ts_col not in schema_cols:
            continue
        read_cols = [ts_col] + bid_sz_cols + ask_sz_cols + optional_cols
        read_cols = [col for col in read_cols if col in schema_cols]
        df = pd.read_parquet(file_path, columns=read_cols)
        frames.append(df)

    if not frames:
        raise RuntimeError(f"No L2 data read for {group.symbol} on {group.date}")

    l2 = pd.concat(frames, ignore_index=True)
    for col in bid_sz_cols + ask_sz_cols + optional_cols:
        if col not in l2.columns:
            l2[col] = np.nan

    if ts_col == "ts_epoch":
        l2["ts_utc"] = pd.to_datetime(l2[ts_col], unit="ns", utc=True)
    else:
        l2["ts_utc"] = pd.to_datetime(l2[ts_col], utc=True)

    l2["ts_et"] = l2["ts_utc"].dt.tz_convert(tz)

    session_start = pd.Timestamp(f"{group.date} {config['session_start']}", tz=tz)
    session_end = pd.Timestamp(f"{group.date} {config['session_end']}", tz=tz)
    l2 = l2[(l2["ts_et"] >= session_start) & (l2["ts_et"] <= session_end)]

    if "has_depth" in l2.columns:
        l2 = l2[l2["has_depth"]]

    if l2.empty:
        raise RuntimeError(
            f"No L2 snapshots in session for {group.symbol} on {group.date}"
        )

    l2["ts_sec"] = l2["ts_et"].dt.floor("s")
    l2 = l2.sort_values("ts_sec")
    l2 = l2.groupby("ts_sec").last()

    full_index = pd.date_range(session_start, session_end, freq="1s", tz=tz)
    l2 = l2.reindex(full_index)

    deep_bid_cols = [f"bid_sz_{lvl}" for lvl in deep_levels]
    deep_ask_cols = [f"ask_sz_{lvl}" for lvl in deep_levels]
    near_bid_cols = [f"bid_sz_{lvl}" for lvl in near_levels]
    near_ask_cols = [f"ask_sz_{lvl}" for lvl in near_levels]

    deep_bid = l2[deep_bid_cols].sum(axis=1, min_count=1)
    deep_ask = l2[deep_ask_cols].sum(axis=1, min_count=1)
    near_bid = l2[near_bid_cols].sum(axis=1, min_count=1)
    near_ask = l2[near_ask_cols].sum(axis=1, min_count=1)

    deep_total = deep_bid + deep_ask
    near_total = near_bid + near_ask

    ratio = deep_total / near_total.replace(0, np.nan)

    spread = None
    if "bid_px_1" in l2.columns and "ask_px_1" in l2.columns:
        spread = l2["ask_px_1"] - l2["bid_px_1"]

    result = pd.DataFrame(
        {
            "deep_total": deep_total,
            "near_total": near_total,
            "ratio": ratio,
            "spread": spread if spread is not None else np.nan,
        },
        index=full_index,
    )

    meta = {
        "max_level": max_level,
        "deep_min": deep_min,
        "deep_max": deep_max,
        "near_max": near_max,
    }

    return result, meta


def rolling_mad(series: pd.Series, window: int, min_periods: int) -> pd.Series:
    def mad(arr: np.ndarray) -> float:
        median = np.nanmedian(arr)
        if np.isnan(median):
            return np.nan
        return float(np.nanmedian(np.abs(arr - median)))

    return series.rolling(window=window, min_periods=min_periods).apply(mad, raw=True)


def find_event_times(
    signal: pd.Series,
    persistence_seconds: int,
    cooldown_seconds: int,
) -> List[pd.Timestamp]:
    signal = signal.fillna(False)
    group_id = signal.ne(signal.shift()).cumsum()
    event_times: List[pd.Timestamp] = []

    for _, group in signal.groupby(group_id):
        if not group.iloc[0]:
            continue
        if len(group) >= persistence_seconds:
            event_times.append(group.index[0])

    filtered: List[pd.Timestamp] = []
    last_time: Optional[pd.Timestamp] = None
    for ts in event_times:
        if last_time is None or (ts - last_time).total_seconds() >= cooldown_seconds:
            filtered.append(ts)
            last_time = ts

    return filtered


def compute_events(
    seconds_df: pd.DataFrame,
    group: L2Group,
    config: dict,
    definitions: Sequence[EventDefinition],
    threshold: float,
) -> List[EventRecord]:
    window = int(config["baseline_window_minutes"] * 60)
    min_periods = int(config["baseline_min_periods"])

    deep_total = seconds_df["deep_total"]
    ratio = seconds_df["ratio"]

    median = None
    mad = None
    robust_z = None
    if config.get("use_robust_z"):
        median = deep_total.rolling(window=window, min_periods=min_periods).median()
        mad = rolling_mad(deep_total, window=window, min_periods=min_periods)
        robust_z = (deep_total - median) / (1.4826 * mad.replace(0, np.nan))

    events: List[EventRecord] = []

    session_start = pd.Timestamp(
        f"{group.date} {config['session_start']}", tz=seconds_df.index.tz
    )
    session_end = pd.Timestamp(
        f"{group.date} {config['session_end']}", tz=seconds_df.index.tz
    )

    earliest = session_start + pd.Timedelta(minutes=config["exclude_first_minutes"])
    latest = session_end - pd.Timedelta(minutes=config["exclude_last_minutes"])

    for definition in definitions:
        if definition.key == "def_a":
            q99 = deep_total.rolling(window=window, min_periods=min_periods).quantile(
                threshold
            )
            unusual = deep_total >= q99
            if robust_z is not None:
                unusual = unusual | (
                    (q99.isna()) & (robust_z >= config["robust_z_threshold"])
                )
            signal = unusual
            threshold_value = threshold
        elif definition.key == "def_b":
            q_ratio = ratio.rolling(window=window, min_periods=min_periods).quantile(
                definition.percentile_ratio
            )
            q_deep = deep_total.rolling(
                window=window, min_periods=min_periods
            ).quantile(definition.percentile_deep)
            signal = (ratio >= q_ratio) & (deep_total >= q_deep)
            threshold_value = definition.percentile_ratio or 0.0
        else:
            raise ValueError(f"Unknown definition: {definition.key}")

        event_times = find_event_times(
            signal=signal,
            persistence_seconds=definition.persistence_seconds,
            cooldown_seconds=config["cooldown_seconds"],
        )

        for ts in event_times:
            if ts < earliest or ts >= latest:
                continue
            event_minute = ts.floor("min")
            deep_value = deep_total.loc[ts]
            ratio_value = ratio.loc[ts]
            events.append(
                EventRecord(
                    symbol=group.symbol,
                    date=group.date,
                    definition=definition.key,
                    threshold=threshold_value,
                    event_ts=ts,
                    event_minute=event_minute,
                    deep_total=float(deep_value) if not pd.isna(deep_value) else np.nan,
                    ratio=float(ratio_value) if not pd.isna(ratio_value) else np.nan,
                )
            )

    return events


def polygon_api_key() -> str:
    for key in ("POLYGON_API_KEY", "POLYGON_APIKEY", "POLYGON_KEY"):
        if key in os.environ:
            return os.environ[key]
    raise RuntimeError("Polygon API key not found in environment")


def fetch_polygon_ohlcv(
    symbol: str,
    date: str,
    tz: str,
    config: dict,
    cache_dir: Path,
) -> pd.DataFrame:
    ensure_dir(cache_dir)
    cache_path = cache_dir / f"{symbol}_{date}.parquet"
    today_et = pd.Timestamp.now(tz=tz).strftime("%Y-%m-%d")
    if cache_path.exists() and date != today_et:
        df = pd.read_parquet(cache_path)
        expected_cols = {"ts_minute", "open", "high", "low", "close", "volume"}
        if not expected_cols.issubset(df.columns):
            raise RuntimeError(f"Cached OHLCV missing columns: {cache_path}")
        df["ts_minute"] = pd.to_datetime(df["ts_minute"])
        if df["ts_minute"].dt.tz is None:
            df["ts_minute"] = df["ts_minute"].dt.tz_localize(tz)
        return df

    api_key = polygon_api_key()
    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol}/range/1/minute/{date}/{date}"
    params = {
        "adjusted": str(config["polygon"]["adjusted"]).lower(),
        "sort": "asc",
        "limit": config["polygon"]["limit"],
        "apiKey": api_key,
    }
    response = requests.get(url, params=params, timeout=30)
    if response.status_code != 200:
        raise RuntimeError(
            f"Polygon request failed ({response.status_code}): {response.text}"
        )

    payload = response.json()
    if "results" not in payload:
        raise RuntimeError(f"Polygon response missing results for {symbol} {date}")

    results = payload["results"]
    if not results:
        raise RuntimeError(f"No OHLCV data returned by Polygon for {symbol} {date}")

    df = pd.DataFrame(results)
    df = df.rename(
        columns={
            "t": "ts_ms",
            "o": "open",
            "h": "high",
            "l": "low",
            "c": "close",
            "v": "volume",
        }
    )
    df["ts_utc"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df["ts_minute"] = df["ts_utc"].dt.tz_convert(tz).dt.floor("min")

    df = df[["ts_minute", "open", "high", "low", "close", "volume"]]
    df = df.drop_duplicates("ts_minute").sort_values("ts_minute")

    session_start = pd.Timestamp(f"{date} {config['session_start']}", tz=tz)
    session_end = pd.Timestamp(f"{date} {config['session_end']}", tz=tz)
    df = df[(df["ts_minute"] >= session_start) & (df["ts_minute"] <= session_end)]

    if df.empty:
        raise RuntimeError(f"No OHLCV data in session for {symbol} {date}")

    df.to_parquet(cache_path, index=False)
    return df


def compute_minute_panel(
    ohlcv: pd.DataFrame,
    symbol: str,
    date: str,
    tz: str,
    config: dict,
    events_by_def: Dict[str, List[pd.Timestamp]],
) -> pd.DataFrame:
    ohlcv = ohlcv.copy()
    ohlcv = ohlcv.sort_values("ts_minute")

    session_start = pd.Timestamp(f"{date} {config['session_start']}", tz=tz)
    minutes_since_open = (
        (ohlcv["ts_minute"] - session_start).dt.total_seconds() / 60
    ).astype(int)
    ohlcv["time_bucket"] = (minutes_since_open // 30).astype(int)

    ohlcv["log_ret_1m"] = np.log(ohlcv["close"] / ohlcv["close"].shift(1))
    ohlcv["vol_30m"] = ohlcv["log_ret_1m"].rolling(30, min_periods=15).std()
    ohlcv["volume_30m"] = ohlcv["volume"].rolling(30, min_periods=15).mean()
    ohlcv["hl_range"] = ohlcv["high"] - ohlcv["low"]

    ohlcv["t0_price"] = ohlcv["open"].shift(-1)
    ohlcv["t1_price"] = ohlcv["close"].shift(-config["forward_minutes"])
    ohlcv["ret_300s"] = np.log(ohlcv["t1_price"] / ohlcv["t0_price"])

    ohlcv["pre_open"] = ohlcv["open"].shift(config["pre_minutes"] - 1)
    ohlcv["ret_pre_300s"] = np.log(ohlcv["close"] / ohlcv["pre_open"])

    panel = ohlcv[
        [
            "ts_minute",
            "time_bucket",
            "ret_300s",
            "ret_pre_300s",
            "vol_30m",
            "volume_30m",
            "hl_range",
        ]
    ].copy()
    panel["symbol"] = symbol
    panel["date"] = date

    for definition, event_minutes in events_by_def.items():
        panel[f"event_{definition}"] = (
            panel["ts_minute"].isin(event_minutes).astype(int)
        )

    return panel


def demean_two_way(
    df: pd.DataFrame, cols: List[str], group_a: str, group_b: str
) -> pd.DataFrame:
    overall = df[cols].mean()
    mean_a = df.groupby(group_a)[cols].transform("mean")
    mean_b = df.groupby(group_b)[cols].transform("mean")
    return df[cols] - mean_a - mean_b + overall


def demean_one_way(df: pd.DataFrame, cols: List[str], group: str) -> pd.DataFrame:
    overall = df[cols].mean()
    mean_group = df.groupby(group)[cols].transform("mean")
    return df[cols] - mean_group + overall


def compute_coef(
    panel: pd.DataFrame,
    event_col: str,
    outcome_col: str,
    include_symbol_fe: bool,
    include_bucket_fe: bool,
    controls: List[str],
) -> float:
    cols = [event_col] + controls
    subset = panel[[outcome_col, "symbol", "time_bucket"] + cols].dropna()
    if subset.empty:
        return float("nan")

    if include_symbol_fe and include_bucket_fe:
        X = demean_two_way(subset, cols, "symbol", "time_bucket")
        y = demean_two_way(subset, [outcome_col], "symbol", "time_bucket")
    elif include_bucket_fe:
        X = demean_one_way(subset, cols, "time_bucket")
        y = demean_one_way(subset, [outcome_col], "time_bucket")
    else:
        X = subset[cols]
        y = subset[[outcome_col]]

    x_vals = X.to_numpy()
    y_vals = y.to_numpy().ravel()
    if x_vals.size == 0:
        return float("nan")

    coef, _, _, _ = np.linalg.lstsq(x_vals, y_vals, rcond=None)
    return float(coef[0])


def bootstrap_effect(
    panel: pd.DataFrame,
    event_col: str,
    outcome_col: str,
    rng: np.random.Generator,
    bootstrap_reps: int,
    include_symbol_fe: bool,
    include_bucket_fe: bool,
    controls: List[str],
) -> Tuple[float, float, float, float]:
    coef = compute_coef(
        panel,
        event_col,
        outcome_col,
        include_symbol_fe,
        include_bucket_fe,
        controls,
    )

    if math.isnan(coef):
        return coef, float("nan"), float("nan"), float("nan")

    grouped = {
        (symbol, date): group
        for (symbol, date), group in panel.groupby(["symbol", "date"], sort=False)
    }
    symbol_dates: Dict[str, List[str]] = {}
    for symbol, date in grouped.keys():
        symbol_dates.setdefault(symbol, []).append(date)

    boot_coefs = []
    for _ in range(bootstrap_reps):
        samples: List[pd.DataFrame] = []
        for symbol, dates in symbol_dates.items():
            if not dates:
                continue
            draw = rng.choice(dates, size=len(dates), replace=True)
            for date in draw:
                samples.append(grouped[(symbol, date)])
        if not samples:
            continue
        sample_df = pd.concat(samples, ignore_index=True)
        boot_coef = compute_coef(
            sample_df,
            event_col,
            outcome_col,
            include_symbol_fe,
            include_bucket_fe,
            controls,
        )
        if not math.isnan(boot_coef):
            boot_coefs.append(boot_coef)

    if not boot_coefs:
        return coef, float("nan"), float("nan"), float("nan")

    boot_arr = np.array(boot_coefs)
    ci_low = float(np.percentile(boot_arr, 2.5))
    ci_high = float(np.percentile(boot_arr, 97.5))
    p_value = float(2 * min((boot_arr >= 0).mean(), (boot_arr <= 0).mean()))

    return coef, ci_low, ci_high, p_value


def compute_effect_table(
    panel: pd.DataFrame,
    definition: str,
    event_col: str,
    outcome_col: str,
    rng: np.random.Generator,
    bootstrap_reps: int,
    include_symbol_fe: bool,
    include_bucket_fe: bool,
    controls: List[str],
) -> pd.DataFrame:
    coef, ci_low, ci_high, p_value = bootstrap_effect(
        panel=panel,
        event_col=event_col,
        outcome_col=outcome_col,
        rng=rng,
        bootstrap_reps=bootstrap_reps,
        include_symbol_fe=include_symbol_fe,
        include_bucket_fe=include_bucket_fe,
        controls=controls,
    )

    analysis_panel = panel[[event_col, outcome_col] + controls].dropna()
    n_events = int(analysis_panel[event_col].sum())
    n_controls = int((analysis_panel[event_col] == 0).sum())

    return pd.DataFrame(
        [
            {
                "definition": definition,
                "coef_event": coef,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "p_value": p_value,
                "n_events": n_events,
                "n_controls": n_controls,
            }
        ]
    )


def per_symbol_effects(
    panel: pd.DataFrame,
    definition: str,
    event_col: str,
    outcome_col: str,
    rng: np.random.Generator,
    bootstrap_reps: int,
    controls: List[str],
) -> pd.DataFrame:
    rows = []
    for symbol, group in panel.groupby("symbol"):
        coef, ci_low, ci_high, _ = bootstrap_effect(
            panel=group,
            event_col=event_col,
            outcome_col=outcome_col,
            rng=rng,
            bootstrap_reps=bootstrap_reps,
            include_symbol_fe=False,
            include_bucket_fe=True,
            controls=controls,
        )
        n_events = int(group[event_col].sum())
        if n_events == 0:
            continue
        rows.append(
            {
                "symbol": symbol,
                "definition": definition,
                "coef_event": coef,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n_events": n_events,
            }
        )

    if not rows:
        return pd.DataFrame(
            columns=[
                "symbol",
                "definition",
                "coef_event",
                "ci_low",
                "ci_high",
                "n_events",
            ]
        )

    return pd.DataFrame(rows)


def generate_placebo_indicator(
    panel: pd.DataFrame,
    event_col: str,
    rng: np.random.Generator,
) -> pd.Series:
    indicator = pd.Series(0, index=panel.index)
    grouped = panel.groupby(["symbol", "date", "time_bucket"])
    for _, group in grouped:
        n_events = int(group[event_col].sum())
        if n_events == 0:
            continue
        eligible_idx = group.index
        if n_events > len(eligible_idx):
            raise RuntimeError("Placebo sampling exceeds available minutes")
        chosen = rng.choice(eligible_idx, size=n_events, replace=False)
        indicator.loc[chosen] = 1

    return indicator


def apply_falsification_shift(
    panel: pd.DataFrame,
    event_col: str,
    shift_minutes: int,
) -> pd.Series:
    event_minutes = panel.loc[panel[event_col] == 1, "ts_minute"] + pd.Timedelta(
        minutes=shift_minutes
    )
    shifted = panel["ts_minute"].isin(event_minutes).astype(int)
    return shifted


def build_event_counts(events: List[EventRecord]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(
            columns=["symbol", "definition", "n_events", "n_days", "avg_events_per_day"]
        )

    df = pd.DataFrame(
        [
            {
                "symbol": event.symbol,
                "definition": event.definition,
                "date": event.date,
            }
            for event in events
        ]
    )
    counts = df.groupby(["symbol", "definition"]).size().reset_index(name="n_events")
    days = (
        df.groupby(["symbol", "definition"])["date"]
        .nunique()
        .reset_index(name="n_days")
    )
    merged = counts.merge(days, on=["symbol", "definition"])
    merged["avg_events_per_day"] = merged["n_events"] / merged["n_days"].replace(
        0, np.nan
    )
    totals = (
        merged.groupby("definition")
        .agg(n_events=("n_events", "sum"), n_days=("n_days", "sum"))
        .reset_index()
    )
    totals["symbol"] = "TOTAL"
    totals["avg_events_per_day"] = totals["n_events"] / totals["n_days"].replace(
        0, np.nan
    )
    merged = pd.concat([merged, totals], ignore_index=True)
    return merged


def markdown_table(df: pd.DataFrame) -> str:
    if df.empty:
        return "(no rows)"
    headers = list(df.columns)
    rows = [headers] + df.astype(str).values.tolist()
    widths = [max(len(str(row[i])) for row in rows) for i in range(len(headers))]
    lines = []
    header_line = (
        "| "
        + " | ".join(str(headers[i]).ljust(widths[i]) for i in range(len(headers)))
        + " |"
    )
    sep_line = "| " + " | ".join("-" * widths[i] for i in range(len(headers))) + " |"
    lines.append(header_line)
    lines.append(sep_line)
    for row in rows[1:]:
        lines.append(
            "| "
            + " | ".join(str(row[i]).ljust(widths[i]) for i in range(len(headers)))
            + " |"
        )
    return "\n".join(lines)


def run_experiment(
    l2_root: Path,
    ohlcv_source: str,
    tz: str,
    run_id: str,
    output_dir: Path,
    placebo: bool,
    falsification: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    symbols: Optional[Sequence[str]],
    config_path: Path,
) -> None:
    if ohlcv_source.lower() != "polygon":
        raise ValueError("Only Polygon OHLCV is supported")

    config = load_config(config_path)
    ensure_dir(output_dir)

    if falsification and falsification != "shift_30m":
        raise ValueError("Only falsification mode supported is 'shift_30m'")

    rng = np.random.default_rng(config["seed"])

    definitions = [
        EventDefinition(
            key="def_a",
            name=config["definitions"]["def_a"]["name"],
            percentile=config["definitions"]["def_a"]["percentile"],
            persistence_seconds=config["definitions"]["def_a"]["persistence_seconds"],
        ),
        EventDefinition(
            key="def_b",
            name=config["definitions"]["def_b"]["name"],
            percentile_ratio=config["definitions"]["def_b"]["percentile_ratio"],
            percentile_deep=config["definitions"]["def_b"]["percentile_deep"],
            persistence_seconds=config["definitions"]["def_b"]["persistence_seconds"],
        ),
    ]

    l2_groups = discover_l2_groups(l2_root, start_date, end_date, symbols)
    events: List[EventRecord] = []
    panel_frames: List[pd.DataFrame] = []
    l2_meta: List[dict] = []
    skipped_groups: List[dict] = []
    dropped_events = {"def_a": 0, "def_b": 0}

    cache_dir = output_dir / "cache" / "ohlcv"

    thresholds = list(config.get("thresholds", [definitions[0].percentile]))
    fallback_threshold = config.get("fallback_threshold")
    if fallback_threshold and fallback_threshold not in thresholds:
        thresholds.append(fallback_threshold)
    thresholds = sorted(set(thresholds), reverse=True)

    for group in l2_groups:
        logger.info("Processing %s %s", group.symbol, group.date)
        try:
            seconds_df, meta = load_l2_seconds(group, config, tz)
        except RuntimeError as exc:
            message = str(exc)
            if (
                message.startswith("No L2 data read")
                or message.startswith("No L2 snapshots in session")
                or message.startswith("Missing bid/ask size columns")
                or message.startswith("Insufficient depth levels")
            ):
                logger.warning("Skipping %s %s: %s", group.symbol, group.date, message)
                skipped_groups.append(
                    {"symbol": group.symbol, "date": group.date, "reason": message}
                )
                continue
            raise
        l2_meta.append({"symbol": group.symbol, "date": group.date, **meta})

        event_records: List[EventRecord] = []
        for threshold in thresholds:
            event_records.extend(
                compute_events(seconds_df, group, config, [definitions[0]], threshold)
            )
        event_records.extend(
            compute_events(seconds_df, group, config, [definitions[1]], thresholds[0])
        )

        events.extend(event_records)

        events_by_def: Dict[str, List[pd.Timestamp]] = {"def_a": [], "def_b": []}
        for record in event_records:
            if record.definition == "def_a" and record.threshold != thresholds[0]:
                continue
            events_by_def[record.definition].append(record.event_minute)

        ohlcv = fetch_polygon_ohlcv(group.symbol, group.date, tz, config, cache_dir)
        panel = compute_minute_panel(
            ohlcv, group.symbol, group.date, tz, config, events_by_def
        )

        for definition in ("def_a", "def_b"):
            mask = (panel[f"event_{definition}"] == 1) & panel["ret_300s"].isna()
            dropped_events[definition] += int(mask.sum())

        panel_frames.append(panel)

    events_df = pd.DataFrame(
        [
            {
                "symbol": event.symbol,
                "date": event.date,
                "definition": event.definition,
                "threshold": event.threshold,
                "event_ts": event.event_ts,
                "event_minute": event.event_minute,
                "deep_total": event.deep_total,
                "ratio": event.ratio,
            }
            for event in events
        ]
    )
    if events_df.empty:
        events_df = pd.DataFrame(
            columns=[
                "symbol",
                "date",
                "definition",
                "threshold",
                "event_ts",
                "event_minute",
                "deep_total",
                "ratio",
            ]
        )

    panel_df = (
        pd.concat(panel_frames, ignore_index=True) if panel_frames else pd.DataFrame()
    )

    events_path = output_dir / "events.parquet"
    panel_path = output_dir / "panel.parquet"
    metrics_path = output_dir / "metrics.csv"
    results_path = output_dir / "RESULTS.md"
    meta_path = output_dir / "run_meta.json"

    events_df.to_parquet(events_path, index=False)
    panel_df.to_parquet(panel_path, index=False)

    controls = ["vol_30m"]
    if config["controls"].get("use_volume_30m"):
        controls.append("volume_30m")
    if config["controls"].get("use_hl_range"):
        controls.append("hl_range")

    analysis_results: List[pd.DataFrame] = []
    placebo_results: List[pd.DataFrame] = []
    falsification_results: List[pd.DataFrame] = []
    pretrend_results: List[pd.DataFrame] = []
    regime_results: List[pd.DataFrame] = []
    sensitivity_results: List[pd.DataFrame] = []

    if panel_df.empty:
        raise RuntimeError("Panel data is empty; cannot run analysis")

    for definition in ("def_a", "def_b"):
        event_col = f"event_{definition}"
        analysis_results.append(
            compute_effect_table(
                panel_df,
                definition,
                event_col,
                "ret_300s",
                rng,
                config["bootstrap_reps"],
                include_symbol_fe=True,
                include_bucket_fe=True,
                controls=controls,
            )
        )
        pretrend_results.append(
            compute_effect_table(
                panel_df,
                definition,
                event_col,
                "ret_pre_300s",
                rng,
                config["bootstrap_reps"],
                include_symbol_fe=True,
                include_bucket_fe=True,
                controls=controls,
            )
        )

        if placebo:
            placebo_indicator = generate_placebo_indicator(panel_df, event_col, rng)
            panel_df[f"placebo_{definition}"] = placebo_indicator
            placebo_results.append(
                compute_effect_table(
                    panel_df,
                    definition,
                    f"placebo_{definition}",
                    "ret_300s",
                    rng,
                    config["bootstrap_reps"],
                    include_symbol_fe=True,
                    include_bucket_fe=True,
                    controls=controls,
                )
            )

        if falsification:
            shift_minutes = 30
            panel_df[f"falsification_{definition}"] = apply_falsification_shift(
                panel_df, event_col, shift_minutes
            )
            falsification_results.append(
                compute_effect_table(
                    panel_df,
                    definition,
                    f"falsification_{definition}",
                    "ret_300s",
                    rng,
                    config["bootstrap_reps"],
                    include_symbol_fe=True,
                    include_bucket_fe=True,
                    controls=controls,
                )
            )

        vol_median = panel_df.groupby(["symbol", "date"])["vol_30m"].transform("median")
        panel_df["regime"] = np.where(panel_df["vol_30m"] >= vol_median, "high", "low")
        for label, reg_group in panel_df.groupby("regime"):
            if reg_group.empty:
                continue
            coef, ci_low, ci_high, _ = bootstrap_effect(
                panel=reg_group,
                event_col=event_col,
                outcome_col="ret_300s",
                rng=rng,
                bootstrap_reps=config["bootstrap_reps"],
                include_symbol_fe=True,
                include_bucket_fe=True,
                controls=controls,
            )
            regime_results.append(
                pd.DataFrame(
                    [
                        {
                            "definition": definition,
                            "regime": label,
                            "coef_event": coef,
                            "ci_low": ci_low,
                            "ci_high": ci_high,
                            "n_events": int(reg_group[event_col].sum()),
                        }
                    ]
                )
            )

    primary_df = pd.concat(analysis_results, ignore_index=True)
    pretrend_df = pd.concat(pretrend_results, ignore_index=True)
    placebo_df = (
        pd.concat(placebo_results, ignore_index=True)
        if placebo_results
        else pd.DataFrame()
    )
    falsification_df = (
        pd.concat(falsification_results, ignore_index=True)
        if falsification_results
        else pd.DataFrame()
    )

    per_symbol_df = pd.concat(
        [
            per_symbol_effects(
                panel_df,
                definition,
                f"event_{definition}",
                "ret_300s",
                rng,
                config["bootstrap_reps"],
                controls,
            )
            for definition in ("def_a", "def_b")
        ],
        ignore_index=True,
    )

    event_counts_df = build_event_counts(events)

    sensitivity_df = pd.DataFrame()
    if not events_df.empty:
        main_threshold = thresholds[0]
        def_a_main = events_df[
            (events_df["definition"] == "def_a")
            & (events_df["threshold"] == main_threshold)
        ]
        if fallback_threshold and len(def_a_main) < config["min_events_target"]:
            for threshold in thresholds:
                if threshold == main_threshold:
                    continue
                event_minutes = events_df[
                    (events_df["definition"] == "def_a")
                    & (events_df["threshold"] == threshold)
                ]["event_minute"]
                panel_df["event_sensitivity"] = (
                    panel_df["ts_minute"].isin(event_minutes).astype(int)
                )
                result = compute_effect_table(
                    panel_df,
                    "def_a",
                    "event_sensitivity",
                    "ret_300s",
                    rng,
                    config["bootstrap_reps"],
                    include_symbol_fe=True,
                    include_bucket_fe=True,
                    controls=controls,
                )
                result["threshold"] = threshold
                sensitivity_results.append(result)
            panel_df = panel_df.drop(columns=["event_sensitivity"])
        if sensitivity_results:
            sensitivity_df = pd.concat(sensitivity_results, ignore_index=True)

    regime_df = (
        pd.concat(regime_results, ignore_index=True)
        if regime_results
        else pd.DataFrame()
    )

    metrics_frames = [
        primary_df.assign(analysis="primary"),
        pretrend_df.assign(analysis="pretrend"),
    ]
    if not placebo_df.empty:
        metrics_frames.append(placebo_df.assign(analysis="placebo"))
    if not falsification_df.empty:
        metrics_frames.append(falsification_df.assign(analysis="falsification"))
    if not regime_df.empty:
        metrics_frames.append(regime_df.assign(analysis="regime"))
    if not sensitivity_df.empty:
        metrics_frames.append(sensitivity_df.assign(analysis="sensitivity"))

    metrics_df = pd.concat(metrics_frames, ignore_index=True)
    metrics_df.to_csv(metrics_path, index=False)

    results_sections = []
    results_sections.append("# Deep L2 Liquidity Impact Results\n")
    results_sections.append("## Event Counts\n")
    results_sections.append(markdown_table(event_counts_df))
    results_sections.append("\n## Pooled Effect (Primary)\n")
    results_sections.append(markdown_table(primary_df))
    results_sections.append("\n## Per-Symbol Effects\n")
    results_sections.append(markdown_table(per_symbol_df))
    results_sections.append("\n## Placebo Results\n")
    results_sections.append(markdown_table(placebo_df))
    results_sections.append("\n## Falsification Results\n")
    results_sections.append(markdown_table(falsification_df))
    results_sections.append("\n## Pre-Trend Check\n")
    results_sections.append(markdown_table(pretrend_df))
    results_sections.append("\n## Regime Stratification\n")
    results_sections.append(markdown_table(regime_df))
    results_sections.append("\n## Threshold Sensitivity\n")
    results_sections.append(markdown_table(sensitivity_df))

    results_sections.append("\n## Notes\n")
    results_sections.append(
        f"Dropped events due to missing forward bars: {json.dumps(dropped_events)}\n"
    )
    if skipped_groups:
        results_sections.append(
            f"Skipped L2 groups with no data: {len(skipped_groups)}\n"
        )
    if sensitivity_df.shape[0] > 0:
        results_sections.append(
            "Fallback threshold applied for Definition A due to low counts.\n"
        )

    results_path.write_text("\n".join(results_sections), encoding="utf-8")

    run_meta = {
        "run_id": run_id,
        "mode": (
            "placebo" if placebo else "falsification" if falsification else "primary"
        ),
        "placebo": placebo,
        "falsification": falsification,
        "config": config,
        "seed": config["seed"],
        "l2_root": str(l2_root),
        "ohlcv_source": ohlcv_source,
        "timezone": tz,
        "start_date": start_date,
        "end_date": end_date,
        "symbols": list(symbols) if symbols else None,
        "l2_groups": len(l2_groups),
        "l2_meta": l2_meta,
        "skipped_l2_groups": skipped_groups,
        "dropped_events": dropped_events,
        "thresholds": thresholds,
        "fallback_threshold_used": bool(sensitivity_df.shape[0]),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }
    meta_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")

    ticket_summary_path = output_dir.parent / "l2_deep_liquidity_300s_summary.md"
    ticket_results_path = output_dir.parent / "l2_deep_liquidity_300s_results.csv"
    ticket_placebo_path = output_dir.parent / "l2_deep_liquidity_300s_placebo.csv"
    ticket_falsification_path = (
        output_dir.parent / "l2_deep_liquidity_300s_falsification.csv"
    )
    ticket_metadata_path = output_dir.parent / "l2_deep_liquidity_300s_metadata.json"

    ticket_summary_path.write_text("\n".join(results_sections), encoding="utf-8")
    primary_df.to_csv(ticket_results_path, index=False)
    placebo_df.to_csv(ticket_placebo_path, index=False)
    falsification_df.to_csv(ticket_falsification_path, index=False)
    ticket_metadata_path.write_text(json.dumps(run_meta, indent=2), encoding="utf-8")
