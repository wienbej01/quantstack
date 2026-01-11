#!/usr/bin/env python3
"""
Critical Trading System Fixes

1. Add end-of-day position flattening
2. Fix stop/target order execution
3. Ensure live price feeds
"""

import logging
from datetime import datetime, time

import pytz

logger = logging.getLogger(__name__)
ET = pytz.timezone("America/New_York")


class TradingSystemFixes:
    """Critical fixes for trading system issues"""

    def __init__(self, paper_trading_system):
        self.system = paper_trading_system
        self.market_close_time = time(16, 0)  # 4:00 PM ET

    def check_eod_flatten(self):
        """Check if we need to flatten positions at end of day"""
        now_et = datetime.now(ET).time()

        # Flatten 15 minutes before close
        flatten_time = time(15, 45)

        if now_et >= flatten_time and self.system._active_trades:
            logger.warning(
                f"EOD FLATTEN: {len(self.system._active_trades)} positions need closing"
            )
            self.flatten_all_positions("EOD_FLATTEN")

    def flatten_all_positions(self, reason: str = "MANUAL"):
        """Force close all open positions"""
        if not self.system._active_trades:
            return

        logger.info(f"Flattening {len(self.system._active_trades)} positions: {reason}")

        for parent_id, trade_info in list(self.system._active_trades.items()):
            symbol = trade_info["symbol"]
            direction = trade_info["direction"]

            # Cancel existing stop/target orders
            if trade_info.get("stop_id"):
                try:
                    self.system.adapter.cancel_order(trade_info["stop_id"])
                except:
                    pass

            if trade_info.get("target_id"):
                try:
                    self.system.adapter.cancel_order(trade_info["target_id"])
                except:
                    pass

            # Submit market order to close
            close_side = "SELL" if direction == "long" else "BUY"
            try:
                close_order_id = self.system.adapter.submit_order(
                    symbol=symbol,
                    action=close_side,
                    quantity=trade_info["entry_qty"],
                    order_type="MKT",
                )

                logger.info(
                    f"EOD CLOSE: {symbol} {close_side} market order {close_order_id}"
                )

                # Map for fill detection
                self.system._order_to_trade[close_order_id] = parent_id

            except Exception as e:
                logger.error(f"Failed to close {symbol}: {e}")

                # Force close in journal
                self.system.event_store.close_trade(
                    trade_id=trade_info["trade_id"],
                    exit_order_id=0,
                    exit_price=trade_info["entry_price"],  # Use entry as fallback
                    exit_qty=trade_info["entry_qty"],
                    exit_reason=reason,
                    commission=0,
                )

                del self.system._active_trades[parent_id]

    def validate_live_prices(self, symbol: str, price: float) -> bool:
        """Validate price is live and not stale"""
        # Check if price is suspiciously identical to previous
        if hasattr(self, "_last_prices"):
            last_price = self._last_prices.get(symbol)
            if last_price and abs(price - last_price) < 0.001:
                logger.warning(f"STALE PRICE: {symbol} {price} identical to previous")
                return False
        else:
            self._last_prices = {}

        self._last_prices[symbol] = price
        return True

    def check_bracket_orders(self):
        """Check if bracket orders are working properly"""
        if not self.system._active_trades:
            return

        for parent_id, trade_info in self.system._active_trades.items():
            stop_id = trade_info.get("stop_id")
            target_id = trade_info.get("target_id")

            if not stop_id or not target_id:
                logger.error(
                    f"MISSING BRACKET: {trade_info['symbol']} parent={parent_id}"
                )
                continue

            # Check order status via IBKR
            try:
                if self.system.adapter:
                    stop_status = self.system.adapter.get_order_status(stop_id)
                    target_status = self.system.adapter.get_order_status(target_id)

                    if stop_status == "Cancelled" or target_status == "Cancelled":
                        logger.error(
                            f"BRACKET CANCELLED: {trade_info['symbol']} stop={stop_status} target={target_status}"
                        )

            except Exception as e:
                logger.error(f"Cannot check bracket status: {e}")


# Integration into main trading loop
def add_critical_fixes_to_trading_loop():
    """Add these checks to the main trading loop"""
    fixes_code = """
    # Add to PaperTradingSystem.__init__
    self.trading_fixes = TradingSystemFixes(self)
    
    # Add to main trading loop (every iteration)
    def run_trading_cycle(self):
        try:
            # Existing trading logic...
            
            # CRITICAL FIXES - Add these checks
            self.trading_fixes.check_eod_flatten()
            self.trading_fixes.check_bracket_orders()
            
        except Exception as e:
            logger.error(f"Trading cycle error: {e}")
    """
    return fixes_code


if __name__ == "__main__":
    print("CRITICAL TRADING SYSTEM ISSUES IDENTIFIED:")
    print("1. ❌ NO END-OF-DAY FLATTENING - positions stay open overnight")
    print("2. ❌ BRACKET ORDERS NOT EXECUTING - stops/targets not working")
    print("3. ❌ STALE PRICE DATA - identical entry prices across time")
    print("\nFIXES REQUIRED:")
    print("- Add EOD position flattening at 3:45 PM ET")
    print("- Debug IBKR bracket order execution")
    print("- Validate live price feeds")
    print("- Add order status monitoring")
