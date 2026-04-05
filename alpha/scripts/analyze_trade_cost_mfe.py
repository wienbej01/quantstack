from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import psycopg2
import pyarrow as pa
import pyarrow.dataset as ds


RAW_L2_ROOTS = [
    Path("/home/jacobw/quantstack-v2/data/l2/l2_maximum/raw"),
    Path("/home/jacobw/quantstack/data/l2/l2_maximum/raw"),
    Path("/home/jacobw/quantstack/data/l2_maximum/raw"),
]

CURRENT_PATH_TEMPLATES = {
    "bid_depth_obi": (10.0, 15.0),
    "high_obi_depth": (10.0, 15.0),
    "large_order_size": (10.0, 15.0),
    "micro_offset_exhaustion": (50.0, 75.0),
    "obi_depth_combo": (10.0, 15.0),
    "obi_momentum": (10.0, 15.0),
}


@dataclass(frozen=True)
class AnalysisConfig:
    start_date: str
    end_date: str | None
    output_dir: Path
    max_horizon_seconds: int
    horizons: tuple[int, ...]
    path_horizons: tuple[int, ...]
    path_stop_bps: tuple[float, ...]
    path_r_multiples: tuple[float, ...]
    path_system: str
    matrix_min_decided: int


@dataclass
class TradePath:
    trade_id: str
    system: str
    strategy: str
    substrategy: str
    symbol: str
    session_date_et: str
    direction: str
    entry_price: float
    exit_price: float
    exit_reason: str
    gross_pnl: float
    net_pnl: float
    gross_bps_on_entry: float
    net_bps_on_entry: float
    hold_seconds: float
    exit_elapsed_seconds: float
    raw_root_used: str | None
    elapsed_seconds: np.ndarray
    favorable_bps: np.ndarray
    adverse_bps: np.ndarray


def parse_args() -> AnalysisConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Analyze gross/net trade performance, entry-side MFE, and path-aware "
            "holding-period x R matrices from saved raw L2 data."
        )
    )
    parser.add_argument(
        "--start-date", default="2026-02-20", help="Inclusive ET session date."
    )
    parser.add_argument("--end-date", default=None, help="Inclusive ET session date.")
    parser.add_argument(
        "--output-dir",
        default="reports/trade_cost_mfe_extended",
        help="Directory for CSV/JSON/Markdown outputs.",
    )
    parser.add_argument(
        "--max-horizon-seconds",
        type=int,
        default=300,
        help="Maximum forward horizon from entry used for MFE/path analysis.",
    )
    parser.add_argument(
        "--horizons",
        default="60,180,300",
        help="Comma-separated forward horizons in seconds for MFE summaries.",
    )
    parser.add_argument(
        "--path-horizons",
        default="30,60,120,180,300",
        help="Comma-separated holding periods in seconds for path-aware matrices.",
    )
    parser.add_argument(
        "--path-stop-bps",
        default="5,10,15,20,30,50",
        help="Comma-separated stop sizes in bps for path-aware matrices.",
    )
    parser.add_argument(
        "--path-r-multiples",
        default="1.0,1.5,2.0",
        help="Comma-separated TP/SL R multiples for path-aware matrices.",
    )
    parser.add_argument(
        "--path-system",
        default="l2-scalping",
        help="System to use for the path-aware holding-period x R matrix.",
    )
    parser.add_argument(
        "--matrix-min-decided",
        type=int,
        default=10,
        help="Minimum decided trades used when selecting best matrix cells.",
    )
    args = parser.parse_args()

    horizons = parse_int_tuple(args.horizons)
    path_horizons = parse_int_tuple(args.path_horizons)
    path_stop_bps = parse_float_tuple(args.path_stop_bps)
    path_r_multiples = parse_float_tuple(args.path_r_multiples)
    max_horizon_seconds = max(
        args.max_horizon_seconds,
        max(horizons, default=0),
        max(path_horizons, default=0),
    )
    return AnalysisConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=Path(args.output_dir),
        max_horizon_seconds=max_horizon_seconds,
        horizons=horizons,
        path_horizons=path_horizons,
        path_stop_bps=path_stop_bps,
        path_r_multiples=path_r_multiples,
        path_system=args.path_system,
        matrix_min_decided=args.matrix_min_decided,
    )


def parse_int_tuple(value: str) -> tuple[int, ...]:
    parsed = tuple(sorted({int(part) for part in value.split(",") if part.strip()}))
    if not parsed:
        raise ValueError("At least one integer value is required.")
    return parsed


def parse_float_tuple(value: str) -> tuple[float, ...]:
    parsed = tuple(sorted({float(part) for part in value.split(",") if part.strip()}))
    if not parsed:
        raise ValueError("At least one numeric value is required.")
    return parsed


