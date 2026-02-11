#!/usr/bin/env python3
"""
Ops check + minimal auto-fix loop (single round).

Designed for non-interactive runs (systemd-run). It will:
- check critical services (system + user)
- probe IBKR gateway (readonly connection)
- sanity check DB activity (trades + executions)
- check WAL growth (fill WAL file line-count delta)
- attempt safe fixes (restart services only when clearly down)

It will also send an NTFY notification (best-effort).
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

REPO_ROOT = Path("/home/jacobw/quantstack")
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

STATE_DIR = Path.home() / ".quantstack" / "ops_checks"
STATE_PATH = STATE_DIR / "state.json"


@dataclass(frozen=True)
class CheckResult:
    ok: bool
    msg: str
    fixed: bool = False


def _run(
    cmd: list[str], *, timeout: int = 12, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def _user_systemctl_env() -> dict[str, str]:
    env = os.environ.copy()
    runtime_dir = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    env["XDG_RUNTIME_DIR"] = runtime_dir
    env.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path={runtime_dir}/bus")
    return env


def _systemctl_is_active(unit: str, *, user: bool) -> tuple[bool, str]:
    cmd = ["systemctl"]
    env = None
    if user:
        cmd.append("--user")
        env = _user_systemctl_env()
    cmd.extend(["is-active", unit])
    try:
        proc = _run(cmd, timeout=6, env=env)
    except Exception as exc:
        return False, f"systemctl error: {exc}"
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode == 0 and out == "active":
        return True, "active"
    detail = out or "inactive"
    if err:
        detail += f" ({err.splitlines()[-1]})"
    return False, detail


def _restart_unit(unit: str, *, user: bool) -> tuple[bool, str]:
    cmd = ["systemctl"]
    env = None
    if user:
        cmd.append("--user")
        env = _user_systemctl_env()
    cmd.extend(["restart", unit])
    try:
        proc = _run(cmd, timeout=45, env=env)
    except Exception as exc:
        return False, f"restart error: {exc}"
    if proc.returncode == 0:
        return True, "restarted"
    msg = (proc.stderr or proc.stdout or "restart failed").strip().splitlines()[-1]
    return False, msg[:200]


def _pgrep(pattern: str) -> bool:
    try:
        proc = _run(["pgrep", "-f", pattern], timeout=4)
        return proc.returncode == 0 and bool((proc.stdout or "").strip())
    except Exception:
        return False


def _psql_scalar(sql: str) -> int:
    proc = _run(
        ["psql", "-d", "trading", "-U", "jacobw", "-t", "-A", "-c", sql],
        timeout=12,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "psql failed").strip()[:200])
    out = (proc.stdout or "").strip()
    return int(out) if out else 0


def _psql_kv(sql: str) -> list[tuple[str, int]]:
    proc = _run(
        ["psql", "-d", "trading", "-U", "jacobw", "-t", "-A", "-F", "|", "-c", sql],
        timeout=12,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "psql failed").strip()[:200])
    rows: list[tuple[str, int]] = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line or "|" not in line:
            continue
        k, v = line.split("|", 1)
        try:
            rows.append((k.strip(), int(v.strip())))
        except ValueError:
            continue
    return rows


def _today_et_sql_date_expr() -> str:
    return "((now() at time zone 'America/New_York')::date)"


def _ib_gateway_probe() -> CheckResult:
    host = os.environ.get("IBKR_GATEWAY_HOST", "127.0.0.1")
    port = int(os.environ.get("IBKR_GATEWAY_PORT", "7494"))
    client_id = int(os.environ.get("IBKR_HEALTHCHECK_CLIENT_ID", "997"))

    try:
        from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig
        from qx_broker.ibkr.errors import is_client_id_in_use
    except Exception as exc:
        return CheckResult(False, f"qx_broker import failed: {exc}")

    candidate_ids = [client_id]
    if 900 <= client_id < 999:
        candidate_ids.append(client_id + 1)

    last_err = None
    for cid in candidate_ids:
        session = IBKRSession(
            IBKRSessionConfig(
                system_name="OPS_CHECK",
                connection=IBKRConnectionConfig(
                    host=host,
                    port=port,
                    client_id=cid,
                    readonly=True,
                    connect_timeout=5,
                    request_timeout=5,
                    reconnect_attempts=0,
                    allow_client_id_fallback=False,
                ),
            )
        )
        try:
            if not session.connect():
                err = session.last_error
                if err and is_client_id_in_use(err.code):
                    last_err = f"client_id {cid} in use"
                    continue
                return CheckResult(
                    False, f"connect failed to {host}:{port} (client_id={cid})"
                )
            accounts = session.call(session.ib.managedAccounts, timeout=5) or []
            if not accounts:
                return CheckResult(
                    False, f"connected but no accounts returned (client_id={cid})"
                )
            return CheckResult(True, f"connected {host}:{port} (client_id={cid})")
        except Exception as exc:
            last_err = str(exc)[:120]
        finally:
            try:
                session.disconnect()
            except Exception:
                pass

    return CheckResult(False, f"connect failed: {last_err or 'unknown'}")


def _wal_growth_check() -> CheckResult:
    wal_dir = REPO_ROOT / "logs" / "wal"
    wal_path = wal_dir / f"fills_{datetime.now(timezone.utc).strftime('%Y%m%d')}.jsonl"
    if not wal_path.exists():
        return CheckResult(True, "no WAL file yet")

    try:
        proc = _run(["wc", "-l", str(wal_path)], timeout=10)
        if proc.returncode != 0:
            return CheckResult(
                False, f"wc failed: {(proc.stderr or proc.stdout)[:120]}"
            )
        n = int((proc.stdout or "0").strip().split()[0])
    except Exception as exc:
        return CheckResult(False, f"WAL check failed: {exc}")

    last_n = None
    try:
        if STATE_PATH.exists():
            last_n = int(json.loads(STATE_PATH.read_text()).get("wal_lines", 0))
    except Exception:
        last_n = None

    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps({"wal_lines": n}, indent=2, sort_keys=True))
    except Exception:
        pass

    if last_n is None:
        return CheckResult(True, f"WAL lines={n}")

    delta = n - last_n
    if delta <= 0:
        return CheckResult(True, f"WAL stable (lines={n}, delta={delta})")
    # If dedup is working, growth should be low unless there are new executions.
    if delta > 5000:
        return CheckResult(
            False, f"WAL growing fast (lines={n}, +{delta} since last check)"
        )
    return CheckResult(True, f"WAL growth OK (lines={n}, +{delta})")


def _service_check_and_fix(name: str) -> CheckResult:
    # Map to unit + fallback pgrep pattern.
    unit_map: dict[str, tuple[str, bool, str]] = {
        "l2-scalping": ("l2-scalping.service", False, "l2_scalping/src/main.py"),
        "intraday-paper": ("intraday-paper.service", False, "paper_trade.py"),
        "l2-vwap-reversion": (
            "l2-vwap-reversion.service",
            True,
            "l2_vwap_reversion/src/main.py",
        ),
    }
    unit, is_user, pat = unit_map[name]
    ok, detail = _systemctl_is_active(unit, user=is_user)
    if ok:
        # Lightweight sanity: ensure the expected process exists.
        if not _pgrep(pat):
            # It's running but we can't find the process: likely a false positive or wrapper only.
            return CheckResult(False, f"{unit} active but process missing: {pat}")
        return CheckResult(True, "running")

    # Attempt restart as the only automatic fix. Safe and reversible.
    restarted, rmsg = _restart_unit(unit, user=is_user)
    if restarted:
        ok2, detail2 = _systemctl_is_active(unit, user=is_user)
        if ok2 and _pgrep(pat):
            return CheckResult(True, f"was {detail}; fixed via restart", fixed=True)
        return CheckResult(False, f"restart issued but still {detail2}", fixed=True)

    return CheckResult(False, f"{detail}; restart failed: {rmsg}")


def _db_activity_check() -> CheckResult:
    try:
        et_date = _today_et_sql_date_expr()
        v1 = _psql_kv(
            "SELECT COALESCE(system, 'unknown') AS system, COUNT(*)::int "
            "FROM trades "
            f"WHERE (entry_time::timestamptz AT TIME ZONE 'America/New_York')::date = {et_date} "
            "GROUP BY 1 ORDER BY 2 DESC;"
        )
        execs = _psql_kv(
            "SELECT COALESCE(system, 'unknown') AS system, COUNT(*)::int "
            "FROM executions "
            "WHERE ibkr_time > now() - interval '15 minutes' "
            "GROUP BY 1 ORDER BY 2 DESC;"
        )
        parts = []
        if v1:
            parts.append("trades=" + ", ".join([f"{k}:{v}" for k, v in v1[:5]]))
        else:
            parts.append("trades=0")
        if execs:
            parts.append("exec15m=" + ", ".join([f"{k}:{v}" for k, v in execs[:5]]))
        else:
            parts.append("exec15m=0")
        return CheckResult(True, " | ".join(parts))
    except Exception as exc:
        return CheckResult(False, f"db check failed: {exc}")


def _send_ntfy(
    title: str, message: str, *, priority: str = "default", tags: str = ""
) -> None:
    # Best-effort: avoid failing the run if ntfy is down.
    try:
        cmd = ["curl", "-H", f"Title: {title}", "-H", f"Priority: {priority}"]
        if tags:
            cmd.extend(["-H", f"Tags: {tags}"])
        cmd.extend(["-d", message, "ntfy.sh/jacobw-trading-alerts"])
        _run(cmd, timeout=6)
    except Exception:
        return


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--round", type=int, default=0)
    parser.add_argument("--scheduled-after-minutes", type=int, default=0)
    args = parser.parse_args()

    now_et = datetime.now(ET)
    header = f"Ops Check {args.round or ''} @ {now_et.strftime('%Y-%m-%d %H:%M:%S ET')}".strip()
    lines: list[str] = [header, ""]

    checks: list[tuple[str, CheckResult]] = []

    # Connectivity and core services
    checks.append(("IB Gateway", _ib_gateway_probe()))
    for svc in ["l2-scalping", "intraday-paper", "l2-vwap-reversion"]:
        checks.append((svc, _service_check_and_fix(svc)))

    # Data/recording signals
    checks.append(("DB Activity", _db_activity_check()))
    checks.append(("WAL Growth", _wal_growth_check()))

    failed = [(name, res) for name, res in checks if not res.ok]
    fixed = [(name, res) for name, res in checks if res.fixed]

    if not failed:
        lines.append("OK: all checks passed")
        lines.append("")
        for name, res in checks:
            suffix = " (fixed)" if res.fixed else ""
            lines.append(f"✅ {name}: {res.msg}{suffix}")
        _send_ntfy(
            "✅ Ops Check OK",
            "\n".join(lines),
            priority="default",
            tags="white_check_mark",
        )
        print("\n".join(lines))
        return 0

    lines.append(f"FAILED: {len(failed)} check(s) failed")
    if fixed:
        lines.append(f"Auto-fixes attempted: {', '.join([n for n, _ in fixed])}")
    lines.append("")
    for name, res in failed:
        suffix = " (fixed attempted)" if res.fixed else ""
        lines.append(f"❌ {name}: {res.msg}{suffix}")
    lines.append("")
    lines.append("All checks:")
    for name, res in checks:
        icon = "✅" if res.ok else "❌"
        suffix = (
            " (fixed)"
            if res.fixed and res.ok
            else " (fix attempted)" if res.fixed else ""
        )
        lines.append(f"{icon} {name}: {res.msg}{suffix}")

    _send_ntfy(
        "⚠️ Ops Check Issues",
        "\n".join(lines),
        priority="high",
        tags="warning,rotating_light",
    )
    print("\n".join(lines))
    return 1


if __name__ == "__main__":
    sys.exit(main())
