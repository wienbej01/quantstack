"""Paper/shadow runner for the alpha action-ranker."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import pandas as pd

from scripts.run_hypothesis_test import load_polygon_bars
from scripts.run_ml_action_ranker_budget_backtest import (
    RankedAction,
    _base_config,
    _score_symbol,
    _select_topk,
)
from src.data import GoldLoader, L2Loader

logger = logging.getLogger(__name__)

ALPHA_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ALPHA_ROOT.parent
ET = ZoneInfo("America/New_York")

KNOWN_NYSE = {
    "SMR",
    "VST",
    "INSM",
    "F",
    "GE",
    "BAC",
    "C",
    "JPM",
    "WFC",
    "XOM",
    "CVX",
}
KNOWN_ARCA = {"UNG", "SPY", "QQQ", "IWM", "EFA", "EEM", "GLD", "SLV", "TLT", "HYG"}


@dataclass(frozen=True)
class PaperRunConfig:
    """Configuration for one alpha paper/shadow scoring pass."""

    date: str
    artifact_path: Path = ALPHA_ROOT / "models" / "action_ranker_xgb_2026-03-19.pkl"
    sip_root: Path = Path("/home/jacobw/quantstack-v2/data/daily_sip")
    output_dir: Path = ALPHA_ROOT / "output" / "paper_trading" / "action_ranker"
    polygon_cache_dir: Path = ALPHA_ROOT / "output" / "polygon_ohlcv_cache"
    bar_source: str = "polygon"
    max_symbols: int = 3
    daily_top_k: int = 4
    max_longs_per_day: int = 2
    min_score: float = 0.5
    cutoff_et: str | None = None
    l2_source_type: str = "any"
    execution_mode: str = "shadow"
    exit_mode: str = "time_only"
    execution_quantity: int = 10
    execution_stop_bps: float = 50.0
    execution_target_bps: float = 5000.0
    execution_max_action_age_seconds: int = 180
    ibkr_host: str = "127.0.0.1"
    ibkr_port: int = 7494
    ibkr_client_id: int = 410
    ibkr_account_id: str | None = None
    order_ref_prefix: str = "ALPHA_ML"


def current_et_date() -> str:
    """Return the current ET date used by SIP/L2 daily partitions."""
    return datetime.now(tz=ET).strftime("%Y-%m-%d")


def current_et_time() -> str:
    """Return the current ET clock time in HH:MM:SS form."""
    return datetime.now(tz=ET).strftime("%H:%M:%S")


def is_market_window(
    *,
    start_time: str = "09:31:00",
    end_time: str = "16:00:00",
) -> bool:
    """Return True during the paper service runtime window on weekdays."""
    now = datetime.now(tz=ET)
    if now.weekday() >= 5:
        return False
    current = now.strftime("%H:%M:%S")
    return start_time <= current <= end_time


def _resolve_path(path: Path | str) -> Path:
    resolved = Path(path).expanduser()
    if resolved.is_absolute():
        return resolved
    return (REPO_ROOT / resolved).resolve()


def load_daily_sip_symbols(date: str, sip_root: Path | str) -> list[str]:
    """Load the official daily SIP symbols for a single ET date."""
    sip_file = _resolve_path(sip_root) / f"date={date}" / "sip_universe.json"
    with sip_file.open("r") as handle:
        payload = json.load(handle)
    symbols = payload.get("symbols", []) if isinstance(payload, dict) else payload
    if not isinstance(symbols, list):
        raise ValueError(f"SIP symbols must be a list in {sip_file}")
    return [symbol.strip().upper() for symbol in symbols if isinstance(symbol, str) and symbol.strip()]


def filter_l2_scalping_symbols(symbols: list[str], *, max_symbols: int = 3) -> list[str]:
    """Mirror the l2-scalping SIP filter and depth-subscription cap."""
    nyse_symbols: list[str] = []
    for symbol in symbols:
        symbol = symbol.strip().upper()
        if not symbol:
            continue
        if symbol in KNOWN_NYSE:
            nyse_symbols.append(symbol)
        elif symbol not in KNOWN_ARCA:
            nyse_symbols.append(symbol)
    return nyse_symbols[: max(int(max_symbols), 0)]


def _cutoff_timestamp(date: str, cutoff_et: str | None) -> pd.Timestamp:
    if cutoff_et:
        raw = cutoff_et
        if len(raw) == 5:
            raw = f"{raw}:00"
        return pd.Timestamp(f"{date} {raw}", tz=ET)
    return pd.Timestamp(datetime.now(tz=ET))


def _filter_bars_to_cutoff(bars: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if bars.empty:
        return bars
    out = bars.copy()
    out["ts"] = pd.to_datetime(out["ts"])
    if out["ts"].dt.tz is None:
        cutoff_cmp = cutoff.tz_localize(None)
    else:
        cutoff_cmp = cutoff
    return out[out["ts"] <= cutoff_cmp].copy()


def _filter_l2_to_cutoff(l2: pd.DataFrame, cutoff: pd.Timestamp) -> pd.DataFrame:
    if l2.empty:
        return l2
    out = l2.copy()
    out["ts_utc"] = pd.to_datetime(out["ts_utc"], utc=True)
    return out[out["ts_utc"] <= cutoff.tz_convert("UTC")].copy()


def _load_symbol_bars(
    *,
    symbol: str,
    date: str,
    bar_source: str,
    config: dict[str, Any],
) -> pd.DataFrame:
    if bar_source == "polygon":
        return load_polygon_bars(symbol, date, date, config)
    if bar_source == "gold":
        return GoldLoader().load_bars(symbol, date, date)
    raise ValueError(f"Unsupported bar source: {bar_source}")


def _timestamp_to_et(timestamp: Any) -> pd.Timestamp:
    out = pd.Timestamp(timestamp)
    if out.tzinfo is None:
        return out.tz_localize(ET)
    return out.tz_convert(ET)


def _price_for_action(action: RankedAction, bars: pd.DataFrame) -> float | None:
    if bars.empty or "ts" not in bars.columns:
        return None
    out = bars.copy()
    out["ts"] = pd.to_datetime(out["ts"])
    action_ts = pd.Timestamp(action.timestamp)
    if out["ts"].dt.tz is None:
        action_cmp = action_ts.tz_localize(None) if action_ts.tzinfo else action_ts
    else:
        action_cmp = _timestamp_to_et(action_ts)
    after_action = out[out["ts"] > action_cmp]
    if after_action.empty:
        after_action = out[out["ts"] >= action_cmp]
    if after_action.empty:
        return None
    row = after_action.sort_values("ts").iloc[0]
    for column in ("open", "o", "close", "c"):
        if column in row and pd.notna(row[column]):
            price = float(row[column])
            return price if price > 0 else None
    return None


def _execution_prices(
    *,
    side: str,
    entry_price: float | None,
    stop_bps: float,
    target_bps: float,
) -> tuple[float | None, float | None]:
    if entry_price is None or entry_price <= 0:
        return None, None
    stop_delta = entry_price * (float(stop_bps) / 10000.0)
    target_delta = entry_price * (float(target_bps) / 10000.0)
    if side == "long":
        return round(entry_price - stop_delta, 2), round(entry_price + target_delta, 2)
    return round(entry_price + stop_delta, 2), round(entry_price - target_delta, 2)


def ranked_action_to_dict(
    action: RankedAction,
    *,
    entry_price: float | None = None,
    stop_bps: float = 100.0,
    target_bps: float = 100.0,
    execution_mode: str = "shadow",
) -> dict[str, Any]:
    """Serialize a ranked action into an auditable paper intent record."""
    timestamp = pd.Timestamp(action.timestamp)
    context = getattr(action, "context", None) or {}
    stop_price, target_price = _execution_prices(
        side=action.side.value,
        entry_price=entry_price,
        stop_bps=stop_bps,
        target_bps=target_bps,
    )
    return {
        "action_id": (
            f"{action.date}|{action.symbol}|{timestamp.isoformat()}|"
            f"{action.side.value}|{int(action.hold_minutes)}"
        ),
        "date": action.date,
        "symbol": action.symbol,
        "timestamp": timestamp.isoformat(),
        "side": action.side.value,
        "hold_minutes": int(action.hold_minutes),
        "score": float(action.score),
        "paper_only": execution_mode == "shadow",
        "execution_mode": execution_mode,
        "execution_assumption": "entry_next_bar_open_time_exit_at_selected_hold",
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "context": context,
    }


def _record_signal_id(action_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quantstack-alpha-ml:{action_id}"))


def _trade_signal_data(trade: dict[str, Any]) -> dict[str, Any]:
    payload = trade.get("signal_data")
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, str):
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _trade_due_for_time_exit(trade: dict[str, Any], *, now: pd.Timestamp) -> bool:
    metadata = _trade_signal_data(trade)
    hold_minutes = metadata.get("hold_minutes")
    if hold_minutes is None:
        return False
    entry_time = trade.get("entry_time")
    if entry_time is None:
        return False
    entry_ts = pd.Timestamp(entry_time)
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    else:
        entry_ts = entry_ts.tz_convert("UTC")
    return now >= entry_ts + pd.Timedelta(minutes=int(hold_minutes))


def _open_exit_order_exists(trade_db: Any, trade_id: str) -> bool:
    conn = trade_db.db.pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM orders_v2
            WHERE trade_id = %s
              AND system = 'alpha-ml'
              AND role IN ('EXIT', 'TIME_EXIT')
              AND COALESCE(status, '') NOT IN (
                  'FILLED', 'Filled', 'CANCELLED', 'Cancelled',
                  'ApiCancelled', 'Inactive', 'REJECTED', 'Rejected'
              )
            LIMIT 1
            """,
            (trade_id,),
        )
        return cur.fetchone() is not None
    finally:
        trade_db.db.pool.putconn(conn)


