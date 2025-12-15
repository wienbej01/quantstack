#!/usr/bin/env python3
"""Production live trading with SIP selection, paper trading, and L2 collection."""

import logging
import os
import sys
import time
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any

import yaml

# Add paths
sys.path.insert(0, str(Path.home() / "transalpha" / "l2"))
sys.path.insert(0, "qx-data")

from qx_data.live.l2_collector import QuantstackL2Collector
from qx_data.live.ml_predictor import PaperTrader, RegimeAwarePredictor
from qx_data.live.polygon_sip import PolygonSIPSelector


class ProductionTradingSystem:
    """Complete production trading system."""

    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)
        
        self.logger = self._setup_logging()
        
        # Initialize components
        self.polygon_sip = PolygonSIPSelector()
        self.ml_predictor = RegimeAwarePredictor("./models/regime_aware")
        self.paper_trader = PaperTrader()
        
        # State
        self.sip_universe = []
        self.l2_symbols = []
        self.l2_collector = None
        self.trading_connected = False
        
    def _setup_logging(self) -> logging.Logger:
        """Setup logging."""
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_dir / 'production_trading.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)

    def get_sip_universe(self) -> list[str]:
        """Get daily SIP universe from Polygon."""
        try:
            universe = self.polygon_sip.get_sip_universe(
                top_k=self.config["sip"]["config"]["top_k"],
                min_score=self.config["sip"]["config"]["score_floor"]
            )
            self.logger.info(f"SIP universe: {len(universe)} symbols")
            return universe
        except Exception as e:
            self.logger.error(f"SIP selection failed: {e}")
            return []

    def select_l2_symbols(self, sip_universe: list[str]) -> list[str]:
        """Select top NYSE symbols for L2 collection."""
        try:
            nyse_symbols = self.polygon_sip.get_nyse_symbols(sip_universe)
            
            # Select top 6 NYSE symbols for maximum L2 data collection
            l2_symbols = nyse_symbols[:6]
            self.logger.info(f"L2 symbols selected: {l2_symbols}")
            return l2_symbols
        except Exception as e:
            self.logger.error(f"L2 symbol selection failed: {e}")
            return []

    def is_market_hours(self) -> bool:
        """Check if in market hours (9:30-16:00 ET)."""
        now = datetime.now()
        # Simple time check - would need proper ET timezone for production
        current_time = now.time()
        return dt_time(9, 30) <= current_time <= dt_time(16, 0)

    def is_l2_collection_time(self) -> bool:
        """Check if in L2 collection windows."""
        now = datetime.now()
        current_time = now.time()
        
        # Opening hour: 9:30-10:30
        # Power hour: 15:00-16:00
        return (dt_time(9, 30) <= current_time <= dt_time(10, 30) or 
                dt_time(15, 0) <= current_time <= dt_time(16, 0))

    def start_l2_collection(self):
        """Start strategic L2 data collection."""
        if not self.l2_symbols:
            return
            
        config = {
            'host': '127.0.0.1',
            'port': 7497,
            'client_id': 300,
            'levels': 10,
            'max_symbols': 6,  # Maximize subscription usage
            'rotate_seconds': 600,  # 10-minute rotation
            'output_dir': './data/production_l2',
            'run_id': f"prod_{datetime.now().strftime('%Y%m%d')}",
            'windows': '09:30-10:30,15:00-16:00'
        }
        
        try:
            self.l2_collector = QuantstackL2Collector(self.l2_symbols, config)
            self.l2_collector.start_collection()
            self.logger.info(f"L2 collection started: {self.l2_symbols}")
        except Exception as e:
            self.logger.error(f"L2 collection start failed: {e}")

    def stop_l2_collection(self):
        """Stop L2 collection."""
        if self.l2_collector:
            try:
                metadata = self.l2_collector.stop_collection()
                self.logger.info(f"L2 collection stopped: {metadata.get('counters', {})}")
            except Exception as e:
                self.logger.error(f"L2 collection stop failed: {e}")
            finally:
                self.l2_collector = None

    def connect_trading(self) -> bool:
        """Connect to IBKR for paper trading."""
        if not self.trading_connected:
            self.trading_connected = self.paper_trader.connect()
        return self.trading_connected

    def execute_paper_trades(self):
        """Execute paper trades based on ML predictions."""
        if not self.connect_trading():
            return
            
        try:
            positions = self.paper_trader.get_positions()
            
            # Analyze top symbols for trading opportunities
            for symbol in self.sip_universe[:20]:  # Limit analysis
                
                # Get market data for ML features
                market_data = self.polygon_sip.get_market_data(symbol)
                if not market_data:
                    continue
                
                # Make ML prediction
                prediction = self.ml_predictor.predict(symbol, market_data)
                if prediction is None:
                    continue
                
                current_position = positions.get(symbol, 0)
                
                # Trading logic based on prediction
                if prediction > 0.65 and current_position <= 0:  # Strong buy signal
                    self.paper_trader.place_order(symbol, "BUY", 100)
                    self.logger.info(f"PAPER BUY: {symbol} (score: {prediction:.3f})")
                    
                elif prediction < 0.35 and current_position >= 0:  # Strong sell signal
                    if current_position > 0:
                        self.paper_trader.place_order(symbol, "SELL", current_position)
                    else:
                        self.paper_trader.place_order(symbol, "SELL", 100)
                    self.logger.info(f"PAPER SELL: {symbol} (score: {prediction:.3f})")
                    
        except Exception as e:
            self.logger.error(f"Paper trading failed: {e}")

    def run_daily_setup(self):
        """Run daily setup tasks."""
        self.logger.info("=== DAILY SETUP ===")
        
        # 1. Get SIP universe from Polygon
        self.sip_universe = self.get_sip_universe()
        
        # 2. Select L2 symbols (top NYSE from SIP)
        self.l2_symbols = self.select_l2_symbols(self.sip_universe)
        
        self.logger.info(f"Setup complete: {len(self.sip_universe)} SIP, {len(self.l2_symbols)} L2")

    def run_trading_loop(self):
        """Main production trading loop."""
        self.logger.info("=== STARTING PRODUCTION TRADING ===")
        
        # Verify API key
        if not os.getenv('POLYGON_API_KEY'):
            self.logger.error("POLYGON_API_KEY not set")
            return
        
        # Daily setup
        self.run_daily_setup()
        
        l2_active = False
        last_trade_time = 0
        
        try:
            while True:
                current_time = time.time()
                
                # L2 Collection Management (opening + power hour)
                if self.is_l2_collection_time() and not l2_active:
                    self.start_l2_collection()
                    l2_active = True
                elif not self.is_l2_collection_time() and l2_active:
                    self.stop_l2_collection()
                    l2_active = False
                
                # Poll L2 data if collecting
                if l2_active and self.l2_collector:
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
                if int(current_time) % 60 == 0:  # Every minute
                    market_status = "OPEN" if self.is_market_hours() else "CLOSED"
                    l2_status = "COLLECTING" if l2_active else "IDLE"
                    self.logger.info(
                        f"Status: {market_status} | L2: {l2_status} | "
                        f"SIP: {len(self.sip_universe)} | L2 Symbols: {len(self.l2_symbols)}"
                    )
                
                time.sleep(1)
                
        except KeyboardInterrupt:
            self.logger.info("Shutdown signal received")
        except Exception as e:
            self.logger.error(f"Trading loop error: {e}")
        finally:
            # Cleanup
            if l2_active:
                self.stop_l2_collection()
            if self.trading_connected:
                self.paper_trader.disconnect()
            self.logger.info("Production trading stopped")


def main():
    """Main entry point."""
    config_path = "experiments/live_regime_aware/config.yaml"
    
    if not Path(config_path).exists():
        print(f"❌ Config file not found: {config_path}")
        return
    
    system = ProductionTradingSystem(config_path)
    system.run_trading_loop()


if __name__ == "__main__":
    main()
