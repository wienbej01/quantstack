#!/usr/bin/env python3
"""Live trading system - Trade ALL NYSE SIP symbols with regime-aware model."""

import logging
import os
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Optional

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, "qx-data")

from daily_sip_scheduler import load_daily_sip_results, run_daily_sip_selection
from qx_data.live.l2_collector import QuantstackL2Collector
from qx_data.live.ml_predictor import PaperTrader, RegimeAwarePredictor


class LiveTradingSystem:
    """Live trading system - ALL NYSE SIP symbols + L2 collection."""

    def __init__(self):
        self.logger = self._setup_logging()
        
        # Components
        self.ml_predictor = RegimeAwarePredictor("./models/regime_aware")
        self.paper_trader = PaperTrader()
        self.l2_collector: Optional[QuantstackL2Collector] = None
        
        # State
        self.sip_universe = []  # ALL NYSE symbols that pass SIP
        self.l2_symbols = []    # Top 6 for L2 collection
        self.trading_connected = False
        self.l2_active = False
        
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

    def load_or_create_daily_universe(self):
        """Load today's SIP universe or create if missing."""
        date_str = datetime.now().strftime('%Y-%m-%d')
        
        # Try to load existing results
        sip_universe, l2_symbols = load_daily_sip_results(date_str)
        
        if sip_universe is None:
            self.logger.info("No daily SIP results found, running selection...")
            sip_universe, l2_symbols = run_daily_sip_selection()
            
            if sip_universe is None:
                self.logger.error("Failed to create daily SIP universe")
                return False
        
        self.sip_universe = sip_universe
        self.l2_symbols = l2_symbols
        
        self.logger.info(f"Daily universe loaded: {len(self.sip_universe)} NYSE SIP symbols, {len(self.l2_symbols)} L2 symbols")
        return True

    def is_market_hours(self) -> bool:
        """Check if in market hours (9:30-16:00 ET)."""
        now = datetime.now()
        current_time = now.time()
        return dt_time(9, 30) <= current_time <= dt_time(16, 0)

    def is_l2_collection_time(self) -> bool:
        """Check if in L2 collection windows."""
        now = datetime.now()
        current_time = now.time()
        
        # Opening hour: 9:30-10:30, Power hour: 15:00-16:00
        return (dt_time(9, 30) <= current_time <= dt_time(10, 30) or 
                dt_time(15, 0) <= current_time <= dt_time(16, 0))

    def start_l2_collection(self):
        """Start L2 data collection for top NYSE symbols."""
        if not self.l2_symbols:
            self.logger.warning("No L2 symbols available")
            return
            
        config = {
            'host': '127.0.0.1',
            'port': 7497,
            'client_id': 500,
            'levels': 10,
            'max_symbols': len(self.l2_symbols),
            'rotate_seconds': 300,  # 5-minute rotation
            'output_dir': './data/live_l2',
            'run_id': f"live_{datetime.now().strftime('%Y%m%d')}",
            'windows': '09:30-10:30,15:00-16:00'
        }
        
        try:
            self.l2_collector = QuantstackL2Collector(self.l2_symbols, config)
            self.l2_collector.start_collection()
            self.l2_active = True
            self.logger.info(f"L2 collection started: {self.l2_symbols}")
        except Exception as e:
            self.logger.error(f"L2 collection start failed: {e}")

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
        if not self.trading_connected:
            self.trading_connected = self.paper_trader.connect()
            if self.trading_connected:
                self.logger.info("Paper trading connected")
        return self.trading_connected

    def execute_paper_trades(self):
        """Execute paper trades on ALL NYSE SIP symbols."""
        if not self.connect_trading():
            return
            
        try:
            positions = self.paper_trader.get_positions()
            trades_executed = 0
            
            # Trade ALL SIP universe symbols (not just top 20)
            self.logger.info(f"Analyzing {len(self.sip_universe)} NYSE SIP symbols for trades...")
            
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
                
                # Trading logic based on +13% regime-aware strategy
                if prediction > 0.65 and current_position <= 0:  # Strong buy
                    success = self.paper_trader.place_order(symbol, "BUY", 100)
                    if success:
                        trades_executed += 1
                        self.logger.info(f"PAPER BUY: {symbol} (score: {prediction:.3f})")
                        
                elif prediction < 0.35 and current_position >= 0:  # Strong sell
                    quantity = max(current_position, 100)
                    success = self.paper_trader.place_order(symbol, "SELL", quantity)
                    if success:
                        trades_executed += 1
                        self.logger.info(f"PAPER SELL: {symbol} (score: {prediction:.3f})")
                
                # No limit on trades - trade ALL qualifying symbols
                    
            self.logger.info(f"Executed {trades_executed} paper trades from {len(self.sip_universe)} NYSE symbols")
                
        except Exception as e:
            self.logger.error(f"Paper trading failed: {e}")

    def run_live_system(self):
        """Main live trading system loop."""
        self.logger.info("=== STARTING LIVE TRADING SYSTEM ===")
        self.logger.info("Trading ALL NYSE SIP symbols + L2 collection on top 6")
        
        # Verify prerequisites
        if not os.getenv('POLYGON_API_KEY'):
            self.logger.error("POLYGON_API_KEY not set")
            return
        
        # Load daily universe
        if not self.load_or_create_daily_universe():
            return
        
        last_trade_time = 0
        
        try:
            while True:
                current_time = time.time()
                
                # L2 Collection Management
                should_collect_l2 = self.is_l2_collection_time()
                
                if should_collect_l2 and not self.l2_active:
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
                
                # Status logging (every 2 minutes)
                if int(current_time) % 120 == 0:
                    market_status = "OPEN" if self.is_market_hours() else "CLOSED"
                    l2_status = "COLLECTING" if self.l2_active else "IDLE"
                    
                    self.logger.info(
                        f"Status: {market_status} | L2: {l2_status} | "
                        f"NYSE SIP: {len(self.sip_universe)} | L2: {len(self.l2_symbols)}"
                    )
                
                time.sleep(5)  # 5-second polling
                
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received")
        except Exception as e:
            self.logger.error(f"System error: {e}")
        finally:
            # Cleanup
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
