"""L2 Scalping Order Manager - ib_insync implementation."""

from __future__ import annotations

import logging
import queue
import threading
import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable

from ib_insync import LimitOrder, MarketOrder, Order, Trade

from qx_broker.ibkr import (
    ContractFactory,
    IBKRConnectionConfig,
    IBKROrderConfig,
    IBKROrderManager as BaseOrderManager,
    IBKRSession,
    IBKRSessionConfig,
)

logger = logging.getLogger(__name__)


class OrderSide(Enum):
    """Order side."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(Enum):
    """Order type."""

    MKT = "MKT"
    LMT = "LMT"
    LIMIT = "LMT"
    IOC = "IOC"


@dataclass(frozen=True)
class OrderRequest:
    """Order request."""

    symbol: str
    quantity: int
    side: OrderSide
    order_type: OrderType = OrderType.MKT
    price: float | None = None
    time_in_force: str | None = None
    client_order_id: str | None = None
    stop_loss_price: float | None = None
    profit_target_price: float | None = None


@dataclass(frozen=True)
class OrderUpdate:
    """Order status update."""

    order_id: str
    symbol: str
    status: str
    filled_qty: int = 0
    avg_price: float = 0.0


@dataclass(frozen=True)
class PlaceOrderResult:
    """Result of an order placement attempt."""

    order_id: str | None
    success: bool
    rejection_reason: str = ""

    @property
    def is_margin_rejection(self) -> bool:
        r = self.rejection_reason.lower()
        return any(kw in r for kw in ("margin", "insufficient", "equity with loan"))


class IBKROrderManager:
    """Order manager using ib_insync via qx_broker."""

    SYSTEM_NAME = "L2_SCALPING_ORDERS"

    def __init__(self, config: dict):
        self.config = config
        ibkr_cfg = config.get("ibkr", {})
        orders_cfg = config.get("orders", {})
        account_cfg = config.get("account", {})
        market_data_cfg = config.get("market_data", {})

        self.host = str(ibkr_cfg.get("host", "127.0.0.1"))
        self.port = int(ibkr_cfg.get("port", 7497))
        base_client_id = int(
            ibkr_cfg.get("order_client_id_base", ibkr_cfg.get("order_client_id", 200))
        )
        client_id_max = int(ibkr_cfg.get("client_id_max", base_client_id))
        client_id_fallbacks = max(0, client_id_max - base_client_id)

        timeout = float(ibkr_cfg.get("timeout", 30))
        connection = IBKRConnectionConfig(
            host=self.host,
            port=self.port,
            client_id=base_client_id,
            connect_timeout=timeout,
            request_timeout=timeout,
            reconnect_attempts=int(ibkr_cfg.get("max_reconnect_attempts", 5)),
            reconnect_backoff_sec=float(ibkr_cfg.get("reconnect_delay", 5)),
            allow_client_id_fallback=client_id_fallbacks > 0,
            client_id_fallbacks=client_id_fallbacks,
        )
        session_cfg = IBKRSessionConfig(system_name=self.SYSTEM_NAME, connection=connection)
        self.session = IBKRSession(session_cfg)
        self.client_id = base_client_id

        account_id = account_cfg.get("account_id")
        if account_id in {"", "DU123456"}:
            account_id = None
            logger.warning("IBKR account_id is placeholder; will resolve from gateway")

        order_cfg = IBKROrderConfig(
            order_ref_prefix=str(orders_cfg.get("order_ref_prefix", "L2SCALP")),
            account=account_id,
            min_cancel_interval_sec=float(orders_cfg.get("min_cancel_interval_sec", 2.0)),
        )
        self._order_manager = BaseOrderManager(self.session, order_cfg)
        self._account_id = order_cfg.account

        self._default_tif = str(orders_cfg.get("default_tif", "DAY"))
        self._exchange = str(orders_cfg.get("exchange", market_data_cfg.get("exchange", "SMART")))

        self._contracts = ContractFactory(self.session)
        self._order_queue: queue.Queue[OrderUpdate] = queue.Queue()
        self._fill_queue: queue.Queue[tuple[Trade, object]] = queue.Queue()
        self._fill_callbacks: list[Callable[[Trade, object], None]] = []
        self._trades: dict[str, Trade] = {}
        self._bracket_children: dict[str, dict[str, str | None]] = {}
        self._lock = threading.Lock()
        self._events_attached = False

    def connect(self) -> bool:
        """Connect to IBKR gateway."""
        if not self.session.connect():
            logger.error("Order Manager failed to connect")
            return False

        self._attach_events()
        if not self._account_id:
            self._account_id = self._resolve_account_id()
        logger.info("Order Manager connected (client_id=%s)", self.session.active_client_id)
        return True

    def disconnect(self) -> None:
        """Disconnect from IBKR gateway."""
        self.session.disconnect()
        logger.info("Order Manager disconnected")

    def _attach_events(self) -> None:
        if self._events_attached:
            return

        def _register() -> None:
            ib = self.session.ib
            ib.execDetailsEvent += self._on_exec_details
            ib.orderStatusEvent += self._on_order_status

        try:
            self.session.call(_register, timeout=5)
            self._events_attached = True
        except Exception as exc:
            logger.warning("Failed to attach IBKR events: %s", exc)

    def _resolve_account_id(self) -> str | None:
        try:
            accounts = self.session.call(self.session.ib.managedAccounts, timeout=5)
            if accounts:
                return accounts[0]
        except Exception as exc:
            logger.warning("managedAccounts lookup failed: %s", exc)

        try:
            summary = self.session.call(self.session.ib.accountSummary, timeout=10)
            if summary:
                return summary[0].account
        except Exception as exc:
            logger.warning("accountSummary lookup failed: %s", exc)

        return None

    def place_order(self, order_request: OrderRequest) -> str | None:
        """Place an order with optional bracket orders."""
        result = self.place_order_safe(order_request)
        return result.order_id if result.success else None

    def place_order_safe(self, order_request: OrderRequest) -> PlaceOrderResult:
        """Place an order and return structured result with rejection info."""
        try:
            contract = self._contracts.stock(order_request.symbol, exchange=self._exchange)
            contract = self._contracts.qualify(contract)

            # Check if bracket orders requested
            if order_request.stop_loss_price or order_request.profit_target_price:
                oid = self._place_bracket_order(contract, order_request)
                if oid:
                    return PlaceOrderResult(order_id=oid, success=True)
                return PlaceOrderResult(order_id=None, success=False, rejection_reason="bracket order failed")

            # Simple order
            order = self._build_order(order_request)

            if self._account_id:
                order.account = self._account_id
            if order_request.client_order_id:
                order.orderRef = order_request.client_order_id

            result = self._order_manager.place_order(contract, order)
            trade = result.trade
            order_id = str(trade.order.orderId)

            with self._lock:
                self._trades[order_id] = trade

            logger.info(
                "Order placed: %s %s %s -> %s",
                order_request.symbol,
                order_request.side.value,
                order_request.quantity,
                order_id,
            )

            return PlaceOrderResult(order_id=order_id, success=True)
        except Exception as exc:
            reason = str(exc)
            logger.error("Order placement error: %s", reason)
            return PlaceOrderResult(order_id=None, success=False, rejection_reason=reason)

    def _place_bracket_order(self, contract, order_request: OrderRequest) -> str | None:
        """Place bracket order with stop-loss and profit-target."""
        try:
            # Parent order
            parent = self._build_order(order_request)
            parent.transmit = False
            if self._account_id:
                parent.account = self._account_id
            if order_request.client_order_id:
                parent.orderRef = order_request.client_order_id

            # Place parent
            parent_result = self._order_manager.place_order(contract, parent)
            parent_trade = parent_result.trade
            parent_id = parent_trade.order.orderId

            with self._lock:
                self._trades[str(parent_id)] = parent_trade

            # Child orders
            children = []
            exit_side = "SELL" if order_request.side == OrderSide.BUY else "BUY"

            # Stop-loss
            if order_request.stop_loss_price:
                stop = Order()
                stop.orderId = self.session.ib.client.getReqId()
                stop.action = exit_side
                stop.orderType = "STP"
                stop.auxPrice = order_request.stop_loss_price
                stop.totalQuantity = order_request.quantity
                stop.parentId = parent_id
                stop.transmit = False
                if self._account_id:
                    stop.account = self._account_id
                children.append(stop)

            # Profit target
            if order_request.profit_target_price:
                target = Order()
                target.orderId = self.session.ib.client.getReqId()
                target.action = exit_side
                target.orderType = "LMT"
                target.lmtPrice = order_request.profit_target_price
                target.totalQuantity = order_request.quantity
                target.parentId = parent_id
                target.transmit = len(children) == 0  # Transmit last child
                if self._account_id:
                    target.account = self._account_id
                children.append(target)

            # Place children
            stop_id: str | None = None
            target_id: str | None = None
            for i, child in enumerate(children):
                child.transmit = (i == len(children) - 1)  # Transmit last
                child_result = self._order_manager.place_order(contract, child)
                child_trade = child_result.trade
                with self._lock:
                    self._trades[str(child_trade.order.orderId)] = child_trade
                if child.orderType == "STP":
                    stop_id = str(child_trade.order.orderId)
                elif child.orderType == "LMT":
                    target_id = str(child_trade.order.orderId)

            with self._lock:
                self._bracket_children[str(parent_id)] = {
                    "stop_id": stop_id,
                    "target_id": target_id,
                }

            logger.info(
                "Bracket order placed: %s %s %s -> parent=%s, stop=%s, target=%s",
                order_request.symbol,
                order_request.side.value,
                order_request.quantity,
                parent_id,
                order_request.stop_loss_price,
                order_request.profit_target_price,
            )

            return str(parent_id)
        except Exception as exc:
            logger.error("Bracket order placement error: %s", exc)
            return None

    def get_bracket_children(self, parent_id: str) -> dict[str, str | None]:
        """Get bracket child order IDs for a parent order."""
        with self._lock:
            return self._bracket_children.get(str(parent_id), {"stop_id": None, "target_id": None})

    def place_oca_exit_orders(
        self,
        symbol: str,
        entry_side: str,
        quantity: int,
        stop_loss_price: float | None,
        profit_target_price: float | None,
        oca_group: str | None = None,
    ) -> dict[str, str | None]:
        """Place OCA exit orders (stop + target) after entry fill."""
        try:
            contract = self._contracts.stock(symbol, exchange=self._exchange)
            contract = self._contracts.qualify(contract)

            exit_side = "SELL" if entry_side.upper() == "BUY" else "BUY"
            oca_group = oca_group or f"OCA_{symbol}_{int(time.time()*1000)}"

            order_ids: dict[str, str | None] = {"stop_id": None, "target_id": None}
            orders: list[Order] = []

            if stop_loss_price is not None:
                stop = Order()
                stop.action = exit_side
                stop.orderType = "STP"
                stop.auxPrice = float(stop_loss_price)
                stop.totalQuantity = int(quantity)
                stop.ocaGroup = oca_group
                stop.ocaType = 1
                if self._account_id:
                    stop.account = self._account_id
                orders.append(stop)

            if profit_target_price is not None:
                target = Order()
                target.action = exit_side
                target.orderType = "LMT"
                target.lmtPrice = float(profit_target_price)
                target.totalQuantity = int(quantity)
                target.ocaGroup = oca_group
                target.ocaType = 1
                if self._account_id:
                    target.account = self._account_id
                orders.append(target)

            for order in orders:
                result = self._order_manager.place_order(contract, order)
                trade = result.trade
                order_id = str(trade.order.orderId)
                with self._lock:
                    self._trades[order_id] = trade
                if order.orderType == "STP":
                    order_ids["stop_id"] = order_id
                elif order.orderType == "LMT":
                    order_ids["target_id"] = order_id

            logger.info(
                "OCA exit orders placed: %s %s qty=%s stop=%s target=%s oca=%s",
                symbol,
                exit_side,
                quantity,
                stop_loss_price,
                profit_target_price,
                oca_group,
            )
            return order_ids
        except Exception as exc:
            logger.error("OCA exit order placement error: %s", exc)
            return {"stop_id": None, "target_id": None}

    def _build_order(self, request: OrderRequest):
        action = request.side.value
        tif = request.time_in_force or self._default_tif
        if request.order_type == OrderType.MKT:
            return MarketOrder(action, request.quantity, tif=tif)

        limit_price = request.price
        if limit_price is None:
            raise ValueError("Limit orders require a price")

        if request.order_type == OrderType.IOC and not request.time_in_force:
            tif = "IOC"

        return LimitOrder(action, request.quantity, limit_price, tif=tif)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        try:
            with self._lock:
                trade = self._trades.get(str(order_id))
            if not trade:
                return False
            self._order_manager.cancel_order(trade)
            logger.info("Order cancelled: %s", order_id)
            return True
        except Exception as exc:
            logger.error("Cancel order error: %s", exc)
            return False

    def cancel_all_orders(self) -> None:
        """Cancel all open orders."""
        try:
            for trade in self._order_manager.open_trades():
                self._order_manager.cancel_order(trade)
        except Exception as exc:
            logger.error("Cancel all orders error: %s", exc)

    def get_positions(self) -> list[dict]:
        """Get current positions."""
        try:
            positions = self.session.call(self.session.ib.positions, timeout=10)
            data = []
            for pos in positions:
                data.append(
                    {
                        "symbol": pos.contract.symbol,
                        "quantity": int(pos.position),
                        "avg_price": float(pos.avgCost or 0.0),
                    }
                )
            return data
        except Exception as exc:
            logger.error("Get positions error: %s", exc)
            return []

    def get_next_order_update(self, timeout: float = 0.1) -> OrderUpdate | None:
        """Get next order update from queue."""
        try:
            return self._order_queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def add_fill_callback(self, callback: Callable[[Trade, object], None]) -> None:
        """Register a callback for order fills."""
        self._fill_callbacks.append(callback)

    def process_fills(self) -> None:
        """Dispatch queued fills to registered callbacks."""
        while True:
            try:
                trade, fill = self._fill_queue.get_nowait()
            except queue.Empty:
                break
            for callback in self._fill_callbacks:
                try:
                    callback(trade, fill)
                except Exception as exc:
                    logger.error("Fill callback error: %s", exc)

    def health_check(self) -> dict:
        """Return health status."""
        return {
            "connected": self.session.is_connected(),
            "account": self._account_id,
            "queue_size": self._order_queue.qsize(),
        }

    def _on_order_status(self, trade: Trade, *_args) -> None:
        try:
            order_id = str(trade.order.orderId)
            symbol = trade.contract.symbol if trade.contract else ""
            status = trade.orderStatus.status
            filled_qty = int(trade.orderStatus.filled or 0)
            avg_price = float(trade.orderStatus.avgFillPrice or 0.0)

            update = OrderUpdate(
                order_id=order_id,
                symbol=symbol,
                status=status,
                filled_qty=filled_qty,
                avg_price=avg_price,
            )
            self._order_queue.put(update)
        except Exception as exc:
            logger.error("Order status handler error: %s", exc)

    def _on_exec_details(self, trade: Trade, fill) -> None:
        try:
            order_id = str(trade.order.orderId)
            with self._lock:
                self._trades[order_id] = trade
            self._fill_queue.put((trade, fill))
        except Exception as exc:
            logger.error("Exec details handler error: %s", exc)