def _cancel_alpha_child_orders(
    *,
    session: Any,
    order_ref_prefix: str,
    symbol: str,
) -> list[int]:
    prefix = f"{order_ref_prefix}_ENTRY_{symbol}"

    def _cancel_open_children() -> list[int]:
        cancelled: list[int] = []
        done_statuses = {
            "Filled",
            "Cancelled",
            "ApiCancelled",
            "Inactive",
        }
        for trade in session.ib.openTrades():
            order = trade.order
            order_ref = str(getattr(order, "orderRef", "") or "")
            status = str(getattr(trade.orderStatus, "status", "") or "")
            parent_id = int(getattr(order, "parentId", 0) or 0)
            if not order_ref.startswith(prefix):
                continue
            if parent_id <= 0 or status in done_statuses:
                continue
            session.ib.cancelOrder(order)
            cancelled.append(int(order.orderId))
        return cancelled

    try:
        return list(session.call(_cancel_open_children, timeout=5))
    except Exception:
        logger.exception("Failed to cancel alpha child orders for %s", symbol)
        return []


def _submit_due_time_exits(
    *,
    run_config: PaperRunConfig,
    session: Any,
    adapter: Any,
    trade_db: Any,
    shared_pos: Any = None,
    audit: Any = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "checked": 0,
        "due": 0,
        "submitted": 0,
        "skipped_pending_entry": 0,
        "skipped_existing_exit": 0,
        "failed": 0,
        "orders": [],
    }
    if run_config.exit_mode != "time_only":
        return summary
    now_utc = pd.Timestamp.utcnow()
    for trade in trade_db.get_open_trades():
        if trade.get("system") != "alpha-ml":
            continue
        summary["checked"] += 1
        if not _trade_due_for_time_exit(trade, now=now_utc):
            continue
        summary["due"] += 1
        trade_id = str(trade["trade_id"])
        if _open_exit_order_exists(trade_db, trade_id):
            summary["skipped_existing_exit"] += 1
            continue
        entry_qty = int(trade.get("entry_qty") or 0)
        if entry_qty <= 0:
            summary["skipped_pending_entry"] += 1
            continue
        symbol = str(trade["symbol"])
        direction = str(trade["direction"]).lower()
        action = "SELL" if direction == "long" else "BUY"
        order_id = adapter.submit_order(symbol, action, abs(entry_qty), order_type="MKT")
        if order_id is None:
            summary["failed"] += 1
            summary["orders"].append(
                {"trade_id": trade_id, "symbol": symbol, "status": "submit_failed"}
            )
            continue
        cancelled_children = _cancel_alpha_child_orders(
            session=session,
            order_ref_prefix=run_config.order_ref_prefix,
            symbol=symbol,
        )

        metadata = _trade_signal_data(trade)
        trade_db.upsert_order(
            symbol=symbol,
            ibkr_order_id=int(order_id),
            trade_id=trade_id,
            signal_id=metadata.get("signal_id"),
            side=action,
            order_type="MKT",
            role="TIME_EXIT",
            order_ref=f"{run_config.order_ref_prefix}_TIME_EXIT_{symbol}",
            quantity=abs(entry_qty),
            status="SUBMITTED",
            raw_order={
                "exit_mode": "time_only",
                "cancelled_child_order_ids": cancelled_children,
            },
        )
        trade_db.append_order_event(
            ibkr_order_id=int(order_id),
            symbol=symbol,
            event_type="SUBMITTED",
            status="SUBMITTED",
            message="Alpha ML time-exit market order submitted",
            payload={"role": "TIME_EXIT", "trade_id": trade_id},
        )
        trade_db.link_order(trade_id, int(order_id), is_entry=False, symbol=symbol)
        summary["submitted"] += 1
        summary["orders"].append(
            {
                "trade_id": trade_id,
                "symbol": symbol,
                "order_id": int(order_id),
                "cancelled_child_order_ids": cancelled_children,
                "status": "submitted",
            }
        )
        # Clear shared position on exit
        if shared_pos is not None:
            try:
                shared_pos.upsert("alpha-ml", symbol, 0, 0.0)
            except Exception:
                logger.warning("Failed to clear shared_positions for %s on time exit", symbol)
        if audit is not None:
            try:
                from cpapi.audit_logger import EventType  # type: ignore
                audit.log_event(
                    EventType.TRADE_CLOSE,
                    f"Alpha ML time-exit submitted: {symbol} order_id={order_id}",
                    context={"symbol": symbol, "trade_id": trade_id, "ibkr_order_id": int(order_id), "exit_mode": "time_only"},
                )
            except Exception:
                pass
    return summary


