#!/usr/bin/env python3
"""
Market open recording checks.

Validates:
1) Audit log has TRADE_OPEN/TRADE_CLOSE for today's ET date.
2) TradeDB order IDs are populated for today's trades.
3) L2 raw and features data are being written for today's ET date.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

import psycopg2
from qx_broker.notify import send_status_message

ET = ZoneInfo("America/New_York")
MANILA = ZoneInfo("Asia/Manila")

AUDIT_DIR = Path("/home/jacobw/quantstack/logs/audit")
L2_BASE = Path("/home/jacobw/quantstack/data/l2/l2_maximum")

SYSTEMS = ("l2-scalping", "l2-vwap-reversion", "intraday-paper")
STALE_MINUTES = 10


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        return default


AUDIT_TRADE_GRACE_MINUTES = _env_int("AUDIT_TRADE_GRACE_MINUTES", 30)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str
    details: str

    def line(self) -> str:
        return f"{self.name}: {self.status} - {self.details}"


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD.") from exc


def _audit_files_for_et_date(target_date: date) -> list[Path]:
    start_et = datetime.combine(target_date, time.min, tzinfo=ET)
    end_et = datetime.combine(target_date, time.max, tzinfo=ET)
    mnl_dates = {
        start_et.astimezone(MANILA).date(),
        end_et.astimezone(MANILA).date(),
    }
    return [AUDIT_DIR / f"audit_{d.isoformat()}.jsonl" for d in sorted(mnl_dates)]


def _within_trade_grace(now_et: datetime, target_date: date) -> bool:
    if now_et.date() != target_date:
        return False
    market_open = datetime.combine(target_date, time(9, 30), tzinfo=ET)
    return now_et < market_open + timedelta(minutes=AUDIT_TRADE_GRACE_MINUTES)


def check_audit_events(
    target_date: date, systems: Iterable[str], now_et: datetime
) -> CheckResult:
    files = _audit_files_for_et_date(target_date)
    counts = {system: {"open": 0, "close": 0} for system in systems}
    files_found = 0

    for path in files:
        if not path.exists():
            continue
        files_found += 1
        try:
            with path.open() as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    event_type = record.get("event_type")
                    if event_type not in {"TRADE_OPEN", "TRADE_CLOSE"}:
                        continue
                    timestamp_et = record.get("timestamp_et")
                    if not timestamp_et:
                        continue
                    try:
                        event_time = datetime.fromisoformat(timestamp_et).astimezone(ET)
                    except ValueError:
                        continue
                    if event_time.date() != target_date:
                        continue
                    service = record.get("service")
                    if service not in counts:
                        continue
                    if event_type == "TRADE_OPEN":
                        counts[service]["open"] += 1
                    else:
                        counts[service]["close"] += 1
        except OSError as exc:
            return CheckResult(
                "Audit Log",
                "FAIL",
                f"failed to read {path}: {exc}",
            )

    if files_found == 0:
        checked = ", ".join(str(p) for p in files)
        return CheckResult(
            "Audit Log",
            "FAIL",
            f"no audit files found for {target_date} (checked: {checked})",
        )

    total_events = sum(v["open"] + v["close"] for v in counts.values())
    missing_systems = [
        system
        for system, data in counts.items()
        if data["open"] == 0 and data["close"] == 0
    ]

    detail_parts = [
        f"{system} open={data['open']} close={data['close']}"
        for system, data in counts.items()
    ]
    details = "; ".join(detail_parts)
    in_grace = _within_trade_grace(now_et, target_date)

    if total_events == 0:
        if in_grace:
            return CheckResult(
                "Audit Log",
                "OK",
                f"within grace window ({AUDIT_TRADE_GRACE_MINUTES}m after open); "
                f"no trade events yet; {details}",
            )
        return CheckResult(
            "Audit Log",
            "WARN",
            f"no TRADE_OPEN/TRADE_CLOSE events for {target_date} ET",
        )
    if missing_systems:
        missing = ", ".join(missing_systems)
        if in_grace:
            return CheckResult(
                "Audit Log",
                "OK",
                f"within grace window ({AUDIT_TRADE_GRACE_MINUTES}m after open); "
                f"no trade events yet for {missing}; {details}",
            )
        return CheckResult(
            "Audit Log",
            "WARN",
            f"missing events for {missing}; {details}",
        )
    return CheckResult("Audit Log", "OK", details)


def check_trade_db(target_date: date, systems: Iterable[str]) -> CheckResult:
    try:
        conn = psycopg2.connect(database="trading", user="jacobw")
    except Exception as exc:  # pragma: no cover - connection errors
        return CheckResult("TradeDB", "FAIL", f"connection failed: {exc}")

    systems = tuple(systems)
    aliases = {"l2-vwap-reversion": "l2-vwap"}
    normalized_systems = tuple(aliases.get(s, s) for s in systems)

    summary: dict[str, dict[str, int]] = {}
    for system in systems:
        summary[system] = {
            "trades": 0,
            "missing_entry": 0,
            "closed_trades": 0,
            "missing_exit": 0,
        }

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                      to_regclass('public.trades_v2') IS NOT NULL AS has_v2,
                      to_regclass('public.executions') IS NOT NULL AS has_exec,
                      to_regclass('public.trade_order_links') IS NOT NULL AS has_links,
                      to_regclass('public.trades') IS NOT NULL AS has_trades
                    """
                )
                has_v2, has_exec, has_links, has_trades = cur.fetchone()

                if has_v2 and has_exec and has_links:
                    # V2: validate that any trades created today have order links,
                    # and that any executions today are mapped to a trade_id.
                    cur.execute(
                        """
                        WITH day_trades AS (
                          SELECT trade_id, system, status
                          FROM trades_v2
                          WHERE (COALESCE(entry_time, created_at) AT TIME ZONE 'America/New_York')::date = %s
                            AND system = ANY(%s)
                        ),
                        link_counts AS (
                          SELECT trade_id, COUNT(*) AS links
                          FROM trade_order_links
                          GROUP BY trade_id
                        )
                        SELECT
                          t.system,
                          COUNT(*) AS trades,
                          SUM(CASE WHEN COALESCE(l.links, 0) = 0 THEN 1 ELSE 0 END) AS missing_links,
                          SUM(CASE WHEN t.status = 'CLOSED' THEN 1 ELSE 0 END) AS closed_trades
                        FROM day_trades t
                        LEFT JOIN link_counts l ON l.trade_id = t.trade_id
                        GROUP BY t.system
                        """,
                        (target_date.isoformat(), list(normalized_systems)),
                    )
                    rows = cur.fetchall()

                    # Default totals.
                    totals = {
                        sys: {"trades": 0, "missing_links": 0, "closed_trades": 0}
                        for sys in normalized_systems
                    }
                    for system, trades, missing_links, closed_trades in rows:
                        if system in totals:
                            totals[system] = {
                                "trades": int(trades or 0),
                                "missing_links": int(missing_links or 0),
                                "closed_trades": int(closed_trades or 0),
                            }

                    # Check for orphan executions (fills captured but not linked to trades).
                    cur.execute(
                        """
                        SELECT system, COUNT(*) AS orphan_execs
                        FROM executions
                        WHERE (ibkr_time AT TIME ZONE 'America/New_York')::date = %s
                          AND system = ANY(%s)
                          AND trade_id IS NULL
                        GROUP BY system
                        """,
                        (target_date.isoformat(), list(normalized_systems)),
                    )
                    orphan_rows = {r[0]: int(r[1] or 0) for r in cur.fetchall()}

                    # Map back to requested system names.
                    total_trades = 0
                    total_missing_links = 0
                    detail_parts = []
                    for requested in systems:
                        sys_norm = aliases.get(requested, requested)
                        t = totals.get(
                            sys_norm,
                            {"trades": 0, "missing_links": 0, "closed_trades": 0},
                        )
                        orphan_execs = orphan_rows.get(sys_norm, 0)
                        total_trades += t["trades"]
                        total_missing_links += t["missing_links"]
                        detail_parts.append(
                            f"{requested} trades={t['trades']} missing_links={t['missing_links']} "
                            f"closed={t['closed_trades']} orphan_execs={orphan_execs}"
                        )
                    details = "; ".join(detail_parts)

                    if total_trades == 0:
                        return CheckResult(
                            "TradeDB",
                            "WARN",
                            f"0 trades for {target_date} ET; order link mapping not validated",
                        )
                    if total_missing_links > 0:
                        return CheckResult(
                            "TradeDB",
                            "FAIL",
                            f"missing order links detected; {details}",
                        )
                    if any(orphan_rows.get(sys, 0) > 0 for sys in normalized_systems):
                        return CheckResult(
                            "TradeDB", "WARN", f"orphan executions detected; {details}"
                        )
                    return CheckResult("TradeDB", "OK", details)

                if not has_trades:
                    return CheckResult(
                        "TradeDB",
                        "FAIL",
                        "missing trades tables (neither v1 nor v2 found)",
                    )

                cur.execute(
                    """
                    SELECT
                        system,
                        COUNT(*) AS trades,
                        SUM(
                            CASE
                                WHEN entry_order_id IS NULL OR entry_order_id = 0
                                THEN 1
                                ELSE 0
                            END
                        ) AS missing_entry,
                        SUM(CASE WHEN status = 'CLOSED' THEN 1 ELSE 0 END) AS closed_trades,
                        SUM(
                            CASE
                                WHEN status = 'CLOSED'
                                     AND (exit_order_id IS NULL OR exit_order_id = 0)
                                THEN 1
                                ELSE 0
                            END
                        ) AS missing_exit
                    FROM trades
                    WHERE entry_time::date = %s
                    GROUP BY system
                    """,
                    (target_date.isoformat(),),
                )
                for row in cur.fetchall():
                    system = row[0]
                    if system not in summary:
                        continue
                    summary[system] = {
                        "trades": int(row[1]),
                        "missing_entry": int(row[2] or 0),
                        "closed_trades": int(row[3] or 0),
                        "missing_exit": int(row[4] or 0),
                    }
    except Exception as exc:
        return CheckResult("TradeDB", "FAIL", f"query failed: {exc}")
    finally:
        conn.close()

    total_trades = sum(data["trades"] for data in summary.values())
    total_missing_entry = sum(data["missing_entry"] for data in summary.values())
    total_missing_exit = sum(data["missing_exit"] for data in summary.values())

    detail_parts = [
        (
            f"{system} trades={data['trades']} missing_entry={data['missing_entry']}"
            f" closed={data['closed_trades']} missing_exit={data['missing_exit']}"
        )
        for system, data in summary.items()
    ]
    details = "; ".join(detail_parts)

    if total_trades == 0:
        return CheckResult(
            "TradeDB",
            "WARN",
            f"0 trades for {target_date} ET; order_id mapping not validated",
        )
    if total_missing_entry > 0 or total_missing_exit > 0:
        return CheckResult(
            "TradeDB",
            "FAIL",
            f"missing order IDs detected; {details}",
        )
    return CheckResult("TradeDB", "OK", details)


