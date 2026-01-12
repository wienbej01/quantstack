"""
IBKR Platform Client - HTTP client for services to connect to IBKR Platform.

Replaces direct ib_insync connections with REST API calls to centralized platform.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass
class PlatformConfig:
    """Configuration for platform client."""

    base_url: str = "http://127.0.0.1:8000"
    timeout: int = 30
    retry_attempts: int = 3
    retry_delay: float = 1.0


class IBKRPlatformClient:
    """
    HTTP client for IBKR Platform.

    Provides same interface as ib_insync but routes through centralized platform.
    """

    def __init__(
        self, service_id: str, service_name: str, config: PlatformConfig = None
    ):
        self.service_id = service_id
        self.service_name = service_name
        self.config = config or PlatformConfig()
        self._session = requests.Session()
        self._registered = False

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request to platform."""
        url = f"{self.config.base_url}{endpoint}"
        kwargs.setdefault("timeout", self.config.timeout)

        for attempt in range(self.config.retry_attempts):
            try:
                resp = self._session.request(method, url, **kwargs)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 404:
                    raise ConnectionError(f"Platform endpoint not found: {endpoint}")
                else:
                    logger.warning(
                        f"Platform request failed: {resp.status_code} {resp.text[:200]}"
                    )
                    if attempt == self.config.retry_attempts - 1:
                        raise ConnectionError(
                            f"Platform request failed: {resp.status_code}"
                        )
            except requests.exceptions.RequestException as e:
                if attempt == self.config.retry_attempts - 1:
                    raise ConnectionError(f"Platform connection failed: {e}")
                time.sleep(self.config.retry_delay * (attempt + 1))

        raise ConnectionError("Max retry attempts exceeded")

    # === Service Management ===

    def register(self, endpoints: List[str] = None) -> bool:
        """Register service with platform."""
        try:
            endpoints = endpoints or ["market-data", "orders", "positions"]
            data = {
                "service_id": self.service_id,
                "name": self.service_name,
                "endpoints": endpoints,
            }
            result = self._request("POST", "/services/register", json=data)
            self._registered = True
            logger.info(f"Registered with platform: {self.service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to register with platform: {e}")
            return False

    def heartbeat(self) -> bool:
        """Send heartbeat to platform."""
        try:
            self._request("POST", f"/services/{self.service_id}/heartbeat")
            return True
        except Exception as e:
            logger.warning(f"Heartbeat failed: {e}")
            return False

    def unregister(self) -> bool:
        """Unregister from platform."""
        try:
            self._request("DELETE", f"/services/{self.service_id}")
            self._registered = False
            logger.info(f"Unregistered from platform: {self.service_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to unregister: {e}")
            return False

    # === Platform Health ===

    def is_healthy(self) -> bool:
        """Check if platform is healthy."""
        try:
            result = self._request("GET", "/health")
            return result.get("status") == "healthy"
        except Exception:
            return False

    def get_platform_status(self) -> Dict[str, Any]:
        """Get platform status."""
        return self._request("GET", "/health")

    # === Authentication ===

    def check_auth_status(self) -> bool:
        """Check IBKR authentication status."""
        result = self._request("GET", "/api/auth/status")
        return result.get("authenticated", False)

    # === Accounts ===

    def get_accounts(self) -> List[str]:
        """Get IBKR accounts."""
        result = self._request("GET", "/api/accounts")
        return result.get("accounts", [])

    def switch_account(self, account_id: str) -> bool:
        """Switch active account."""
        try:
            self._request(
                "POST", "/api/accounts/switch", params={"account_id": account_id}
            )
            return True
        except Exception as e:
            logger.error(f"Failed to switch account: {e}")
            return False

    # === Market Data ===

    def get_market_snapshot(
        self, conids: List[int], fields: List[str] = None
    ) -> List[Dict]:
        """Get market data snapshot."""
        data = {"conids": conids}
        if fields:
            data["fields"] = fields
        result = self._request("POST", "/api/market-data/snapshot", json=data)
        return result.get("data", [])

    def get_historical_data(
        self,
        conid: int,
        period: str = "1d",
        bar: str = "1min",
        exchange: str = None,
        outside_rth: bool = False,
    ) -> Dict[str, Any]:
        """Get historical market data."""
        params = {
            "conid": conid,
            "period": period,
            "bar": bar,
            "outside_rth": outside_rth,
        }
        if exchange:
            params["exchange"] = exchange
        result = self._request("GET", "/api/market-data/historical", params=params)
        return result.get("data", {})

    # === Contracts ===

    def search_contracts(self, symbol: str, sec_type: str = "STK") -> List[Dict]:
        """Search contracts by symbol."""
        params = {"symbol": symbol, "sec_type": sec_type}
        result = self._request("GET", "/api/contracts/search", params=params)
        return result.get("contracts", [])

    def get_contract_info(self, conid: int) -> Dict[str, Any]:
        """Get contract information."""
        result = self._request("GET", f"/api/contracts/{conid}")
        return result.get("contract", {})

    # === Positions & Portfolio ===

    def get_positions(self, account_id: str, page: int = 0) -> List[Dict]:
        """Get positions for account."""
        result = self._request(
            "GET", f"/api/positions/{account_id}", params={"page": page}
        )
        return result.get("positions", [])

    def get_portfolio_summary(self, account_id: str) -> Dict[str, Any]:
        """Get portfolio summary."""
        result = self._request("GET", f"/api/portfolio/{account_id}")
        return result.get("portfolio", {})

    def get_pnl(self) -> Dict[str, Any]:
        """Get account P&L."""
        result = self._request("GET", "/api/pnl")
        return result.get("pnl", {})

    # === Orders ===

    def get_live_orders(
        self, filters: List[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        """Get live orders."""
        params = {"force": force}
        if filters:
            params["filters"] = ",".join(filters)
        result = self._request("GET", "/api/orders", params=params)
        return result.get("orders", {})

    def get_trades(self, days: int = 1) -> List[Dict]:
        """Get recent trades."""
        result = self._request("GET", "/api/trades", params={"days": days})
        return result.get("trades", [])

    def place_order(
        self,
        account_id: str,
        symbol: str,
        quantity: int,
        side: str,
        order_type: str = "MKT",
        price: float = None,
    ) -> Dict[str, Any]:
        """Place an order."""
        data = {
            "account_id": account_id,
            "symbol": symbol,
            "quantity": quantity,
            "side": side,
            "order_type": order_type,
        }
        if price:
            data["price"] = price
        result = self._request("POST", "/api/orders/place", json=data)
        return result.get("result", {})

    def cancel_order(self, account_id: str, order_id: str) -> Dict[str, Any]:
        """Cancel an order."""
        result = self._request("DELETE", f"/api/orders/{account_id}/{order_id}")
        return result.get("result", {})

    # === Utility ===

    def tickle(self) -> Dict[str, Any]:
        """Manual tickle to platform."""
        result = self._request("POST", "/api/tickle")
        return result.get("result", {})

    # === Context Manager Support ===

    def __enter__(self):
        """Context manager entry."""
        if not self._registered:
            self.register()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self._registered:
            self.unregister()


# === Compatibility Layer ===


class IBKRPlatformAdapter:
    """
    Adapter to make platform client compatible with existing ib_insync code.

    Provides similar interface to ib_insync.IB for drop-in replacement.
    """

    def __init__(self, service_id: str, service_name: str):
        self.client = IBKRPlatformClient(service_id, service_name)
        self.connected = False

    def connect(self, host: str = None, port: int = None, clientId: int = None) -> bool:
        """Connect to platform (replaces ib_insync connect)."""
        success = self.client.register()
        if success:
            self.connected = self.client.is_healthy()
        return self.connected

    def disconnect(self):
        """Disconnect from platform."""
        self.client.unregister()
        self.connected = False

    def isConnected(self) -> bool:
        """Check if connected."""
        return self.connected and self.client.is_healthy()

    # Delegate other methods to platform client
    def __getattr__(self, name):
        return getattr(self.client, name)
