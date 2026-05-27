"""Paper/shadow runner for the alpha action-ranker."""

from __future__ import annotations

import json
import logging
import os
import signal
import sys
import time
import uuid
import importlib
from dataclasses import dataclass
from datetime import datetime, timezone
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
    system_name: str = "alpha-ml"
    l2_meta_gate_mode: str = "off"
    l2_meta_gate_unknown: str = "allow"
    rejected_action_cooldown_seconds: int = 300
    no_new_entries_after: str = "15:45:00"


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


def _at_or_after_et(clock_time: str) -> bool:
    return current_et_time() >= clock_time


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
    ib: Any = None,
) -> pd.DataFrame:
    if bar_source == "polygon":
        bars = load_polygon_bars(symbol, date, date, config)
        if bars.empty and ib is not None:
            return _ibkr_bar_fallback(ib, symbol, date)
        return bars
    if bar_source == "gold":
        return GoldLoader().load_bars(symbol, date, date)
    raise ValueError(f"Unsupported bar source: {bar_source}")


def _ibkr_bar_fallback(ib: Any, symbol: str, date: str) -> pd.DataFrame:
    """Fetch 1-min bars from IBKR when Polygon has no same-day data."""
    try:
        from ib_insync import Stock
        contract = Stock(symbol, "SMART", "USD")
        ib.qualifyContracts(contract)
        ibkr_bars = ib.reqHistoricalData(
            contract,
            endDateTime="",
            durationStr="1 D",
            barSizeSetting="1 min",
            whatToShow="TRADES",
            useRTH=True,
            formatDate=2,
        )
        if not ibkr_bars:
            return pd.DataFrame()
        rows = [
            {
                "ts": pd.Timestamp(b.date).tz_convert(ET) if b.date.tzinfo else pd.Timestamp(b.date).tz_localize(ET),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "symbol": symbol,
            }
            for b in ibkr_bars
        ]
        logger.info("Polygon empty for %s %s, fell back to IBKR bars (%d rows)", symbol, date, len(rows))
        return pd.DataFrame(rows)
    except Exception as exc:
        logger.warning("IBKR bar fallback failed for %s: %s", symbol, exc)
        return pd.DataFrame()


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


def _record_signal_id(action_id: str, *, system_name: str = "alpha-ml") -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"quantstack:{system_name}:{action_id}"))


def _normalize_l2_gate_mode(mode: str) -> str:
    normalized = str(mode or "off").strip().lower()
    return normalized if normalized in {"off", "shadow", "enforce"} else "off"


def _normalize_l2_gate_unknown(action: str) -> str:
    normalized = str(action or "allow").strip().lower()
    return normalized if normalized in {"allow", "reduce", "veto"} else "allow"


def _gate_payload_from_result(result: Any, *, fallback_reason: str | None = None) -> dict[str, Any]:
    if isinstance(result, dict):
        decision = result.get("decision") or result.get("action") or result.get("gate_decision")
        reason = result.get("reason") or result.get("reason_code") or result.get("reasons") or fallback_reason
        payload = dict(result)
    else:
        decision = getattr(result, "decision", None) or getattr(result, "action", None)
        reason = (
            getattr(result, "reason", None)
            or getattr(result, "reason_code", None)
            or getattr(result, "reasons", None)
            or fallback_reason
        )
        payload = {
            key: getattr(result, key)
            for key in ("decision", "action", "reason", "reason_code", "reasons", "score", "size_multiplier", "features")
            if hasattr(result, key)
        }
    if hasattr(decision, "value"):
        decision = decision.value
    decision_text = str(decision or "UNKNOWN").upper()
    if decision_text not in {"ALLOW", "REDUCE", "VETO", "UNKNOWN"}:
        decision_text = "UNKNOWN"
    payload["decision"] = decision_text
    payload["reason"] = str(reason or "unspecified")
    return payload


