#!/usr/bin/env python3
"""L2 VWAP Mean Reversion - Main entry point.

Uses same SIP symbols as l2-scalping and reads L2 data from l2-scalping's output.
Implements bracket orders with stop-loss and take-profit.
Reports trades to PostgreSQL event store and posts audit logs.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from datetime import datetime
from datetime import time as dt_time
from pathlib import Path
from zoneinfo import ZoneInfo

import nest_asyncio

nest_asyncio.apply()

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent))
# Add parent for cpapi imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from data.bar_feed import AggregatedBarFeed
from execution.order_manager import (
    BracketOrderResult,
    OrderManager,
    OrderSide,
    round_to_tick_size,
)
from qx_broker.ibkr import IBKRConnectionConfig, IBKRSession, IBKRSessionConfig
from reporting.trade_journal import TradeJournal
from strategy import Side, Signal, Strategy

# Import Client ID Manager
from cpapi.client_id_manager import ClientIDManager

# Import margin checker (Feb 9 incident fix)
from cpapi.margin_check import MarginChecker
from cpapi.shared_positions import SharedPositionLedger

# Import Trade Database V2
from cpapi.trade_integration import TradeIntegration

# Import SIP integration from l2-scalping
sys.path.insert(0, "/home/jacobw/quantstack/l2_scalping/src/data")
from sip_integration import get_scalping_symbols

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

# Market hours (ET)
MARKET_OPEN = dt_time(9, 30)
MARKET_CLOSE = dt_time(16, 0)
PRE_MARKET_START = dt_time(9, 26)
POST_MARKET_END = dt_time(16, 5)
EOD_FLATTEN_TIME = dt_time(15, 55)


class VWAPReversionSystem:
    """Main system orchestrator - uses l2-scalping's SIP symbols and L2 data."""

    def __init__(self, config: dict):
        self.config = config
        self._running = False
        self._current_bracket: BracketOrderResult | None = None
        self._current_trade_id: str | None = None
        self._current_db_trade_id: int | None = None  # Trade DB V2 ID

        # Trade journal with PostgreSQL + audit logging
        self.journal = TradeJournal()

        # Trade Database V2 (will be initialized after connection)
        self.trade_db = None

        # Margin checker (initialized after IBKR connection)
        self.margin_checker: MarginChecker | None = None
        self._consecutive_margin_rejections = 0
        self._max_margin_rejections = 3  # Stop trading after 3 consecutive

        # Shared position ledger for cross-service awareness
        try:
            self.shared_ledger = SharedPositionLedger()
        except Exception:
            self.shared_ledger = None

        # Load SIP symbols (same as l2-scalping)
        max_symbols = config.get("universe", {}).get("max_symbols", 3)
        try:
            self.symbols = get_scalping_symbols(max_symbols=max_symbols)
            logger.info(f"Using SIP symbols (same as l2-scalping): {self.symbols}")
        except RuntimeError as e:
            logger.error(f"Failed to load SIP symbols: {e}")
            self.journal.log_error(f"Failed to load SIP symbols: {e}")
            self.symbols = []

        if not self.symbols:
            logger.error("No symbols available - system will not trade")

        # Initialize IBKR sessions with dynamic client IDs
        ibkr_cfg = config.get("ibkr", {})

        # Client ID manager for dynamic allocation
        self.client_id_mgr = ClientIDManager.from_config("l2_vwap", config)
        data_client_id = self.client_id_mgr.get_data_id()
        order_client_id = self.client_id_mgr.get_order_id()

        # Data session for bar feed
        data_connection = IBKRConnectionConfig(
            host=ibkr_cfg.get("host", "127.0.0.1"),
            port=ibkr_cfg.get("port", 7494),
            client_id=data_client_id,
            connect_timeout=ibkr_cfg.get("timeout", 30),
            request_timeout=ibkr_cfg.get("timeout", 30),
            reconnect_attempts=ibkr_cfg.get("max_reconnect_attempts", 5),
        )
        data_session_cfg = IBKRSessionConfig(
            system_name="L2_VWAP_DATA",
            connection=data_connection,
        )
        self.data_session = IBKRSession(data_session_cfg)

        # Order session
        order_connection = IBKRConnectionConfig(
            host=ibkr_cfg.get("host", "127.0.0.1"),
            port=ibkr_cfg.get("port", 7494),
            client_id=order_client_id,
            connect_timeout=ibkr_cfg.get("timeout", 30),
            request_timeout=ibkr_cfg.get("timeout", 30),
            reconnect_attempts=ibkr_cfg.get("max_reconnect_attempts", 5),
        )
        order_session_cfg = IBKRSessionConfig(
            system_name="L2_VWAP_ORDERS",
            connection=order_connection,
        )
        self.order_session = IBKRSession(order_session_cfg)

        # Components
        self.bar_feed = AggregatedBarFeed(self.data_session, config)
        self.order_manager = OrderManager(self.order_session, config)
        self.strategy = Strategy(config)

        # Track actual fill prices
        self._entry_fill_price: float | None = None
        self._exit_fill_price: float | None = None

        # Exit parameters for bracket orders
        exits_cfg = config.get("exits", {})
        self.tp_long = exits_cfg.get("take_profit_long", 1.005)
        self.tp_short = exits_cfg.get("take_profit_short", 0.995)
        self.sl_long = exits_cfg.get("stop_loss_long", 0.9925)
        self.sl_short = exits_cfg.get("stop_loss_short", 1.0075)

        # Register bar callback
        self.bar_feed.add_callback(self._on_bar)

        # Register fill callback
        self.order_manager.set_fill_callback(self._on_fill)

    def _on_fill(
        self,
        order_id: int,
        symbol: str,
        side: str,
        filled_qty: int,
        avg_price: float,
        is_entry: bool,
    ) -> None:
        """Handle fill events - update position with actual fill prices."""
        logger.info(
            f"Fill: {symbol} {side} {filled_qty}@{avg_price:.4f} (entry={is_entry})"
        )

        if is_entry:
            self._entry_fill_price = avg_price
            # Update position entry_price with actual fill
            if self.strategy.position and self.strategy.position.symbol == symbol:
                self.strategy.position.entry_price = avg_price
                # OrderManager only calls back on final Filled status, but be safe and
                # reflect the actual filled quantity in our tracked position.
                self.strategy.position.shares = int(filled_qty)
                logger.info(f"Updated position entry_price to {avg_price:.4f}")
        else:
            self._exit_fill_price = avg_price
            # Log exit with actual fill price
            pos = self.strategy.position
            if pos and pos.symbol == symbol:
                pnl = (avg_price - pos.entry_price) * pos.shares
                if pos.side == Side.SHORT:
                    pnl = -pnl
                self.journal.log_exit(
                    symbol=symbol,
                    side=pos.side.value,
                    entry_price=pos.entry_price,
                    exit_price=avg_price,
                    quantity=pos.shares,
                    reason="bracket_fill",
                    pnl=pnl,
                    exit_order_id=order_id,
                )
                self._current_trade_id = None
                self.strategy.close_position()

                # Remove from shared position ledger
                if self.shared_ledger:
                    try:
                        self.shared_ledger.remove("l2-vwap", symbol)
                    except Exception as e:
                        logger.debug("Shared ledger remove failed: %s", e)

    def _on_bar(self, bar) -> None:
        """Handle incoming bar data."""
        logger.info(f"_on_bar called: {bar.symbol} @ {bar.close:.2f}")

        # Only process bars for our SIP symbols
        if bar.symbol not in self.symbols:
            logger.warning(f"{bar.symbol} not in SIP symbols {self.symbols}")
            return

        now_et = datetime.now(ET)

        # Check for EOD flatten
        if now_et.time() >= EOD_FLATTEN_TIME and self.strategy.position:
            self._eod_flatten()
            return

        signal = self.strategy.on_bar(bar)
        if signal:
            self._execute_signal(signal)

    def _execute_signal(self, signal: Signal) -> None:
        """Execute trade signal with bracket orders."""
        # Circuit breaker: stop trading after consecutive margin rejections
        if self._consecutive_margin_rejections >= self._max_margin_rejections:
            logger.warning(
                "Trading halted: %d consecutive margin rejections",
                self._consecutive_margin_rejections,
            )
            return

        # Calculate position size: 2% equity risk
        equity = getattr(self, "_account_equity", None) or self.config.get(
            "risk", {}
        ).get("account_equity", 100000)
        risk_per_trade = equity * 0.02

        # Stop loss distance
        if signal.side == Side.LONG:
            stop_pct = 1.0 - self.sl_long  # e.g., 0.995 -> 0.005 = 0.5%
        else:
            stop_pct = self.sl_short - 1.0  # e.g., 1.005 -> 0.005 = 0.5%

        stop_distance = signal.price * stop_pct
        position_size = (
            int(risk_per_trade / stop_distance) if stop_distance > 0 else 100
        )

        # Cap at 2% of equity in notional
        max_notional = int((equity * 0.02) / signal.price)
        position_size = min(position_size, max_notional, 10000)  # Max 10k shares

        if self.strategy.position is None:
            # Only check our own tracked position, not global IBKR positions
            # This allows multiple strategies to trade the same symbol independently

            # Pre-trade margin check (Feb 9 incident fix)
            if self.margin_checker:
                from ib_insync import MarketOrder as IB_MarketOrder
                from ib_insync import Stock

                check_contract = Stock(signal.symbol, "SMART", "USD")
                check_action = "BUY" if signal.side == Side.LONG else "SELL"
                check_order = IB_MarketOrder(check_action, position_size)
                margin_result = self.margin_checker.check(
                    check_contract, check_order, signal.symbol
                )
                if not margin_result.allowed:
                    self._consecutive_margin_rejections += 1
                    logger.warning(
                        "MARGIN CHECK BLOCKED entry %s %s %d: %s (rejection %d/%d)",
                        signal.side.value,
                        signal.symbol,
                        position_size,
                        margin_result.reason,
                        self._consecutive_margin_rejections,
                        self._max_margin_rejections,
                    )
                    return
                self._consecutive_margin_rejections = 0

            # Global margin budget check across all services
            if self.shared_ledger:
                try:
                    equity = self.config.get("risk", {}).get("account_equity", 100000)
                    est_margin = signal.price * position_size * 0.25
                    allowed, reason = self.shared_ledger.check_global_margin(
                        est_margin, equity
                    )
                    if not allowed:
                        logger.warning("Global margin cap blocked entry: %s", reason)
                        return
                except Exception as e:
                    logger.debug("Global margin check unavailable: %s", e)

            # Entry signal - use bracket order
            side = OrderSide.BUY if signal.side == Side.LONG else OrderSide.SELL

            # Calculate SL/TP prices
            if signal.side == Side.LONG:
                stop_loss = round_to_tick_size(signal.price * self.sl_long)
                take_profit = round_to_tick_size(signal.price * self.tp_long)
            else:
                stop_loss = round_to_tick_size(signal.price * self.sl_short)
                take_profit = round_to_tick_size(signal.price * self.tp_short)

            result = self.order_manager.submit_bracket_order(
                symbol=signal.symbol,
                side=side,
                quantity=position_size,
                entry_price=signal.price,
                stop_loss_price=stop_loss,
                take_profit_price=take_profit,
            )

            if result:
                self._current_bracket = result
                self.strategy.open_position(
                    symbol=signal.symbol,
                    side=signal.side,
                    entry_price=signal.price,
                    entry_time=signal.timestamp,
                    shares=position_size,
                )

                # Write to shared position ledger
                if self.shared_ledger:
                    try:
                        self.shared_ledger.upsert(
                            "l2-vwap",
                            signal.symbol,
                            position_size,
                            signal.price,
                        )
                    except Exception as e:
                        logger.debug("Shared ledger upsert failed: %s", e)

                # Open trade in Trade Database V2
                if self.trade_db:
                    try:
                        self._current_db_trade_id = self.trade_db.open_trade(
                            symbol=signal.symbol,
                            direction="long" if signal.side == Side.LONG else "short",
                            signal_price=signal.price,
                            stop_loss=stop_loss,
                            take_profit=take_profit,
                            metadata={
                                "strategy": "vwap_reversion",
                                "vwap": signal.vwap,
                                "l2_ratio": signal.l2_ratio,
                            },
                        )
                        self.trade_db.link_order(
                            self._current_db_trade_id, result.parent_id, is_entry=True
                        )
                        if result.stop_loss_id:
                            self.trade_db.link_order(
                                self._current_db_trade_id,
                                result.stop_loss_id,
                                is_entry=False,
                            )
                        if result.take_profit_id:
                            self.trade_db.link_order(
                                self._current_db_trade_id,
                                result.take_profit_id,
                                is_entry=False,
                            )
                        logger.info(
                            f"Trade DB V2: opened trade_id={self._current_db_trade_id}"
                        )
                    except Exception as e:
                        logger.error(f"Failed to record trade in DB V2: {e}")

                # Log to trade database and audit
                self._current_trade_id = self.journal.log_entry(
                    symbol=signal.symbol,
                    side=signal.side.value,
                    price=signal.price,
                    quantity=position_size,
                    vwap=signal.vwap,
                    l2_ratio=signal.l2_ratio,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                    entry_order_id=result.parent_id,
                )
        else:
            # Exit signal - cancel bracket and flatten
            pos = self.strategy.position
            side = OrderSide.SELL if pos.side == Side.LONG else OrderSide.BUY

            # Cancel existing bracket orders
            if self._current_bracket:
                self.order_manager.cancel_bracket(self._current_bracket.parent_id)
                self._current_bracket = None

            # Submit market exit
            result = self.order_manager.submit_market_order(
                symbol=pos.symbol,
                side=side,
                quantity=pos.shares,
            )

            if result:
                # Don't log exit here - _on_fill callback will handle it with actual fill price
                pass

    def _eod_flatten(self) -> None:
        """Flatten all positions at EOD."""
        pos = self.strategy.position
        if not pos:
            return

        logger.warning(f"EOD FLATTEN: Closing {pos.side.value} {pos.symbol}")

        # Cancel bracket orders
        if self._current_bracket:
            self.order_manager.cancel_bracket(self._current_bracket.parent_id)
            self._current_bracket = None

        # Flatten position
        side = OrderSide.SELL if pos.side == Side.LONG else OrderSide.BUY
        result = self.order_manager.submit_market_order(
            symbol=pos.symbol,
            side=side,
            quantity=pos.shares,
        )

        if result:
            # Don't log exit here - _on_fill callback will handle it with actual fill price
            pass

    def connect(self) -> bool:
        """Connect to IBKR gateway."""
        if not self.symbols:
            logger.error("No symbols to trade")
            return False

        logger.info("Connecting to IBKR gateway...")

        if not self.data_session.connect():
            logger.error("Failed to connect data session")
            self.journal.log_error("Failed to connect data session")
            return False

        if not self.order_session.connect():
            logger.error("Failed to connect order session")
            self.journal.log_error("Failed to connect order session")
            return False

        if not self.order_manager.connect():
            logger.error("Failed to connect order manager")
            self.journal.log_error("Failed to connect order manager")
            return False

        logger.info("Connected to IBKR gateway")

        # Fetch account value for risk-based sizing
        try:
            ib = self.order_session.ib
            ib.reqAccountSummary()
            import time as _t

            _t.sleep(2)
            for item in ib.accountSummary():
                if item.tag == "NetLiquidation":
                    self._account_equity = float(item.value)
                    logger.info(f"Account equity: ${self._account_equity:,.0f}")
                    break
            else:
                self._account_equity = self.config.get("risk", {}).get(
                    "account_equity", 100000
                )
                logger.warning(
                    f"Could not fetch account equity, using config: ${self._account_equity:,.0f}"
                )
        except Exception as e:
            self._account_equity = self.config.get("risk", {}).get(
                "account_equity", 100000
            )
            logger.warning(
                f"Account equity fetch failed ({e}), using config: ${self._account_equity:,.0f}"
            )

        return True

    def disconnect(self) -> None:
        """Disconnect from IBKR gateway."""
        # Flatten any open position
        if self.strategy.position:
            self._eod_flatten()

        self.bar_feed.unsubscribe_all()
        self.data_session.disconnect()
        self.order_session.disconnect()

        # Clear shared position ledger for this service
        if self.shared_ledger:
            try:
                self.shared_ledger.clear_service("l2-vwap")
            except Exception as e:
                logger.debug("Shared ledger cleanup failed: %s", e)

        logger.info("Disconnected from IBKR gateway")

    def start(self) -> None:
        """Start the trading system."""
        self._running = True

        if not self.connect():
            logger.error("Failed to connect, exiting")
            self.journal.log_error("Failed to connect to IBKR gateway")
            return

        # Initialize Trade Database V2
        try:
            self.trade_db = TradeIntegration(
                ib=self.order_session.ib,
                system_name="l2-vwap",
                ib_call=self.order_session.call,
            )
            self.trade_db.start()
            logger.info("Trade Database V2 initialized")

            # Register fill callback for immediate fill notification
            self.order_manager.set_fill_callback(self._on_fill)
            logger.info("Fill callback registered")
        except Exception as e:
            logger.error(f"Failed to initialize Trade Database V2: {e}")
            self.journal.log_error(f"Trade DB V2 init failed: {e}")

        # Initialize margin checker using order session's whatIfOrder
        try:
            self.margin_checker = MarginChecker(
                ib_what_if_fn=lambda contract, order: self.order_session.call(
                    self.order_session.ib.whatIfOrder, contract, order, timeout=10
                )
            )
            logger.info("Margin checker initialized")
        except Exception as e:
            logger.error(f"Failed to initialize margin checker: {e}")
            self.journal.log_error(f"Margin checker init failed: {e}")

        # Log service start
        self.journal.log_service_start(self.symbols)
        logger.info(
            f"Subscribing to bars for {len(self.symbols)} SIP symbols: {self.symbols}"
        )
        self.bar_feed.subscribe(self.symbols)

        try:
            # Keep the process alive while bar callbacks do the work.
            while self._running:
                now_et = datetime.now(ET)
                current_time = now_et.time()

                if current_time > POST_MARKET_END:
                    logger.info("Market closed, shutting down")
                    break

                time.sleep(1)
        finally:
            # Log service stop
            self.journal.log_service_stop("market_close")
            try:
                if self.trade_db:
                    self.trade_db.stop()
            except Exception as e:
                logger.error(f"Error stopping Trade DB V2: {e}")
            self.disconnect()

    def stop(self) -> None:
        """Stop the trading system."""
        logger.info("Stopping trading system...")
        self._running = False

        # Stop Trade Database V2
        if self.trade_db:
            try:
                self.trade_db.stop()
                logger.info("Trade Database V2 stopped")
            except Exception as e:
                logger.error(f"Error stopping Trade DB V2: {e}")

        # Flatten position and cancel orders
        if self.strategy.position:
            self._eod_flatten()
        self.order_manager.cancel_all()

        # Log service stop
        self.journal.log_service_stop("manual_stop")