def fetch_closed_trades(config: AnalysisConfig) -> pd.DataFrame:
    conn = psycopg2.connect(dbname="trading")
    try:
        with conn.cursor() as cur:
            sql = """
                SELECT
                    trade_id::text,
                    system,
                    COALESCE(strategy, '') AS strategy,
                    COALESCE(substrategy, '') AS substrategy,
                    symbol,
                    direction,
                    entry_time,
                    exit_time,
                    entry_price::float8 AS entry_price,
                    exit_price::float8 AS exit_price,
                    entry_qty,
                    exit_qty,
                    gross_pnl::float8 AS gross_pnl,
                    total_commission::float8 AS total_commission,
                    net_pnl::float8 AS net_pnl,
                    hold_seconds::float8 AS hold_seconds,
                    COALESCE(exit_reason, '') AS exit_reason,
                    signal_price::float8 AS signal_price,
                    entry_slippage_bps::float8 AS entry_slippage_bps,
                    exit_slippage_bps::float8 AS exit_slippage_bps,
                    ((entry_time AT TIME ZONE 'America/New_York')::date)::text AS session_date_et
                FROM trades_v2
                WHERE status = 'CLOSED'
                  AND entry_time IS NOT NULL
                  AND exit_time IS NOT NULL
                  AND entry_time >= %s::date
            """
            params: list[Any] = [config.start_date]
            if config.end_date:
                sql += " AND ((entry_time AT TIME ZONE 'America/New_York')::date) <= %s::date"
                params.append(config.end_date)
            sql += """
                  AND entry_price IS NOT NULL
                  AND exit_price IS NOT NULL
                  AND entry_qty IS NOT NULL
                  AND exit_qty IS NOT NULL
                ORDER BY entry_time
            """
            cur.execute(sql, params)
            rows = cur.fetchall()
            columns = [desc[0] for desc in cur.description]
    finally:
        conn.close()

    trades = pd.DataFrame(rows, columns=columns)
    if trades.empty:
        raise RuntimeError("No closed trades found for the requested date range.")

    trades["strategy_key"] = trades.apply(
        lambda row: " / ".join(
            [
                part
                for part in [row["system"], row["strategy"], row["substrategy"]]
                if part
            ]
        ),
        axis=1,
    )
    trades["entry_notional"] = trades["entry_price"] * trades["entry_qty"].abs()
    trades["exit_notional"] = trades["exit_price"] * trades["exit_qty"].abs()
    trades["roundtrip_notional"] = trades["entry_notional"] + trades["exit_notional"]
    trades["gross_bps_on_entry"] = np.where(
        trades["entry_notional"] > 0,
        trades["gross_pnl"] / trades["entry_notional"] * 10000.0,
        np.nan,
    )
    trades["net_bps_on_entry"] = np.where(
        trades["entry_notional"] > 0,
        trades["net_pnl"] / trades["entry_notional"] * 10000.0,
        np.nan,
    )
    trades["commission_bps_on_entry"] = np.where(
        trades["entry_notional"] > 0,
        trades["total_commission"] / trades["entry_notional"] * 10000.0,
        np.nan,
    )
    return trades


def resolve_raw_symbol_dir(
    session_date_et: str, symbol: str
) -> tuple[Path | None, str | None]:
    for root in RAW_L2_ROOTS:
        symbol_dir = root / f"date={session_date_et}" / f"symbol={symbol}"
        if symbol_dir.exists() and any(symbol_dir.glob("*.parquet")):
            return symbol_dir, str(root)
    return None, None


def load_mid_series(
    session_date_et: str, symbol: str
) -> tuple[pd.DataFrame | None, str | None]:
    symbol_dir, root_used = resolve_raw_symbol_dir(session_date_et, symbol)
    if symbol_dir is None:
        return None, None

    parquet_files = sorted(symbol_dir.glob("*.parquet"))
    if not parquet_files:
        return None, root_used

    schema = pa.schema(
        [
            pa.field("ts_epoch", pa.float64()),
            pa.field("l1_mid", pa.float64()),
            pa.field("l1_bid", pa.float64()),
            pa.field("l1_ask", pa.float64()),
            pa.field("l1_spread", pa.float64()),
        ]
    )
    table = ds.dataset(parquet_files, format="parquet", schema=schema).to_table(
        columns=["ts_epoch", "l1_mid", "l1_bid", "l1_ask", "l1_spread"]
    )
    mids = table.to_pandas()
    mids = mids[np.isfinite(mids["ts_epoch"]) & np.isfinite(mids["l1_mid"])]
    mids = mids[np.isfinite(mids["l1_bid"]) & np.isfinite(mids["l1_ask"])]
    mids = mids[np.isfinite(mids["l1_spread"])]
    mids = mids[(mids["l1_ask"] >= mids["l1_bid"]) & (mids["l1_spread"] >= 0)]
    mids = mids[mids["l1_mid"] > 0]
    if mids.empty:
        return None, root_used

    mids = (
        mids[["ts_epoch", "l1_mid"]].sort_values("ts_epoch").drop_duplicates("ts_epoch")
    )
    return mids.reset_index(drop=True), root_used