def _evaluate_l2_meta_gate(record: dict[str, Any], run_config: PaperRunConfig) -> dict[str, Any]:
    mode = _normalize_l2_gate_mode(run_config.l2_meta_gate_mode)
    unknown = _normalize_l2_gate_unknown(run_config.l2_meta_gate_unknown)
    if mode == "off":
        return {
            "mode": "off",
            "decision": "ALLOW",
            "reason": "disabled",
            "effective_action": "allow",
        }

    request = {
        "symbol": str(record.get("symbol", "")),
        "direction": str(record.get("side", "")),
        "price": record.get("entry_price"),
        "strategy": "action_ranker",
        "signal_id": _record_signal_id(str(record.get("action_id", "")), system_name=run_config.system_name),
        "system": run_config.system_name,
        "action_id": record.get("action_id"),
        "timestamp": record.get("timestamp"),
    }
    try:
        gate_module = importlib.import_module("l2_meta_gate")
        gate_fn = None
        for name in ("evaluate_l2_meta_gate", "evaluate_meta_gate", "evaluate_gate", "evaluate"):
            candidate = getattr(gate_module, name, None)
            if callable(candidate):
                gate_fn = candidate
                break
        if gate_fn is None:
            payload = _gate_payload_from_result(None, fallback_reason="gate_function_missing")
        else:
            gate_input_cls = getattr(gate_module, "GateInput", None)
            gate_action_cls = getattr(gate_module, "GateAction", None)
            features = dict(record.get("context") or {})
            if callable(gate_input_cls):
                signal_time = None
                if request.get("timestamp"):
                    try:
                        signal_time = pd.Timestamp(request["timestamp"]).to_pydatetime()
                    except Exception:
                        signal_time = None
                gate_input = gate_input_cls(
                    symbol=request["symbol"],
                    direction=request["direction"],
                    features=features,
                    signal_time=signal_time,
                    signal_price=request["price"],
                    strategy=request["strategy"],
                    mode=mode,
                )
                unknown_policy = None
                if gate_action_cls is not None:
                    unknown_policy = getattr(gate_action_cls, unknown.upper(), None)
                try:
                    if unknown_policy is None:
                        result = gate_fn(gate_input)
                    else:
                        result = gate_fn(gate_input, unknown_policy=unknown_policy)
                except TypeError:
                    result = gate_fn(gate_input)
            else:
                try:
                    result = gate_fn(request)
                except TypeError:
                    try:
                        result = gate_fn(request=request)
                    except TypeError:
                        result = gate_fn(**request)
            payload = _gate_payload_from_result(result)
    except Exception as exc:
        payload = _gate_payload_from_result(None, fallback_reason=f"gate_unavailable:{exc.__class__.__name__}")

    decision = str(payload.get("decision", "UNKNOWN")).upper()
    effective_action = decision.lower()
    if decision == "UNKNOWN":
        effective_action = unknown
    if mode == "shadow":
        executable = True
    elif effective_action == "veto":
        executable = False
    else:
        executable = True
    payload.update(
        {
            "mode": mode,
            "unknown_action": unknown,
            "effective_action": effective_action,
            "executable": executable,
        }
    )
    return payload


def _apply_l2_meta_gate(
    records: list[dict[str, Any]],
    run_config: PaperRunConfig,
) -> list[dict[str, Any]]:
    gated: list[dict[str, Any]] = []
    for record in records:
        out = dict(record)
        meta_gate = _evaluate_l2_meta_gate(out, run_config)
        out["meta_gate"] = meta_gate
        context = dict(out.get("context") or {})
        context["meta_gate"] = meta_gate
        out["context"] = context
        gated.append(out)
    return gated


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


def _trade_due_for_time_exit(trade: dict[str, Any], *, now: pd.Timestamp, max_hold_minutes: int = 60) -> bool:
    metadata = _trade_signal_data(trade)
    hold_minutes = metadata.get("hold_minutes")
    if hold_minutes is None:
        hold_minutes = max_hold_minutes
    entry_time = trade.get("entry_time")
    if entry_time is None:
        return False
    entry_ts = pd.Timestamp(entry_time)
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    else:
        entry_ts = entry_ts.tz_convert("UTC")
    target_minutes = min(int(hold_minutes), max_hold_minutes)
    return now >= entry_ts + pd.Timedelta(minutes=target_minutes)


