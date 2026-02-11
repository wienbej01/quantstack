"""L2 Scalping System - Main Trading Loop

Integrates signals, execution, and risk management for live scalping.
"""

import logging
import signal
import sys
import threading
import time
import uuid
from pathlib import Path

# Add parent directory to path for cpapi imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import yaml
from data.l2_feed import L2DataFeed, L2Snapshot
from execution.order_manager import (
    IBKROrderManager,
    OrderRequest,
    OrderSide,
    OrderType,
    PlaceOrderResult,
)
from exit_guard import ExitGuard
from fill_processor import FillProcessor
from order_tracker import OrderTracker

# Import new position tracking components
from position_manager import PositionManager
from reporting.performance_reporter import PerformanceReporter
from reporting.trade_journal import TradeJournal
from risk.risk_manager import CircuitBreaker, RiskManager
from scheduler import MarketScheduler

# Import system components
from signals.context_filter import ContextFeatureComputer, ContextFilter, TradeTier
from signals.l2_signals import L2SignalGenerator
from signals.l2_signals import L2Snapshot as SignalSnapshot
from signals.l2_signals import SignalValidator
from signals.pattern_rules import (
    MultiRuleSignalGenerator,
    ResistanceSignalGenerator,
    RuleName,
    SizeSignalGenerator,
)

from cpapi.audit_logger import get_audit_logger
from cpapi.emergency_alerts import EmergencyAlerts
from cpapi.margin_check import MarginChecker
from cpapi.shared_positions import SharedPositionLedger

# Import Trade Database V2
from cpapi.trade_integration import TradeIntegration

