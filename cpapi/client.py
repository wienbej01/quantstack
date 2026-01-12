"""
IBKR Client Portal API v1.0 REST Client.

Based on official IBKR Campus documentation:
https://www.interactivebrokers.com/campus/ibkr-api-page/cpapi-v1/

Key characteristics:
- REST-based (no socket connections)
- Base URL: https://localhost:5000/v1/api
- Session timeout: ~6 minutes without activity
- Tickle endpoint must be called every ~60 seconds
- 10 req/s global pacing limit
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

import requests
import urllib3

# Suppress SSL warnings for localhost self-signed cert
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


@dataclass
class CPAPIConfig:
    """Configuration for Client Portal API."""

    base_url: str = "https://localhost:5000/v1/api"
    tickle_interval: int = 55  # seconds (doc says ~60s)
    request_timeout: int = 30
    verify_ssl: bool = False  # Gateway uses self-signed cert


@dataclass
class SessionState:
    """Track session state."""

    authenticated: bool = False
    connected: bool = False
    competing: bool = False
    accounts: list = field(default_factory=list)
    selected_account: str = ""
    last_tickle: float = 0.0


class CPAPIClient:
    """
    IBKR Client Portal API v1.0 REST Client.

    Usage:
        client = CPAPIClient()
        if client.check_auth_status():
            accounts = client.get_accounts()
            # ... use API
        client.stop()
    """

    def __init__(self, config: CPAPIConfig | None = None, client_id: str = "default"):
        self.config = config or CPAPIConfig()
        self.client_id = client_id
        self.state = SessionState()
        self._session = requests.Session()
        self._tickle_thread: threading.Thread | None = None
        self._stop_tickle = threading.Event()

    def _request(self, method: str, endpoint: str, **kwargs) -> dict | list | None:
        """Make HTTP request to CPAPI."""
        url = f"{self.config.base_url}{endpoint}"
        kwargs.setdefault("timeout", self.config.request_timeout)
        kwargs.setdefault("verify", self.config.verify_ssl)

        try:
            resp = self._session.request(method, url, **kwargs)
            if resp.status_code == 200:
                return resp.json() if resp.text else {}
            elif resp.status_code == 429:
                logger.warning(f"[{self.client_id}] Rate limited (429)")
                return None
            else:
                logger.error(
                    f"[{self.client_id}] {method} {endpoint} -> {resp.status_code}: {resp.text[:200]}"
                )
                return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[{self.client_id}] Request failed: {e}")
            return None

    # === Session Management ===

    def check_auth_status(self) -> bool:
        """Check authentication status. POST /iserver/auth/status"""
        data = self._request("POST", "/iserver/auth/status", json={})
        if data:
            self.state.authenticated = data.get("authenticated", False)
            self.state.connected = data.get("connected", False)
            self.state.competing = data.get("competing", False)
            logger.info(
                f"[{self.client_id}] Auth: authenticated={self.state.authenticated}, connected={self.state.connected}"
            )
            return self.state.authenticated
        return False

    def init_brokerage_session(self, compete: bool = True) -> bool:
        """Initialize brokerage session. POST /iserver/auth/ssodh/init"""
        data = self._request(
            "POST",
            "/iserver/auth/ssodh/init",
            json={"publish": True, "compete": compete},
        )
        if data:
            self.state.authenticated = data.get("authenticated", False)
            logger.info(
                f"[{self.client_id}] Brokerage session initialized: {self.state.authenticated}"
            )
            return self.state.authenticated
        return False

    def tickle(self) -> dict | None:
        """Ping server to keep session alive. POST /tickle"""
        data = self._request("POST", "/tickle", json={})
        if data:
            self.state.last_tickle = time.time()
            # Update auth status from tickle response
            iserver = data.get("iserver", {}).get("authStatus", {})
            self.state.authenticated = iserver.get(
                "authenticated", self.state.authenticated
            )
            self.state.connected = iserver.get("connected", self.state.connected)
        return data

    def start_tickle_thread(self):
        """Start background thread to keep session alive."""
        if self._tickle_thread and self._tickle_thread.is_alive():
            return
        self._stop_tickle.clear()
        self._tickle_thread = threading.Thread(target=self._tickle_loop, daemon=True)
        self._tickle_thread.start()
        logger.info(f"[{self.client_id}] Tickle thread started")

    def _tickle_loop(self):
        """Background tickle loop."""
        while not self._stop_tickle.wait(self.config.tickle_interval):
            self.tickle()

    def stop(self):
        """Stop tickle thread and cleanup."""
        self._stop_tickle.set()
        if self._tickle_thread:
            self._tickle_thread.join(timeout=2)
        logger.info(f"[{self.client_id}] Stopped")

    def logout(self) -> bool:
        """Logout from session. POST /logout"""
        data = self._request("POST", "/logout", json={})
        if data and data.get("status"):
            self.state.authenticated = False
            logger.info(f"[{self.client_id}] Logged out")
            return True
        return False

    # === Accounts ===

    def get_accounts(self) -> list[str]:
        """
        Get brokerage accounts. GET /iserver/accounts
        MUST be called before other /iserver endpoints.
        """
        data = self._request("GET", "/iserver/accounts")
        if data:
            self.state.accounts = data.get("accounts", [])
            self.state.selected_account = data.get("selectedAccount", "")
            logger.info(f"[{self.client_id}] Accounts: {self.state.accounts}")
            return self.state.accounts
        return []

    def switch_account(self, account_id: str) -> bool:
        """Switch active account. POST /iserver/account"""
        data = self._request("POST", "/iserver/account", json={"acctId": account_id})
        if data and data.get("set"):
            self.state.selected_account = account_id
            logger.info(f"[{self.client_id}] Switched to account: {account_id}")
            return True
        return False

    # === Portfolio ===

    def get_portfolio_accounts(self) -> list[dict]:
        """Get portfolio accounts. GET /portfolio/accounts"""
        return self._request("GET", "/portfolio/accounts") or []

    def get_positions(self, account_id: str, page: int = 0) -> list[dict]:
        """Get positions. GET /portfolio/{accountId}/positions/{pageId}"""
        return self._request("GET", f"/portfolio/{account_id}/positions/{page}") or []

    def get_portfolio_summary(self, account_id: str) -> dict:
        """Get portfolio summary. GET /portfolio/{accountId}/summary"""
        return self._request("GET", f"/portfolio/{account_id}/summary") or {}

    def get_account_pnl(self) -> dict:
        """Get account P&L. GET /iserver/account/pnl/partitioned"""
        return self._request("GET", "/iserver/account/pnl/partitioned") or {}

    # === Market Data ===

    def get_market_snapshot(
        self, conids: list[int], fields: list[str] | None = None
    ) -> list[dict]:
        """
        Get market data snapshot. GET /iserver/marketdata/snapshot
        Max 100 conids, 50 fields per request.
        """
        params = {"conids": ",".join(map(str, conids))}
        if fields:
            params["fields"] = ",".join(fields)
        return self._request("GET", "/iserver/marketdata/snapshot", params=params) or []

    def get_historical_data(
        self,
        conid: int,
        period: str = "1d",
        bar: str = "1min",
        exchange: str | None = None,
        outside_rth: bool = False,
    ) -> dict:
        """
        Get historical market data. GET /iserver/marketdata/history
        Max 5 concurrent requests.
        """
        params = {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outsideRth": outside_rth,
        }
        if exchange:
            params["exchange"] = exchange
        return self._request("GET", "/iserver/marketdata/history", params=params) or {}

    def unsubscribe_all_market_data(self) -> bool:
        """Unsubscribe from all market data. GET /iserver/marketdata/unsubscribeall"""
        data = self._request("GET", "/iserver/marketdata/unsubscribeall")
        return data.get("unsubscribed", False) if data else False

    # === Contract Search ===

    def search_contract(self, symbol: str, sec_type: str = "STK") -> list[dict]:
        """Search contract by symbol. GET /iserver/secdef/search"""
        params = {"symbol": symbol, "secType": sec_type}
        return self._request("GET", "/iserver/secdef/search", params=params) or []

    def get_contract_info(self, conid: int) -> dict:
        """Get contract info. GET /iserver/contract/{conid}/info"""
        return self._request("GET", f"/iserver/contract/{conid}/info") or {}

    # === Orders ===

    def get_live_orders(
        self, filters: list[str] | None = None, force: bool = False
    ) -> dict:
        """Get live orders. GET /iserver/account/orders"""
        params = {}
        if filters:
            params["filters"] = ",".join(filters)
        if force:
            params["force"] = "true"
        return self._request("GET", "/iserver/account/orders", params=params) or {}

    def get_trades(self, days: int = 1) -> list[dict]:
        """Get trades. GET /iserver/account/trades"""
        return (
            self._request("GET", "/iserver/account/trades", params={"days": days}) or []
        )

    def place_order(self, account_id: str, orders: list[dict]) -> list[dict]:
        """
        Place order. POST /iserver/account/{accountId}/orders
        May return reply ID requiring confirmation.
        """
        return (
            self._request(
                "POST", f"/iserver/account/{account_id}/orders", json={"orders": orders}
            )
            or []
        )

    def confirm_order(self, reply_id: str, confirmed: bool = True) -> list[dict]:
        """Confirm order reply. POST /iserver/reply/{replyId}"""
        return (
            self._request(
                "POST", f"/iserver/reply/{reply_id}", json={"confirmed": confirmed}
            )
            or []
        )

    def cancel_order(self, account_id: str, order_id: str) -> dict:
        """Cancel order. DELETE /iserver/account/{accountId}/order/{orderId}"""
        return (
            self._request("DELETE", f"/iserver/account/{account_id}/order/{order_id}")
            or {}
        )

    # === Utility ===

    def validate_sso(self) -> dict:
        """Validate SSO session. GET /sso/validate"""
        return self._request("GET", "/sso/validate") or {}

    def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        return self.state.authenticated and self.state.connected