def _open_exit_order_exists(trade_db: Any, trade_id: str, *, system_name: str) -> bool:
    conn = trade_db.db.pool.getconn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT 1
            FROM orders_v2
            WHERE trade_id = %s
              AND system = %s
              AND role IN ('EXIT', 'TIME_EXIT')
              AND COALESCE(status, '') NOT IN (
                  'FILLED', 'Filled', 'CANCELLED', 'Cancelled',
                  'ApiCancelled', 'Inactive', 'REJECTED', 'Rejected'
              )
            LIMIT 1
            """,
            (trade_id, system_name),
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
        if trade.get("system") != run_config.system_name:
            continue
        summary["checked"] += 1
        if not _trade_due_for_time_exit(trade, now=now_utc):
            continue
        summary["due"] += 1
        trade_id = str(trade["trade_id"])
        if _open_exit_order_exists(trade_db, trade_id, system_name=run_config.system_name):
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
        # Close canonical trades_v2 row — UnifiedFillProcessor may not see the fill
        # if the session disconnects before it arrives.
        try:
            trade_db.close_trade(
                trade_id,
                exit_price=float(trade.get("entry_price") or 0),  # best estimate; fill price unknown
                exit_reason="TIME_EXIT",
                pnl=None,  # let DB compute from fill if possible
            )
        except Exception as _ce:
            logger.warning("close_trade failed for time_exit %s: %s", trade_id, _ce)
        # Clear shared position on exit
        if shared_pos is not None:
            try:
                shared_pos.upsert(run_config.system_name, symbol, 0, 0.0)
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


def _read_recent_rejected_action_ids(path: Path, *, cooldown_seconds: int) -> set[str]:
    if cooldown_seconds <= 0 or not path.exists():
        return set()
    cutoff = datetime.now(timezone.utc).timestamp() - cooldown_seconds
    rejected: set[str] = set()
    with path.open("r") as handle:
        for line in handle:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            action_id = payload.get("action_id")
            rejected_at = payload.get("rejected_at")
            if not isinstance(action_id, str) or not isinstance(rejected_at, str):
                continue
            try:
                rejected_ts = datetime.fromisoformat(rejected_at.replace("Z", "+00:00")).timestamp()
            except ValueError:
                continue
            if rejected_ts >= cutoff:
                rejected.add(action_id)
    return rejected


def _append_rejected_action(path: Path, record: dict[str, Any], *, reason: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "action_id": record.get("action_id"),
        "symbol": record.get("symbol"),
        "reason": reason,
        "meta_gate": record.get("meta_gate"),
        "rejected_at": datetime.utcnow().isoformat() + "Z",
    }
    with path.open("a") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _execute_records_if_enabled(
    *,
    run_config: PaperRunConfig,
    records: list[dict[str, Any]],
    pass_cutoff: pd.Timestamp | None = None,
    shared_session: Any = None,
    shared_trade_db: Any = None,
    shared_adapter: Any = None,
    shared_manager: Any = None,
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "mode": run_config.execution_mode,
        "exit_mode": run_config.exit_mode,
        "attempted": 0,
        "submitted": 0,
        "skipped_stale": 0,
        "skipped_missing_price": 0,
        "skipped_l2_meta_gate": 0,
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
    # However, skip the IBKR connection entirely when there are no records
    # AND no open system trades (avoids reconnect spam when data is unavailable).
    owns_session = shared_session is None
    if not records and owns_session:
        try:
            import psycopg2
            _conn = psycopg2.connect(dbname="trading")
            try:
                _cur = _conn.cursor()
                _cur.execute(
                    "SELECT COUNT(*) FROM trades_v2 WHERE system=%s AND status='OPEN'",
                    (run_config.system_name,),
                )
                _open_count = _cur.fetchone()[0]
            finally:
                _conn.close()
            if _open_count == 0:
                logger.info("No executable records and no open %s trades - skipping IBKR connection", run_config.system_name)
                return summary
        except Exception:
            pass  # fall through to normal IBKR path if DB check fails

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

    audit = AuditLogger(run_config.system_name)
    shared_pos = SharedPositionLedger()
    output_root = _resolve_path(run_config.output_dir) / f"date={run_config.date}"
    submitted_path = output_root / "submitted_actions.jsonl"
    rejected_path = output_root / "rejected_actions.jsonl"

    # Reuse shared session/components if provided; otherwise create ephemeral ones
    session = shared_session
    trade_db = shared_trade_db
    adapter = shared_adapter
    manager = shared_manager

    if owns_session:
        session = IBKRSession(
            IBKRSessionConfig(
                system_name=run_config.system_name,
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
        if owns_session:
            if not session.connect():
                audit.log_event(EventType.DEPENDENCY_FAIL, f"{run_config.system_name} IBKR connect failed", Severity.ERROR)
                summary["error"] = "ibkr_connect_failed"
                summary["failed"] = len(fresh_records)
                return summary
            audit.log_event(EventType.SERVICE_READY, f"{run_config.system_name} IBKR connected", context={"client_id": run_config.ibkr_client_id})
            adapter = IBKRLiveAdapter(
                session,
                system_name=run_config.system_name,
                client_id=run_config.ibkr_client_id,
                order_ref_prefix=run_config.order_ref_prefix,
                account_id=run_config.ibkr_account_id,
            )
            adapter.attach_handlers()
            manager = OrderManager(
                adapter,
                RiskLimits(
                    daily_loss_limit=200.0,
                    max_concurrent_positions=3,
                    max_position_pct=0.02,
                    max_trades_per_day=999,
                ),
            )
            trade_db = TradeIntegration(
                ib=session.ib,
                system_name=run_config.system_name,
                ib_call=session.call,
            )
            trade_db.start()
            # Reconcile stale open DB rows from prior sessions
            try:
                result = trade_db.reconcile_startup()
                if result:
                    logger.info("Alpha ML startup reconciliation: %s", result)
            except Exception as _re:
                logger.warning("Alpha ML startup reconciliation failed: %s", _re)

        summary["time_exits"] = _submit_due_time_exits(
            run_config=run_config,
            session=session,
            adapter=adapter,
            trade_db=trade_db,
            shared_pos=shared_pos,
            audit=audit,
        )

        # Wait for MKT time-exit fills before disconnecting
        if summary["time_exits"].get("submitted", 0) > 0:
            logger.info("Waiting 5s for time-exit fills to settle...")
            time.sleep(5)
            session.ib.sleep(0)  # pump ib_insync event loop to process fills

        if not fresh_records:
            return summary

        _last_order_time: float = 0.0
        _ORDER_COOLDOWN_SECONDS = 60
        _open_symbols: set[str] = set()
        try:
            for trade in trade_db.get_open_trades():
                if trade.get("system") == run_config.system_name:
                    _open_symbols.add(str(trade["symbol"]).upper())
        except Exception:
            pass

        for record in fresh_records:
            # Enforce cooldown between consecutive orders so IBKR position state
            # has time to settle and OrderManager.can_trade() sees accurate counts.
            elapsed = time.monotonic() - _last_order_time
            if _last_order_time > 0 and elapsed < _ORDER_COOLDOWN_SECONDS:
                time.sleep(_ORDER_COOLDOWN_SECONDS - elapsed)

            # Block same-symbol entry if already holding or pending
            if str(record["symbol"]).upper() in _open_symbols:
                summary["orders"].append({"action_id": record["action_id"], "symbol": record["symbol"], "status": "skipped_symbol_already_open"})
                continue

            summary["attempted"] += 1
            signal_id = _record_signal_id(str(record["action_id"]), system_name=run_config.system_name)
            audit.log_event(
                EventType.TRADE_SIGNAL,
                f"Alpha ML signal: {record['side']} {record['symbol']} score={record['score']:.3f}",
                context={"symbol": record["symbol"], "signal_id": signal_id, "score": record["score"], "action_id": record["action_id"]},
            )
            meta_gate = record.get("meta_gate") if isinstance(record.get("meta_gate"), dict) else {}
            if _normalize_l2_gate_mode(run_config.l2_meta_gate_mode) == "enforce" and not meta_gate.get("executable", True):
                summary["skipped_l2_meta_gate"] += 1
                reason = str(meta_gate.get("reason") or "l2_meta_gate_veto")
                try:
                    trade_db.record_signal(
                        symbol=str(record["symbol"]),
                        signal_id=signal_id,
                        strategy="action_ranker",
                        direction=str(record["side"]).upper(),
                        signal_time=_timestamp_to_et(record["timestamp"]).to_pydatetime(),
                        signal_price=float(record["entry_price"]),
                        signal_strength=float(record["score"]),
                        decision="REJECT",
                        features=record,
                    )
                except Exception as db_err:
                    logger.warning("Alpha ML gate rejection signal recording failed: %s", db_err)
                _append_rejected_action(rejected_path, record, reason=reason)
                audit.log_event(
                    EventType.ORDER_REJECT,
                    f"Alpha ML L2 meta gate rejected: {record['symbol']}",
                    Severity.WARNING,
                    context={"reason": reason, "symbol": record["symbol"], "signal_id": signal_id, "meta_gate": meta_gate},
                )
                summary["orders"].append(
                    {
                        "action_id": record["action_id"],
                        "symbol": record["symbol"],
                        "status": "l2_meta_gate_rejected",
                        "meta_gate": meta_gate,
                    }
                )
                continue
            quantity = max(int(run_config.execution_quantity), 1)
            if (
                _normalize_l2_gate_mode(run_config.l2_meta_gate_mode) == "enforce"
                and str(meta_gate.get("effective_action", "")).lower() == "reduce"
            ):
                multiplier = float(meta_gate.get("size_multiplier") or 0.5)
                quantity = max(1, int(quantity * multiplier))
            intent = OrderIntent(
                symbol=str(record["symbol"]),
                direction=str(record["side"]),
                quantity=quantity,
                entry_price=float(record["entry_price"]),
                stop_price=float(record["stop_price"]),
                target_price=float(record["target_price"]),
                strategy="action_ranker",
                signal_id=signal_id,
            )
            order = manager.submit_order(intent)
            if not order:
                audit.log_event(EventType.ORDER_REJECT, f"Alpha ML order rejected: {record['symbol']}", Severity.WARNING, context={"reason": "order_manager_rejected", "symbol": record["symbol"], "signal_id": signal_id})
                _append_rejected_action(rejected_path, record, reason="order_manager_rejected")
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
            _open_symbols.add(str(record["symbol"]).upper())
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

            # Register in shared positions — use pending quantity so other services
            # don't enter the same symbol while the bracket is live.
            # NOTE: this is an optimistic upsert (order submitted but not yet filled).
            # If the limit entry never fills, the stale row will be cleared by
            # reconcile_startup() on next startup or by the daily orphan sweeper.
            qty = intent.quantity if record["side"] == "long" else -intent.quantity
            try:
                shared_pos.upsert(run_config.system_name, str(record["symbol"]), qty, float(record["entry_price"]))
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
        if owns_session:
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


def run_paper_once(
    run_config: PaperRunConfig,
    *,
    shared_session: Any = None,
    shared_trade_db: Any = None,
    shared_adapter: Any = None,
    shared_manager: Any = None,
) -> dict[str, Any]:
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
        "system_name": run_config.system_name,
        "l2_meta_gate_mode": _normalize_l2_gate_mode(run_config.l2_meta_gate_mode),
        "l2_meta_gate_unknown": _normalize_l2_gate_unknown(run_config.l2_meta_gate_unknown),
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
                ib=shared_session.ib if shared_session is not None and hasattr(shared_session, 'ib') else None,
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
    selected_records = _apply_l2_meta_gate(selected_records, run_config)

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
    recently_rejected = _read_recent_rejected_action_ids(
        output_root / "rejected_actions.jsonl",
        cooldown_seconds=run_config.rejected_action_cooldown_seconds,
    )
    executable_records = [
        record
        for record in selected_records
        if record["action_id"] not in already_submitted
        and record["action_id"] not in recently_rejected
    ]
    if _at_or_after_et(run_config.no_new_entries_after):
        logger.info(
            "Alpha ML: blocking %d new entries after cutoff %s ET",
            len(executable_records),
            run_config.no_new_entries_after,
        )
        executable_records = []

    execution_summary = _execute_records_if_enabled(
        run_config=run_config,
        records=executable_records,
        pass_cutoff=cutoff,
        shared_session=shared_session,
        shared_trade_db=shared_trade_db,
        shared_adapter=shared_adapter,
        shared_manager=shared_manager,
    )

    status.update(
        {
            "status": "ok",
            "cutoff_et": cutoff.isoformat(),
            "symbols": symbol_status,
            "ranked_actions": len(ranked_records),
            "selected_actions": len(selected_records),
            "new_paper_signals": len(new_records),
            "rejected_action_cooldown_seconds": run_config.rejected_action_cooldown_seconds,
            "recent_rejected_actions": len(recently_rejected),
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
    """On SIGTERM: close all open system trades via market orders."""
    logger.info("Alpha ML: emergency close triggered")
    try:
        _add_quantstack_v2_import_paths()
        from cpapi.audit_logger import AuditLogger, EventType, Severity  # type: ignore
        from cpapi.shared_positions import SharedPositionLedger  # type: ignore
        from cpapi.trade_integration import TradeIntegration  # type: ignore
        from execution.ibkr_live_adapter import IBKRLiveAdapter  # type: ignore
        from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig  # type: ignore

        audit = AuditLogger(run_config.system_name)
        shared_pos = SharedPositionLedger()
        session = IBKRSession(
            IBKRSessionConfig(
                system_name=run_config.system_name,
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
        trade_db = TradeIntegration(ib=session.ib, system_name=run_config.system_name, ib_call=session.call)
        trade_db.start()
        adapter = IBKRLiveAdapter(session, system_name=run_config.system_name, client_id=run_config.ibkr_client_id + 1, order_ref_prefix=run_config.order_ref_prefix)
        adapter.attach_handlers()
        try:
            for trade in trade_db.get_open_trades():
                if trade.get("system") != run_config.system_name:
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
                        shared_pos.upsert(run_config.system_name, symbol, 0, 0.0)
                    except Exception:
                        pass
                    # Close canonical trades_v2 row
                    try:
                        trade_db.close_trade(
                            str(trade.get("trade_id")),
                            exit_price=float(trade.get("entry_price") or 0),
                            exit_reason="EMERGENCY_CLOSE",
                            pnl=None,
                        )
                    except Exception as _ce:
                        logger.warning("close_trade failed for emergency close %s: %s", symbol, _ce)
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
        audit: Any = AuditLogger(run_config.system_name)
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
                audit.log_event(EventType.SERVICE_STOP, f"{run_config.system_name} stopped via SIGTERM")
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_sigterm)

    if audit:
        try:
            audit.log_event(EventType.SERVICE_START, f"{run_config.system_name} paper trading started", context={"execution_mode": run_config.execution_mode, "exit_mode": run_config.exit_mode})
        except Exception:
            pass

    # --- S1: Persistent session lifecycle ---
    session = None
    trade_db = None
    adapter = None
    manager = None

    if run_config.execution_mode == "ibkr_paper":
        try:
            from cpapi.trade_integration import TradeIntegration  # type: ignore
            from execution.ibkr_live_adapter import IBKRLiveAdapter  # type: ignore
            from execution.order_manager import OrderManager, RiskLimits  # type: ignore
            from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig  # type: ignore

            session = IBKRSession(
                IBKRSessionConfig(
                    system_name=run_config.system_name,
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
            if session.connect():
                if audit:
                    audit.log_event(EventType.SERVICE_READY, f"{run_config.system_name} IBKR connected", context={"client_id": run_config.ibkr_client_id})
                adapter = IBKRLiveAdapter(
                    session,
                    system_name=run_config.system_name,
                    client_id=run_config.ibkr_client_id,
                    order_ref_prefix=run_config.order_ref_prefix,
                    account_id=run_config.ibkr_account_id,
                )
                adapter.attach_handlers()
                manager = OrderManager(
                    adapter,
                    RiskLimits(
                        daily_loss_limit=200.0,
                        max_concurrent_positions=3,
                        max_position_pct=0.02,
                        max_trades_per_day=999,
                    ),
                )
                trade_db = TradeIntegration(
                    ib=session.ib,
                    system_name=run_config.system_name,
                    ib_call=session.call,
                )
                trade_db.start()
            else:
                logger.error("Alpha ML: initial IBKR connect failed, will retry per-pass")
                session = None
        except Exception:
            logger.exception("Alpha ML: failed to create persistent session, will retry per-pass")
            session = None

    interval = max(int(interval_seconds), 5)
    try:
        while True:
            if current_et_time() >= session_end:
                logger.info("Session end reached at %s ET before scoring", current_et_time())
                logger.info("Alpha ML: flattening open positions at session end")
                _emergency_close_all_positions(run_config)
                if audit:
                    try:
                        audit.log_event(EventType.SERVICE_STOP, f"{run_config.system_name} paper trading session ended", context={"exit_mode": "session_end", "positions_flattened": True})
                    except Exception:
                        pass
                return

            # Reconnect if persistent session dropped
            if run_config.execution_mode == "ibkr_paper" and session is not None:
                try:
                    if not session.ib.isConnected():
                        logger.warning("Alpha ML: IBKR connection dropped, reconnecting")
                        if session.connect() and audit:
                            audit.log_event(EventType.SERVICE_READY, f"{run_config.system_name} IBKR reconnected", context={"client_id": run_config.ibkr_client_id})
                except Exception:
                    logger.exception("Alpha ML: reconnect check failed")

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
                    system_name=run_config.system_name,
                    l2_meta_gate_mode=run_config.l2_meta_gate_mode,
                    l2_meta_gate_unknown=run_config.l2_meta_gate_unknown,
                    rejected_action_cooldown_seconds=run_config.rejected_action_cooldown_seconds,
                    no_new_entries_after=run_config.no_new_entries_after,
                ),
                shared_session=session,
                shared_trade_db=trade_db,
                shared_adapter=adapter,
                shared_manager=manager,
            )
            logger.info("Paper pass status: %s", status.get("status"))
            time.sleep(interval)
    finally:
        # Tear down persistent session
        if trade_db is not None:
            try:
                trade_db.stop()
            except Exception:
                logger.exception("Failed to stop alpha trade integration")
        if session is not None:
            try:
                session.disconnect()
            except Exception:
                logger.exception("Failed to disconnect alpha IBKR session")