def _dir_stats(path: Path, now_et: datetime) -> tuple[int, float | None]:
    if not path.exists():
        return 0, None
    latest = None
    count = 0
    for file in path.rglob("*.parquet"):
        if not file.is_file():
            continue
        count += 1
        mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=ET)
        if latest is None or mtime > latest:
            latest = mtime
    if count == 0 or latest is None:
        return 0, None
    age_min = (now_et - latest).total_seconds() / 60
    return count, age_min


def _format_age(age_min: float | None) -> str:
    return "n/a" if age_min is None else f"{age_min:.1f}"


def check_l2_data(target_date: date, now_et: datetime) -> CheckResult:
    raw_dir = L2_BASE / "raw" / f"date={target_date.isoformat()}"
    features_dir = L2_BASE / "features" / f"date={target_date.isoformat()}"

    raw_count, raw_age = _dir_stats(raw_dir, now_et)
    feat_count, feat_age = _dir_stats(features_dir, now_et)

    failures = []
    warnings = []

    if not raw_dir.exists():
        failures.append(f"raw dir missing ({raw_dir})")
    elif raw_count == 0:
        failures.append("raw dir has no parquet files")
    elif raw_age is not None and raw_age > STALE_MINUTES:
        warnings.append(f"raw latest age {raw_age:.1f}m")

    if not features_dir.exists():
        failures.append(f"features dir missing ({features_dir})")
    elif feat_count == 0:
        failures.append("features dir has no parquet files")
    elif feat_age is not None and feat_age > STALE_MINUTES:
        warnings.append(f"features latest age {feat_age:.1f}m")

    details = (
        f"raw files={raw_count} age_min={_format_age(raw_age)}; "
        f"features files={feat_count} age_min={_format_age(feat_age)}"
    )

    if failures:
        return CheckResult("L2 Data", "FAIL", "; ".join(failures))
    if warnings:
        return CheckResult("L2 Data", "WARN", f"{details}; {', '.join(warnings)}")
    return CheckResult("L2 Data", "OK", details)


