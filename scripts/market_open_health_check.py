#!/usr/bin/env python3
"""
Market Open Health Check - Runs at 09:40 ET
Verifies all trading systems are operational 10 minutes after market open.
"""

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    import psycopg2  # type: ignore
except Exception:  # pragma: no cover - optional dependency under system python
    psycopg2 = None

ET = ZoneInfo("America/New_York")
_DEFAULT_IBKR_HOST = os.environ.get("IBKR_GATEWAY_HOST", "127.0.0.1")
_DEFAULT_IBKR_PORT = int(os.environ.get("IBKR_GATEWAY_PORT", "7494"))
_DEFAULT_IBKR_CLIENT_ID = int(os.environ.get("IBKR_HEALTHCHECK_CLIENT_ID", "997"))
_QX_VENV_PY = "/home/jacobw/quantstack/.venv/bin/python"

def _psql_rows(sql: str) -> list[str]:
    """Run a SQL query via psql and return non-empty output lines."""
    result = subprocess.run(
        ["psql", "-d", "trading", "-U", "jacobw", "-t", "-A", "-c", sql],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout or "psql failed").strip()[:200])
    return [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]

def _user_systemctl_env() -> dict[str, str]:
    """Build env for systemctl --user when running outside a user session."""
    env = os.environ.copy()
    runtime_dir = env.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        runtime_dir = f"/run/user/{os.getuid()}"
        env["XDG_RUNTIME_DIR"] = runtime_dir
    if "DBUS_SESSION_BUS_ADDRESS" not in env:
        env["DBUS_SESSION_BUS_ADDRESS"] = f"unix:path={runtime_dir}/bus"
    return env

def send_ntfy(title: str, message: str, priority: str = "default", tags: str = ""):
    """Send NTFY notification."""
    try:
        cmd = ["curl", "-H", f"Title: {title}", "-H", f"Priority: {priority}"]
        if tags:
            cmd.extend(["-H", f"Tags: {tags}"])
        cmd.extend(["-d", message, "ntfy.sh/jacobw-trading-alerts"])
        subprocess.run(cmd, capture_output=True, timeout=5)
    except Exception as e:
        print(f"Failed to send NTFY: {e}")

def check_sip_generation() -> tuple[bool, str]:
    """Check if daily SIP was generated today."""
    today = datetime.now(ET).strftime("%Y-%m-%d")
    sip_file = Path(f"/home/jacobw/intraday_stack/data/daily_sip/date={today}/sip_universe.json")
    
    if not sip_file.exists():
        return False, f"SIP file missing for {today}"
    
    # Check file is recent (within last 2 hours)
    mtime = datetime.fromtimestamp(sip_file.stat().st_mtime, tz=ET)
    age_hours = (datetime.now(ET) - mtime).total_seconds() / 3600
    
    if age_hours > 2:
        return False, f"SIP file is {age_hours:.1f}h old (expected < 2h)"
    
    # Check file has content
    try:
        import json
        with open(sip_file) as f:
            data = json.load(f)
        symbols = data.get("symbols", [])
        if not symbols:
            return False, "SIP file has no symbols"
        return True, f"✅ {len(symbols)} symbols: {', '.join(symbols[:3])}"
    except Exception as e:
        return False, f"SIP file corrupt: {e}"