def to_utc_epoch(ts: Any) -> float:
    timestamp = pd.Timestamp(ts)
    if timestamp.tzinfo is None:
        return timestamp.timestamp()
    return timestamp.tz_convert("UTC").timestamp()


def build_trade_paths(
    trades: pd.DataFrame,
    max_horizon_seconds: int,
) -> tuple[list[TradePath], pd.DataFrame]:
    cache: dict[tuple[str, str], tuple[pd.DataFrame | None, str | None]] = {}
    trade_paths: list[TradePath] = []
    coverage_roots: list[str] = []

    for trade in trades.itertuples(index=False):
        key = (trade.session_date_et, trade.symbol)
        if key not in cache:
            cache[key] = load_mid_series(trade.session_date_et, trade.symbol)
        mids, root_used = cache[key]
        if mids is None or mids.empty:
            continue

        entry_ts = to_utc_epoch(trade.entry_time)
        exit_ts = to_utc_epoch(trade.exit_time)
        if exit_ts < entry_ts:
            continue

        forward = mids[
            (mids["ts_epoch"] >= entry_ts)
            & (mids["ts_epoch"] <= entry_ts + max_horizon_seconds)
        ]
        if forward.empty:
            continue

        mids_np = forward["l1_mid"].to_numpy(dtype=float)
        elapsed_seconds = forward["ts_epoch"].to_numpy(dtype=float) - entry_ts
        entry_price = float(trade.entry_price)

        if trade.direction == "long":
            favorable = (mids_np - entry_price) / entry_price * 10000.0
            adverse = (entry_price - mids_np) / entry_price * 10000.0
        elif trade.direction == "short":
            favorable = (entry_price - mids_np) / entry_price * 10000.0
            adverse = (mids_np - entry_price) / entry_price * 10000.0
        else:
            continue

        trade_paths.append(
            TradePath(
                trade_id=trade.trade_id,
                system=trade.system,
                strategy=trade.strategy,
                substrategy=trade.substrategy,
                symbol=trade.symbol,
                session_date_et=trade.session_date_et,
                direction=trade.direction,
                entry_price=float(trade.entry_price),
                exit_price=float(trade.exit_price),
                exit_reason=trade.exit_reason,
                gross_pnl=float(trade.gross_pnl),
                net_pnl=float(trade.net_pnl),
                gross_bps_on_entry=float(trade.gross_bps_on_entry),
                net_bps_on_entry=float(trade.net_bps_on_entry),
                hold_seconds=float(trade.hold_seconds or 0.0),
                exit_elapsed_seconds=float(max(exit_ts - entry_ts, 0.0)),
                raw_root_used=root_used,
                elapsed_seconds=elapsed_seconds,
                favorable_bps=favorable,
                adverse_bps=adverse,
            )
        )
        if root_used:
            coverage_roots.append(root_used)

    coverage = (
        pd.Series(coverage_roots, dtype="string")
        .value_counts()
        .rename_axis("raw_root_used")
        .reset_index(name="covered_trades")
    )
    return trade_paths, coverage