def _add_quantstack_v2_import_paths() -> Path:
    v2_root = Path(
        os.getenv("QUANTSTACK_V2_ROOT", "/home/jacobw/trading/repos/quantstack-v2")
    ).expanduser()
    for candidate in (
        v2_root / "shared",
        v2_root / "shared" / "qx-broker" / "src",
        v2_root / "services" / "intraday-paper" / "src",
    ):
        text = str(candidate)
        if text not in sys.path:
            sys.path.insert(0, text)
    return v2_root


def _read_submitted_action_ids(path: Path) -> set[str]:
    """Read action_ids that have already been submitted to IBKR (separate from emitted signals)."""
    if not path.exists():
        return set()
    submitted: set[str] = set()
    with path.open("r") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = payload.get("action_id")
            if isinstance(action_id, str):
                submitted.add(action_id)
    return submitted


def _append_submitted_action_id(path: Path, action_id: str, order_id: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        handle.write(json.dumps({"action_id": action_id, "order_id": order_id, "submitted_at": datetime.utcnow().isoformat() + "Z"}) + "\n")


def _execute_records_if_enabled(
    *,
    run_config: PaperRunConfig,
    records: list[dict[str, Any]],
    pass_cutoff: pd.Timestamp | None = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": run_config.execution_mode,
        "exit_mode": run_config.exit_mode,
        "attempted": 0,
        "submitted": 0,
        "skipped_stale": 0,
        "skipped_missing_price": 0,
        "failed": 0,
        "time_exits": {},
        "orders": [],
    }
    if run_config.execution_mode == "shadow":
        return summary
    if run_config.execution_mode != "ibkr_paper":
        summary["error"] = f"unsupported execution mode: {run_config.execution_mode}"
        return summary
    # NOTE: Do NOT early-return when records is empty — time-exits for
    # existing open trades must still be processed every pass.

    # Use pass cutoff as the reference time for staleness — not wall clock vs bar timestamp.
    # Bar timestamps are always in the past; what matters is whether this pass is recent.
    ref_time = pass_cutoff if pass_cutoff is not None else pd.Timestamp(datetime.now(tz=ET))
    now_et = pd.Timestamp(datetime.now(tz=ET))
    pass_age_seconds = (now_et - ref_time).total_seconds() if pass_cutoff is not None else 0.0

    fresh_records: list[dict[str, Any]] = []
    for record in records:
        # Skip if the scoring pass itself is too old (processing took too long)
        if pass_age_seconds > run_config.execution_max_action_age_seconds:
            summary["skipped_stale"] += 1
            continue
        if not record.get("entry_price") or not record.get("stop_price") or not record.get("target_price"):
            summary["skipped_missing_price"] += 1
            continue
        fresh_records.append(record)

    _add_quantstack_v2_import_paths()
    from cpapi.audit_logger import AuditLogger, EventType, Severity  # type: ignore
    from cpapi.shared_positions import SharedPositionLedger  # type: ignore
    from cpapi.trade_integration import TradeIntegration  # type: ignore
    from execution.ibkr_live_adapter import IBKRLiveAdapter, OrderIntent  # type: ignore
    from execution.order_manager import OrderManager, RiskLimits  # type: ignore
    from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig  # type: ignore

    audit = AuditLogger("alpha-ml")
    shared_pos = SharedPositionLedger()
    submitted_path = _resolve_path(run_config.output_dir) / f"date={run_config.date}" / "submitted_actions.jsonl"

    session = IBKRSession(
        IBKRSessionConfig(
            system_name="alpha-ml",
            connection=IBKRConnectionConfig(
                host=run_config.ibkr_host,
                port=run_config.ibkr_port,
                client_id=run_config.ibkr_client_id,
                readonly=False,
                allow_client_id_fallback=True,
                client_id_fallbacks=5,
            ),
        )
    )
    trade_db = None
    try:
        if not session.connect():
            audit.log_event(EventType.DEPENDENCY_FAIL, "alpha-ml IBKR connect failed", Severity.ERROR)
            summary["error"] = "ibkr_connect_failed"
            summary["failed"] = len(fresh_records)
            return summary
        audit.log_event(EventType.SERVICE_READY, "alpha-ml IBKR connected", context={"client_id": run_config.ibkr_client_id})
        adapter = IBKRLiveAdapter(
            session,
            system_name="alpha-ml",
            client_id=run_config.ibkr_client_id,
            order_ref_prefix=run_config.order_ref_prefix,
            account_id=run_config.ibkr_account_id,
        )
        adapter.attach_handlers()
        manager = OrderManager(
            adapter,
            RiskLimits(
                daily_loss_limit=200.0,
                max_concurrent_positions=2,
                max_position_pct=0.02,
                max_trades_per_day=max(int(run_config.daily_top_k), 1),
            ),
        )
        trade_db = TradeIntegration(
            ib=session.ib,
            system_name="alpha-ml",
            ib_call=session.call,
        )
        trade_db.start()
        summary["time_exits"] = _submit_due_time_exits(
            run_config=run_config,
            session=session,
            adapter=adapter,
            trade_db=trade_db,
            shared_pos=shared_pos,
            audit=audit,
        )

        if not fresh_records:
            return summary

        _last_order_time: float = 0.0
        _ORDER_COOLDOWN_SECONDS = 60

        for record in fresh_records:
            # Enforce cooldown between consecutive orders so IBKR position state
            # has time to settle and OrderManager.can_trade() sees accurate counts.
            elapsed = time.monotonic() - _last_order_time
            if _last_order_time > 0 and elapsed < _ORDER_COOLDOWN_SECONDS:
                time.sleep(_ORDER_COOLDOWN_SECONDS - elapsed)

            summary["attempted"] += 1
            signal_id = _record_signal_id(str(record["action_id"]))
            audit.log_event(
                EventType.TRADE_SIGNAL,
                f"Alpha ML signal: {record['side']} {record['symbol']} score={record['score']:.3f}",
                context={"symbol": record["symbol"], "signal_id": signal_id, "score": record["score"], "action_id": record["action_id"]},
            )
            intent = OrderIntent(
                symbol=str(record["symbol"]),
                direction=str(record["side"]),
                quantity=max(int(run_config.execution_quantity), 1),
                entry_price=float(record["entry_price"]),
                stop_price=float(record["stop_price"]),
                target_price=float(record["target_price"]),
                strategy="action_ranker",
                signal_id=signal_id,
            )
            order = manager.submit_order(intent)
            if not order:
                audit.log_event(EventType.ORDER_REJECT, f"Alpha ML order rejected: {record['symbol']}", Severity.WARNING, context={"symbol": record["symbol"], "signal_id": signal_id})
                summary["failed"] += 1
                summary["orders"].append(
                    {
                        "action_id": record["action_id"],
                        "symbol": record["symbol"],
                        "status": "rejected_or_not_submitted",
                    }
                )
                continue

            order_ref = f"{run_config.order_ref_prefix}_ENTRY_{record['symbol']}"
            db_trade_id = trade_db.open_trade(
                symbol=str(record["symbol"]),
                direction=str(record["side"]),
                signal_price=float(record["entry_price"]),
                stop_loss=float(record["stop_price"]),
                take_profit=float(record["target_price"]),
                metadata={
                    "strategy": "action_ranker",
                    "signal_id": signal_id,
                    "action_id": record["action_id"],
                    "score": record["score"],
                    "hold_minutes": record["hold_minutes"],
                    "exit_mode": run_config.exit_mode,
                    "entry_timestamp": record["timestamp"],
                },
            )
            try:
                trade_db.record_signal(
                    symbol=str(record["symbol"]),
                    signal_id=signal_id,
                    strategy="action_ranker",
                    direction=str(record["side"]).upper(),
                    signal_time=_timestamp_to_et(record["timestamp"]).to_pydatetime(),
                    signal_price=float(record["entry_price"]),
                    signal_strength=float(record["score"]),
                    decision="TRADE",
                    features=record,
                )
                trade_db.upsert_order(
                    symbol=str(record["symbol"]),
                    ibkr_order_id=int(order.order_id),
                    trade_id=db_trade_id,
                    signal_id=signal_id,
                    side="BUY" if record["side"] == "long" else "SELL",
                    order_type="BRACKET",
                    role="ENTRY",
                    order_ref=order_ref,
                    quantity=intent.quantity,
                    limit_price=float(intent.entry_price),
                    stop_price=float(intent.stop_price),
                    target_price=float(intent.target_price),
                    status="SUBMITTED",
                    raw_order={"strategy": "action_ranker", "action_id": record["action_id"]},
                )
                trade_db.append_order_event(
                    ibkr_order_id=int(order.order_id),
                    symbol=str(record["symbol"]),
                    event_type="SUBMITTED",
                    status="SUBMITTED",
                    message="Alpha ML bracket order submitted",
                    payload={"role": "ENTRY", "signal_id": signal_id},
                )
                trade_db.link_order(db_trade_id, int(order.order_id), is_entry=True, symbol=str(record["symbol"]))
            except Exception as db_err:
                logger.error("Alpha ML DB recording failed (order already placed): %s", db_err)

            _last_order_time = time.monotonic()

            # Register in shared positions so other services don't treat this as a ghost
            qty = intent.quantity if record["side"] == "long" else -intent.quantity
            try:
                shared_pos.upsert("alpha-ml", str(record["symbol"]), qty, float(record["entry_price"]))
            except Exception:
                logger.warning("Failed to update shared_positions for %s", record["symbol"])

            audit.log_event(
                EventType.TRADE_OPEN,
                f"Alpha ML trade opened: {record['side']} {record['symbol']} x{intent.quantity} @ {record['entry_price']}",
                context={"symbol": record["symbol"], "trade_id": db_trade_id, "signal_id": signal_id, "ibkr_order_id": int(order.order_id)},
            )
            audit.log_event(
                EventType.ORDER_SUBMIT,
                f"Alpha ML bracket order submitted: {record['symbol']} order_id={order.order_id}",
                context={"symbol": record["symbol"], "ibkr_order_id": int(order.order_id), "trade_id": db_trade_id},
            )

            _append_submitted_action_id(submitted_path, str(record["action_id"]), int(order.order_id))

            summary["submitted"] += 1
            summary["orders"].append(
                {
                    "action_id": record["action_id"],
                    "symbol": record["symbol"],
                    "order_id": int(order.order_id),
                    "bracket_ids": [int(item) for item in order.bracket_ids],
                    "trade_id": db_trade_id,
                    "signal_id": signal_id,
                    "status": "submitted",
                }
            )
    except Exception as exc:
        logger.exception("Alpha ML IBKR paper execution failed")
        audit.log_event(EventType.ERROR, f"Alpha ML execution error: {exc}", Severity.ERROR)
        summary["error"] = str(exc)
        summary["failed"] += max(len(fresh_records) - summary["submitted"], 0)
    finally:
        if trade_db is not None:
            try:
                trade_db.stop()
            except Exception:
                logger.exception("Failed to stop alpha trade integration")
        try:
            session.disconnect()
        except Exception:
            logger.exception("Failed to disconnect alpha IBKR session")
    return summary


def _read_emitted_action_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    emitted: set[str] = set()
    with path.open("r") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = payload.get("action_id")
            if isinstance(action_id, str):
                emitted.add(action_id)
    return emitted


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(f"{path.suffix}.tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp_path.replace(path)


def run_paper_once(run_config: PaperRunConfig) -> dict[str, Any]:
    """Run one bounded paper/shadow scoring pass and write output artifacts."""
    date = run_config.date
    output_root = _resolve_path(run_config.output_dir) / f"date={date}"
    output_root.mkdir(parents=True, exist_ok=True)

    status: dict[str, Any] = {
        "date": date,
        "mode": (
            "ibkr_paper_orders"
            if run_config.execution_mode == "ibkr_paper"
            else "paper_shadow_no_orders"
        ),
        "execution_mode": run_config.execution_mode,
        "exit_mode": run_config.exit_mode,
        "bar_source": run_config.bar_source,
        "artifact_path": str(_resolve_path(run_config.artifact_path)),
        "min_score": run_config.min_score,
        "daily_top_k": run_config.daily_top_k,
        "max_longs_per_day": run_config.max_longs_per_day,
        "max_symbols": run_config.max_symbols,
        "started_at_utc": datetime.utcnow().isoformat() + "Z",
        "output_dir": str(output_root),
    }

    try:
        sip_symbols = load_daily_sip_symbols(date, run_config.sip_root)
    except FileNotFoundError as exc:
        status.update({"status": "missing_sip", "error": str(exc)})
        _write_json(output_root / "status.json", status)
        return status
    except Exception as exc:
        status.update({"status": "invalid_sip", "error": str(exc)})
        _write_json(output_root / "status.json", status)
        return status

    symbols = filter_l2_scalping_symbols(sip_symbols, max_symbols=run_config.max_symbols)
    status["sip_symbols"] = len(sip_symbols)
    status["symbols_selected_from_sip"] = symbols
    if not symbols:
        status.update({"status": "no_symbols_after_sip_filter"})
        _write_json(output_root / "status.json", status)
        return status

    artifact = joblib.load(_resolve_path(run_config.artifact_path))
    config = _base_config(run_config.bar_source)
    config.setdefault("data", {})["polygon_cache_dir"] = str(
        _resolve_path(run_config.polygon_cache_dir)
    )
    cutoff = _cutoff_timestamp(date, run_config.cutoff_et)
    l2_loader = L2Loader()

    ranked: list[RankedAction] = []
    bars_by_symbol: dict[str, pd.DataFrame] = {}
    symbol_status: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        symbol_status[symbol] = {"bars": 0, "l2_snapshots": 0, "ranked_actions": 0}
        try:
            bars = _load_symbol_bars(
                symbol=symbol,
                date=date,
                bar_source=run_config.bar_source,
                config=config,
            )
            bars = _filter_bars_to_cutoff(bars, cutoff)
            if bars.empty:
                symbol_status[symbol]["error"] = "no_bars_before_cutoff"
                continue
            bars["symbol"] = symbol
            bars_by_symbol[symbol] = bars.copy()
            symbol_status[symbol]["bars"] = int(len(bars))
        except Exception as exc:
            symbol_status[symbol]["error"] = f"bars: {exc}"
            logger.warning("Skipping %s %s due to bar load error: %s", symbol, date, exc)
            continue

        try:
            l2 = l2_loader.load_snapshots(
                symbol,
                date,
                source_type=run_config.l2_source_type,  # type: ignore[arg-type]
            )
            l2 = _filter_l2_to_cutoff(l2, cutoff)
            if l2.empty:
                symbol_status[symbol]["error"] = "no_l2_before_cutoff"
                continue
            symbol_status[symbol]["l2_snapshots"] = int(len(l2))
        except Exception as exc:
            symbol_status[symbol]["error"] = f"l2: {exc}"
            logger.warning("Skipping %s %s due to L2 load error: %s", symbol, date, exc)
            continue

        symbol_ranked = _score_symbol(
            date=date,
            symbol=symbol,
            bars_df=bars,
            l2_df=l2,
            config=config,
            artifact=artifact,
        )
        symbol_status[symbol]["ranked_actions"] = int(len(symbol_ranked))
        ranked.extend(symbol_ranked)

    selected = _select_topk(
        ranked,
        top_k=run_config.daily_top_k,
        max_longs_per_day=run_config.max_longs_per_day,
        min_score=run_config.min_score,
        weak_context_gate=None,
    )
    ranked_records = [
        ranked_action_to_dict(
            action,
            entry_price=_price_for_action(action, bars_by_symbol.get(action.symbol, pd.DataFrame())),
            stop_bps=run_config.execution_stop_bps,
            target_bps=run_config.execution_target_bps,
            execution_mode="shadow",
        )
        for action in ranked
    ]
    selected_records = [
        ranked_action_to_dict(
            action,
            entry_price=_price_for_action(action, bars_by_symbol.get(action.symbol, pd.DataFrame())),
            stop_bps=run_config.execution_stop_bps,
            target_bps=run_config.execution_target_bps,
            execution_mode=run_config.execution_mode,
        )
        for action in selected
    ]

    pd.DataFrame(ranked_records).to_csv(output_root / "ranked_actions.csv", index=False)
    pd.DataFrame(selected_records).to_csv(
        output_root / "selected_actions.csv", index=False
    )
    _write_json(
        output_root / "latest_signals.json",
        {
            "date": date,
            "generated_at_utc": datetime.utcnow().isoformat() + "Z",
            "selected_actions": selected_records,
        },
    )

    jsonl_path = output_root / "paper_signals.jsonl"
    submitted_path = output_root / "submitted_actions.jsonl"
    emitted = _read_emitted_action_ids(jsonl_path)
    # New signals = not yet recorded in paper_signals.jsonl
    new_records = [
        record for record in selected_records if record["action_id"] not in emitted
    ]
    if new_records:
        with jsonl_path.open("a") as handle:
            for record in new_records:
                handle.write(json.dumps(record, sort_keys=True) + "\n")

    # For execution: filter by submitted_actions.jsonl (separate from signal emission)
    already_submitted = _read_submitted_action_ids(submitted_path)
    executable_records = [
        record for record in selected_records if record["action_id"] not in already_submitted
    ]

    execution_summary = _execute_records_if_enabled(
        run_config=run_config,
        records=executable_records,
        pass_cutoff=cutoff,
    )

    status.update(
        {
            "status": "ok",
            "cutoff_et": cutoff.isoformat(),
            "symbols": symbol_status,
            "ranked_actions": len(ranked_records),
            "selected_actions": len(selected_records),
            "new_paper_signals": len(new_records),
            "executable_records": len(executable_records),
            "execution": execution_summary,
            "paper_signals_jsonl": str(jsonl_path),
            "latest_signals_json": str(output_root / "latest_signals.json"),
            "ranked_actions_csv": str(output_root / "ranked_actions.csv"),
            "selected_actions_csv": str(output_root / "selected_actions.csv"),
            "completed_at_utc": datetime.utcnow().isoformat() + "Z",
        }
    )
    _write_json(output_root / "status.json", status)
    return status


def _emergency_close_all_positions(run_config: PaperRunConfig) -> None:
    """On SIGTERM: close all open alpha-ml trades via market orders."""
    logger.info("Alpha ML: emergency close triggered")
    try:
        _add_quantstack_v2_import_paths()
        from cpapi.audit_logger import AuditLogger, EventType, Severity  # type: ignore
        from cpapi.shared_positions import SharedPositionLedger  # type: ignore
        from cpapi.trade_integration import TradeIntegration  # type: ignore
        from execution.ibkr_live_adapter import IBKRLiveAdapter  # type: ignore
        from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig  # type: ignore

        audit = AuditLogger("alpha-ml")
        shared_pos = SharedPositionLedger()
        session = IBKRSession(
            IBKRSessionConfig(
                system_name="alpha-ml",
                connection=IBKRConnectionConfig(
                    host=run_config.ibkr_host,
                    port=run_config.ibkr_port,
                    client_id=run_config.ibkr_client_id + 1,  # use +1 to avoid conflict with main client
                    readonly=False,
                    allow_client_id_fallback=True,
                    client_id_fallbacks=3,
                ),
            )
        )
        if not session.connect():
            logger.error("Alpha ML emergency close: IBKR connect failed")
            return
        trade_db = TradeIntegration(ib=session.ib, system_name="alpha-ml", ib_call=session.call)
        trade_db.start()
        adapter = IBKRLiveAdapter(session, system_name="alpha-ml", client_id=run_config.ibkr_client_id + 1, order_ref_prefix=run_config.order_ref_prefix)
        adapter.attach_handlers()
        try:
            for trade in trade_db.get_open_trades():
                if trade.get("system") != "alpha-ml":
                    continue
                symbol = str(trade["symbol"])
                direction = str(trade.get("direction", "long")).lower()
                entry_qty = int(trade.get("entry_qty") or 0)
                if entry_qty <= 0:
                    continue
                action = "SELL" if direction == "long" else "BUY"
                order_id = adapter.submit_order(symbol, action, abs(entry_qty), order_type="MKT")
                if order_id:
                    try:
                        shared_pos.upsert("alpha-ml", symbol, 0, 0.0)
                    except Exception:
                        pass
                    audit.log_event(EventType.TRADE_CLOSE, f"Alpha ML emergency close: {symbol}", context={"symbol": symbol, "trade_id": str(trade.get("trade_id")), "exit_mode": "emergency"})
                    logger.info("Alpha ML emergency close submitted: %s order_id=%s", symbol, order_id)
        finally:
            trade_db.stop()
            session.disconnect()
    except Exception:
        logger.exception("Alpha ML emergency close failed")


def run_paper_loop(
    run_config: PaperRunConfig,
    *,
    interval_seconds: int = 60,
    session_end: str = "16:00:00",
) -> None:
    """Run repeated paper passes until the ET session-end clock time."""
    _add_quantstack_v2_import_paths()
    try:
        from cpapi.audit_logger import AuditLogger, EventType  # type: ignore
        audit: Any = AuditLogger("alpha-ml")
    except Exception:
        audit = None

    # SIGTERM handler: close positions then exit cleanly
    _shutdown = {"requested": False}

    def _handle_sigterm(signum: int, frame: Any) -> None:
        logger.info("Alpha ML: SIGTERM received, closing positions")
        _shutdown["requested"] = True
        _emergency_close_all_positions(run_config)
        if audit:
            try:
                audit.log_event(EventType.SERVICE_STOP, "alpha-ml stopped via SIGTERM")
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if audit:
        try:
            audit.log_event(EventType.SERVICE_START, "alpha-ml paper trading started", context={"execution_mode": run_config.execution_mode, "exit_mode": run_config.exit_mode})
        except Exception:
            pass

    interval = max(int(interval_seconds), 5)
    while True:
        status = run_paper_once(
            PaperRunConfig(
                date=run_config.date,
                artifact_path=run_config.artifact_path,
                sip_root=run_config.sip_root,
                output_dir=run_config.output_dir,
                polygon_cache_dir=run_config.polygon_cache_dir,
                bar_source=run_config.bar_source,
                max_symbols=run_config.max_symbols,
                daily_top_k=run_config.daily_top_k,
                max_longs_per_day=run_config.max_longs_per_day,
                min_score=run_config.min_score,
                cutoff_et=None,
                l2_source_type=run_config.l2_source_type,
                execution_mode=run_config.execution_mode,
                exit_mode=run_config.exit_mode,
                execution_quantity=run_config.execution_quantity,
                execution_stop_bps=run_config.execution_stop_bps,
                execution_target_bps=run_config.execution_target_bps,
                execution_max_action_age_seconds=run_config.execution_max_action_age_seconds,
                ibkr_host=run_config.ibkr_host,
                ibkr_port=run_config.ibkr_port,
                ibkr_client_id=run_config.ibkr_client_id,
                ibkr_account_id=run_config.ibkr_account_id,
                order_ref_prefix=run_config.order_ref_prefix,
            )
        )
        logger.info("Paper pass status: %s", status.get("status"))
        if current_et_time() >= session_end:
            logger.info("Session end reached at %s ET", current_et_time())
            if audit:
                try:
                    audit.log_event(EventType.SERVICE_STOP, "alpha-ml paper trading session ended")
                except Exception:
                    pass
            return
        time.sleep(interval)