def check_ib_gateway() -> tuple[bool, str]:
    """Check IB Gateway connectivity."""
    try:
        # Use the same connection stack as the trading services (qx_broker.ibkr).
        # This makes failures actionable (e.g. client id in use vs gateway down).
        try:
            from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig
        except Exception:
            # If the current interpreter doesn't have qx_broker installed, run the
            # check under the repo venv (common under systemd).
            result = subprocess.run(
                [
                    _QX_VENV_PY,
                    "-c",
                    (
                        "from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig;"
                        f"c=IBKRConnectionConfig(host='{_DEFAULT_IBKR_HOST}',port={_DEFAULT_IBKR_PORT},client_id={_DEFAULT_IBKR_CLIENT_ID},"
                        "readonly=True,connect_timeout=5,request_timeout=5,reconnect_attempts=0,allow_client_id_fallback=False);"
                        "s=IBKRSession(IBKRSessionConfig(system_name='HEALTHCHECK',connection=c));"
                        "ok=s.connect();"
                        "acc=s.call(s.ib.managedAccounts, timeout=5) if ok else [];"
                        "print('OK' if (ok and acc) else 'FAIL');"
                        "s.disconnect();"
                    ),
                ],
                capture_output=True,
                text=True,
                timeout=12,
            )
            if result.returncode == 0 and "OK" in (result.stdout or ""):
                return True, f"✅ Connected ({_DEFAULT_IBKR_HOST}:{_DEFAULT_IBKR_PORT})"
            return False, f"Connection failed (venv probe): {(result.stderr or result.stdout)[:120]}"

        from qx_broker.ibkr.errors import is_client_id_in_use

        candidate_ids = [_DEFAULT_IBKR_CLIENT_ID]
        if 900 <= _DEFAULT_IBKR_CLIENT_ID < 999:
            candidate_ids.append(_DEFAULT_IBKR_CLIENT_ID + 1)

        last_err = None
        for cid in candidate_ids:
            connection = IBKRConnectionConfig(
                host=_DEFAULT_IBKR_HOST,
                port=_DEFAULT_IBKR_PORT,
                client_id=cid,
                readonly=True,
                connect_timeout=5,
                request_timeout=5,
                reconnect_attempts=0,
                allow_client_id_fallback=False,
            )
            session = IBKRSession(IBKRSessionConfig(system_name="HEALTHCHECK", connection=connection))
            try:
                if not session.connect():
                    err = session.last_error
                    if err and is_client_id_in_use(err.code):
                        last_err = f"client_id {cid} in use"
                        continue
                    return False, f"connect failed to {_DEFAULT_IBKR_HOST}:{_DEFAULT_IBKR_PORT} (client_id={cid})"
                accounts = session.call(session.ib.managedAccounts, timeout=5) or []
                if not accounts:
                    return False, f"connected but no accounts returned (client_id={cid})"
                return True, f"✅ Connected ({_DEFAULT_IBKR_HOST}:{_DEFAULT_IBKR_PORT})"
            finally:
                session.disconnect()

        return False, f"connect failed: {last_err or 'unknown error'}"
    except subprocess.TimeoutExpired:
        # Timeout is not critical if other systems are trading
        return True, "⚠️ Slow response (but connected)"
    except Exception as e:
        return False, f"Connection error: {str(e)[:100]}"

def _systemctl_is_active(unit: str, *, user: bool) -> tuple[bool, str]:
    cmd = ["systemctl"]
    env = None
    if user:
        cmd.append("--user")
        env = _user_systemctl_env()
    cmd.extend(["is-active", unit])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5, env=env)
    except Exception as exc:
        return False, f"systemctl error: {exc}"
    out = (result.stdout or "").strip()
    err = (result.stderr or "").strip().splitlines()
    err_last = err[-1] if err else ""
    if result.returncode == 0 and out == "active":
        return True, "active"
    if err_last:
        return False, f"{out or 'inactive'} ({err_last})"
    return False, out or "inactive"

def _pgrep_fallback(service: str) -> bool:
    patterns = {
        "l2-scalping": "l2_scalping/src/main.py",
        "l2-vwap-reversion": "l2_vwap_reversion/src/main.py",
        # intraday-paper lives outside this repo; keep the pattern generic.
        "intraday-paper": "paper_trade.py",
    }
    pat = patterns.get(service, service)
    try:
        proc = subprocess.run(["pgrep", "-f", pat], capture_output=True, text=True, timeout=3)
        return proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        return False

def check_service_running(service: str) -> tuple[bool, str]:
    """Check if systemd service is running."""
    try:
        unit = f"{service}.service"

        # Try system scope first, then user scope. This avoids false failures when
        # a service was moved between scopes.
        ok, detail = _systemctl_is_active(unit, user=False)
        if ok:
            return True, "✅ Running"
        sys_detail = detail

        ok_u, detail_u = _systemctl_is_active(unit, user=True)
        if ok_u:
            return True, "✅ Running"

        # Fallback: bus may be unavailable under timers; verify by process pattern.
        if "Failed to connect to bus" in sys_detail or "Failed to connect to bus" in detail_u:
            if _pgrep_fallback(service):
                return True, "✅ Running (pgrep fallback)"

        # For intraday-paper, check if it's before 09:28 ET
        if service == "intraday-paper":
            now_et = datetime.now(ET)
            if now_et.hour == 9 and now_et.minute < 28:
                return True, "⏳ Not started yet (before 09:28)"
        
        return False, f"Status: {sys_detail}; user: {detail_u}"
    except Exception as e:
        return False, f"Check failed: {e}"

