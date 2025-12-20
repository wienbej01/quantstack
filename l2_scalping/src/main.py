"""L2 Scalping System - Main Trading Loop

Integrates signals, execution, and risk management for live scalping.
"""

import logging
import signal
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import yaml
from data.l2_feed import L2DataFeed, L2Snapshot, MockL2DataFeed
from execution.order_manager import IBKROrderManager, OrderRequest, OrderSide, OrderType
from risk.risk_manager import CircuitBreaker, RiskManager

# Import system components
from signals.l2_signals import L2SignalGenerator
from signals.l2_signals import L2Snapshot as SignalSnapshot
from signals.l2_signals import SignalValidator

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("logs/scalping_system.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


class ScalpingSystem:
    """Main L2 scalping trading system"""

    def __init__(self, config_dir: str = "config"):
        self.config_dir = Path(config_dir)
        self.config = self._load_config()

        # System components
        self.signal_generator = L2SignalGenerator(self.config["strategy"])
        self.signal_validator = SignalValidator(self.config["strategy"])
        self.risk_manager = RiskManager(self.config["risk"])
        self.circuit_breaker = CircuitBreaker(self.config["risk"]["circuit_breaker"])
        self.order_manager = IBKROrderManager(self.config["ibkr"])

        # Data feed (mock or real based on config)
        if self.config["strategy"].get("mock_data", {}).get("enabled", False):
            logger.warning("USING MOCK DATA - REMOVE BEFORE PAPER TRADING")
            self.data_feed = MockL2DataFeed(self.config["strategy"]["mock_data"])
        else:
            self.data_feed = L2DataFeed(self.config["ibkr"]["market_data"])

        # System state
        self.is_running = False
        self.account_value = self.config["ibkr"]["account"].get(
            "initial_capital", 100000
        )
        self.active_positions: Dict[str, Dict] = {}

        # Performance tracking
        self.trades_today = 0
        self.pnl_today = 0.0
        self.signals_generated = 0
        self.signals_traded = 0

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Scalping System initialized")

    def _load_config(self) -> Dict:
        """Load all configuration files"""
        config = {}

        config_files = {
            "strategy": "strategy.yaml",
            "risk": "risk.yaml",
            "ibkr": "ibkr.yaml",
        }

        for key, filename in config_files.items():
            filepath = self.config_dir / filename
            with open(filepath, "r") as f:
                config[key] = yaml.safe_load(f)

        logger.info(f"Loaded configuration from {self.config_dir}")
        return config

    def start(self) -> None:
        """Start the trading system"""
        logger.info("=" * 60)
        logger.info("STARTING L2 SCALPING SYSTEM")
        logger.info("=" * 60)

        # Connect to IBKR
        if not self.order_manager.connect():
            logger.error("Failed to connect order manager")
            return

        if not self.data_feed.connect():
            logger.error("Failed to connect data feed")
            self.order_manager.disconnect()
            return

        # Register data callback
        self.data_feed.add_data_callback(self._on_market_data)

        # Register fill callback
        self.order_manager.add_fill_callback(self._on_order_fill)

        self.is_running = True
        logger.info("System started successfully")

        # Start monitoring thread
        monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        monitor_thread.start()

        # Main loop
        try:
            while self.is_running:
                # Process order updates
                order_update = self.order_manager.get_next_order_update(timeout=0.1)
                if order_update:
                    self._process_order_update(order_update)

                # Check positions for exits
                self._check_position_exits()

                time.sleep(0.01)  # 100Hz main loop

        except KeyboardInterrupt:
            logger.info("Received shutdown signal")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the trading system"""
        logger.info("Stopping trading system...")
        self.is_running = False

        # Cancel all orders
        self.order_manager.cancel_all_orders()

        # Close all positions
        self._close_all_positions()

        # Disconnect
        self.data_feed.disconnect()
        self.order_manager.disconnect()

        # Print final stats
        self._print_daily_summary()

        logger.info("System stopped")

    def _on_market_data(self, snapshot: L2Snapshot) -> None:
        """Handle incoming market data"""
        try:
            # Convert to signal snapshot format
            signal_snapshot = SignalSnapshot(
                symbol=snapshot.symbol,
                timestamp=snapshot.timestamp,
                mid=snapshot.mid,
                spread=snapshot.spread,
                obi_1=snapshot.obi_1,
                obi_5=snapshot.obi_5,
                depth_bid=snapshot.depth_bid,
                depth_ask=snapshot.depth_ask,
                pressure=snapshot.pressure,
            )

            # Update existing position P&L
            if snapshot.symbol in self.active_positions:
                self.risk_manager.update_position_pnl(snapshot.symbol, snapshot.mid)
                return  # Don't generate new signals if we have a position

            # Generate signal
            signal = self.signal_generator.generate_signal(signal_snapshot)
            self.signals_generated += 1

            # Validate signal
            is_valid, reason = self.signal_validator.is_valid_signal(
                signal, signal_snapshot
            )

            if not is_valid:
                logger.debug(f"Signal rejected for {snapshot.symbol}: {reason}")
                return

            # Check if we should trade
            if signal.signal_type.value == 0:  # No signal
                return

            # Execute trade
            self._execute_signal(signal, snapshot)

        except Exception as e:
            logger.error(f"Error processing market data: {e}", exc_info=True)

    def _execute_signal(self, signal, snapshot: L2Snapshot) -> None:
        """Execute trading signal"""
        try:
            # Check risk limits
            should_stop, reason = self.risk_manager.should_stop_trading()
            if should_stop:
                logger.warning(f"Trading stopped: {reason}")
                return

            # Calculate position size
            quantity = self.risk_manager.calculate_position_size(
                symbol=signal.symbol,
                signal_strength=signal.strength,
                confidence=signal.confidence,
                account_value=self.account_value,
                price=snapshot.mid,
            )

            # Pre-trade risk check
            can_trade, reason = self.risk_manager.check_pre_trade_risk(
                symbol=signal.symbol,
                quantity=quantity,
                price=snapshot.mid,
                account_value=self.account_value,
            )

            if not can_trade:
                logger.info(f"Trade rejected: {reason}")
                return

            # Determine order side and price
            if signal.signal_type.value > 0:  # Long
                side = OrderSide.BUY
                limit_price = snapshot.ask  # Buy at ask
            else:  # Short
                side = OrderSide.SELL
                limit_price = snapshot.bid  # Sell at bid

            # Create order request
            order_request = OrderRequest(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                price=limit_price,
                order_type=(
                    OrderType.IOC
                    if self.config["ibkr"]["orders"]["use_ioc_for_scalping"]
                    else OrderType.LIMIT
                ),
                time_in_force=(
                    "IOC"
                    if self.config["ibkr"]["orders"]["use_ioc_for_scalping"]
                    else "DAY"
                ),
            )

            # Place order
            order_id = self.order_manager.place_order(order_request)

            if order_id:
                self.signals_traded += 1
                logger.info(
                    f"Executed signal: {signal.symbol} {side.value} {quantity}@{limit_price:.4f}"
                )
            else:
                logger.error(f"Failed to place order for {signal.symbol}")

        except Exception as e:
            logger.error(f"Error executing signal: {e}", exc_info=True)

    def _on_order_fill(self, trade, fill) -> None:
        """Handle order fill"""
        try:
            symbol = trade.contract.symbol
            filled_qty = fill.execution.shares
            fill_price = fill.execution.price
            side = fill.execution.side

            logger.info(f"Order filled: {symbol} {side} {filled_qty}@{fill_price:.4f}")

            # Add position to risk manager
            if side == "BOT":  # Bought
                self.risk_manager.add_position(symbol, filled_qty, fill_price)

                # Track position for exit
                self.active_positions[symbol] = {
                    "quantity": filled_qty,
                    "entry_price": fill_price,
                    "entry_time": time.time(),
                    "side": "LONG",
                }
            else:  # Sold (short)
                self.risk_manager.add_position(symbol, -filled_qty, fill_price)

                self.active_positions[symbol] = {
                    "quantity": filled_qty,
                    "entry_price": fill_price,
                    "entry_time": time.time(),
                    "side": "SHORT",
                }

        except Exception as e:
            logger.error(f"Error handling fill: {e}", exc_info=True)

    def _check_position_exits(self) -> None:
        """Check if positions should be exited"""
        current_time = time.time()

        for symbol in list(self.active_positions.keys()):
            position = self.active_positions[symbol]

            # Get current price
            snapshot = self.data_feed.get_latest_snapshot(symbol)
            if not snapshot:
                continue

            # Calculate P&L
            if position["side"] == "LONG":
                pnl = (snapshot.mid - position["entry_price"]) * position["quantity"]
            else:  # SHORT
                pnl = (position["entry_price"] - snapshot.mid) * position["quantity"]

            pnl_bps = (pnl / (position["entry_price"] * position["quantity"])) * 10000

            # Check exit conditions
            should_exit = False
            exit_reason = ""

            # Time-based exit
            hold_time = current_time - position["entry_time"]
            max_hold = self.config["strategy"]["max_hold_seconds"]

            if hold_time >= max_hold:
                should_exit = True
                exit_reason = f"Max hold time ({max_hold}s)"

            # Profit target
            profit_target = self.config["risk"]["per_trade"]["profit_target_bps"]
            if pnl_bps >= profit_target:
                should_exit = True
                exit_reason = f"Profit target ({pnl_bps:.1f} bps)"

            # Stop loss
            max_loss = self.config["risk"]["per_trade"]["max_loss_bps"]
            if pnl_bps <= -max_loss:
                should_exit = True
                exit_reason = f"Stop loss ({pnl_bps:.1f} bps)"

            # Exit position
            if should_exit:
                self._exit_position(symbol, snapshot.mid, exit_reason)

    def _exit_position(self, symbol: str, exit_price: float, reason: str) -> None:
        """Exit a position"""
        try:
            if symbol not in self.active_positions:
                return

            position = self.active_positions[symbol]

            # Create exit order
            if position["side"] == "LONG":
                side = OrderSide.SELL
                limit_price = exit_price * 0.999  # Slightly below mid for quick fill
            else:
                side = OrderSide.BUY
                limit_price = exit_price * 1.001  # Slightly above mid

            order_request = OrderRequest(
                symbol=symbol,
                side=side,
                quantity=position["quantity"],
                price=limit_price,
                order_type=OrderType.IOC,
                time_in_force="IOC",
            )

            order_id = self.order_manager.place_order(order_request)

            if order_id:
                # Close position in risk manager
                realized_pnl = self.risk_manager.close_position(symbol, exit_price)

                # Check circuit breaker
                triggered, cb_reason = self.circuit_breaker.check_circuit_breaker(
                    realized_pnl
                )
                if triggered:
                    logger.critical(f"CIRCUIT BREAKER TRIGGERED: {cb_reason}")
                    self.is_running = False

                # Remove from active positions
                del self.active_positions[symbol]

                logger.info(
                    f"Exited position: {symbol} P&L=${realized_pnl:.2f} - {reason}"
                )
            else:
                logger.error(f"Failed to exit position: {symbol}")

        except Exception as e:
            logger.error(f"Error exiting position: {e}", exc_info=True)

    def _close_all_positions(self) -> None:
        """Close all open positions"""
        for symbol in list(self.active_positions.keys()):
            snapshot = self.data_feed.get_latest_snapshot(symbol)
            if snapshot:
                self._exit_position(symbol, snapshot.mid, "System shutdown")

    def _process_order_update(self, update) -> None:
        """Process order status update"""
        logger.debug(f"Order update: {update.symbol} {update.status}")

    def _monitor_loop(self) -> None:
        """Background monitoring loop"""
        while self.is_running:
            try:
                # Log system health every 60 seconds
                time.sleep(60)

                risk_metrics = self.risk_manager.get_risk_metrics(self.account_value)
                data_health = self.data_feed.health_check()
                order_health = self.order_manager.health_check()

                logger.info(
                    f"System Health - "
                    f"P&L: ${risk_metrics.daily_pnl:.2f}, "
                    f"Trades: {risk_metrics.daily_trades}, "
                    f"Positions: {len(risk_metrics.current_positions)}, "
                    f"Risk: {risk_metrics.risk_status.value}, "
                    f"Data: {data_health['connected']}, "
                    f"Orders: {order_health['connected']}"
                )

            except Exception as e:
                logger.error(f"Error in monitor loop: {e}")

    def _print_daily_summary(self) -> None:
        """Print daily trading summary"""
        logger.info("=" * 60)
        logger.info("DAILY SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Signals Generated: {self.signals_generated}")
        logger.info(f"Signals Traded: {self.signals_traded}")
        logger.info(
            f"Trade Rate: {100*self.signals_traded/max(1,self.signals_generated):.1f}%"
        )
        logger.info(f"Total Trades: {self.risk_manager.daily_trades}")
        logger.info(f"Daily P&L: ${self.risk_manager.daily_pnl:.2f}")
        logger.info("=" * 60)

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self.is_running = False


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="L2 Scalping System")
    parser.add_argument("--config", default="config", help="Configuration directory")
    args = parser.parse_args()

    # Create system
    system = ScalpingSystem(config_dir=args.config)

    # Start trading
    system.start()


if __name__ == "__main__":
    main()
