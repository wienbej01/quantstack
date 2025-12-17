#!/usr/bin/env python3
"""Live trading system - LIVE DATA ONLY with robust error handling."""

import sys
from pathlib import Path

# Add paths FIRST before any other imports
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

from qx_data.live.ibkr_data import IBKRMarketDataManager
from qx_data.live.l2_collector import QuantstackL2Collector
from qx_data.live.ml_predictor import PaperTrader, RegimeAwarePredictor
from qx_data.live.performance_monitor import PerformanceMonitor

logging.basicConfig(
    level=logging.ERROR, 
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("logs/live_trading.log"),
        logging.StreamHandler()
    ]
)

# Also log warnings for critical connection/subscription issues
logging.getLogger("qx_data.live.ibkr_data").setLevel(logging.WARNING)
logging.getLogger("__main__").setLevel(logging.ERROR)


class LiveTradingSystem:
    """Live trading system with robust error handling."""

    def __init__(self):
        self.logger = self._setup_logging()
        self.et_tz = pytz.timezone("America/New_York")

        # Components
        self.ml_predictor = RegimeAwarePredictor("./models/regime_aware")
        self.paper_trader = PaperTrader()
        self.ibkr_data = IBKRMarketDataManager(client_id=3)
        self.performance = PerformanceMonitor()
        self.l2_collector: QuantstackL2Collector | None = None

        # State
        self.sip_universe = []
        self.l2_symbols = []
        self.trading_connected = False
        self.data_subscribed = False
        self.l2_active = False
        self.ibkr_available = False

    def _setup_logging(self) -> logging.Logger:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)

        logging.basicConfig(
            level=logging.ERROR,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(log_dir / "live_trading.log"),
                logging.StreamHandler(),
            ],
        )
        return logging.getLogger(__name__)

    def get_et_time(self) -> datetime:
        """Get current time in ET timezone."""
        return datetime.now(self.et_tz)

    def check_ibkr_connection(self) -> bool:
        """Test IBKR connection availability."""
        try:
            from ib_insync import IB

            ib = IB()
            ib.connect("127.0.0.1", 7497, clientId=999, readonly=True, timeout=3)
            if ib.isConnected():
                ib.disconnect()
                return True
            else:
                self.logger.error("CRITICAL: IBKR connection failed - not connected after connect()")
                return False
        except Exception as e:
            self.logger.error(f"CRITICAL: IBKR connection exception: {e}", exc_info=True)
            return False

    def load_or_create_daily_universe(self):
        """Load today's SIP universe - LIVE DATA ONLY."""
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Try to load existing results first
        sip_universe, l2_symbols = load_daily_sip_results(date_str)

        if sip_universe is None:
            self.logger.info("No daily SIP results found, running LIVE analysis...")
            try:
                sip_universe, l2_symbols = run_daily_sip_selection()
            except Exception as e:
                self.logger.error(f"SIP selection failed: {e}")
                raise RuntimeError("LIVE SIP analysis failed")

            if sip_universe is None:
                raise RuntimeError("LIVE SIP analysis returned no results")

        self.sip_universe = sip_universe
        self.l2_symbols = l2_symbols

        self.logger.info(
            f"LIVE universe loaded: {len(self.sip_universe)} NYSE SIP symbols, {len(self.l2_symbols)} L2 symbols"
        )
        return True

    def is_market_hours(self) -> bool:
        """Check if in market hours (9:30-16:00 ET) with proper timezone."""
        et_now = self.get_et_time()
        current_time = et_now.time()

        # Check if it's a weekday (Monday=0, Sunday=6)
        if et_now.weekday() >= 5:  # Saturday or Sunday
            return False

        return dt_time(9, 30) <= current_time <= dt_time(16, 0)

    def is_l2_collection_time(self) -> bool:
        """Check if in L2 collection windows with proper timezone."""
        et_now = self.get_et_time()
        current_time = et_now.time()

        # Check if it's a weekday
        if et_now.weekday() >= 5:
            return False

        # Opening hour: 9:30-10:30, Power hour: 15:00-16:00
        return dt_time(9, 30) <= current_time <= dt_time(10, 30) or dt_time(
            15, 0
        ) <= current_time <= dt_time(16, 0)

    def start_l2_collection(self):
        """Start L2 data collection if IBKR available."""
        if not self.ibkr_available:
            self.logger.warning("L2 collection skipped - IBKR not available")
            return

        if not self.l2_symbols:
            self.logger.warning("No L2 symbols available")
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
        except Exception as e:
            self.logger.error(f"CRITICAL: L2 collection start failed: {e}", exc_info=True)
            self.l2_active = False

    def stop_l2_collection(self):
        """Stop L2 collection."""
        if self.l2_collector:
            try:
                metadata = self.l2_collector.stop_collection()
                counters = metadata.get("counters", {})
            except Exception as e:
                self.logger.error(f"CRITICAL: L2 collection stop failed: {e}", exc_info=True)
            finally:
                self.l2_collector = None
                self.l2_active = False

    def connect_trading(self) -> bool:
        """Connect to IBKR for paper trading."""
        if not self.ibkr_available:
            return False

        if not self.trading_connected:
            try:
                self.trading_connected = self.paper_trader.connect()
                if not self.trading_connected:
                    self.logger.error("CRITICAL: Paper trading connection failed")
            except Exception as e:
                self.logger.error(f"CRITICAL: Paper trading connection exception: {e}", exc_info=True)
                self.trading_connected = False
        return self.trading_connected

    def subscribe_market_data(self):
        """Subscribe to real-time market data for SIP universe."""
        if not self.ibkr_available or not self.sip_universe:
            return False

        if not self.data_subscribed:
            try:
                if not self.ibkr_data.connect():
                    self.logger.error("CRITICAL: Failed to connect IBKRMarketDataManager")
                    return False
                self.ibkr_data.subscribe_symbols(self.sip_universe)
                # Check if any subscriptions succeeded
                if len(self.ibkr_data.subscribed_symbols) == 0:
                    self.logger.error("CRITICAL: No symbols subscribed successfully - all subscriptions failed")
                    return False
                self.data_subscribed = True
                return True
            except Exception as e:
                self.logger.error(f"CRITICAL: Market data subscription exception: {e}", exc_info=True)
                self.data_subscribed = False
                return False
        return True

    def execute_paper_trades(self):
        """Execute paper trades on ALL NYSE SIP symbols using REAL IBKR data (optimized for 1-min)."""
        self.performance.start_cycle()

        if not self.connect_trading():
            self.logger.warning("Paper trading skipped - IBKR not available")
            self.performance.record_skipped_cycle()
            return

        # Ensure market data is subscribed
        sub_result = self.subscribe_market_data()
        self.logger.error(
            f"DEBUG: subscribe_market_data returned {sub_result}, data_subscribed={self.data_subscribed}"
        )
        if not sub_result:
            self.logger.warning("Paper trading skipped - market data not available")
            self.performance.record_skipped_cycle()
            return

        try:
            positions = self.paper_trader.get_positions()
            trades_executed = 0

            self.logger.error(
                f"DEBUG: Starting trade execution, subscribed={self.data_subscribed}"
            )

            # Phase 1: Fetch real-time data (fast)
            phase_start = time.time()
            all_current_data = self.ibkr_data.get_all_current_data()

            self.logger.error(
                f"DEBUG: got {len(all_current_data)} symbols, keys: {list(all_current_data.keys())[:5]}"
            )

            if not all_current_data:
                self.logger.warning("No market data available, skipping cycle")
                self.performance.record_skipped_cycle()
                return

            # Phase 2: Compute cross-sectional features (optimized)
            cross_features = self.ibkr_data.compute_cross_sectional_features(
                all_current_data
            )

            # Phase 3: Fetch historical bars in parallel (optimized)
            all_hist_bars = self.ibkr_data.get_all_historical_bars(
                self.sip_universe, periods=20
            )
            feature_time = time.time() - phase_start
            self.performance.record_phase("features", feature_time)

            # Check if we're running out of time
            if self.performance.should_skip_cycle():
                self.logger.warning(
                    f"Feature computation took {feature_time:.1f}s, skipping predictions"
                )
                self.performance.record_skipped_cycle()
                return

            # Compute market-wide statistics for regime detection
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

            # Phase 4: ML predictions
            pred_start = time.time()
            predictions = []

            for symbol in self.sip_universe:
                if symbol not in cross_features:
                    continue

                # Get historical bars for lookback features
                hist_bars = all_hist_bars.get(symbol)
                if hist_bars is None or len(hist_bars) < 5:
                    continue

                # Compute relative strength features
                closes = hist_bars["close"].values
                rel_strength_5 = (
                    (closes[-1] - closes[-5]) / closes[-5] if len(closes) >= 5 else 0
                )
                rel_strength_10 = (
                    (closes[-1] - closes[-10]) / closes[-10] if len(closes) >= 10 else 0
                )
                rel_strength_20 = (
                    (closes[-1] - closes[-20]) / closes[-20] if len(closes) >= 20 else 0
                )

                # Combine all features
                features = {
                    **cross_features[symbol],
                    **market_data,
                    "rel_strength_5": rel_strength_5,
                    "rel_strength_10": rel_strength_10,
                    "rel_strength_20": rel_strength_20,
                    "market_ret_5": market_ret,
                    "market_ret_10": market_ret,
                    "cross_dispersion": market_volatility,
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
                if prediction is not None:
                    predictions.append((symbol, prediction))

            pred_time = time.time() - pred_start
            self.performance.record_phase("predictions", pred_time)

            # Phase 5: Place orders
            order_start = time.time()
            for symbol, prediction in predictions:
                current_position = positions.get(symbol, 0)

                # Trading logic based on regime-aware strategy
                if prediction > 0.65 and current_position <= 0:
                    success = self.paper_trader.place_order(symbol, "BUY", 100)
                    if success:
                        trades_executed += 1
                        self.logger.info(
                            f"PAPER BUY: {symbol} (score: {prediction:.3f})"
                        )

                elif prediction < 0.35 and current_position >= 0:
                    quantity = max(current_position, 100)
                    success = self.paper_trader.place_order(symbol, "SELL", quantity)
                    if success:
                        trades_executed += 1
                        self.logger.info(
                            f"PAPER SELL: {symbol} (score: {prediction:.3f})"
                        )

            order_time = time.time() - order_start
            self.performance.record_phase("orders", order_time)

            cycle_time = self.performance.end_cycle()

            self.logger.info(
                f"Executed {trades_executed} paper trades from {len(self.sip_universe)} symbols "
                f"(cycle: {cycle_time:.1f}s, features: {feature_time:.1f}s, pred: {pred_time:.1f}s, orders: {order_time:.1f}s)"
            )

        except Exception as e:
            self.logger.error(f"CRITICAL: Paper trading cycle failed: {e}", exc_info=True)
            self.performance.record_skipped_cycle()

    def run_live_system(self):
        """Main live trading system loop - LIVE DATA ONLY."""
        # Check prerequisites
        if not os.getenv("POLYGON_API_KEY"):
            raise RuntimeError("POLYGON_API_KEY not set")

        # Check IBKR availability
        self.ibkr_available = self.check_ibkr_connection()

        # Load daily universe (LIVE DATA ONLY)
        self.load_or_create_daily_universe()

        last_trade_time = 0
        last_ibkr_check = 0

        try:
            while True:
                current_time = time.time()
                et_now = self.get_et_time()

                # Recheck IBKR every 5 minutes if not available
                if not self.ibkr_available and (current_time - last_ibkr_check) > 300:
                    self.ibkr_available = self.check_ibkr_connection()
                    last_ibkr_check = current_time

                # L2 Collection Management
                should_collect_l2 = self.is_l2_collection_time()

                if should_collect_l2 and not self.l2_active and self.ibkr_available:
                    self.start_l2_collection()
                elif not should_collect_l2 and self.l2_active:
                    self.stop_l2_collection()

                # Poll L2 data if active
                if self.l2_active and self.l2_collector:
                    try:
                        self.l2_collector.poll_once()
                    except Exception as e:
                        self.logger.error(f"L2 polling failed: {e}")

                # Paper Trading (every 1 minute during market hours)
                if self.is_market_hours() and current_time - last_trade_time > 60:
                    self.execute_paper_trades()
                    last_trade_time = current_time

                time.sleep(5)

        except KeyboardInterrupt:
            pass
        except Exception as e:
            self.logger.error(f"CRITICAL: System error in main loop: {e}", exc_info=True)
        finally:
            try:
                if self.l2_active:
                    self.stop_l2_collection()
            except Exception as e:
                self.logger.error(f"CRITICAL: L2 stop failed in cleanup: {e}", exc_info=True)

            try:
                if self.trading_connected:
                    self.paper_trader.disconnect()
            except Exception as e:
                self.logger.error(f"CRITICAL: Paper trader disconnect failed: {e}", exc_info=True)

            try:
                if self.data_subscribed:
                    self.ibkr_data.disconnect()
            except Exception as e:
                self.logger.error(f"CRITICAL: IBKR disconnect failed: {e}", exc_info=True)


def main():
    """Main entry point."""
    system = LiveTradingSystem()
    system.run_live_system()


if __name__ == "__main__":
    main()