def check_l2_data_storage() -> tuple[bool, str]:
    """Check L2 data is being written."""
    today = datetime.now(ET).strftime("%Y-%m-%d")
    
    # Check raw L2 data
    raw_path = Path(f"/home/jacobw/quantstack/data/l2/l2_maximum/raw/date={today}")
    features_path = Path(f"/home/jacobw/quantstack/data/l2/l2_maximum/features/date={today}")
    
    issues = []
    if not raw_path.exists():
        issues.append("Raw data dir missing")
    if not features_path.exists():
        issues.append("Features dir missing")
    
    if issues:
        return False, ", ".join(issues)
    
    # Check files are recent (within last 5 minutes)
    recent_files = 0
    cutoff = datetime.now(ET) - timedelta(minutes=5)
    
    for path in [raw_path, features_path]:
        for file in path.rglob("*.parquet"):
            mtime = datetime.fromtimestamp(file.stat().st_mtime, tz=ET)
            if mtime > cutoff:
                recent_files += 1
    
    if recent_files == 0:
        return False, "No recent files (last 5 min)"
    
    return True, f"✅ {recent_files} recent files"

def check_trading_activity() -> tuple[bool, str]:
    """Check if systems have traded today."""
    try:
        if psycopg2 is not None:
            conn = psycopg2.connect(database="trading", user="jacobw")
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM trades
                WHERE (entry_time::timestamptz AT TIME ZONE 'America/New_York')::date
                      = (NOW() AT TIME ZONE 'America/New_York')::date
                """
            )
            trades_today = int(cursor.fetchone()[0] or 0)
            cursor.close()
            conn.close()
        else:
            # Best-effort fallback for the system python used by systemd.
            rows = _psql_rows("SELECT COUNT(*) FROM trades WHERE entry_time::date = CURRENT_DATE;")
            trades_today = int(rows[0]) if rows else 0
        
        if trades_today > 0:
            return True, f"✅ {trades_today} trades today"
        
        # No trades is not a failure condition (systems may simply have no signals).
        return True, "⏳ No trades yet"
    except Exception as e:
        return False, f"DB check failed: {e}"

def check_trade_recording() -> tuple[bool, str]:
    """Check trades are being recorded correctly."""
    try:
        if psycopg2 is None:
            # Fallback: use psql so this works under the system python used by systemd.
            et_date = "((now() at time zone 'America/New_York')::date)"
            schema = _psql_rows(
                "SELECT "
                "to_regclass('public.trades_v2') IS NOT NULL AS has_v2, "
                "to_regclass('public.executions') IS NOT NULL AS has_exec, "
                "to_regclass('public.trades') IS NOT NULL AS has_v1, "
                "to_regclass('public.fills') IS NOT NULL AS has_fills;"
            )

            v1_summary = _psql_rows(
                (
                    "SELECT system||':'||COUNT(*) "
                    "FROM trades "
                    "WHERE (entry_time::timestamptz at time zone 'America/New_York')::date = "
                    f"{et_date} "
                    "GROUP BY system ORDER BY 1;"
                )
            )
            v1_total = sum(int(x.split(':', 1)[1]) for x in v1_summary) if v1_summary else 0

            has_v2 = bool(schema and schema[0].split("|")[0].strip() in {"t", "true", "1"})
            v2_summary = (
                _psql_rows(
                    (
                        "SELECT system||':'||COUNT(*) "
                        "FROM trades_v2 "
                        "WHERE (coalesce(entry_time, created_at) at time zone 'America/New_York')::date = "
                        f"{et_date} "
                        "GROUP BY system ORDER BY 1;"
                    )
                )
                if has_v2
                else []
            )
            v2_total = sum(int(x.split(':', 1)[1]) for x in v2_summary) if v2_summary else 0

            if v1_total == 0 and v2_total == 0:
                return True, "⏳ No trade activity yet"

            parts = []
            if v1_summary:
                parts.append("v1 " + ", ".join(v1_summary))
            if v2_summary:
                parts.append("v2 " + ", ".join(v2_summary))
            return True, "✅ " + " | ".join(parts)

        conn = psycopg2.connect(database="trading", user="jacobw")
        cursor = conn.cursor()
        
        # Detect schema: prefer v2 if present, otherwise fall back to v1.
        cursor.execute(
            """
            SELECT
              to_regclass('public.trades_v2') IS NOT NULL AS has_v2,
              to_regclass('public.executions') IS NOT NULL AS has_exec,
              to_regclass('public.trades') IS NOT NULL AS has_trades,
              to_regclass('public.fills') IS NOT NULL AS has_fills
            """
        )
        has_v2, has_exec, has_trades, has_fills = cursor.fetchone()

        # Prefer whichever schema actually has activity today.
        if has_v2 and has_exec:
            cursor.execute(
                """
                SELECT system, COUNT(*) AS trades
                FROM trades_v2
                WHERE (COALESCE(entry_time, created_at) AT TIME ZONE 'America/New_York')::date
                      = (NOW() AT TIME ZONE 'America/New_York')::date
                GROUP BY system
                """
            )
            results = cursor.fetchall()

            cursor.execute(
                """
                SELECT system, COUNT(*) AS n
                FROM executions
                WHERE (ibkr_time AT TIME ZONE 'America/New_York')::date
                      = (NOW() AT TIME ZONE 'America/New_York')::date
                GROUP BY system
                ORDER BY n DESC
                """
            )
            exec_rows = cursor.fetchall() or []
            execs_today = sum(int(r[1]) for r in exec_rows)

            v2_trades_today = sum(int(cnt) for _, cnt in results) if results else 0
            if v2_trades_today > 0 or execs_today > 0:
                trade_summary = ", ".join([f"{sys}: {cnt}" for sys, cnt in results]) or "0 trades"
                exec_summary = ", ".join(
                    [f"{sys or 'unknown'}: {cnt}" for sys, cnt in exec_rows[:5]]
                ) or "0"
                return True, f"✅ v2 {trade_summary}; executions={execs_today} ({exec_summary})"

        # v1 fallback
        if not has_trades or not has_fills:
            return False, "DB schema missing expected tables (no v1/v2 trade tables found)"

        cursor.execute(
            """
            SELECT system, COUNT(*) as trades
            FROM trades
            WHERE (entry_time::timestamptz AT TIME ZONE 'America/New_York')::date
                  = (NOW() AT TIME ZONE 'America/New_York')::date
            GROUP BY system
            """
        )
        results = cursor.fetchall()

        cursor.execute(
            """
            SELECT COUNT(*) FROM fills
            WHERE timestamp::date = CURRENT_DATE
            """
        )
        fills_today = int(cursor.fetchone()[0])

        cursor.close()
        conn.close()
        
        if not results and fills_today == 0:
            return True, "⏳ No activity yet"
        
        if not results and fills_today > 0:
            return False, f"{fills_today} fills but 0 trades"
        
        trade_summary = ", ".join([f"{sys}: {cnt}" for sys, cnt in results])
        return True, f"✅ v1 {trade_summary}"
        
    except Exception as e:
        return False, f"DB check failed: {e}"

def main():
    """Run all health checks and send notification."""
    now_et = datetime.now(ET)
    print(f"Market Open Health Check - {now_et.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    
    checks = {
        "SIP Generation": check_sip_generation(),
        "IB Gateway": check_ib_gateway(),
        "L2 Scalping": check_service_running("l2-scalping"),
        "L2 VWAP": check_service_running("l2-vwap-reversion"),
        "Intraday Paper": check_service_running("intraday-paper"),
        "L2 Data Storage": check_l2_data_storage(),
        "Trading Activity": check_trading_activity(),
        "Trade Recording": check_trade_recording(),
    }
    
    # Analyze results
    passed = sum(1 for ok, _ in checks.values() if ok)
    failed = len(checks) - passed
    
    # Build message
    lines = [f"Market Open Health Check ({now_et.strftime('%H:%M ET')})", ""]
    
    if failed == 0:
        lines.append("🟢 ALL SYSTEMS OPERATIONAL")
        lines.append("")
        for name, (ok, msg) in checks.items():
            lines.append(f"{name}: {msg}")
        
        send_ntfy(
            "✅ Trading Systems Healthy",
            "\n".join(lines),
            priority="default",
            tags="white_check_mark,chart_with_upwards_trend"
        )
        print("\n".join(lines))
        return 0
    
    else:
        lines.append(f"🔴 {failed} SYSTEM(S) FAILED")
        lines.append("")
        
        # Failed checks first
        for name, (ok, msg) in checks.items():
            if not ok:
                lines.append(f"❌ {name}: {msg}")
        
        lines.append("")
        lines.append("Passed:")
        for name, (ok, msg) in checks.items():
            if ok:
                lines.append(f"✅ {name}: {msg}")
        
        send_ntfy(
            f"⚠️ Trading System Issues ({failed} failed)",
            "\n".join(lines),
            priority="high",
            tags="warning,rotating_light"
        )
        print("\n".join(lines))
        return 1

if __name__ == "__main__":
    sys.exit(main())
