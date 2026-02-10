#!/usr/bin/env python3
"""
Pre-Flight System Validation

Runs before SIP generation (09:00 ET) to validate critical infrastructure.
Checks: Gateway process, Gateway authentication, Polygon API
"""

import os
import subprocess
import sys
from datetime import datetime

ERRORS = []


def send_ntfy(title: str, message: str, priority: str = "high", tags: str = "warning"):
    """Send NTFY notification."""
    import urllib.request

    try:
        safe_title = title.encode("ascii", "ignore").decode("ascii") or "Pre-Flight"
        req = urllib.request.Request(
            "https://ntfy.sh/jacobw-trading-alerts",
            data=message.encode("utf-8"),
            headers={"Title": safe_title, "Priority": priority, "Tags": tags},
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"NTFY failed: {e}")


def test(name: str, func) -> bool:
    """Run test and track errors."""
    try:
        func()
        return True
    except Exception as e:
        ERRORS.append(f"{name}: {e}")
        return False


def check_gateway_process():
    """Check if IBKR Gateway is running."""
    for pattern in ("ibgateway", "tws"):
        result = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
        if result.returncode == 0:
            return
    raise RuntimeError("IBKR Gateway process not running")


def check_gateway_auth():
    """Check if IBKR Gateway is authenticated."""
    from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig
    from qx_broker.ibkr.errors import is_client_id_in_use

    host = os.environ.get("IBKR_GATEWAY_HOST", "127.0.0.1")
    # Paper gateway default is 7494 (and this is the repo-wide default elsewhere).
    # Keep override via IBKR_GATEWAY_PORT for non-standard setups.
    port = int(os.environ.get("IBKR_GATEWAY_PORT", "7494"))
    client_id = int(os.environ.get("IBKR_PREFLIGHT_CLIENT_ID", "998"))

    # Client ID collisions are common (Gateway caches IDs). Preflight is read-only, so it's
    # safe to try a tiny fallback within the utilities range to avoid false failures.
    candidate_ids: list[int] = [client_id]
    if 900 <= client_id < 999:
        candidate_ids.append(client_id + 1)
    last_exc: Exception | None = None

    for cid in candidate_ids:
        connection = IBKRConnectionConfig(
            host=host,
            port=port,
            client_id=cid,
            readonly=True,
            connect_timeout=5,
            request_timeout=5,
            reconnect_attempts=0,
            allow_client_id_fallback=False,
        )
        session_cfg = IBKRSessionConfig(system_name="PREFLIGHT", connection=connection)
        session = IBKRSession(session_cfg)

        try:
            if not session.connect():
                err = session.last_error
                if err and is_client_id_in_use(err.code):
                    last_exc = RuntimeError(f"client_id {cid} in use")
                    continue
                raise RuntimeError(f"Cannot connect to IBKR Gateway (client_id={cid})")

            accounts = session.call(session.ib.managedAccounts, timeout=5) or []
            if not accounts:
                raise RuntimeError(f"No accounts available from IBKR Gateway (client_id={cid})")
            return
        except Exception as exc:
            last_exc = exc
        finally:
            session.disconnect()

    raise RuntimeError(f"Gateway check failed: {last_exc}")


def check_polygon():
    """Check Polygon API connectivity."""
    import urllib.request

    api_key = os.getenv("POLYGON_API_KEY")
    if not api_key:
        raise RuntimeError("POLYGON_API_KEY not set")

    url = (
        "https://api.polygon.io/v2/aggs/ticker/AAPL/range/1/day/2023-01-01/2023-01-02"
        f"?apiKey={api_key}"
    )
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=10) as response:
        if response.status != 200:
            raise RuntimeError(f"Polygon API returned {response.status}")


def main():
    print(f"Pre-flight validation: {datetime.now().isoformat()}")

    # Critical infrastructure checks only
    tests = [
        ("Gateway process", check_gateway_process),
        ("Gateway authenticated", check_gateway_auth),
        ("Polygon API", check_polygon),
    ]

    for name, func in tests:
        if test(name, func):
            print(f"  ✅ {name}")
        else:
            print(f"  ❌ {name}")

    if ERRORS:
        msg = (
            f"Pre-flight FAILED at {datetime.now().strftime('%H:%M ET')}:\n"
            + "\n".join(ERRORS[:5])
        )
        send_ntfy("⚠️ Pre-Flight FAILED", msg, priority="urgent", tags="rotating_light")
        print(f"\n❌ {len(ERRORS)} ERRORS - NTFY alert sent")
        return 1
    else:
        print(f"\n✅ All pre-flight checks passed")
        return 0


if __name__ == "__main__":
    sys.exit(main())
