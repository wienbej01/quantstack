"""
Trading Notifications Module

Provides NTFY notifications for trading activities:
- Trade entries and exits
- P&L reporting
- Strategy identification
- Position management
"""

import logging
from datetime import datetime
from typing import Optional

import requests

logger = logging.getLogger(__name__)

# NTFY channels
NTFY_TRADES = "https://ntfy.sh/jacobw-trading-trades"
NTFY_STATUS = "https://ntfy.sh/jacobw-trading-status"


def send_trade_notification(
    action: str,  # "ENTRY" or "EXIT"
    symbol: str,
    strategy: str,
    direction: str,  # "LONG" or "SHORT"
    price: float,
    quantity: int,
    pnl: Optional[float] = None,
    exit_reason: Optional[str] = None,
):
    """Send trade notification to NTFY."""
    try:
        now_et = datetime.now().strftime("%H:%M:%S ET")

        if action == "ENTRY":
            title = f"📈 {direction} {symbol}"
            message = (
                f"🕐 {now_et}\n"
                f"📊 Strategy: {strategy}\n"
                f"💰 Price: ${price:.2f}\n"
                f"📦 Quantity: {quantity:,} shares\n"
                f"💵 Value: ${price * quantity:,.2f}"
            )
            tags = "chart_with_upwards_trend"

        else:  # EXIT
            pnl_emoji = "💚" if pnl and pnl > 0 else "❤️" if pnl and pnl < 0 else "💛"
            title = f"📉 EXIT {symbol} {pnl_emoji}"
            message = (
                f"🕐 {now_et}\n"
                f"📊 Strategy: {strategy}\n"
                f"💰 Exit Price: ${price:.2f}\n"
                f"📦 Quantity: {quantity:,} shares\n"
                f"{pnl_emoji} P&L: ${pnl:.2f}"
                if pnl
                else ""
            )
            if exit_reason:
                message += f"\n🎯 Reason: {exit_reason}"

            tags = "money_with_wings"

        requests.post(
            NTFY_TRADES,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "3", "Tags": tags},
            timeout=10,
        )

        logger.info(f"Trade notification sent: {action} {symbol}")

    except Exception as e:
        logger.error(f"Failed to send trade notification: {e}")


def send_position_update(symbol: str, unrealized_pnl: float, strategy: str):
    """Send position update notification."""
    try:
        pnl_emoji = "💚" if unrealized_pnl > 0 else "❤️" if unrealized_pnl < 0 else "💛"
        now_et = datetime.now().strftime("%H:%M ET")

        title = f"📊 {symbol} Update {pnl_emoji}"
        message = (
            f"🕐 {now_et}\n"
            f"📊 Strategy: {strategy}\n"
            f"{pnl_emoji} Unrealized P&L: ${unrealized_pnl:.2f}"
        )

        requests.post(
            NTFY_STATUS,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "2", "Tags": "chart"},
            timeout=10,
        )

    except Exception as e:
        logger.error(f"Failed to send position update: {e}")


def send_daily_summary(total_pnl: float, trades_count: int, win_rate: float):
    """Send daily trading summary."""
    try:
        pnl_emoji = "💚" if total_pnl > 0 else "❤️" if total_pnl < 0 else "💛"
        now_et = datetime.now().strftime("%H:%M ET")

        title = f"📈 Daily Summary {pnl_emoji}"
        message = (
            f"🕐 {now_et}\n"
            f"📊 Total Trades: {trades_count}\n"
            f"{pnl_emoji} Total P&L: ${total_pnl:.2f}\n"
            f"🎯 Win Rate: {win_rate:.1%}"
        )

        requests.post(
            NTFY_TRADES,
            data=message.encode("utf-8"),
            headers={"Title": title, "Priority": "3", "Tags": "bar_chart"},
            timeout=10,
        )

    except Exception as e:
        logger.error(f"Failed to send daily summary: {e}")


def send_system_status(message: str, priority: int = 3):
    """Send general system status notification."""
    try:
        now_et = datetime.now().strftime("%H:%M ET")

        requests.post(
            NTFY_STATUS,
            data=f"🕐 {now_et}\n{message}".encode("utf-8"),
            headers={
                "Title": "Trading System",
                "Priority": str(priority),
                "Tags": "gear",
            },
            timeout=10,
        )

    except Exception as e:
        logger.error(f"Failed to send system status: {e}")