def compute_mfe(
    trade_paths: list[TradePath],
    horizons: tuple[int, ...],
    max_horizon_seconds: int,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for path in trade_paths:
        row: dict[str, Any] = {
            "trade_id": path.trade_id,
            "system": path.system,
            "strategy": path.strategy,
            "substrategy": path.substrategy,
            "symbol": path.symbol,
            "session_date_et": path.session_date_et,
            "direction": path.direction,
            "entry_price": path.entry_price,
            "exit_price": path.exit_price,
            "exit_reason": path.exit_reason,
            "gross_pnl": path.gross_pnl,
            "net_pnl": path.net_pnl,
            "gross_bps_on_entry": path.gross_bps_on_entry,
            "net_bps_on_entry": path.net_bps_on_entry,
            "hold_seconds": path.hold_seconds,
            "raw_root_used": path.raw_root_used,
        }

        windows: dict[str, float] = {
            f"{horizon}s": float(horizon) for horizon in horizons
        }
        windows["until_exit"] = path.exit_elapsed_seconds
        windows["max_horizon"] = float(max_horizon_seconds)

        for label, horizon_seconds in windows.items():
            mask = path.elapsed_seconds <= horizon_seconds
            if not mask.any():
                row[f"mfe_{label}_bps"] = np.nan
                row[f"mae_{label}_bps"] = np.nan
                continue
            row[f"mfe_{label}_bps"] = float(np.nanmax(path.favorable_bps[mask]))
            row[f"mae_{label}_bps"] = float(np.nanmax(path.adverse_bps[mask]))

        rows.append(row)

    return pd.DataFrame(rows)


def summarize_strategies(trades: pd.DataFrame) -> pd.DataFrame:
    summaries: list[dict[str, Any]] = []
    for (system, strategy), group in trades.groupby(
        ["system", "strategy"], dropna=False
    ):
        gross = float(group["gross_pnl"].sum())
        commission = float(group["total_commission"].sum())
        net = float(group["net_pnl"].sum())
        net_wins = group.loc[group["net_pnl"] > 0, "net_pnl"]
        net_losses = group.loc[group["net_pnl"] < 0, "net_pnl"]
        summaries.append(
            {
                "system": system,
                "strategy": strategy,
                "trades": int(len(group)),
                "gross_pnl": gross,
                "commission": commission,
                "net_pnl": net,
                "avg_gross_per_trade": gross / len(group),
                "avg_net_per_trade": net / len(group),
                "net_retention": (net / gross) if gross != 0 else np.nan,
                "net_win_rate": float((group["net_pnl"] > 0).mean()),
                "avg_net_bps_on_entry": float(group["net_bps_on_entry"].mean()),
                "avg_commission_bps_on_entry": float(
                    group["commission_bps_on_entry"].mean()
                ),
                "cost_capture_nonzero_share": float(
                    (group["total_commission"] > 0).mean()
                ),
                "break_even_extra_cost_bps_on_entry": max(
                    float(group["gross_bps_on_entry"].mean()),
                    0.0,
                ),
                "break_even_extra_cost_per_trade": max(gross / len(group), 0.0),
                "net_profit_factor": (
                    float(net_wins.sum() / abs(net_losses.sum()))
                    if len(net_losses)
                    else np.inf
                ),
            }
        )
    return pd.DataFrame(summaries).sort_values(
        ["system", "net_pnl"], ascending=[True, False]
    )


def summarize_mfe(mfe: pd.DataFrame, strategy_summary: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for (system, strategy), group in mfe.groupby(["system", "strategy"], dropna=False):
        row = {
            "system": system,
            "strategy": strategy,
            "covered_trades": int(len(group)),
            "avg_realized_gross_bps": float(group["gross_bps_on_entry"].mean()),
            "median_realized_gross_bps": float(group["gross_bps_on_entry"].median()),
            "avg_mfe_max_horizon_bps": float(group["mfe_max_horizon_bps"].mean()),
            "median_mfe_max_horizon_bps": float(group["mfe_max_horizon_bps"].median()),
            "p90_mfe_max_horizon_bps": float(
                np.nanpercentile(group["mfe_max_horizon_bps"], 90)
            ),
            "max_mfe_max_horizon_bps": float(group["mfe_max_horizon_bps"].max()),
            "avg_mfe_until_exit_bps": float(group["mfe_until_exit_bps"].mean()),
            "share_mfe_gt_20bps": float((group["mfe_max_horizon_bps"] > 20).mean()),
            "share_mfe_gt_50bps": float((group["mfe_max_horizon_bps"] > 50).mean()),
            "share_realized_pos": float((group["gross_bps_on_entry"] > 0).mean()),
        }
        horizon_columns = [
            column
            for column in group.columns
            if column.startswith("mfe_") and column.endswith("s_bps")
        ]
        for horizon_col in sorted(horizon_columns):
            row[f"avg_{horizon_col}"] = float(group[horizon_col].mean())
            row[f"median_{horizon_col}"] = float(group[horizon_col].median())
        row["avg_left_on_table_bps"] = (
            row["avg_mfe_max_horizon_bps"] - row["avg_realized_gross_bps"]
        )
        row["median_left_on_table_bps"] = (
            row["median_mfe_max_horizon_bps"] - row["median_realized_gross_bps"]
        )
        row["avg_capture_ratio"] = (
            row["avg_realized_gross_bps"] / row["avg_mfe_max_horizon_bps"]
            if row["avg_mfe_max_horizon_bps"] > 0
            else np.nan
        )
        rows.append(row)

    summary = pd.DataFrame(rows)
    summary = summary.merge(
        strategy_summary[
            [
                "system",
                "strategy",
                "trades",
                "gross_pnl",
                "net_pnl",
                "avg_net_bps_on_entry",
                "break_even_extra_cost_bps_on_entry",
            ]
        ],
        on=["system", "strategy"],
        how="left",
    )
    summary["coverage_share"] = summary["covered_trades"] / summary["trades"]
    return summary.sort_values(
        ["system", "avg_mfe_max_horizon_bps"], ascending=[True, False]
    )


def build_realized_strategy_stats(trades: pd.DataFrame, system: str) -> pd.DataFrame:
    subset = trades[trades["system"] == system].copy()
    rows: list[dict[str, Any]] = []
    for strategy, group in subset.groupby("strategy", dropna=False):
        realized_wins = int((group["gross_bps_on_entry"] > 0).sum())
        realized_losses = int((group["gross_bps_on_entry"] < 0).sum())
        losing_trades = realized_losses
        rows.append(
            {
                "strategy": strategy,
                "trades": int(len(group)),
                "realized_win_rate": float((group["gross_bps_on_entry"] > 0).mean()),
                "realized_wl_ratio": (
                    float(realized_wins / realized_losses)
                    if realized_losses
                    else np.inf
                ),
                "realized_losses": realized_losses,
                "losing_trades": losing_trades,
                "avg_realized_gross_bps": float(group["gross_bps_on_entry"].mean()),
            }
        )
    return pd.DataFrame(rows)


def classify_path_outcome(
    path: TradePath,
    horizon_seconds: int,
    stop_bps: float,
    tp_bps: float,
) -> str | None:
    mask = path.elapsed_seconds <= float(horizon_seconds)
    if not mask.any():
        return None

    favorable = path.favorable_bps[mask]
    adverse = path.adverse_bps[mask]
    tp_hits = np.flatnonzero(favorable >= tp_bps)
    stop_hits = np.flatnonzero(adverse >= stop_bps)
    if tp_hits.size == 0 and stop_hits.size == 0:
        return "NEITHER"
    if tp_hits.size and (stop_hits.size == 0 or tp_hits[0] < stop_hits[0]):
        return "WIN"
    return "LOSS"


def format_bps(value: float) -> str:
    return (
        f"{int(value)}"
        if float(value).is_integer()
        else f"{value:.2f}".rstrip("0").rstrip(".")
    )


def build_path_matrix(
    trade_paths: list[TradePath],
    trades: pd.DataFrame,
    config: AnalysisConfig,
) -> pd.DataFrame:
    realized = build_realized_strategy_stats(trades, config.path_system)
    realized_map = realized.set_index("strategy").to_dict(orient="index")
    system_paths = [path for path in trade_paths if path.system == config.path_system]

    rows: list[dict[str, Any]] = []
    for strategy in sorted({path.strategy for path in system_paths}):
        strategy_paths = [path for path in system_paths if path.strategy == strategy]
        realized_stats = realized_map.get(strategy)
        if not strategy_paths or realized_stats is None:
            continue

        for horizon_seconds in config.path_horizons:
            for stop_bps in config.path_stop_bps:
                for r_multiple in config.path_r_multiples:
                    tp_bps = round(stop_bps * r_multiple, 4)
                    wins = 0
                    losses = 0
                    neither = 0
                    covered = 0
                    rescued_losers = 0

                    for path in strategy_paths:
                        outcome = classify_path_outcome(
                            path, horizon_seconds, stop_bps, tp_bps
                        )
                        if outcome is None:
                            continue
                        covered += 1
                        if outcome == "WIN":
                            wins += 1
                            if path.gross_bps_on_entry < 0:
                                rescued_losers += 1
                        elif outcome == "LOSS":
                            losses += 1
                        else:
                            neither += 1

                    if covered == 0:
                        continue

                    decided = wins + losses
                    rows.append(
                        {
                            "strategy": strategy,
                            "horizon_seconds": horizon_seconds,
                            "stop_bps": stop_bps,
                            "tp_bps": tp_bps,
                            "template": f"{format_bps(stop_bps)}/{format_bps(tp_bps)}",
                            "R_multiple": r_multiple,
                            "trades": int(realized_stats["trades"]),
                            "covered_trades": covered,
                            "decided_trades": decided,
                            "decided_share": (
                                float(decided / covered) if covered else np.nan
                            ),
                            "realized_win_rate": float(
                                realized_stats["realized_win_rate"]
                            ),
                            "realized_wl_ratio": float(
                                realized_stats["realized_wl_ratio"]
                            ),
                            "wins": wins,
                            "losses": losses,
                            "neither": neither,
                            "path_win_rate_decided": (
                                float(wins / decided) if decided else np.nan
                            ),
                            "path_wl_ratio_decided": (
                                float(wins / losses) if losses else np.inf
                            ),
                            "path_win_rate_all": float(wins / covered),
                            "rescued_losers": rescued_losers,
                            "loser_rescue_rate": (
                                float(rescued_losers / realized_stats["losing_trades"])
                                if realized_stats["losing_trades"]
                                else np.nan
                            ),
                            "avg_realized_gross_bps": float(
                                realized_stats["avg_realized_gross_bps"]
                            ),
                        }
                    )

    matrix = pd.DataFrame(rows)
    return matrix.sort_values(
        ["strategy", "horizon_seconds", "R_multiple", "stop_bps"],
        ignore_index=True,
    )


def select_best_matrix_rows(
    matrix: pd.DataFrame, min_decided: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    eligible = matrix[matrix["decided_trades"] >= min_decided].copy()
    if eligible.empty:
        empty = pd.DataFrame(columns=matrix.columns)
        return empty, empty

    eligible["path_wl_ratio_rank"] = eligible["path_wl_ratio_decided"].replace(
        np.inf, 1e12
    )
    eligible = eligible.sort_values(
        [
            "strategy",
            "path_wl_ratio_rank",
            "path_win_rate_decided",
            "decided_trades",
            "path_win_rate_all",
        ],
        ascending=[True, False, False, False, False],
    )
    best_by_strategy = (
        eligible.groupby("strategy", as_index=False)
        .head(1)
        .drop(columns=["path_wl_ratio_rank"])
    )

    best_by_strategy_horizon = (
        eligible.sort_values(
            [
                "strategy",
                "horizon_seconds",
                "path_wl_ratio_rank",
                "path_win_rate_decided",
                "decided_trades",
                "path_win_rate_all",
            ],
            ascending=[True, True, False, False, False, False],
        )
        .groupby(["strategy", "horizon_seconds"], as_index=False)
        .head(1)
        .drop(columns=["path_wl_ratio_rank"])
    )
    return best_by_strategy, best_by_strategy_horizon


def build_current_template_summary(
    matrix: pd.DataFrame,
    horizons: tuple[int, ...],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    current_rows = []
    for strategy, (stop_bps, tp_bps) in CURRENT_PATH_TEMPLATES.items():
        strategy_rows = matrix[
            (matrix["strategy"] == strategy)
            & np.isclose(matrix["stop_bps"], stop_bps)
            & np.isclose(matrix["tp_bps"], tp_bps)
        ]
        if not strategy_rows.empty:
            current_rows.append(strategy_rows)

    if not current_rows:
        empty = pd.DataFrame(columns=matrix.columns)
        return empty, empty

    current_templates = pd.concat(current_rows, ignore_index=True).sort_values(
        ["strategy", "horizon_seconds"]
    )
    max_horizon = max(horizons)
    current_at_max_horizon = current_templates[
        current_templates["horizon_seconds"] == max_horizon
    ].copy()
    current_at_max_horizon = current_at_max_horizon[
        [
            "strategy",
            "trades",
            "stop_bps",
            "tp_bps",
            "R_multiple",
            "realized_win_rate",
            "realized_wl_ratio",
            "path_win_rate_decided",
            "path_wl_ratio_decided",
            "path_win_rate_all",
            "wins",
            "losses",
            "neither",
            "rescued_losers",
            "loser_rescue_rate",
        ]
    ].rename(
        columns={
            "wins": f"wins_{max_horizon}s",
            "losses": f"losses_{max_horizon}s",
            "neither": f"neither_{max_horizon}s",
        }
    )
    return current_templates, current_at_max_horizon


def build_current_template_trade_rows(
    trade_paths: list[TradePath],
    config: AnalysisConfig,
) -> pd.DataFrame:
    horizon_seconds = max(config.path_horizons)
    rows: list[dict[str, Any]] = []
    for path in trade_paths:
        if (
            path.system != config.path_system
            or path.strategy not in CURRENT_PATH_TEMPLATES
        ):
            continue
        stop_bps, tp_bps = CURRENT_PATH_TEMPLATES[path.strategy]
        outcome = classify_path_outcome(path, horizon_seconds, stop_bps, tp_bps)
        if outcome is None:
            continue
        rows.append(
            {
                "trade_id": path.trade_id,
                "strategy": path.strategy,
                "horizon_seconds": horizon_seconds,
                "realized_gross_bps": path.gross_bps_on_entry,
                "stop_bps": stop_bps,
                "tp_bps": tp_bps,
                "R_multiple": round(tp_bps / stop_bps, 4),
                f"path_outcome_{horizon_seconds}s": outcome,
                "raw_root_used": path.raw_root_used,
            }
        )
    return pd.DataFrame(rows).sort_values(["strategy", "trade_id"], ignore_index=True)


def render_markdown(
    config: AnalysisConfig,
    trades: pd.DataFrame,
    strategy_summary: pd.DataFrame,
    mfe_summary: pd.DataFrame,
    coverage: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# Extended Net/Gross and Entry-MFE Analysis")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- Closed trades analyzed: `{len(trades):,}`")
    lines.append(
        f"- ET session range: `{trades['session_date_et'].min()}` to `{trades['session_date_et'].max()}`"
    )
    lines.append(f"- MFE max horizon: `{config.max_horizon_seconds}s`")
    lines.append(f"- MFE horizons: `{', '.join(str(h) for h in config.horizons)}s`")
    lines.append(
        "- MFE-covered trades with raw L2 inside the analyzed window: "
        f"`{int(mfe_summary['covered_trades'].sum()):,}`"
    )
    lines.append("")
    lines.append("## Cost Drag")
    lines.append("")
    for row in strategy_summary.itertuples(index=False):
        lines.append(
            f"- `{row.system} / {row.strategy}`: trades `{row.trades}`, gross "
            f"`{row.gross_pnl:.2f}`, net `{row.net_pnl:.2f}`, avg net/trade "
            f"`{row.avg_net_per_trade:.2f}`, break-even extra cost about "
            f"`{row.break_even_extra_cost_bps_on_entry:.1f}` bps on entry"
        )
    lines.append("")
    lines.append("## Entry MFE")
    lines.append("")
    for row in mfe_summary.itertuples(index=False):
        lines.append(
            f"- `{row.system} / {row.strategy}`: covered `{row.covered_trades}` trades "
            f"(`{row.coverage_share:.1%}` of strategy trades), avg realized gross "
            f"`{row.avg_realized_gross_bps:.1f}` bps, avg max-horizon MFE "
            f"`{row.avg_mfe_max_horizon_bps:.1f}` bps, avg left on table "
            f"`{row.avg_left_on_table_bps:.1f}` bps"
        )
    lines.append("")
    lines.append("## Raw L2 Coverage")
    lines.append("")
    for row in coverage.itertuples(index=False):
        lines.append(f"- `{row.raw_root_used}`: `{row.covered_trades}` covered trades")
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- Explicit commission capture in paper trading is sparse, so gross-vs-net underestimates"
    )
    lines.append(
        "- Entry-MFE uses saved raw L2 mid prices, not later reconstructed bars"
    )
    return "\n".join(lines) + "\n"


def render_path_matrix_markdown(
    config: AnalysisConfig,
    matrix: pd.DataFrame,
    current_templates: pd.DataFrame,
    best_by_strategy: pd.DataFrame,
    best_by_strategy_horizon: pd.DataFrame,
) -> str:
    lines: list[str] = []
    lines.append("# Path-Aware Holding-Period x R Matrix")
    lines.append("")
    lines.append("## Scope")
    lines.append("")
    lines.append(f"- System: `{config.path_system}`")
    lines.append(
        f"- Holding periods: `{', '.join(str(h) for h in config.path_horizons)}s`"
    )
    lines.append(
        f"- Stop grid: `{', '.join(format_bps(s) for s in config.path_stop_bps)}` bps"
    )
    lines.append(
        f"- R multiples: `{', '.join(format_bps(r) for r in config.path_r_multiples)}`"
    )
    lines.append(
        f"- Minimum decided trades for best-cell tables: `{config.matrix_min_decided}`"
    )
    lines.append("")

    if not current_templates.empty:
        lines.append("## Current Templates Across Holding Periods")
        lines.append("")
        current_max_horizon = max(config.path_horizons)
        for row in current_templates[
            current_templates["horizon_seconds"] == current_max_horizon
        ].itertuples(index=False):
            lines.append(
                f"- `{row.strategy}` at `{row.template}` over `{row.horizon_seconds}s`: "
                f"W/L `{row.path_wl_ratio_decided:.2f}`, wins `{row.wins}`, "
                f"losses `{row.losses}`, neither `{row.neither}`"
            )
        lines.append("")

    if not best_by_strategy.empty:
        lines.append("## Best Viable Cell By Strategy")
        lines.append("")
        for row in best_by_strategy.itertuples(index=False):
            lines.append(
                f"- `{row.strategy}`: best at `{row.horizon_seconds}s`, template `{row.template}` "
                f"(R `{row.R_multiple:.2f}`), W/L `{row.path_wl_ratio_decided:.2f}`, "
                f"win rate on decided `{row.path_win_rate_decided:.1%}`, decided `{row.decided_trades}`"
            )
        lines.append("")

    if not best_by_strategy_horizon.empty:
        lines.append("## Best Viable Cell By Strategy And Holding Period")
        lines.append("")
        for row in best_by_strategy_horizon.itertuples(index=False):
            lines.append(
                f"- `{row.strategy}` at `{row.horizon_seconds}s`: `{row.template}` "
                f"(R `{row.R_multiple:.2f}`), W/L `{row.path_wl_ratio_decided:.2f}`, "
                f"decided `{row.decided_trades}`, win rate `{row.path_win_rate_decided:.1%}`"
            )
        lines.append("")

    lines.append("## Notes")
    lines.append("")
    lines.append(
        "- `WIN` means TP was reached before SL inside the holding-period window"
    )
    lines.append(
        "- `LOSS` means SL was reached before TP inside the holding-period window"
    )
    lines.append(
        "- `NEITHER` means neither threshold was reached before the window ended"
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    config = parse_args()
    config.output_dir.mkdir(parents=True, exist_ok=True)

    trades = fetch_closed_trades(config)
    strategy_summary = summarize_strategies(trades)
    trade_paths, coverage = build_trade_paths(trades, config.max_horizon_seconds)
    mfe = compute_mfe(trade_paths, config.horizons, config.max_horizon_seconds)
    mfe_summary = summarize_mfe(mfe, strategy_summary)

    path_matrix = build_path_matrix(trade_paths, trades, config)
    best_by_strategy, best_by_strategy_horizon = select_best_matrix_rows(
        path_matrix,
        config.matrix_min_decided,
    )
    current_templates, current_template_summary = build_current_template_summary(
        path_matrix,
        config.path_horizons,
    )
    current_template_trades = build_current_template_trade_rows(trade_paths, config)
    r15_template_matrix = path_matrix[
        (path_matrix["horizon_seconds"] == max(config.path_horizons))
        & np.isclose(path_matrix["R_multiple"], 1.5)
    ][
        [
            "strategy",
            "template",
            "wins",
            "losses",
            "neither",
            "path_win_rate_decided",
            "path_wl_ratio_decided",
            "path_win_rate_all",
        ]
    ].rename(
        columns={
            "path_win_rate_decided": "win_rate_decided",
            "path_wl_ratio_decided": "wl_ratio_decided",
            "path_win_rate_all": "win_rate_all",
        }
    )

    trades.to_csv(config.output_dir / "trades.csv", index=False)
    strategy_summary.to_csv(config.output_dir / "strategy_summary.csv", index=False)
    mfe.to_csv(config.output_dir / "entry_mfe_trades.csv", index=False)
    mfe_summary.to_csv(config.output_dir / "entry_mfe_summary.csv", index=False)
    coverage.to_csv(config.output_dir / "raw_l2_coverage.csv", index=False)
    path_matrix.to_csv(
        config.output_dir / "entry_strength_horizon_r_matrix.csv", index=False
    )
    best_by_strategy.to_csv(
        config.output_dir / "entry_strength_best_by_strategy.csv", index=False
    )
    best_by_strategy_horizon.to_csv(
        config.output_dir / "entry_strength_best_by_strategy_horizon.csv",
        index=False,
    )
    current_templates.to_csv(
        config.output_dir / "entry_strength_path_current_templates_by_horizon.csv",
        index=False,
    )
    current_template_summary.to_csv(
        config.output_dir / "entry_strength_path_summary.csv",
        index=False,
    )
    current_template_trades.to_csv(
        config.output_dir / "entry_strength_path_trades.csv",
        index=False,
    )
    r15_template_matrix.to_csv(
        config.output_dir / "entry_strength_r15_template_matrix.csv",
        index=False,
    )

    summary_json = {
        "trade_count": int(len(trades)),
        "mfe_covered_trades": int(len(mfe)),
        "path_matrix_rows": int(len(path_matrix)),
        "path_matrix_strategies": (
            int(path_matrix["strategy"].nunique()) if not path_matrix.empty else 0
        ),
        "path_matrix_horizons": [int(h) for h in config.path_horizons],
        "path_matrix_r_multiples": [float(r) for r in config.path_r_multiples],
        "path_matrix_stop_bps": [float(s) for s in config.path_stop_bps],
        "path_system": config.path_system,
        "session_date_min": str(trades["session_date_et"].min()),
        "session_date_max": str(trades["session_date_et"].max()),
        "strategy_summary_rows": int(len(strategy_summary)),
        "mfe_summary_rows": int(len(mfe_summary)),
        "best_strategy_rows": int(len(best_by_strategy)),
        "best_strategy_horizon_rows": int(len(best_by_strategy_horizon)),
    }
    (config.output_dir / "summary.json").write_text(json.dumps(summary_json, indent=2))
    (config.output_dir / "report.md").write_text(
        render_markdown(config, trades, strategy_summary, mfe_summary, coverage)
    )
    (config.output_dir / "path_matrix_report.md").write_text(
        render_path_matrix_markdown(
            config,
            path_matrix,
            current_templates,
            best_by_strategy,
            best_by_strategy_horizon,
        )
    )

    print(json.dumps(summary_json, indent=2))


if __name__ == "__main__":
    main()