def setup_logging(log_dir: Path) -> None:
    """Configure logging."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"vwap_reversion_{datetime.now().strftime('%Y%m%d')}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )


def load_config(config_dir: str) -> dict:
    """Load configuration from YAML files."""
    config_path = Path(config_dir)
    config = {}

    for yaml_file in ["strategy.yaml", "ibkr.yaml"]:
        file_path = config_path / yaml_file
        if file_path.exists():
            with open(file_path) as f:
                config.update(yaml.safe_load(f) or {})

    return config


def main():
    parser = argparse.ArgumentParser(description="L2 VWAP Mean Reversion Paper Trading")
    parser.add_argument("--config", default="config", help="Config directory")
    args = parser.parse_args()

    # Setup
    base_dir = Path(__file__).parent.parent
    setup_logging(base_dir / "logs")
    config = load_config(base_dir / args.config)

    logger.info("=" * 60)
    logger.info("L2 VWAP Mean Reversion Paper Trading System")
    logger.info("Using SIP symbols from l2-scalping")
    logger.info("Using L2 data from l2-scalping output")
    logger.info("Bracket orders with SL/TP enabled")
    logger.info("PostgreSQL event store + audit logging enabled")
    logger.info("=" * 60)

    # Create system
    system = VWAPReversionSystem(config)

    # Signal handlers
    def shutdown_handler(signum, frame):
        logger.info(f"Received signal {signum}, shutting down...")
        system.stop()

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    # Run
    try:
        system.start()
    except Exception as e:
        logger.exception(f"System error: {e}")
        system.journal.log_error(f"System error: {e}")
        system.stop()
        sys.exit(1)

    logger.info("System shutdown complete")


if __name__ == "__main__":
    main()
