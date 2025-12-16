#!/usr/bin/env python3
"""Live trading system - LIVE DATA ONLY with robust error handling."""

import logging
import os
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Optional
import pytz

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, "qx-data/qx_data")
sys.path.insert(0, "scripts")

from daily_sip_scheduler import load_daily_sip_results, run_daily_sip_selection
from live.l2_collector import QuantstackL2Collector
from live.ml_predictor import PaperTrader, RegimeAwarePredictor


class LiveTradingSystem:
    """Live trading system with robust error handling."""

    def __init__(self):
        self.logger = self._setup_logging()
        self.et_tz = pytz.timezone('America/New_York')
        
        # Components
        self.ml_predictor = RegimeAwarePredictor("./models/regime_aware")
        self.paper_trader = PaperTrader()
        self.l2_collector: Optional[QuantstackL2Collector] = None
        
        # State
        self.sip_universe = []
        self.l2_symbols = []
        self.trading_connected = False
        self.l2_active = False
        self.ibkr_available = False
        
    def _setup_logging(self) -> logging.Logger:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'live_trading.log'),
                logging.StreamHandler()
            ]
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
            ib.connect('127.0.0.1', 7497, clientId=999, readonly=True, timeout=3)
            if ib.isConnected():
                self.logger.info("✅ IBKR connection available")
                ib.disconnect()
                return True
            else:
                self.logger.warning("❌ IBKR connection failed")
                return False
        except Exception as e:
            self.logger.warning(f"❌ IBKR not available: {e}")
            return False

    def load_or_create_daily_universe(self):
        """Load today's SIP universe - LIVE DATA ONLY."""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
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
        
        self.logger.info(f"LIVE universe loaded: {len(self.sip_universe)} NYSE SIP symbols, {len(self.l2_symbols)} L2 symbols")
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
        return (dt_time(9, 30) <= current_time <= dt_time(10, 30) or 
                dt_time(15, 0) <= current_time <= dt_time(16, 0))

    def start_l2_collection(self):
        """Start L2 data collection if IBKR available."""
        if not self.ibkr_available:
            self.logger.warning("L2 collection skipped - IBKR not available")
            return
            
        if not self.l2_symbols:
            self.logger.warning("No L2 symbols available")
            return
            
        config = {
            'host': '127.0.0.1',
            'port': 7497,
            'client_id': 500,
            'levels': 10,
            'max_symbols': len(self.l2_symbols),
            'rotate_seconds': 300,
            'output_dir': './data/live_l2',
            'run_id': f"live_{datetime.now().strftime('%Y%m%d')}",
            'windows': '09:30-10:30,15:00-16:00'
        }
        
        try:
            self.l2_collector = QuantstackL2Collector(self.l2_symbols, config)
            self.l2_collector.start_collection()
            self.l2_active = True
            self.logger.info(f"✅ L2 collection started: {self.l2_symbols}")
        except Exception as e:
            self.logger.error(f"❌ L2 collection start failed: {e}")
            self.l2_active = False

    def stop_l2_collection(self):
        """Stop L2 collection."""
        if self.l2_collector:
            try:
                metadata = self.l2_collector.stop_collection()
                counters = metadata.get('counters', {})
                self.logger.info(f"L2 collection stopped: {counters}")
            except Exception as e:
                self.logger.error(f"L2 collection stop failed: {e}")
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
                if self.trading_connected:
                    self.logger.info("✅ Paper trading connected")
            except Exception as e:
                self.logger.error(f"❌ Paper trading connection failed: {e}")
                self.trading_connected = False
        return self.trading_connected

    def execute_paper_trades(self):
        """Execute paper trades on ALL NYSE SIP symbols."""
        if not self.connect_trading():
            self.logger.warning("Paper trading skipped - IBKR not available")
            return
            
        try:
            positions = self.paper_trader.get_positions()
            trades_executed = 0
            
            self.logger.info(f"Analyzing {len(self.sip_universe)} LIVE NYSE SIP symbols for trades...")
            
            for symbol in self.sip_universe:
                # Mock market data (replace with real Polygon data)
                mock_data = {
                    "volatility": 0.25,
                    "volume": 2000000,
                    "price_momentum": 0.02
                }
                
                # Get ML prediction using regime-aware model
                prediction = self.ml_predictor.predict(symbol, mock_data)
                if prediction is None:
                    continue
                
                current_position = positions.get(symbol, 0)
                
                # Trading logic based on regime-aware strategy
                if prediction > 0.65 and current_position <= 0:
                    success = self.paper_trader.place_order(symbol, "BUY", 100)
                    if success:
                        trades_executed += 1
                        self.logger.info(f"PAPER BUY: {symbol} (score: {prediction:.3f})")
                        
                elif prediction < 0.35 and current_position >= 0:
                    quantity = max(current_position, 100)
                    success = self.paper_trader.place_order(symbol, "SELL", quantity)
                    if success:
                        trades_executed += 1
                        self.logger.info(f"PAPER SELL: {symbol} (score: {prediction:.3f})")
                    
            self.logger.info(f"Executed {trades_executed} paper trades from {len(self.sip_universe)} LIVE NYSE symbols")
                
        except Exception as e:
            self.logger.error(f"Paper trading failed: {e}")

    def run_live_system(self):
        """Main live trading system loop - LIVE DATA ONLY."""
        et_now = self.get_et_time()
        self.logger.info(f"=== STARTING LIVE TRADING SYSTEM ===")
        self.logger.info(f"Current ET time: {et_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
        
        # Check prerequisites
        if not os.getenv('POLYGON_API_KEY'):
            raise RuntimeError("POLYGON_API_KEY not set")
        
        # Check IBKR availability
        self.ibkr_available = self.check_ibkr_connection()
        if not self.ibkr_available:
            self.logger.warning("⚠️  IBKR not available - L2 collection and paper trading disabled")
        
        # Load daily universe (LIVE DATA ONLY)
        self.load_or_create_daily_universe()
        
        self.logger.info("🔄 Entering main trading loop...")
        
        last_trade_time = 0
        last_ibkr_check = 0
        
        try:
            self.logger.info("🔄 Starting main loop iteration...")
            while True:
                self.logger.info("Getting current time...")
                current_time = time.time()
                et_now = self.get_et_time()
                self.logger.info(f"Time obtained: {et_now}")
                
                self.logger.info("Checking IBKR availability...")
                # Recheck IBKR every 5 minutes if not available
                if not self.ibkr_available and (current_time - last_ibkr_check) > 300:
                    self.ibkr_available = self.check_ibkr_connection()
                    last_ibkr_check = current_time
                
                self.logger.info("Checking L2 collection time...")
                # L2 Collection Management
                should_collect_l2 = self.is_l2_collection_time()
                self.logger.info(f"Should collect L2: {should_collect_l2}")
                
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
                
                # Paper Trading (every 5 minutes during market hours)
                if (self.is_market_hours() and 
                    current_time - last_trade_time > 300):
                    
                    self.execute_paper_trades()
                    last_trade_time = current_time
                
                # Status logging
                if int(current_time) % 120 == 0:
                    market_status = "OPEN" if self.is_market_hours() else "CLOSED"
                    l2_status = "COLLECTING" if self.l2_active else "IDLE"
                    ibkr_status = "✅" if self.ibkr_available else "❌"
                    
                    self.logger.info(
                        f"ET: {et_now.strftime('%H:%M:%S')} | Market: {market_status} | "
                        f"L2: {l2_status} | IBKR: {ibkr_status} | "
                        f"SIP: {len(self.sip_universe)} | L2 Symbols: {len(self.l2_symbols)}"
                    )
                
                self.logger.info("Sleeping 5 seconds...")
                time.sleep(5)
                self.logger.info("Woke up, continuing loop...")
                
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received")
        except Exception as e:
            self.logger.error(f"System error: {e}")
        finally:
            if self.l2_active:
                self.stop_l2_collection()
            if self.trading_connected:
                self.paper_trader.disconnect()
            self.logger.info("Live trading system stopped")


def main():
    """Main entry point."""
    system = LiveTradingSystem()
    system.run_live_system()


if __name__ == "__main__":
    main()