_audit = get_audit_logger("l2-scalping")

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
        self.signal_validator = SignalValidator(
            self.config["strategy"], self.config["risk"]
        )
        self.risk_manager = RiskManager(self.config["risk"])
        self.circuit_breaker = CircuitBreaker(self.config["risk"]["circuit_breaker"])
        self.order_manager = IBKROrderManager(self.config["ibkr"])

        # Context-aware filtering
        self.context_filter = ContextFilter(self.config["strategy"])
        self.context_computer = ContextFeatureComputer(lookback=30)

        # Pattern-based rules (new)
        self.multi_rule_generator = MultiRuleSignalGenerator(self.config["strategy"])

        # Size signal generator (large order detection)
        self.size_signal_generator = SizeSignalGenerator(self.config["strategy"])

        # Resistance signal generator (AAA quality trades)
        self.resistance_signal_generator = ResistanceSignalGenerator(
            self.config["strategy"]
        )

        # Data feed (production only - mock data must not be enabled)
        if self.config["strategy"].get("mock_data", {}).get("enabled", False):
            raise RuntimeError("Mock data is enabled - disable before paper trading")

        # Load symbols from daily SIP
        from data.sip_integration import get_scalping_symbols

        sip_symbols = get_scalping_symbols()

        if not sip_symbols:
            logger.warning(
                "No NYSE symbols available for L2 scalping - system will not trade"
            )
            # Create empty data feed to maintain system structure
            ibkr_config = self.config["ibkr"].copy()
            ibkr_config = dict(ibkr_config)
            ibkr_config["market_data"] = ibkr_config.get("market_data", {}).copy()
            ibkr_config["market_data"]["symbols"] = []
            self.data_feed = L2DataFeed(ibkr_config)
        else:
            # Update config with SIP symbols
            ibkr_config = self.config["ibkr"].copy()
            ibkr_config = dict(ibkr_config)
            ibkr_config["market_data"] = ibkr_config.get("market_data", {}).copy()
            ibkr_config["market_data"]["symbols"] = sip_symbols

            self.data_feed = L2DataFeed(ibkr_config)

        # Market scheduler
        self.scheduler = MarketScheduler(self.config["strategy"].get("schedule", {}))

        # Trade journal and reporting
        self.trade_journal = TradeJournal(data_dir="data")
        self.reporter = PerformanceReporter(reports_dir="logs")

        # New position tracking components
        self.position_manager = PositionManager()
        self.order_tracker = OrderTracker()
        # FillProcessor will be initialized after order_manager connection

        # Trade Database V2 integration (will be initialized after connection)
        self.trade_db = None

        # Exit retry circuit breaker
        self._alerts = EmergencyAlerts()
        self.exit_guard = ExitGuard(alert_fn=self._alerts.exit_failed)
        # Margin checker (initialized after connection)
        self.margin_checker: MarginChecker | None = None

        # Shared position ledger for cross-service awareness
        try:
            self.shared_ledger = SharedPositionLedger()
        except Exception:
            self.shared_ledger = None

        # System state
        self.is_running = False
        self.account_value = self.config["ibkr"]["account"].get(
            "initial_capital", 100000
        )
        self.risk_manager.account_value = self.account_value
        self.active_positions: dict[str, dict] = {}
        self.pending_entries: dict[int, dict] = {}
        self.scheduled_exits: dict[str, float] = {}  # symbol -> scheduled_exit_time
        self.eod_flattened = False
        self.active_trades: dict[str, int] = (
            {}
        )  # symbol -> trade_id (int) for Trade DB V2
        self._last_exit_check: float = 0.0  # rate-limit exit checks to 1/sec

        # Performance tracking
        self.trades_today = 0
        self.pnl_today = 0.0
        self.signals_generated = 0
        self.signals_traded = 0

        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        logger.info("Scalping System initialized")

    def _generate_trade_id(self) -> str:
        """Generate unique trade ID"""
        return f"l2_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

    def _can_open_position(self, symbol: str) -> bool:
        """Check if we can open a new position using new position manager"""
        # Only check our own tracked positions, not global IBKR positions
        # This allows multiple strategies to trade the same symbol independently

        # Check new position manager
        if self.position_manager.has_open_position(symbol):
            return False
        if self.position_manager.has_pending_entry(symbol):
            return False

        # Also check legacy active positions for backward compatibility
        if symbol in self.active_positions:
            return False

        return True

    def _load_config(self) -> dict:
        """Load all configuration files"""
        config = {}

        config_files = {
            "strategy": "strategy.yaml",
            "risk": "risk.yaml",
            "ibkr": "ibkr.yaml",
        }

        for key, filename in config_files.items():
            filepath = self.config_dir / filename
            with open(filepath) as f:
                config[key] = yaml.safe_load(f)

        logger.info(f"Loaded configuration from {self.config_dir}")
        return config

    def _build_signal_id(self, rule_name: str, symbol: str) -> str:
        """Build a stable signal id for decision/trade linking."""
        return f"l2_{rule_name}_{symbol}_{int(time.time() * 1000)}"

    def _decision_thresholds(self, rule_name: str) -> dict:
        strategy_cfg = self.config.get("strategy", {})
        if rule_name == RuleName.OBI_MOMENTUM.value:
            return {
                "obi_entry_threshold": strategy_cfg.get("obi_entry_threshold", 0.3),
                "obi_extreme_threshold": strategy_cfg.get("obi_extreme_threshold", 0.6),
            }

        rules_cfg = strategy_cfg.get("pattern_rules", {})
        if rule_name == RuleName.OBI_DEPTH_COMBO.value:
            return {
                "d_obi_1_30s": rules_cfg.get("rule1_d_obi_30s", 0.2),
                "depth_ask": rules_cfg.get("rule1_depth_ask", 25000),
            }
        if rule_name == RuleName.BID_DEPTH_OBI.value:
            return {
                "depth_bid": rules_cfg.get("rule2_depth_bid", 20000),
                "d_obi_1_15s": rules_cfg.get("rule2_d_obi_15s", 0.1),
            }
        if rule_name == RuleName.HIGH_OBI_DEPTH.value:
            return {
                "obi_1": rules_cfg.get("rule3_obi_1", 0.1),
                "depth_ask": rules_cfg.get("rule3_depth_ask", 30000),
            }
        return {}

    def _max_hold_seconds(self) -> int:
        """Resolve max hold seconds from nested or flat strategy config."""
        strategy_cfg = self.config.get("strategy", {})
        if isinstance(strategy_cfg, dict) and "strategy" in strategy_cfg:
            strategy_cfg = strategy_cfg.get("strategy", {}) or {}
        max_hold = strategy_cfg.get("max_hold_seconds")
        if max_hold is None:
            max_hold = strategy_cfg.get("default_hold_seconds", 600)
        return int(max_hold)

    def _entry_order_type(self) -> str:
        orders_cfg = self.config.get("ibkr", {}).get("orders", {})
        return str(orders_cfg.get("entry_order_type", "IOC")).upper()

    def _check_margin_gates(
        self, symbol: str, quantity: int, price: float, side: str
    ) -> tuple[bool, str]:
        """Run margin check + global margin budget check before entry.

        Returns (allowed, reason).
        """
        # Individual margin check via IBKR whatIfOrder
        if self.margin_checker:
            try:
                from ib_insync import MarketOrder, Stock

                contract = Stock(symbol, "SMART", "USD")
                order = MarketOrder(side, quantity)
                result = self.margin_checker.check(contract, order, symbol)
                if not result.allowed:
                    return False, f"Margin check: {result.reason}"
                margin_impact = abs(result.margin_impact)
            except Exception as e:
                logger.error("Margin check error (BLOCKING trade): %s", e)
                return False, f"Margin check failed: {e}"
        else:
            margin_impact = price * quantity * 0.25

        # Global margin budget check across all services
        if self.shared_ledger:
            try:
                allowed, reason = self.shared_ledger.check_global_margin(
                    margin_impact, self.account_value
                )
                if not allowed:
                    return False, f"Global margin: {reason}"
            except Exception as e:
                logger.debug("Global margin check unavailable: %s", e)

        return True, "OK"

    def _compute_exit_prices(
        self,
        entry_price: float,
        side: str,
        max_loss_bps: float,
        profit_target_bps: float,
        tick_size: float,
    ) -> tuple[float, float]:
        from cpapi.utils import round_to_tick_size

        if side == "BUY":
            stop_loss_price = round_to_tick_size(
                entry_price * (1 - max_loss_bps / 10000), tick_size
            )
            profit_target_price = round_to_tick_size(
                entry_price * (1 + profit_target_bps / 10000), tick_size
            )
        else:
            stop_loss_price = round_to_tick_size(
                entry_price * (1 + max_loss_bps / 10000), tick_size
            )
            profit_target_price = round_to_tick_size(
                entry_price * (1 - profit_target_bps / 10000), tick_size
            )
        return stop_loss_price, profit_target_price

    def _log_trade_decision(
        self,
        symbol: str,
        direction: str,
        rule_name: str,
        signal_strength: float,
        signal_confidence: float,
        signal_id: str,
        snapshot: L2Snapshot,
        ctx: object | None,
        ctx_result: object | None,
        quantity: int,
        extended_snapshot: object | None = None,
        signal_meta: dict | None = None,
    ) -> None:
        if not hasattr(self.trade_journal, "record_decision"):
            return

        features: dict = {
            "signal_id": signal_id,
            "rule_name": rule_name,
            "signal_strength": signal_strength,
            "signal_confidence": signal_confidence,
            "quantity": quantity,
            "snapshot": {
                "timestamp": snapshot.timestamp,
                "mid": snapshot.mid,
                "spread": snapshot.spread,
                "obi_1": snapshot.obi_1,
                "obi_5": snapshot.obi_5,
                "depth_bid": snapshot.depth_bid,
                "depth_ask": snapshot.depth_ask,
                "pressure": snapshot.pressure,
            },
            "thresholds": self._decision_thresholds(rule_name),
        }

        if signal_meta:
            features["signal_meta"] = signal_meta

        if extended_snapshot is not None:
            features["deltas"] = {
                "d_obi_1_5s": getattr(extended_snapshot, "d_obi_1_5s", 0.0),
                "d_obi_1_15s": getattr(extended_snapshot, "d_obi_1_15s", 0.0),
                "d_obi_1_30s": getattr(extended_snapshot, "d_obi_1_30s", 0.0),
                "d_mid_5s": getattr(extended_snapshot, "d_mid_5s", 0.0),
                "d_mid_30s": getattr(extended_snapshot, "d_mid_30s", 0.0),
            }

        if ctx is not None:
            features["context"] = {
                "rel_vol": ctx.rel_vol,
                "rsi_14": ctx.rsi_14,
                "vol_expansion": ctx.vol_expansion,
                "vol_contraction": ctx.vol_contraction,
                "bb_squeeze": ctx.bb_squeeze,
                "displacement_up": ctx.displacement_up,
                "displacement_down": ctx.displacement_down,
                "mom_15": ctx.mom_15,
            }

        if ctx_result is not None:
            features["context_result"] = {
                "tier": ctx_result.tier.name,
                "size_multiplier": ctx_result.size_multiplier,
                "reasons": ctx_result.reasons,
            }

        self.trade_journal.record_decision(
            symbol=symbol,
            strategy=f"l2_scalping_{rule_name}",
            direction=direction,
            signal_strength=signal_strength,
            decision="TRADE",
            features=features,
        )

    def start(self) -> None:
        """Start the trading system with automatic scheduling"""
        logger.info("=" * 60)
        logger.info("STARTING L2 SCALPING SYSTEM")
        logger.info("=" * 60)

        # Check if auto-start is enabled
        if self.scheduler.auto_start:
            logger.info("Auto-start enabled - will wait for market hours")
            self.scheduler.run_with_schedule(self._run_trading_session)
        else:
            logger.info("Manual mode - starting immediately")
            self._run_trading_session()

    def _run_trading_session(self) -> None:
        """Run a single trading session"""
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

        # Initialize Trade Database V2
        try:
            self.trade_db = TradeIntegration(
                ib=self.order_manager.session.ib,
                system_name="l2-scalping",
                ib_call=self.order_manager.session.call,
            )
            self.trade_db.start()
            logger.info("Trade Database V2 initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Trade Database V2: {e}")
            self.data_feed.disconnect()
            self.order_manager.disconnect()
            return

        # Initialize margin checker
        try:
            self.margin_checker = MarginChecker(
                ib_what_if_fn=self.order_manager._order_manager.what_if
            )
            logger.info("Margin checker initialized")
        except Exception as e:
            logger.warning(f"Margin checker init failed (will skip margin checks): {e}")
            self.margin_checker = None

        # Initialize FillProcessor after connections are established
        self.fill_processor = FillProcessor(
            position_manager=self.position_manager,
            order_tracker=self.order_tracker,
            ib_client=self.order_manager.session.ib,  # Access IB client from order manager session
            contracts=self.data_feed.contracts,  # Access contracts from data feed
            tp_pct=self.config["strategy"].get("profit_target_bps", 20) / 10000,
            sl_pct=self.config["strategy"].get("max_loss_bps", 10) / 10000,
            min_cancel_interval_sec=float(
                self.config.get("ibkr", {})
                .get("orders", {})
                .get("min_cancel_interval_sec", 2.0)
            ),
        )

        # Register data callback
        self.data_feed.add_data_callback(self._on_market_data)

        # Register fill callback
        self.order_manager.add_fill_callback(self._on_order_fill)

        # Register order status callback (if available)
        if hasattr(self.order_manager, "add_order_status_callback"):
            self.order_manager.add_order_status_callback(self._on_order_status)

        # Sync existing IBKR positions to active_positions
        self._sync_ibkr_positions()

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

                # Dispatch fill callbacks on the main thread
                self.order_manager.process_fills()

                # End-of-day flatten safety
                self._check_eod_flatten()

                # Check positions for exits (rate-limited to 1/sec)
                now = time.time()
                if now - self._last_exit_check >= 1.0:
                    self._last_exit_check = now
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

        # Stop Trade Database V2
        if self.trade_db:
            try:
                self.trade_db.stop()
                logger.info("Trade Database V2 stopped")
            except Exception as e:
                logger.error(f"Error stopping Trade DB V2: {e}")

        # Disconnect
        self.data_feed.disconnect()
        self.order_manager.disconnect()

        # Clear shared position ledger for this service
        if self.shared_ledger:
            try:
                self.shared_ledger.clear_service("l2-scalping")
            except Exception as e:
                logger.debug("Shared ledger cleanup failed: %s", e)

        # Print final stats
        self._print_daily_summary()

        logger.info("System stopped")

    def _on_market_data(self, snapshot: L2Snapshot) -> None:
        """Handle incoming market data"""
        try:
            # Update context computer with snapshot data (builds 1-min bars)
            self.context_computer.update_from_snapshot(
                symbol=snapshot.symbol,
                mid=snapshot.mid,
                volume=snapshot.bid_size + snapshot.ask_size,  # Proxy for volume
                timestamp=snapshot.timestamp,
            )

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

            # Block if entry order is pending (prevents race condition accumulation)
            if any(p["symbol"] == snapshot.symbol for p in self.pending_entries.values()):
                return

            # Hard cap: block ALL entries if total IBKR exposure exceeds 10% of account
            if hasattr(self, '_ibkr_exposure_pct') and self._ibkr_exposure_pct > 0.10:
                return

            # Block new entries near EOD or after flatten trigger
            if self.eod_flattened or self.scheduler.is_entry_cutoff_reached():
                return

            # === ORIGINAL OBI MOMENTUM RULE ===
            signal = self.signal_generator.generate_signal(signal_snapshot)
            self.signals_generated += 1

            # Record signal in journal
            self.trade_journal.record_signal(
                symbol=signal.symbol,
                signal_type=signal.signal_type.name,
                signal_strength=signal.confidence,
            )

            # Validate signal
            is_valid, reason = self.signal_validator.is_valid_signal(
                signal, signal_snapshot
            )

            if is_valid and signal.signal_type.value != 0:
                # Check context gates
                ctx = self.context_computer.compute(snapshot.symbol)
                if ctx is not None:
                    ctx_result = self.context_filter.evaluate(
                        ctx, signal.signal_type.value
                    )
                    if ctx_result.tier == TradeTier.BLOCKED:
                        logger.info(
                            f"Trade BLOCKED [{snapshot.symbol}]: {ctx_result.reasons}"
                        )
                    else:
                        # Execute original OBI momentum rule
                        self._execute_signal(
                            signal,
                            snapshot,
                            RuleName.OBI_MOMENTUM,
                            ctx,
                            ctx_result,
                        )

            # === NEW PATTERN-BASED RULES ===
            extended_snap = self.multi_rule_generator.create_extended_snapshot(
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

            pattern_signals = self.multi_rule_generator.generate_pattern_signals(
                extended_snap
            )

            # === SIZE SIGNAL (large order detection) ===
            size_signal = self.size_signal_generator.generate_signal(
                symbol=snapshot.symbol,
                timestamp=snapshot.timestamp,
                depth_bid=snapshot.depth_bid,
                depth_ask=snapshot.depth_ask,
                mid_price=snapshot.mid,
            )
            if size_signal:
                pattern_signals.append(size_signal)

            # === RESISTANCE SIGNAL (AAA quality trades) ===
            # Compute depth imbalance
            depth_total = snapshot.depth_bid + snapshot.depth_ask
            depth_imbalance = (
                (snapshot.depth_bid - snapshot.depth_ask) / depth_total
                if depth_total > 0
                else 0.0
            )

            # Get 99th percentile threshold for large order detection
            large_order_threshold = (
                self.size_signal_generator._get_percentile_threshold(
                    snapshot.symbol, "ask"
                )
            )
            if large_order_threshold is None:
                # During warmup, use price-based estimate
                large_order_threshold = (
                    self.size_signal_generator._get_warmup_threshold(snapshot.symbol)
                )

            resistance_signal = self.resistance_signal_generator.generate_signal(
                symbol=snapshot.symbol,
                timestamp=snapshot.timestamp,
                price=snapshot.mid,
                depth_ask=snapshot.depth_ask,
                depth_imbalance=depth_imbalance,
                large_order_threshold=large_order_threshold,
            )
            if resistance_signal:
                pattern_signals.append(resistance_signal)

            for rule_signal in pattern_signals:
                # Skip if we already have a position or pending entry
                if snapshot.symbol in self.active_positions:
                    break
                if any(p["symbol"] == snapshot.symbol for p in self.pending_entries.values()):
                    break
                if hasattr(self, '_ibkr_exposure_pct') and self._ibkr_exposure_pct > 0.10:
                    break

                # Check context gates for pattern rules too
                ctx = self.context_computer.compute(snapshot.symbol)
                ctx_result = None
                if ctx is not None:
                    ctx_result = self.context_filter.evaluate(
                        ctx, rule_signal.direction
                    )
                    if ctx_result.tier == TradeTier.BLOCKED:
                        logger.debug(
                            f"Pattern rule BLOCKED [{rule_signal.rule_name.value}]: {ctx_result.reasons}"
                        )
                        continue

                # Execute pattern rule signal
                self._execute_pattern_signal(
                    rule_signal,
                    snapshot,
                    extended_snap,
                    ctx,
                    ctx_result,
                )

        except Exception as e:
            logger.error(f"Error processing market data: {e}", exc_info=True)

    def _execute_signal(
        self,
        signal,
        snapshot: L2Snapshot,
        rule_name: RuleName = RuleName.OBI_MOMENTUM,
        ctx: object | None = None,
        ctx_result: object | None = None,
    ) -> None:
        """Execute trading signal"""
        try:
            # Check if we can open a new position (new position tracking)
            if not self._can_open_position(signal.symbol):
                logger.debug(
                    f"Cannot open position for {signal.symbol} - existing position or pending entry"
                )
                return

            # Check entry curfew
            max_hold = self._max_hold_seconds()
            can_open, curfew_reason = self.scheduler.can_open_new_position(max_hold)
            if not can_open:
                logger.info(f"Entry blocked by curfew: {curfew_reason}")
                return

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

            # Ensure minimum quantity
            if quantity < 1:
                logger.debug(f"Quantity too small: {quantity}")
                return

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

            # Margin + global margin budget check
            side_str = "BUY" if signal.signal_type.value > 0 else "SELL"
            margin_ok, margin_reason = self._check_margin_gates(
                signal.symbol, quantity, snapshot.mid, side_str
            )
            if not margin_ok:
                logger.warning(f"Entry blocked by margin gate: {margin_reason}")
                return

            orders_cfg = self.config["ibkr"]["orders"]
            entry_order_type = self._entry_order_type()
            exit_price_source = str(
                orders_cfg.get("exit_price_source", "signal")
            ).lower()
            use_fill_exits = exit_price_source == "fill"
            use_ioc = entry_order_type == "IOC"
            use_market = entry_order_type == "MKT"
            improvement_ticks = orders_cfg.get("ioc_price_improvement_ticks", 0)
            tick_size = orders_cfg.get("tick_size", 0.01)
            price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

            logger.info(
                "ENTRY Config: type=%s, improvement_ticks=%s, tick_size=%s, price_improvement=%.4f",
                entry_order_type,
                improvement_ticks,
                tick_size,
                price_improvement,
            )

            # Determine order side and price
            # For BUY: Add buffer ABOVE signal price to ensure fill if market moves up
            # For SELL: Add buffer BELOW signal price to ensure fill if market moves down
            if signal.signal_type.value > 0:  # Long
                side = OrderSide.BUY
                limit_price = None if use_market else snapshot.ask + price_improvement
            else:  # Short
                side = OrderSide.SELL
                limit_price = None if use_market else snapshot.bid - price_improvement

            stop_loss_price = None
            profit_target_price = None
            if use_market:
                logger.info(
                    "MKT order: %s %s qty=%s", signal.symbol, side.value, quantity
                )
            else:
                logger.info(
                    "%s order: %s limit_price=%.4f",
                    entry_order_type,
                    side.value,
                    limit_price,
                )

            if not use_fill_exits:
                entry_price_for_exits = (
                    limit_price
                    if limit_price is not None
                    else (snapshot.ask if side == OrderSide.BUY else snapshot.bid)
                )
                stop_loss_price, profit_target_price = self._compute_exit_prices(
                    entry_price=entry_price_for_exits,
                    side=side.value,
                    max_loss_bps=self.config["risk"]["per_trade"]["max_loss_bps"],
                    profit_target_bps=self.config["risk"]["per_trade"][
                        "profit_target_bps"
                    ],
                    tick_size=tick_size,
                )

            # Log price improvement if applied
            if price_improvement > 0:
                logger.debug(
                    f"IOC price improvement: {price_improvement:.4f} ({improvement_ticks} ticks)"
                )

            # Build signal id for correlation and logging
            signal_id = self._build_signal_id(rule_name.value, signal.symbol)
            self._log_trade_decision(
                symbol=signal.symbol,
                direction="long" if signal.signal_type.value > 0 else "short",
                rule_name=rule_name.value,
                signal_strength=signal.strength,
                signal_confidence=signal.confidence,
                signal_id=signal_id,
                snapshot=snapshot,
                ctx=ctx,
                ctx_result=ctx_result,
                quantity=quantity,
                signal_meta={
                    "signal_type": signal.signal_type.name,
                    "hidden_liquidity": signal.hidden_liquidity.value,
                    "execution_window": signal.execution_window,
                    "thin_book_warning": signal.thin_book_warning,
                    "median_spread": signal.median_spread,
                    "calibration_points": signal.calibration_points,
                },
            )

            # Create order request with bracket orders
            order_request = OrderRequest(
                symbol=signal.symbol,
                side=side,
                quantity=quantity,
                price=limit_price,
                order_type=(
                    OrderType.MKT
                    if use_market
                    else (OrderType.IOC if use_ioc else OrderType.LIMIT)
                ),
                time_in_force=None if use_market else ("IOC" if use_ioc else "DAY"),
                client_order_id=self._build_order_ref(
                    signal.symbol, "ENTRY", side.value, rule_name.value
                ),
                stop_loss_price=stop_loss_price,
                profit_target_price=profit_target_price,
            )

            # Place order
            order_id = self.order_manager.place_order(order_request)

            if order_id:
                # Generate trade ID and create position tracking
                trade_id = self._generate_trade_id()

                # Open trade in Trade Database V2
                db_trade_id = None
                if self.trade_db:
                    try:
                        db_trade_id = self.trade_db.open_trade(
                            symbol=signal.symbol,
                            direction="LONG" if side == OrderSide.BUY else "SHORT",
                            signal_price=snapshot.mid,
                            stop_loss=stop_loss_price,
                            take_profit=profit_target_price,
                            metadata={
                                "rule": rule_name.value,
                                "strength": signal.strength,
                                "confidence": signal.confidence,
                                "legacy_trade_id": trade_id,
                            },
                        )
                        self.trade_db.link_order(
                            db_trade_id, int(order_id), is_entry=True
                        )
                        # Link bracket child orders (stop/target) for exit fills
                        children = self.order_manager.get_bracket_children(order_id)
                        stop_id = children.get("stop_id")
                        target_id = children.get("target_id")
                        if stop_id:
                            self.trade_db.link_order(
                                db_trade_id, int(stop_id), is_entry=False
                            )
                        if target_id:
                            self.trade_db.link_order(
                                db_trade_id, int(target_id), is_entry=False
                            )
                        self.active_trades[signal.symbol] = db_trade_id
                        logger.info(f"Trade DB V2: opened trade_id={db_trade_id}")
                    except Exception as e:
                        logger.error(f"Failed to record trade in DB V2: {e}")

                # Create position in new position manager
                position = self.position_manager.create_position(
                    entry_order_id=order_id,
                    trade_id=trade_id,
                    symbol=signal.symbol,
                    direction="long" if side == OrderSide.BUY else "short",
                    target_qty=quantity,
                )

                # Track order in new order tracker
                self.order_tracker.add_order(
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=signal.symbol,
                    intent="ENTRY",
                    side=side.value,
                    quantity=quantity,
                    order_type=order_request.order_type.value,
                    limit_price=limit_price if limit_price else 0.0,
                )

                self.signals_traded += 1
                improvement_str = (
                    f" +{price_improvement:.4f}" if price_improvement > 0 else ""
                )
                price_str = (
                    "MKT" if use_market else f"{limit_price:.4f}{improvement_str}"
                )
                stop_str = (
                    "N/A" if stop_loss_price is None else f"{stop_loss_price:.4f}"
                )
                target_str = (
                    "N/A"
                    if profit_target_price is None
                    else f"{profit_target_price:.4f}"
                )
                logger.info(
                    f"TRADE [{rule_name.value}]: {signal.symbol} {side.value} {quantity}@{price_str} "
                    f"[stop={stop_str}, target={target_str}] trade_id={trade_id[:8]}"
                )
                _audit.trade_open(
                    signal.symbol,
                    side.value,
                    quantity,
                    limit_price or snapshot.mid,
                    trade_id,
                )

                # Maintain legacy pending_entries for backward compatibility
                self.pending_entries[str(order_id)] = {
                    "symbol": signal.symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "rule_name": rule_name.value,
                    "signal_id": signal_id,
                    "signal_price": (
                        snapshot.ask if side == OrderSide.BUY else snapshot.bid
                    ),
                    "entry_order_type": entry_order_type,
                    "exit_price_source": exit_price_source,
                    "tick_size": tick_size,
                    "max_loss_bps": self.config["risk"]["per_trade"]["max_loss_bps"],
                    "profit_target_bps": self.config["risk"]["per_trade"][
                        "profit_target_bps"
                    ],
                    "filled_qty": 0,
                    "total_value": 0.0,
                    "exit_order_ids": [],
                    "exit_order_qty": 0,
                }
            else:
                logger.error(f"Failed to place order for {signal.symbol}")

        except Exception as e:
            logger.error(f"Error executing signal: {e}", exc_info=True)

    def _execute_pattern_signal(
        self,
        rule_signal,
        snapshot: L2Snapshot,
        extended_snapshot: object | None = None,
        ctx: object | None = None,
        ctx_result: object | None = None,
    ) -> None:
        """Execute pattern rule signal"""
        try:
            # Check if we can open a new position (new position tracking)
            if not self._can_open_position(snapshot.symbol):
                logger.debug(
                    f"Cannot open position for {snapshot.symbol} - existing position or pending entry"
                )
                return

            # Check entry curfew
            max_hold = self._max_hold_seconds()
            can_open, curfew_reason = self.scheduler.can_open_new_position(max_hold)
            if not can_open:
                logger.info(f"Entry blocked by curfew: {curfew_reason}")
                return

            # Check risk limits
            should_stop, reason = self.risk_manager.should_stop_trading()
            if should_stop:
                logger.warning(f"Trading stopped: {reason}")
                return

            # Calculate position size based on rule confidence
            quantity = self.risk_manager.calculate_position_size(
                symbol=snapshot.symbol,
                signal_strength=rule_signal.strength,
                confidence=rule_signal.confidence,
                account_value=self.account_value,
                price=snapshot.mid,
            )

            # Ensure minimum quantity
            if quantity < 1:
                logger.debug(f"Quantity too small: {quantity}")
                return

            # Pre-trade risk check
            can_trade, reason = self.risk_manager.check_pre_trade_risk(
                symbol=snapshot.symbol,
                quantity=quantity,
                price=snapshot.mid,
                account_value=self.account_value,
            )

            if not can_trade:
                logger.info(f"Trade rejected: {reason}")
                return

            # Margin + global margin budget check
            side_str = "BUY" if rule_signal.direction > 0 else "SELL"
            margin_ok, margin_reason = self._check_margin_gates(
                snapshot.symbol, quantity, snapshot.mid, side_str
            )
            if not margin_ok:
                logger.warning(f"Entry blocked by margin gate: {margin_reason}")
                return

            # Determine risk parameters (AAA signals get special treatment)
            is_aaa = rule_signal.confidence >= 0.90
            if is_aaa:
                max_loss_bps = self.config["risk"]["per_trade"]["aaa_max_loss_bps"]
                profit_target_bps = self.config["risk"]["per_trade"][
                    "aaa_profit_target_bps"
                ]
                quantity = min(
                    int(
                        quantity
                        * self.config["risk"]["per_trade"]["aaa_size_multiplier"]
                    ),
                    self.risk_manager.max_shares,
                )
            else:
                max_loss_bps = self.config["risk"]["per_trade"]["max_loss_bps"]
                profit_target_bps = self.config["risk"]["per_trade"][
                    "profit_target_bps"
                ]

            orders_cfg = self.config["ibkr"]["orders"]
            exit_price_source = str(
                orders_cfg.get("exit_price_source", "signal")
            ).lower()
            use_fill_exits = exit_price_source == "fill"
            entry_order_type = self._entry_order_type()
            use_ioc = entry_order_type == "IOC"
            use_market = entry_order_type == "MKT"
            improvement_ticks = orders_cfg.get("ioc_price_improvement_ticks", 0)
            tick_size = orders_cfg.get("tick_size", 0.01)
            price_improvement = improvement_ticks * tick_size if use_ioc else 0.0

            logger.info(
                "[RULE] ENTRY Config: type=%s, improvement_ticks=%s, tick_size=%s, price_improvement=%.4f",
                entry_order_type,
                improvement_ticks,
                tick_size,
                price_improvement,
            )

            # Determine order side and price
            # For BUY: Add buffer ABOVE signal price to ensure fill if market moves up
            # For SELL: Add buffer BELOW signal price to ensure fill if market moves down
            if rule_signal.direction > 0:  # Long
                side = OrderSide.BUY
                limit_price = None if use_market else snapshot.ask + price_improvement
            else:  # Short
                side = OrderSide.SELL
                limit_price = None if use_market else snapshot.bid - price_improvement

            stop_loss_price = None
            profit_target_price = None
            if use_market:
                logger.info(
                    "[RULE] MKT order: %s %s qty=%s",
                    snapshot.symbol,
                    side.value,
                    quantity,
                )
            else:
                logger.info(
                    "[RULE] %s order: %s limit_price=%.4f",
                    entry_order_type,
                    side.value,
                    limit_price,
                )

            if not use_fill_exits:
                entry_price_for_exits = (
                    limit_price
                    if limit_price is not None
                    else (snapshot.ask if side == OrderSide.BUY else snapshot.bid)
                )
                stop_loss_price, profit_target_price = self._compute_exit_prices(
                    entry_price=entry_price_for_exits,
                    side=side.value,
                    max_loss_bps=max_loss_bps,
                    profit_target_bps=profit_target_bps,
                    tick_size=tick_size,
                )

            # Build signal id for correlation and logging
            signal_id = self._build_signal_id(
                rule_signal.rule_name.value, snapshot.symbol
            )
            self._log_trade_decision(
                symbol=snapshot.symbol,
                direction="long" if rule_signal.direction > 0 else "short",
                rule_name=rule_signal.rule_name.value,
                signal_strength=rule_signal.strength,
                signal_confidence=rule_signal.confidence,
                signal_id=signal_id,
                snapshot=snapshot,
                ctx=ctx,
                ctx_result=ctx_result,
                quantity=quantity,
                extended_snapshot=extended_snapshot,
                signal_meta={"reason": rule_signal.reason},
            )

            # Create order request with bracket orders
            order_request = OrderRequest(
                symbol=snapshot.symbol,
                side=side,
                quantity=quantity,
                price=limit_price,
                order_type=(
                    OrderType.MKT
                    if use_market
                    else (OrderType.IOC if use_ioc else OrderType.LIMIT)
                ),
                time_in_force=None if use_market else ("IOC" if use_ioc else "DAY"),
                client_order_id=self._build_order_ref(
                    snapshot.symbol, "ENTRY", side.value, rule_signal.rule_name.value
                ),
                stop_loss_price=stop_loss_price,
                profit_target_price=profit_target_price,
            )

            # Place order
            order_id = self.order_manager.place_order(order_request)

            if order_id:
                # Generate trade ID and create position tracking
                trade_id = self._generate_trade_id()

                # Create position in new position manager
                position = self.position_manager.create_position(
                    entry_order_id=order_id,
                    trade_id=trade_id,
                    symbol=snapshot.symbol,
                    direction="long" if rule_signal.direction > 0 else "short",
                    target_qty=quantity,
                )

                # Track order in new order tracker
                self.order_tracker.add_order(
                    order_id=order_id,
                    trade_id=trade_id,
                    symbol=snapshot.symbol,
                    intent="ENTRY",
                    side=side.value,
                    quantity=quantity,
                    order_type=order_request.order_type.value,
                    limit_price=limit_price if limit_price else 0.0,
                )

                self.signals_traded += 1
                price_str = "MKT" if use_market else f"{limit_price:.4f}"
                stop_str = (
                    "N/A" if stop_loss_price is None else f"{stop_loss_price:.4f}"
                )
                target_str = (
                    "N/A"
                    if profit_target_price is None
                    else f"{profit_target_price:.4f}"
                )
                logger.info(
                    f"TRADE [{rule_signal.rule_name.value}]: {snapshot.symbol} {side.value} "
                    f"{quantity}@{price_str} [stop={stop_str}, target={target_str}] ({rule_signal.reason}) trade_id={trade_id[:8]}"
                )

                # Maintain legacy pending_entries for backward compatibility
                self.pending_entries[str(order_id)] = {
                    "symbol": snapshot.symbol,
                    "side": side.value,
                    "quantity": quantity,
                    "rule_name": rule_signal.rule_name.value,
                    "signal_id": signal_id,
                    "signal_price": (
                        snapshot.ask if side == OrderSide.BUY else snapshot.bid
                    ),
                    "entry_order_type": entry_order_type,
                    "exit_price_source": exit_price_source,
                    "tick_size": tick_size,
                    "max_loss_bps": max_loss_bps,
                    "profit_target_bps": profit_target_bps,
                    "filled_qty": 0,
                    "total_value": 0.0,
                    "exit_order_ids": [],
                    "exit_order_qty": 0,
                }
            else:
                logger.error(f"Failed to place order for {snapshot.symbol}")

        except Exception as e:
            logger.error(f"Error executing pattern signal: {e}", exc_info=True)

    def _on_order_fill(self, trade, fill) -> None:
        """Handle order fill using new FillProcessor"""
        try:
            symbol = trade.contract.symbol
            filled_qty = int(fill.execution.shares)
            fill_price = fill.execution.price
            side = fill.execution.side
            order_id = int(trade.order.orderId)

            logger.info(f"Order filled: {symbol} {side} {filled_qty}@{fill_price:.4f}")

            # Get tracked order to determine trade_id
            tracked_order = self.order_tracker.get_order(order_id)
            if not tracked_order:
                logger.warning(
                    f"Fill for untracked order {order_id} - using legacy handler"
                )
                self._legacy_fill_handler(trade, fill)
                return

            # Process through new FillProcessor
            is_partial = filled_qty < tracked_order.quantity
            self.fill_processor.process_fill(
                order_id=order_id,
                trade_id=tracked_order.trade_id,
                symbol=symbol,
                side=side,
                qty=filled_qty,
                price=fill_price,
                is_partial=is_partial,
            )

            # Record fill to journal (maintain existing functionality)
            commission = 0.0
            exchange = ""
            exec_id = ""
            realized_pnl = 0.0
            if getattr(fill, "commissionReport", None):
                commission = fill.commissionReport.commission or 0.0
                realized_pnl = fill.commissionReport.realizedPNL or 0.0
            if getattr(fill, "execution", None):
                exchange = fill.execution.exchange or ""
                exec_id = fill.execution.execId or ""

            if hasattr(self.trade_journal, "record_fill"):
                self.trade_journal.record_fill(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=filled_qty,
                    price=fill_price,
                    commission=float(commission or 0.0),
                    exchange=exchange,
                    exec_id=exec_id,
                    realized_pnl=float(realized_pnl or 0.0),
                )

        except Exception as e:
            logger.error(f"Error processing fill: {e}", exc_info=True)

    def _extract_rule_from_ref(self, order_ref: str) -> str:
        """Extract rule name from order reference.

        Example: 'L2SCALP_high_obi_depth_ENTRY_BUY_JOBY_...' -> 'high_obi_depth'
        """
        if not order_ref or "L2SCALP_" not in order_ref:
            return "unknown"

        parts = order_ref.split("_")
        if len(parts) >= 3:
            # L2SCALP_<rule_name>_ENTRY/EXIT_...
            return parts[1]
        return "unknown"

    def _determine_exit_reason(self, order_ref: str) -> str:
        """Determine exit reason from order reference."""
        if "STOP" in order_ref or "SL" in order_ref:
            return "STOP_LOSS"
        elif "TARGET" in order_ref or "TP" in order_ref:
            return "TAKE_PROFIT"
        elif "TIMEOUT" in order_ref or "MAX_HOLD" in order_ref:
            return "MAX_HOLD_TIME"
        elif "EXIT" in order_ref:
            return "SIGNAL_EXIT"
        return "MANUAL"

    def _legacy_fill_handler(self, trade, fill) -> None:
        """Legacy fill handler for backward compatibility"""
        try:
            symbol = trade.contract.symbol
            filled_qty = int(fill.execution.shares)
            fill_price = float(fill.execution.price)
            side = fill.execution.side
            order_id = str(trade.order.orderId)
            order_ref = getattr(trade.order, "orderRef", "") or ""

            # Entry fill (legacy logic)
            if order_id in self.pending_entries:
                pending = self.pending_entries[order_id]
                fill_qty = int(filled_qty)
                pending["filled_qty"] += fill_qty
                pending["total_value"] += float(fill_qty) * float(fill_price)
                entry_side = pending["side"]
                expected_qty = int(pending["quantity"])
                avg_fill_price = (
                    pending["total_value"] / pending["filled_qty"]
                    if pending["filled_qty"]
                    else float(fill_price)
                )

                # Check if fully filled
                order_filled = getattr(trade.orderStatus, "filled", 0) or 0
                total_qty = (
                    getattr(trade.order, "totalQuantity", expected_qty) or expected_qty
                )
                remaining = getattr(trade.orderStatus, "remaining", None)
                status = str(getattr(trade.orderStatus, "status", "") or "")
                fully_filled = pending["filled_qty"] >= expected_qty or float(
                    order_filled
                ) >= float(total_qty)
                terminal = status in {"Cancelled", "Inactive", "ApiCancelled"} or (
                    remaining is not None and float(remaining) == 0.0
                )

                if fully_filled or terminal:
                    self.pending_entries.pop(order_id, None)
                    logger.info(
                        f"Legacy entry fill completed: {symbol} {filled_qty}@{fill_price}"
                    )

                    # Record trade entry to database
                    rule_name = self._extract_rule_from_ref(order_ref)
                    try:
                        trade_id = self.trade_journal.record_trade_entry(
                            symbol=symbol,
                            side=entry_side,
                            quantity=expected_qty,
                            entry_price=avg_fill_price,
                            order_id=order_id,
                            rule_name=rule_name,
                            signal_id=f"l2_{rule_name}_{symbol}_{int(time.time())}",
                            signal_price=avg_fill_price,
                        )

                        if trade_id:
                            self.active_trades[symbol] = trade_id
                            logger.info(f"L2 Trade opened: {trade_id} for {symbol}")
                        else:
                            logger.error(f"Failed to open trade for {symbol}")
                    except Exception as exc:
                        logger.error(
                            f"Error recording trade entry for {symbol}: {exc}",
                            exc_info=True,
                        )

            # Handle completely untracked ENTRY orders (e.g., after restart)
            elif "ENTRY" in order_ref and symbol not in self.active_positions:
                position_side = "SHORT" if side == "SLD" else "LONG"
                self.active_positions[symbol] = {
                    "quantity": filled_qty,
                    "entry_price": fill_price,
                    "entry_time": time.time(),
                    "initial_quantity": filled_qty,
                    "side": position_side,
                    "entry_order_id": order_id,
                    "exit_order_id": None,
                    "exit_order_ids": [],
                    "exit_filled_qty": 0,
                    "exit_total_value": 0.0,
                    "exit_reason": None,
                    "rule_name": (
                        order_ref.split("_")[1] if "_" in order_ref else "unknown"
                    ),
                }
                self.risk_manager.upsert_position(
                    symbol, -filled_qty if side == "SLD" else filled_qty, fill_price
                )
                logger.info(
                    f"Created position from untracked entry: {symbol} {position_side} {filled_qty}@{fill_price}"
                )

                # Record trade entry for untracked orders too
                rule_name = self._extract_rule_from_ref(order_ref)
                try:
                    trade_id = self.trade_journal.record_trade_entry(
                        symbol=symbol,
                        side=position_side,
                        quantity=filled_qty,
                        entry_price=fill_price,
                        order_id=order_id,
                        rule_name=rule_name,
                        signal_id=f"l2_{rule_name}_{symbol}_{int(time.time())}",
                        signal_price=fill_price,
                    )

                    if trade_id:
                        self.active_trades[symbol] = trade_id
                        logger.info(
                            f"L2 Trade opened (untracked): {trade_id} for {symbol}"
                        )
                except Exception as exc:
                    logger.error(
                        f"Error recording untracked trade entry for {symbol}: {exc}",
                        exc_info=True,
                    )

        except Exception as e:
            logger.error(f"Error in legacy fill handler: {e}", exc_info=True)

    def _on_order_status(self, trade) -> None:
        """Handle order status updates from IB"""
        try:
            order_id = int(trade.order.orderId)
            status = trade.orderStatus.status

            # Update order tracker
            tracked_order = self.order_tracker.get_order(order_id)
            if tracked_order:
                self.order_tracker.update_status(order_id, status)
                logger.debug(f"Order {order_id} status: {status}")

                if status == "Filled":
                    self._handle_order_filled(trade)
                elif status == "Cancelled":
                    self._handle_order_cancelled(trade)
            else:
                logger.debug(f"Status update for untracked order {order_id}: {status}")

        except Exception as e:
            logger.error(f"Error processing order status: {e}", exc_info=True)

    def _handle_order_filled(self, trade) -> None:
        """Handle order filled status"""
        order_id = int(trade.order.orderId)
        tracked_order = self.order_tracker.get_order(order_id)

        if tracked_order and tracked_order.intent == "ENTRY":
            logger.info(f"Entry order {order_id} fully filled")
        elif tracked_order and tracked_order.intent in ("TP", "SL"):
            logger.info(f"Exit order {order_id} ({tracked_order.intent}) fully filled")

    def _handle_order_cancelled(self, trade) -> None:
        """Handle order cancelled status"""
        order_id = int(trade.order.orderId)
        tracked_order = self.order_tracker.get_order(order_id)

        if tracked_order:
            logger.info(f"Order {order_id} ({tracked_order.intent}) cancelled")

            # If entry order cancelled, clean up position
            if tracked_order.intent == "ENTRY":
                position = self.position_manager.get_position_by_order(order_id)
                if position and position.filled_qty == 0:
                    self.position_manager.close_position(order_id)
                    logger.info(
                        f"Cleaned up unfilled position for {tracked_order.symbol}"
                    )

    def _handle_fill(self, trade) -> None:
        """Handle order fill"""
        try:
            if not trade.fills:
                return

            fill = trade.fills[-1]
            symbol = trade.contract.symbol
            filled_qty = fill.execution.shares
            fill_price = fill.execution.price
            side = fill.execution.side
            order_id = str(trade.order.orderId)

            logger.info(f"Order filled: {symbol} {side} {filled_qty}@{fill_price:.4f}")

            # Record fill to shared event store + audit log
            commission = 0.0
            exchange = ""
            exec_id = ""
            realized_pnl = 0.0
            if getattr(fill, "commissionReport", None):
                commission = fill.commissionReport.commission or 0.0
                realized_pnl = fill.commissionReport.realizedPNL or 0.0
            if getattr(fill, "execution", None):
                exchange = fill.execution.exchange or ""
                exec_id = fill.execution.execId or ""

            if hasattr(self.trade_journal, "record_fill"):
                self.trade_journal.record_fill(
                    order_id=int(order_id) if order_id.isdigit() else 0,
                    symbol=symbol,
                    side=side,
                    quantity=int(filled_qty),
                    price=fill_price,
                    commission=float(commission or 0.0),
                    exchange=exchange,
                    exec_id=exec_id,
                    realized_pnl=float(realized_pnl or 0.0),
                )

            # Entry fill
            if order_id in self.pending_entries:
                pending = self.pending_entries[order_id]
                fill_qty = int(filled_qty)
                pending["filled_qty"] += fill_qty
                pending["total_value"] += float(fill_qty) * float(fill_price)
                entry_side = pending["side"]
                expected_qty = int(pending["quantity"])
                avg_fill_price = (
                    pending["total_value"] / pending["filled_qty"]
                    if pending["filled_qty"]
                    else float(fill_price)
                )

                order_filled = getattr(trade.orderStatus, "filled", 0) or 0
                total_qty = (
                    getattr(trade.order, "totalQuantity", expected_qty) or expected_qty
                )
                remaining = getattr(trade.orderStatus, "remaining", None)
                status = str(getattr(trade.orderStatus, "status", "") or "")
                fully_filled = pending["filled_qty"] >= expected_qty or float(
                    order_filled
                ) >= float(total_qty)
                terminal = status in {"Cancelled", "Inactive", "ApiCancelled"} or (
                    remaining is not None and float(remaining) == 0.0
                )

                if (
                    pending.get("exit_price_source") == "fill"
                    and pending["filled_qty"] > 0
                ):
                    stop_loss_price, profit_target_price = self._compute_exit_prices(
                        entry_price=avg_fill_price,
                        side=entry_side,
                        max_loss_bps=pending.get("max_loss_bps", 0.0),
                        profit_target_bps=pending.get("profit_target_bps", 0.0),
                        tick_size=pending.get("tick_size", 0.01),
                    )
                    desired_exit_qty = int(pending["filled_qty"])
                    if pending.get("exit_order_qty") != desired_exit_qty:
                        # Replace existing exit orders to match filled quantity
                        for exit_id in pending.get("exit_order_ids", []):
                            self.order_manager.cancel_order(exit_id)
                        exit_ids = self.order_manager.place_oca_exit_orders(
                            symbol=symbol,
                            entry_side=entry_side,
                            quantity=desired_exit_qty,
                            stop_loss_price=stop_loss_price,
                            profit_target_price=profit_target_price,
                        )
                        pending["exit_order_ids"] = [
                            oid for oid in exit_ids.values() if oid
                        ]
                        pending["exit_order_qty"] = desired_exit_qty
                        pending["exit_order_time"] = (
                            time.time()
                        )  # Track when exit orders placed

                signed_delta = fill_qty if entry_side.upper() == "BUY" else -fill_qty

                if symbol not in self.active_positions:
                    self.risk_manager.upsert_position(
                        symbol, signed_delta, float(fill_price)
                    )
                    position_side = "LONG" if entry_side.upper() == "BUY" else "SHORT"
                    self.active_positions[symbol] = {
                        "quantity": int(pending["filled_qty"]),
                        "entry_price": avg_fill_price,
                        "entry_time": time.time(),
                        "initial_quantity": int(pending["filled_qty"]),
                        "side": position_side,
                        "entry_order_id": order_id,
                        "exit_order_id": None,
                        "exit_order_ids": pending.get("exit_order_ids", []),
                        "exit_order_time": pending.get(
                            "exit_order_time"
                        ),  # Track exit order time
                        "exit_filled_qty": 0,
                        "exit_total_value": 0.0,
                        "exit_reason": None,
                        "rule_name": pending.get("rule_name", "obi_momentum"),
                        "signal_id": pending.get("signal_id"),
                    }

                    hold_seconds = self.config["strategy"]["strategy"].get(
                        "default_hold_seconds", 300
                    )
                    self.scheduled_exits[symbol] = time.time() + hold_seconds
                    logger.info(f"Scheduled exit for {symbol} in {hold_seconds}s")

                    trade_id = self.trade_journal.record_trade_entry(
                        symbol=symbol,
                        side=entry_side,
                        quantity=int(pending["filled_qty"]),
                        entry_price=avg_fill_price,
                        order_id=str(order_id),
                        rule_name=pending.get("rule_name", "obi_momentum"),
                        signal_id=pending.get("signal_id"),
                        signal_price=pending.get("signal_price", avg_fill_price),
                    )
                    self.active_positions[symbol]["trade_id"] = trade_id

                    # Write to shared position ledger
                    if self.shared_ledger:
                        try:
                            self.shared_ledger.upsert(
                                "l2-scalping",
                                symbol,
                                int(pending["filled_qty"]),
                                avg_fill_price,
                            )
                        except Exception as e:
                            logger.debug("Shared ledger upsert failed: %s", e)

                else:
                    position = self.active_positions[symbol]
                    prev_qty = position["quantity"]
                    delta_qty = int(pending["filled_qty"]) - prev_qty
                    if delta_qty != 0:
                        delta_signed = (
                            delta_qty if entry_side.upper() == "BUY" else -delta_qty
                        )
                        self.risk_manager.upsert_position(
                            symbol, delta_signed, float(fill_price)
                        )
                        position["quantity"] = int(pending["filled_qty"])
                        position["entry_price"] = avg_fill_price
                        position["initial_quantity"] = max(
                            int(position.get("initial_quantity", 0)),
                            int(pending["filled_qty"]),
                        )
                        position["exit_order_ids"] = pending.get("exit_order_ids", [])

                if not fully_filled and not terminal:
                    logger.info(
                        "Partial fill: %s %s filled=%s/%s",
                        symbol,
                        order_id,
                        pending["filled_qty"],
                        expected_qty,
                    )
                    return

                entry_qty = int(pending["filled_qty"])
                if entry_qty <= 0:
                    self.pending_entries.pop(order_id, None)
                    return

                self.pending_entries.pop(order_id, None)
                return

            # Exit fill
            position = self.active_positions.get(symbol)
            exit_ids = position.get("exit_order_ids", []) if position else []
            if position and (
                position.get("exit_order_id") == order_id or order_id in exit_ids
            ):
                exit_fill_qty = int(filled_qty)
                if exit_fill_qty <= 0:
                    return

                position["exit_filled_qty"] = (
                    int(position.get("exit_filled_qty", 0)) + exit_fill_qty
                )
                position["exit_total_value"] = float(
                    position.get("exit_total_value", 0.0)
                ) + (exit_fill_qty * float(fill_price))

                remaining_qty = position["quantity"] - exit_fill_qty
                if remaining_qty > 0:
                    self.risk_manager.reduce_position(
                        symbol, exit_fill_qty, float(fill_price)
                    )
                    position["quantity"] = remaining_qty
                    logger.info(
                        "Partial exit fill: %s %s filled=%s remaining=%s",
                        symbol,
                        order_id,
                        exit_fill_qty,
                        remaining_qty,
                    )
                    return

                total_qty = int(position.get("initial_quantity", position["quantity"]))
                avg_exit_price = (
                    position["exit_total_value"] / position["exit_filled_qty"]
                    if position.get("exit_filled_qty")
                    else float(fill_price)
                )
                entry_price = position["entry_price"]
                if position["side"] == "LONG":
                    pnl = (avg_exit_price - entry_price) * total_qty
                else:
                    pnl = (entry_price - avg_exit_price) * total_qty

                commission = self._estimate_commission(total_qty)

                # Get trade_id from active_trades dict
                trade_id = self.active_trades.get(symbol, "")
                exit_reason = self._determine_exit_reason(order_ref)
                rule_name = position.get("rule_name", "obi_momentum")

                if trade_id:
                    try:
                        self.trade_journal.record_trade_exit(
                            trade_id=trade_id,
                            symbol=symbol,
                            exit_price=avg_exit_price,
                            exit_qty=total_qty,
                            pnl=pnl,
                            commission=commission,
                            rule_name=rule_name,
                            exit_reason=exit_reason,
                            exit_order_id=order_id,
                        )
                        logger.info(
                            f"L2 Trade closed: {trade_id} for {symbol} @ {avg_exit_price}"
                        )
                        _audit.trade_close(
                            symbol,
                            position["side"],
                            total_qty,
                            avg_exit_price,
                            pnl,
                            trade_id,
                        )
                        # Close in Trade DB V2 (fallback if auto-close didn't trigger)
                        db_trade_id = self.active_trades.get(symbol)
                        if self.trade_db and db_trade_id:
                            try:
                                self.trade_db.close_trade(db_trade_id, avg_exit_price, total_qty, pnl, exit_reason)
                            except Exception as db_exc:
                                logger.error(f"DB V2 close_trade failed for {symbol}: {db_exc}")
                        del self.active_trades[symbol]
                    except Exception as exc:
                        logger.error(
                            f"Error recording trade exit for {symbol}: {exc}",
                            exc_info=True,
                        )
                else:
                    logger.warning(
                        f"Exit fill for {symbol} but no active trade_id found"
                    )
                    # Fallback to old method for backward compatibility
                    self.trade_journal.record_trade_exit(
                        trade_id=position.get("trade_id", ""),
                        symbol=symbol,
                        exit_price=avg_exit_price,
                        exit_qty=total_qty,
                        pnl=pnl,
                        commission=commission,
                        rule_name=rule_name,
                        exit_reason=position.get("exit_reason", "L2_SIGNAL"),
                        exit_order_id=order_id,
                    )

                realized_pnl = self.risk_manager.close_position(symbol, avg_exit_price)

                triggered, cb_reason = self.circuit_breaker.check_circuit_breaker(
                    realized_pnl, self.account_value
                )
                if triggered:
                    logger.critical(f"CIRCUIT BREAKER TRIGGERED: {cb_reason}")
                    self.is_running = False

                del self.active_positions[symbol]
                # Clean up scheduled exit
                self.scheduled_exits.pop(symbol, None)

                # Remove from shared position ledger
                if self.shared_ledger:
                    try:
                        self.shared_ledger.remove("l2-scalping", symbol)
                    except Exception as e:
                        logger.debug("Shared ledger remove failed: %s", e)

        except Exception as e:
            logger.error(f"Error handling fill: {e}", exc_info=True)

    def _check_position_exits(self) -> None:
        """Check if positions should be exited"""
        current_time = time.time()
        exit_price_source = str(
            self.config.get("ibkr", {})
            .get("orders", {})
            .get("exit_price_source", "signal")
        ).lower()

        for symbol in list(self.active_positions.keys()):
            position = self.active_positions[symbol]

            if exit_price_source == "fill" and not position.get("exit_order_ids"):
                stop_loss_price, profit_target_price = self._compute_exit_prices(
                    entry_price=position["entry_price"],
                    side="BUY" if position["side"] == "LONG" else "SELL",
                    max_loss_bps=self.config["risk"]["per_trade"]["max_loss_bps"],
                    profit_target_bps=self.config["risk"]["per_trade"][
                        "profit_target_bps"
                    ],
                    tick_size=self.config["ibkr"]["orders"].get("tick_size", 0.01),
                )
                exit_ids = self.order_manager.place_oca_exit_orders(
                    symbol=symbol,
                    entry_side="BUY" if position["side"] == "LONG" else "SELL",
                    quantity=position["quantity"],
                    stop_loss_price=stop_loss_price,
                    profit_target_price=profit_target_price,
                )
                position["exit_order_ids"] = [oid for oid in exit_ids.values() if oid]

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
            force_exit = False  # Force market order if True

            # CRITICAL: Max hold time (safety backstop) - FORCE EXIT
            hold_time = current_time - position["entry_time"]
            max_hold = self._max_hold_seconds()
            if hold_time >= max_hold:
                # Check if we already have exit orders working
                if position.get("exit_order_ids"):
                    # OCA orders exist - check how long they've been there
                    exit_order_time = position.get(
                        "exit_order_time", position["entry_time"]
                    )
                    exit_order_age = current_time - exit_order_time
                    # Only force cancel if exit orders have been pending for > 60 seconds
                    if exit_order_age < 60:
                        logger.info(
                            f"{symbol}: Max hold exceeded but exit orders working ({exit_order_age:.0f}s old)"
                        )
                        continue
                    else:
                        logger.warning(
                            f"FORCE EXIT: {symbol} exit orders stale ({exit_order_age:.0f}s)"
                        )
                        should_exit = True
                        force_exit = True
                        exit_reason = f"MAX_HOLD_EXCEEDED ({hold_time:.0f}s >= {max_hold}s), exit orders stale"
                else:
                    # No exit orders - force exit immediately
                    should_exit = True
                    force_exit = True
                    exit_reason = f"MAX_HOLD_EXCEEDED ({hold_time:.0f}s >= {max_hold}s)"
                    logger.warning(f"FORCE EXIT: {symbol} exceeded max hold time")

            # Scheduled exit (primary time-based exit)
            if not should_exit:
                scheduled_time = self.scheduled_exits.get(symbol)
                if scheduled_time and current_time >= scheduled_time:
                    should_exit = True
                    exit_reason = f"Scheduled exit ({hold_time:.0f}s)"

            if exit_price_source == "fill" and position.get("exit_order_ids"):
                if should_exit and force_exit:
                    # Only force market exit if explicitly forcing
                    self._exit_position(
                        symbol, snapshot.mid, exit_reason, force_market=True
                    )
                    # Reset exit_order_time to prevent re-triggering on next tick
                    position["exit_order_time"] = current_time
                # Otherwise let OCA orders work
                continue

            # Profit target (early exit on profit)
            if not should_exit:
                profit_target = self.config["risk"]["per_trade"]["profit_target_bps"]
                if pnl_bps >= profit_target:
                    should_exit = True
                    exit_reason = f"Profit target ({pnl_bps:.1f} bps)"

            # Stop loss (early exit on loss)
            if not should_exit:
                max_loss = self.config["risk"]["per_trade"]["max_loss_bps"]
                if pnl_bps <= -max_loss:
                    should_exit = True
                    exit_reason = f"Stop loss ({pnl_bps:.1f} bps)"

            # Exit position
            if should_exit:
                self._exit_position(
                    symbol, snapshot.mid, exit_reason, force_market=force_exit
                )

    def _exit_position(
        self, symbol: str, exit_price: float, reason: str, force_market: bool = False
    ) -> None:
        """Exit a position

        Args:
            symbol: Symbol to exit
            exit_price: Current market price
            reason: Exit reason for logging
            force_market: If True, use market order for immediate exit
        """
        try:
            if symbol not in self.active_positions:
                return

            position = self.active_positions[symbol]
            if position.get("exit_order_id") and not force_market:
                return

            # Exit guard: check if we're allowed to attempt exit
            can_exit, guard_reason = self.exit_guard.can_attempt_exit(symbol)
            if not can_exit:
                logger.debug(f"Exit blocked for {symbol}: {guard_reason}")
                return

            # Cancel existing exit orders ONLY if forcing market exit
            # Don't cancel OCA orders that are still working - let them execute naturally
            if force_market:
                # Only cancel if orders exist and haven't filled yet
                for exit_id in position.get("exit_order_ids", []):
                    try:
                        self.order_manager.cancel_order(exit_id)
                    except Exception as e:
                        logger.debug(f"Could not cancel exit order {exit_id}: {e}")
                position["exit_order_ids"] = []
                if position.get("exit_order_id"):
                    try:
                        self.order_manager.cancel_order(position["exit_order_id"])
                    except Exception as e:
                        logger.debug(
                            f"Could not cancel exit order {position['exit_order_id']}: {e}"
                        )
                    position["exit_order_id"] = None
            elif position.get("exit_order_id"):
                # Exit order already exists and we're not forcing - skip
                logger.debug(f"Exit order already exists for {symbol}, skipping")
                return

            # Create exit order
            if position["side"] == "LONG":
                side = OrderSide.SELL
            else:
                side = OrderSide.BUY

            order_request = OrderRequest(
                symbol=symbol,
                side=side,
                quantity=position["quantity"],
                price=None,
                order_type=OrderType.MKT,
                time_in_force=None,
                client_order_id=self._build_order_ref(symbol, "EXIT", side.value),
            )

            result = self.order_manager.place_order_safe(order_request)

            if result.success:
                self.exit_guard.record_attempt(symbol, success=True)
                position["exit_order_id"] = result.order_id
                position["exit_order_ids"] = [str(result.order_id)]
                position["exit_reason"] = reason
                logger.info(
                    f"Exit order placed (MARKET): {symbol} {side.value} "
                    f"{position['quantity']}@MKT ref={exit_price:.4f} - {reason}"
                )
            else:
                self.exit_guard.record_attempt(
                    symbol, success=False, rejection_reason=result.rejection_reason
                )
                if result.is_margin_rejection:
                    logger.critical(
                        f"MARGIN REJECTION on exit for {symbol}: {result.rejection_reason}"
                    )

        except Exception as e:
            logger.error(f"Error exiting position: {e}", exc_info=True)

    def _close_all_positions(self) -> None:
        """Close all open positions"""
        for symbol in list(self.active_positions.keys()):
            snapshot = self.data_feed.get_latest_snapshot(symbol)
            if snapshot:
                self._exit_position(
                    symbol,
                    snapshot.mid,
                    "System shutdown",
                    force_market=True,
                )

    def _check_eod_flatten(self) -> None:
        """Force close all positions at EOD.

        Hardened: resets exit guards, uses global cancel, retries on failure.
        Closing positions frees margin, so exits should succeed even when tight.
        """
        if self.eod_flattened:
            return
        if not self.scheduler.is_eod_flatten_time():
            return

        logger.warning("EOD FLATTEN: Triggering forced position close")

        # Reset exit guards — closing frees margin, so retries are valid
        self.exit_guard.reset_all()

        # Global cancel first to clear all pending orders
        try:
            if hasattr(self.order_manager, "_order_manager") and hasattr(
                self.order_manager._order_manager, "ib"
            ):
                self.order_manager._order_manager.ib.reqGlobalCancel()
                logger.info("EOD FLATTEN: reqGlobalCancel sent")
                time.sleep(1)  # Brief pause for cancels to propagate
        except Exception as exc:
            logger.warning(f"EOD FLATTEN: reqGlobalCancel failed: {exc}")

        try:
            self.order_manager.cancel_all_orders()
        except Exception as exc:
            logger.warning(f"EOD FLATTEN: Failed to cancel orders: {exc}")

        # Attempt to flatten each position, retry once on failure
        remaining = list(self.active_positions.keys())
        for attempt in range(2):
            if not remaining:
                break
            if attempt > 0:
                logger.warning(
                    f"EOD FLATTEN: Retry attempt {attempt + 1} for {remaining}"
                )
                time.sleep(2)
                self.exit_guard.reset_all()

            still_open = []
            for symbol in remaining:
                snapshot = self.data_feed.get_latest_snapshot(symbol)
                if snapshot:
                    self._exit_position(
                        symbol,
                        snapshot.mid,
                        "EOD_FLATTEN",
                        force_market=True,
                    )
                    # Check if exit was blocked by guard (margin rejection)
                    if symbol in self.active_positions and not self.active_positions[
                        symbol
                    ].get("exit_order_id"):
                        still_open.append(symbol)
            remaining = still_open

        if remaining:
            logger.critical(
                "EOD FLATTEN: FAILED to close %d positions: %s — MANUAL INTERVENTION NEEDED",
                len(remaining),
                remaining,
            )

        self.eod_flattened = True

    def _process_order_update(self, update) -> None:
        """Process order status update"""
        logger.debug(f"Order update: {update.symbol} {update.status}")

    def _sync_ibkr_positions(self) -> None:
        """Sync existing IBKR positions to active_positions on startup.

        Also reconciles against shared_positions table if available.
        """
        logger.info("Starting IBKR position sync...")
        try:
            # Wait for IBKR to send position data
            import time as time_module

            time_module.sleep(2)

            positions = self.order_manager.get_positions()
            logger.info(f"Got {len(positions) if positions else 0} positions from IBKR")
            if not positions:
                logger.info("No existing IBKR positions to sync")
                return

            # Get symbols we're trading today
            trading_symbols = (
                set(self.data_feed.symbols)
                if hasattr(self.data_feed, "symbols")
                else set()
            )
            logger.info(f"Trading symbols: {trading_symbols}")

            # Load shared positions for reconciliation
            shared_pos = {}
            try:
                from cpapi.shared_positions import SharedPositionLedger

                ledger = SharedPositionLedger()
                for sp in ledger.get_all("l2-scalping"):
                    shared_pos[sp["symbol"]] = sp
            except Exception as e:
                logger.debug(f"Shared positions unavailable: {e}")

            ibkr_symbols = set()
            for pos in positions:
                symbol = pos["symbol"]
                qty = int(pos["quantity"])
                avg_price = float(pos["avg_price"])

                if qty == 0:
                    continue

                ibkr_symbols.add(symbol)

                # Always sync ALL IBKR positions to risk manager to prevent
                # re-entry after restarts (even for non-trading symbols)
                self.risk_manager.upsert_position(symbol, qty, avg_price)

                # Only add to active_positions if we're trading this symbol
                if trading_symbols and symbol not in trading_symbols:
                    logger.warning(
                        f"IBKR position in non-trading symbol {symbol} qty={qty} — tracked in risk manager only"
                    )
                    continue

                if symbol not in self.active_positions:
                    position_side = "SHORT" if qty < 0 else "LONG"
                    self.active_positions[symbol] = {
                        "quantity": abs(qty),
                        "entry_price": avg_price,
                        "entry_time": time.time(),
                        "initial_quantity": abs(qty),
                        "side": position_side,
                        "entry_order_id": "synced",
                        "exit_order_id": None,
                        "exit_order_ids": [],
                        "exit_filled_qty": 0,
                        "exit_total_value": 0.0,
                        "exit_reason": None,
                        "rule_name": "synced_from_ibkr",
                    }
                    self.risk_manager.upsert_position(symbol, qty, avg_price)
                    logger.info(
                        f"Synced IBKR position: {symbol} {position_side} {abs(qty)}@{avg_price:.4f}"
                    )

            logger.info(
                f"Position sync complete: {len(self.active_positions)} active positions"
            )

            # Reconcile: shared_positions entries not in IBKR → mark closed
            for sym, sp in shared_pos.items():
                if sym not in ibkr_symbols and sp.get("quantity", 0) != 0:
                    logger.warning(
                        "RECONCILE: %s in shared_positions but not in IBKR — marking closed",
                        sym,
                    )
                    try:
                        from cpapi.shared_positions import SharedPositionLedger

                        SharedPositionLedger().remove("l2-scalping", sym)
                    except Exception:
                        pass

            # Reconcile: IBKR positions not in shared_positions → log warning
            for sym in ibkr_symbols:
                if sym not in shared_pos and sym in self.active_positions:
                    logger.warning(
                        "RECONCILE: %s in IBKR but not in shared_positions — adding",
                        sym,
                    )
                    try:
                        from cpapi.shared_positions import SharedPositionLedger

                        pos_data = self.active_positions[sym]
                        SharedPositionLedger().upsert(
                            "l2-scalping",
                            sym,
                            pos_data["quantity"],
                            pos_data["entry_price"],
                        )
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"Error syncing IBKR positions: {e}", exc_info=True)

    def _monitor_loop(self) -> None:
        """Background monitoring loop"""
        while self.is_running:
            try:
                time.sleep(60)

                # Query IBKR positions and compute total exposure
                try:
                    positions = self.order_manager.get_positions()
                    total_notional = sum(
                        abs(int(p["quantity"])) * float(p["avg_price"])
                        for p in (positions or [])
                        if int(p["quantity"]) != 0
                    )
                    self._ibkr_exposure_pct = total_notional / max(1, self.account_value)
                    if self._ibkr_exposure_pct > 0.05:
                        logger.warning(
                            "IBKR exposure %.1f%% of account ($%.0f / $%.0f)",
                            self._ibkr_exposure_pct * 100, total_notional, self.account_value,
                        )
                except Exception as e:
                    logger.debug("IBKR exposure check failed: %s", e)

                risk_metrics = self.risk_manager.get_risk_metrics(self.account_value)
                data_health = self.data_feed.health_check()
                order_health = self.order_manager.health_check()

                logger.info(
                    f"System Health - "
                    f"P&L: ${risk_metrics.daily_pnl:.2f}, "
                    f"Trades: {risk_metrics.daily_trades}, "
                    f"Positions: {len(risk_metrics.current_positions)}, "
                    f"Risk: {risk_metrics.risk_status.value}, "
                    f"Data: {data_health.get('data_healthy', data_health.get('connected', False))}, "
                    f"Fresh: {data_health.get('fresh_snapshots', 0)}/{data_health.get('symbols_subscribed', 0)}, "
                    f"Orders: {order_health['connected']}, "
                    f"IBKR_Exposure: {getattr(self, '_ibkr_exposure_pct', 0):.1%}"
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

        # Generate daily report
        summary = self.trade_journal.get_daily_summary()
        report_text = self.reporter.generate_daily_report(
            summary, self.trade_journal.journal_file
        )
        self.reporter.print_report(report_text)

        logger.info("=" * 60)

    def _signal_handler(self, signum, frame) -> None:
        """Handle shutdown signals"""
        logger.info(f"Received signal {signum}")
        self.is_running = False

    def _build_order_ref(
        self, symbol: str, intent: str, side: str, rule_name: str = "obi_momentum"
    ) -> str:
        """Build order reference for tagging with rule name"""
        prefix = self.config["ibkr"]["orders"].get("order_ref_prefix", "L2SCALP")
        return f"{prefix}_{rule_name}_{intent}_{side}_{symbol}_{int(time.time()*1000)}"

    def _estimate_commission(self, quantity: int) -> float:
        """Estimate commission and fees for trade reporting"""
        orders_cfg = self.config["ibkr"]["orders"]
        per_share_commission = orders_cfg.get("commission_per_share", 0.0)
        per_share_fee = orders_cfg.get("fee_per_share", 0.0)
        return (per_share_commission + per_share_fee) * abs(quantity)


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
