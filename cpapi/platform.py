"""
IBKR API Platform - Centralized IBKR connection management.

Provides unified HTTP API for all trading services, eliminating direct ib_insync connections.
Built on Client Portal Gateway (port 5000) for reliability.
"""

import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cpapi.audit_logger import EventType, Severity, get_audit_logger
from cpapi.client import CPAPIClient, CPAPIConfig

logger = logging.getLogger(__name__)
audit = get_audit_logger("ibkr-platform")


@dataclass
class ServiceRegistration:
    """Service registration info."""

    service_id: str
    name: str
    registered_at: datetime
    last_heartbeat: datetime
    endpoints: list[str]


class ServiceRegisterRequest(BaseModel):
    """Service registration request."""

    service_id: str
    name: str
    endpoints: list[str]


@dataclass
class MarketDataRequest:
    """Market data request."""

    conids: list[int]
    fields: list[str] | None = None


@dataclass
class OrderRequest:
    """Order placement request."""

    account_id: str
    symbol: str
    quantity: int
    side: str  # BUY/SELL
    order_type: str  # MKT/LMT
    price: float | None = None


class IBKRPlatform:
    """Centralized IBKR API platform."""

    def __init__(self, config: CPAPIConfig = None):
        self.config = config or CPAPIConfig()
        self.client = CPAPIClient(self.config, "platform")
        self.services: dict[str, ServiceRegistration] = {}
        self.app = FastAPI(title="IBKR API Platform", version="1.0.0")
        self._setup_routes()
        self._setup_middleware()

        # Background tasks
        self._monitor_thread = None
        self._stop_event = threading.Event()

    def _setup_middleware(self):
        """Setup FastAPI middleware."""
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def _setup_routes(self):
        """Setup API routes."""

        @self.app.get("/health")
        async def health_check():
            """Platform health check."""
            return {
                "status": "healthy",
                "authenticated": self.client.state.authenticated,
                "connected": self.client.state.connected,
                "services": len(self.services),
                "timestamp": datetime.now().isoformat(),
            }

        @self.app.post("/services/register")
        async def register_service(request: ServiceRegisterRequest):
            """Register a service with the platform."""
            self.services[request.service_id] = ServiceRegistration(
                service_id=request.service_id,
                name=request.name,
                registered_at=datetime.now(),
                last_heartbeat=datetime.now(),
                endpoints=request.endpoints,
            )
            logger.info(f"Registered service: {request.name} ({request.service_id})")
            return {"status": "registered", "service_id": request.service_id}

        @self.app.post("/services/{service_id}/heartbeat")
        async def service_heartbeat(service_id: str):
            """Service heartbeat."""
            if service_id in self.services:
                self.services[service_id].last_heartbeat = datetime.now()
                return {"status": "ok"}
            raise HTTPException(404, "Service not registered")

        @self.app.delete("/services/{service_id}")
        async def unregister_service(service_id: str):
            """Unregister a service."""
            if service_id in self.services:
                del self.services[service_id]
                logger.info(f"Unregistered service: {service_id}")
                return {"status": "unregistered"}
            raise HTTPException(404, "Service not found")

        # === IBKR API Endpoints ===

        @self.app.get("/api/auth/status")
        async def auth_status():
            """Check IBKR authentication status."""
            authenticated = self.client.check_auth_status()
            return {
                "authenticated": authenticated,
                "connected": self.client.state.connected,
                "competing": self.client.state.competing,
                "accounts": self.client.state.accounts,
            }

        @self.app.get("/api/accounts")
        async def get_accounts():
            """Get IBKR accounts."""
            accounts = self.client.get_accounts()
            return {
                "accounts": accounts,
                "selected": self.client.state.selected_account,
            }

        @self.app.post("/api/accounts/switch")
        async def switch_account(account_id: str):
            """Switch active account."""
            success = self.client.switch_account(account_id)
            if success:
                return {"status": "switched", "account": account_id}
            raise HTTPException(400, "Failed to switch account")

        @self.app.get("/api/positions/{account_id}")
        async def get_positions(account_id: str, page: int = 0):
            """Get positions for account."""
            positions = self.client.get_positions(account_id, page)
            return {"positions": positions, "account": account_id}

        @self.app.get("/api/portfolio/{account_id}")
        async def get_portfolio(account_id: str):
            """Get portfolio summary."""
            summary = self.client.get_portfolio_summary(account_id)
            return {"portfolio": summary, "account": account_id}

        @self.app.get("/api/pnl")
        async def get_pnl():
            """Get account P&L."""
            pnl = self.client.get_account_pnl()
            return {"pnl": pnl}

        @self.app.post("/api/market-data/snapshot")
        async def market_snapshot(request: MarketDataRequest):
            """Get market data snapshot."""
            data = self.client.get_market_snapshot(request.conids, request.fields)
            return {"data": data, "timestamp": datetime.now().isoformat()}

        @self.app.get("/api/market-data/historical")
        async def historical_data(
            conid: int,
            period: str = "1d",
            bar: str = "1min",
            exchange: str | None = None,
            outside_rth: bool = False,
        ):
            """Get historical market data."""
            data = self.client.get_historical_data(
                conid, period, bar, exchange, outside_rth
            )
            return {"data": data, "conid": conid}

        @self.app.get("/api/contracts/search")
        async def search_contracts(symbol: str, sec_type: str = "STK"):
            """Search contracts by symbol."""
            contracts = self.client.search_contract(symbol, sec_type)
            return {"contracts": contracts, "symbol": symbol}

        @self.app.get("/api/contracts/{conid}")
        async def contract_info(conid: int):
            """Get contract information."""
            info = self.client.get_contract_info(conid)
            return {"contract": info, "conid": conid}

        @self.app.get("/api/orders")
        async def get_orders(filters: str | None = None, force: bool = False):
            """Get live orders."""
            filter_list = filters.split(",") if filters else None
            orders = self.client.get_live_orders(filter_list, force)
            return {"orders": orders}

        @self.app.get("/api/trades")
        async def get_trades(days: int = 1):
            """Get recent trades."""
            trades = self.client.get_trades(days)
            return {"trades": trades, "days": days}

        @self.app.post("/api/orders/place")
        async def place_order(request: OrderRequest):
            """Place an order."""
            # Convert request to IBKR order format
            order_data = {
                "conid": 0,  # Will need contract lookup
                "orderType": request.order_type,
                "side": request.side,
                "quantity": request.quantity,
            }
            if request.price:
                order_data["price"] = request.price

            result = self.client.place_order(request.account_id, [order_data])
            return {"result": result, "request": asdict(request)}

        @self.app.delete("/api/orders/{account_id}/{order_id}")
        async def cancel_order(account_id: str, order_id: str):
            """Cancel an order."""
            result = self.client.cancel_order(account_id, order_id)
            return {"result": result, "order_id": order_id}

        @self.app.post("/api/tickle")
        async def tickle():
            """Manual tickle to keep session alive."""
            result = self.client.tickle()
            return {"result": result, "timestamp": datetime.now().isoformat()}

    def start_monitoring(self):
        """Start background monitoring."""
        if self._monitor_thread and self._monitor_thread.is_alive():
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("Started platform monitoring")

    def _monitor_loop(self):
        """Background monitoring loop."""
        while not self._stop_event.wait(30):  # Check every 30s
            try:
                # Check authentication
                if not self.client.state.authenticated:
                    logger.warning(
                        "Platform not authenticated, attempting to reconnect"
                    )
                    self.client.check_auth_status()
                    if not self.client.state.authenticated:
                        self.client.init_brokerage_session()

                # Clean up stale services
                now = datetime.now()
                stale_services = []
                for service_id, service in self.services.items():
                    if (now - service.last_heartbeat).seconds > 300:  # 5 minutes
                        stale_services.append(service_id)

                for service_id in stale_services:
                    logger.warning(f"Removing stale service: {service_id}")
                    del self.services[service_id]

            except Exception as e:
                logger.error(f"Monitor loop error: {e}")

    def start(self, host: str = "127.0.0.1", port: int = 8000):
        """Start the platform server."""
        logger.info(f"Starting IBKR API Platform on {host}:{port}")

        # Initialize IBKR connection
        if not self.client.check_auth_status():
            logger.warning(
                "Not authenticated - services will have limited functionality"
            )
        else:
            # Get accounts to initialize session
            self.client.get_accounts()
            self.client.start_tickle_thread()

        # Start monitoring
        self.start_monitoring()

        # Start server
        uvicorn.run(self.app, host=host, port=port, log_level="info")

    def stop(self):
        """Stop the platform."""
        logger.info("Stopping IBKR API Platform")
        self._stop_event.set()
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
        self.client.stop()


def main():
    """Main entry point."""
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    audit.service_start(context={"host": "0.0.0.0", "port": 8000})

    platform = IBKRPlatform()
    try:
        audit.service_ready()
        platform.start()
    except KeyboardInterrupt:
        logger.info("Received interrupt signal")
        audit.log_event(EventType.INFO, "Received interrupt signal", Severity.WARNING)
    except Exception as e:
        logger.error(f"Platform error: {e}", exc_info=True)
        audit.service_error(str(e), context={"exception": type(e).__name__})
        raise
    finally:
        platform.stop()
        audit.service_stop(exit_code=0)


if __name__ == "__main__":
    main()
