#!/usr/bin/env python3
"""Enhanced live trading system with best practices from PAPER_TRADING_GUIDE."""

import sys
from pathlib import Path

# Add paths FIRST
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, str(repo_root / "qx-data" / "src"))
sys.path.insert(0, str(repo_root / "scripts"))

import logging
import os
import time
from datetime import datetime
from datetime import time as dt_time

import pytz
from daily_sip_scheduler import load_daily_sip_results, run_daily_sip_selection

from qx_data.live.event_store import EventStore
from qx_data.live.ibkr_data_tagged import create_quantstack_manager
from qx_data.live.l2_collector import QuantstackL2Collector
from qx_data.live.ml_predictor import RegimeAwarePredictor
from qx_data.live.order_manager import EnhancedPaperTrader, OrderIntent
from qx_data.live.performance_monitor import PerformanceMonitor
from qx_data.live.risk_manager import RiskLimits, RiskManager

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/enhanced_live_trading.log"),
        logging.StreamHandler(),
    ],
)


class EnhancedLiveTradingSystem:
    """Enhanced live trading system with comprehensive risk management."""

    def __init__(self):
        self.logger = self._setup_logging()
        self.et_tz = pytz.timezone("America/New_York")

        # Enhanced components
        self.ml_predictor = RegimeAwarePredictor("./models/regime_aware")
        self.paper_trader = EnhancedPaperTrader(system_name="QUANTSTACK", client_id=999)
        self.ibkr_data = create_quantstack_manager()
        self.performance = PerformanceMonitor()
        self.event_store = EventStore()

        # Risk management
        self.risk_limits = RiskLimits(
            daily_loss_limit=500.0,
            max_concurrent_positions=4,
            max_trades_per_day=50,
            min_confidence_threshold=0.65,
        )
        self.risk_manager = RiskManager(self.risk_limits)

        # State
        self.sip_universe = []
        self.l2_symbols = []
        self.trading_connected = False
        self.data_subscribed = False
        self.l2_active = False
        self.ibkr_available = False
        self.l2_collector = None

    def _setup_logging(self) -> logging.Logger:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        return logging.getLogger(__name__)

    def get_et_time(self) -> datetime:
        """Get current time in ET timezone."""
        return datetime.now(self.et_tz)

    def check_ibkr_connection(self) -> bool:
        """Test IBKR connection availability."""
        try:
            from ib_insync import IB

            ib = IB()
            ib.connect("127.0.0.1", 7497, clientId=998, readonly=True, timeout=3)
            if ib.isConnected():
                ib.disconnect()
                return True
            return False
        except Exception as e:
            self.logger.error(f"IBKR connection test failed: {e}")
            return False

    def load_or_create_daily_universe(self):
        """Load today's SIP universe."""
        date_str = self.get_et_time().strftime("%Y-%m-%d")
        sip_universe, l2_symbols = load_daily_sip_results(date_str)

        if sip_universe is None:
            self.logger.info("Running LIVE SIP analysis...")
            try:
                sip_universe, l2_symbols = run_daily_sip_selection()
            except Exception as e:
                self.logger.error(f"SIP selection failed: {e}")
                raise RuntimeError("LIVE SIP analysis failed")

        self.sip_universe = sip_universe or []
        self.l2_symbols = l2_symbols or []

        self.logger.info(
            f"Universe loaded: {len(self.sip_universe)} SIP symbols, "
            f"{len(self.l2_symbols)} L2 symbols"
        )

    def is_market_hours(self) -> bool:
        """Check if in market hours (9:30-16:00 ET)."""
        et_now = self.get_et_time()
        current_time = et_now.time()

        if et_now.weekday() >= 5:  # Weekend
            return False

        return dt_time(9, 30) <= current_time <= dt_time(16, 0)

    def is_l2_collection_time(self) -> bool:
        """Check if in L2 collection windows."""
        et_now = self.get_et_time()
        current_time = et_now.time()

        if et_now.weekday() >= 5:
            return False

        # Opening hour: 9:30-10:30, Power hour: 15:00-16:00
        return dt_time(9, 30) <= current_time <= dt_time(10, 30) or dt_time(
            15, 0
        ) <= current_time <= dt_time(16, 0)

    def start_l2_collection(self):
        """Start L2 data collection."""
        if not self.ibkr_available or not self.l2_symbols:
            return

        config = {
            "host": "127.0.0.1",
            "port": 7497,
            "client_id": 500,
            "levels": 10,
            "max_symbols": len(self.l2_symbols),
            "rotate_seconds": 300,
            "output_dir": "./data/live_l2",
            "run_id": f"live_{datetime.now().strftime('%Y%m%d')}",
            "windows": "09:30-10:30,15:00-16:00",
        }

        try:
            self.l2_collector = QuantstackL2Collector(self.l2_symbols, config)
            self.l2_collector.start_collection()
            self.l2_active = True
            self.logger.info("L2 collection started")
        except Exception as e:
            self.logger.error(f"L2 collection start failed: {e}")

    def stop_l2_collection(self):
        """Stop L2 collection."""
        if self.l2_collector:
            try:
                self.l2_collector.stop_collection()
                self.logger.info("L2 collection stopped")
            except Exception as e:
                self.logger.error(f"L2 stop failed: {e}")
            finally:
                self.l2_collector = None
                self.l2_active = False

    def connect_trading(self) -> bool:
        """Connect to IBKR for enhanced paper trading."""
        if not self.ibkr_available:
            return False

        if not self.trading_connected:
            try:
                self.trading_connected = self.paper_trader.connect()
                if self.trading_connected:
                    self.logger.info("Enhanced paper trading connected")
            except Exception as e:
                self.logger.error(f"Paper trading connection failed: {e}")
                self.trading_connected = False

        return self.trading_connected

    def subscribe_market_data(self):
        """Subscribe to real-time market data."""
        if not self.ibkr_available or not self.sip_universe:
            return False

        if not self.data_subscribed:
            try:
                if not self.ibkr_data.connect():
                    return False

                self.ibkr_data.subscribe_symbols(self.sip_universe)

                if len(self.ibkr_data.subscribed_symbols) == 0:
                    self.logger.error("No symbols subscribed successfully")
                    return False

                self.data_subscribed = True
                return True
            except Exception as e:
                self.logger.error(f"Market data subscription failed: {e}")
                return False

        return True

    def execute_enhanced_paper_trades(self):
        """Execute paper trades with enhanced risk management and journaling."""
        self.performance.start_cycle()

        if not self.connect_trading():
            self.logger.warning("Trading skipped - IBKR not available")
            self.performance.record_skipped_cycle()
            return

        if not self.subscribe_market_data():
            self.logger.warning("Trading skipped - market data not available")
            self.performance.record_skipped_cycle()
            return

        try:
            positions = self.paper_trader.get_positions()
            trades_executed = 0

            # Phase 1: Fetch real-time data
            phase_start = time.time()
            all_current_data = self.ibkr_data.get_all_current_data()

            if not all_current_data:
                self.logger.warning("No market data available")
                self.performance.record_skipped_cycle()
                return

            # Phase 2: Compute features
            try:
                cross_features = self.ibkr_data.compute_cross_sectional_features(
                    all_current_data
                )
                all_hist_bars = self.ibkr_data.get_all_historical_bars(
                    self.sip_universe, duration="1 D"
                )
            except Exception as e:
                self.logger.error(f"Feature computation failed: {e}")
                self.performance.record_skipped_cycle()
                return

            feature_time = time.time() - phase_start
            self.performance.record_phase("features", feature_time)

            # Market-wide statistics
            returns = []
            for sym, data in all_current_data.items():
                last = data.get("last", 0)
                close = data.get("close", 0)
                if last > 0 and close > 0:
                    returns.append((last - close) / close)

            market_ret = sum(returns) / len(returns) if returns else 0
            market_volatility = (
                (sum((r - market_ret) ** 2 for r in returns) / len(returns)) ** 0.5
                if returns
                else 0.02
            )

            market_data = {
                "market_ret": market_ret,
                "market_volatility": market_volatility,
            }

            # Phase 3: ML predictions with enhanced decision logging
            pred_start = time.time()

            for symbol in self.sip_universe:
                if symbol not in cross_features:
                    continue

                hist_bars = all_hist_bars.get(symbol)
                if hist_bars is None or len(hist_bars) < 5:
                    continue

                # Compute features
                closes = hist_bars["close"].values
                features = {
                    **cross_features[symbol],
                    **market_data,
                    "rel_strength_5": (
                        (closes[-1] - closes[-5]) / closes[-5]
                        if len(closes) >= 5
                        else 0
                    ),
                    "rel_strength_10": (
                        (closes[-1] - closes[-10]) / closes[-10]
                        if len(closes) >= 10
                        else 0
                    ),
                    "rel_strength_20": (
                        (closes[-1] - closes[-20]) / closes[-20]
                        if len(closes) >= 20
                        else 0
                    ),
                    "market_breadth": (
                        sum(1 for r in returns if r > 0) / len(returns)
                        if returns
                        else 0.5
                    ),
                    "up_down_ratio": (
                        (sum(1 for r in returns if r > 0) + 1)
                        / (sum(1 for r in returns if r < 0) + 1)
                        if returns
                        else 1.0
                    ),
                    "sector_momentum": 0.0,
                }

                # Get ML prediction
                prediction = self.ml_predictor.predict(symbol, features)
                if prediction is None:
                    continue

                regime = self.ml_predictor.detect_regime(features)
                current_position = positions.get(symbol, 0)
                current_price = all_current_data[symbol].get("last", 0)

                # Enhanced decision logic with risk management
                decision = "NO_TRADE"
                rejection_reason = ""

                if prediction > 0.65 and current_position <= 0:
                    direction = "long"
                    position_value = 100 * current_price

                    can_trade, reason = self.risk_manager.can_trade(
                        symbol, prediction, position_value
                    )

                    if can_trade:
                        # Calculate stop/target prices
                        stop_price = current_price * 0.98  # 2% stop
                        target_price = current_price * 1.04  # 4% target

                        intent = OrderIntent(
                            symbol=symbol,
                            direction=direction,
                            quantity=100,
                            entry_price=current_price,
                            stop_price=stop_price,
                            target_price=target_price,
                            strategy="regime_aware",
                            confidence=prediction,
                        )

                        order_ids = self.paper_trader.place_bracket_order(intent)
                        if order_ids:
                            decision = "TRADE"
                            trades_executed += 1

                            # Log order and start trade tracking
                            self.event_store.log_order(
                                order_ids[0],
                                symbol,
                                "BUY",
                                100,
                                "BRACKET",
                                current_price,
                                stop_price,
                                target_price,
                                "QUANTSTACK",
                                f"QUANTSTACK_999_regime_aware_{symbol}",
                            )

                            self.risk_manager.record_trade_start(
                                symbol, direction, 100, current_price, prediction
                            )

                            self.logger.info(
                                f"ENHANCED BUY: {symbol} @ {current_price:.2f} "
                                f"(conf={prediction:.3f}, regime={regime})"
                            )
                    else:
                        rejection_reason = reason

                elif prediction < 0.35 and current_position >= 0:
                    direction = "short"
                    position_value = max(current_position, 100) * current_price

                    can_trade, reason = self.risk_manager.can_trade(
                        symbol, 1 - prediction, position_value
                    )

                    if can_trade:
                        quantity = max(current_position, 100)
                        stop_price = current_price * 1.02
                        target_price = current_price * 0.96

                        intent = OrderIntent(
                            symbol=symbol,
                            direction=direction,
                            quantity=quantity,
                            entry_price=current_price,
                            stop_price=stop_price,
                            target_price=target_price,
                            strategy="regime_aware",
                            confidence=1 - prediction,
                        )

                        order_ids = self.paper_trader.place_bracket_order(intent)
                        if order_ids:
                            decision = "TRADE"
                            trades_executed += 1

                            self.risk_manager.record_trade_start(
                                symbol,
                                direction,
                                quantity,
                                current_price,
                                1 - prediction,
                            )

                            self.logger.info(
                                f"ENHANCED SELL: {symbol} @ {current_price:.2f} "
                                f"(conf={1-prediction:.3f}, regime={regime})"
                            )
                    else:
                        rejection_reason = reason

                # Log all decisions
                self.event_store.log_ml_decision(
                    symbol,
                    "regime_aware",
                    direction if "direction" in locals() else "none",
                    prediction,
                    prediction,
                    regime,
                    decision,
                    rejection_reason,
                    features,
                )

            pred_time = time.time() - pred_start
            self.performance.record_phase("predictions", pred_time)

            cycle_time = self.performance.end_cycle()

            # Log cycle summary
            risk_status = self.risk_manager.get_risk_status()
            self.logger.info(
                f"Enhanced cycle: {trades_executed} trades, {cycle_time:.1f}s "
                f"(daily: {risk_status['daily_trades']}/{self.risk_limits.max_trades_per_day}, "
                f"pnl: ${risk_status['daily_pnl']:.2f})"
            )

        except Exception as e:
            self.logger.error(f"Enhanced trading cycle failed: {e}", exc_info=True)
            self.performance.record_skipped_cycle()

    def run_enhanced_system(self):
        """Main enhanced live trading system loop."""
        if not os.getenv("POLYGON_API_KEY"):
            raise RuntimeError("POLYGON_API_KEY not set")

        # Check IBKR availability
        self.ibkr_available = self.check_ibkr_connection()

        # Load universe
        self.load_or_create_daily_universe()

        # Reset daily risk counters
        self.risk_manager.reset_daily_counters()

        last_trade_time = 0
        last_ibkr_check = 0
        last_risk_report = 0

        try:
            while True:
                current_time = time.time()

                # Recheck IBKR every 5 minutes
                if not self.ibkr_available and (current_time - last_ibkr_check) > 300:
                    self.ibkr_available = self.check_ibkr_connection()
                    last_ibkr_check = current_time

                # L2 Collection Management
                should_collect_l2 = self.is_l2_collection_time()
                if should_collect_l2 and not self.l2_active and self.ibkr_available:
                    self.start_l2_collection()
                elif not should_collect_l2 and self.l2_active:
                    self.stop_l2_collection()

                # Poll L2 data
                if self.l2_active and self.l2_collector:
                    try:
                        self.l2_collector.poll_once()
                    except Exception as e:
                        self.logger.error(f"L2 polling failed: {e}")

                # Enhanced paper trading (every 1 minute)
                if self.is_market_hours() and current_time - last_trade_time > 60:
                    self.execute_enhanced_paper_trades()
                    last_trade_time = current_time

                # Risk status report (every 10 minutes)
                if current_time - last_risk_report > 600:
                    risk_status = self.risk_manager.get_risk_status()
                    self.logger.info(f"Risk Status: {risk_status}")
                    last_risk_report = current_time

                time.sleep(5)

        except KeyboardInterrupt:
            self.logger.info("Shutdown requested")
        except Exception as e:
            self.logger.error(f"System error: {e}", exc_info=True)
        finally:
            # Cleanup
            if self.l2_active:
                self.stop_l2_collection()
            if self.trading_connected:
                self.paper_trader.disconnect()
            if self.data_subscribed:
                self.ibkr_data.disconnect()


def main():
    """Main entry point."""
    system = EnhancedLiveTradingSystem()
    system.run_enhanced_system()


if __name__ == "__main__":
    main()