def _overall_status(results: Iterable[CheckResult]) -> str:
    if any(result.status == "FAIL" for result in results):
        return "FAIL"
    if any(result.status == "WARN" for result in results):
        return "WARN"
    return "OK"


def _priority_and_tags(overall: str) -> tuple[int, str]:
    if overall == "FAIL":
        return 4, "warning"
    if overall == "WARN":
        return 3, "warning"
    return 2, "status"


def main() -> int:
    parser = argparse.ArgumentParser(description="Market open recording checks")
    parser.add_argument(
        "--date",
        help="ET date in YYYY-MM-DD format (default: today ET)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    now_et = datetime.now(ET)
    target_date = now_et.date()
    if args.date:
        target_date = _parse_date(args.date)

    results = [
        check_audit_events(target_date, SYSTEMS, now_et),
        check_trade_db(target_date, SYSTEMS),
        check_l2_data(target_date, now_et),
    ]

    overall = _overall_status(results)
    priority, tags = _priority_and_tags(overall)

    lines = [
        f"Market Open Recording Checks ({now_et.strftime('%Y-%m-%d %H:%M ET')})",
        f"ET date: {target_date.isoformat()}",
        f"Overall: {overall}",
        "",
    ]
    lines.extend(result.line() for result in results)

    message = "\n".join(lines)
    try:
        send_status_message(message, priority=priority, tags=tags)
    except Exception as exc:  # pragma: no cover - notification failure
        logger.error("Failed to send NTFY status: %s", exc)

    print(message)
    return 1 if overall == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
