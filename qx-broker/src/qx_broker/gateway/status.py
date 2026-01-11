from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from qx_broker.gateway.config import GatewayConfig


@dataclass(frozen=True)
class StatusReport:
    ok: bool
    maintenance: bool
    message: str


def should_check_status(now: datetime | None = None) -> bool:
    et = ZoneInfo("America/New_York")
    current = now or datetime.now(et)
    if current.weekday() >= 5:
        return True
    market_open = time(8, 30)
    market_close = time(17, 0)
    return not (market_open <= current.time() <= market_close)


def fetch_status(config: GatewayConfig) -> StatusReport:
    if not should_check_status():
        return StatusReport(
            ok=True,
            maintenance=False,
            message="Skipped status check during ET trading hours.",
        )

    request = Request(config.status_url, headers={"User-Agent": "quantstack-gateway"})
    try:
        with urlopen(request, timeout=10) as response:
            content = response.read().decode("utf-8", errors="ignore")
    except Exception as exc:
        return StatusReport(
            ok=False,
            maintenance=False,
            message=f"Status page unreachable: {exc}",
        )

    lowered = content.lower()
    for keyword in config.status_keywords:
        if keyword.lower() in lowered:
            return StatusReport(
                ok=True,
                maintenance=True,
                message=f"Status indicates maintenance: matched '{keyword}'.",
            )

    return StatusReport(ok=True, maintenance=False, message="Status page ok.")
