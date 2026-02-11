"""NTFY notification helpers (ASCII-only messages)."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Optional
from urllib import request

logger = logging.getLogger(__name__)

NTFY_TRADES = os.environ.get("NTFY_TRADES", "https://ntfy.sh/jacobw-trading-trades")
NTFY_STATUS = os.environ.get("NTFY_STATUS", "https://ntfy.sh/jacobw-trading-status")
NTFY_ALERTS = os.environ.get("NTFY_ALERTS", "https://ntfy.sh/jacobw-trading-alerts")


def _post(url: str, message: str, title: str, priority: int, tags: str) -> None:
    data = message.encode("utf-8")
    headers = {
        "Title": title,
        "Priority": str(priority),
        "Tags": tags,
    }
    req = request.Request(url, data=data, headers=headers, method="POST")
    with request.urlopen(req, timeout=10) as resp:
        resp.read()


def _format_strategy(strategy: str) -> str:
    """Format strategy tag for display (replace colon with space)."""
    # Convert "l2-scalping:vwap" to "l2-scalping vwap"
    return strategy.replace(":", " ")


def send_trade_notification(
    action: str,
    symbol: str,
    strategy: str,
    direction: str,
    price: float,
    quantity: int,
    pnl: Optional[float] = None,
    exit_reason: Optional[str] = None,
    position_id: Optional[str] = None,
) -> None:
    """Send trade notification to NTFY."""
    try:
        now_et = datetime.now().strftime("%H:%M:%S ET")
        strategy_display = _format_strategy(strategy)

        if action == "ENTRY":
            pos_id = f" [{position_id}]" if position_id else ""
            title = f"Opening {symbol} position{pos_id}"
            message = (
                f"Time: {now_et}\n"
                f"Strategy: {strategy_display}\n"
                f"Side: {direction}\n"
                f"Quantity: {quantity:,}\n"
                f"Price: ${price:.2f}\n"
                f"Value: ${price * quantity:,.2f}"
            )
            tags = "trade"
        else:
            # EXIT
            pos_id = position_id if position_id else symbol
            pnl_str = f" ${pnl:.2f}" if pnl is not None else ""
            title = f"Closing position {pos_id}{pnl_str}"
            message = (
                f"Time: {now_et}\n"
                f"Symbol: {symbol}\n"
                f"Strategy: {strategy_display}\n"
                f"Exit Price: ${price:.2f}\n"
                f"Quantity: {quantity:,}"
            )
            if pnl is not None:
                message += f"\nPnL: ${pnl:.2f}"
            if exit_reason:
                message += f"\nReason: {exit_reason}"
            tags = "trade"

        _post(NTFY_TRADES, message, title, priority=3, tags=tags)
        logger.info("Trade notification sent: %s %s", action, symbol)
    except Exception as exc:
        logger.error("Failed to send trade notification: %s", exc)


def send_position_update(symbol: str, unrealized_pnl: float, strategy: str) -> None:
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        title = f"Position Update {symbol}"
        message = (
            f"Time: {now_et}\n"
            f"Strategy: {strategy}\n"
            f"Unrealized PnL: ${unrealized_pnl:.2f}"
        )
        _post(NTFY_STATUS, message, title, priority=2, tags="position")
    except Exception as exc:
        logger.error("Failed to send position update: %s", exc)


def send_daily_summary(total_pnl: float, trades_count: int, win_rate: float) -> None:
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        title = "Daily Summary"
        message = (
            f"Time: {now_et}\n"
            f"Total Trades: {trades_count}\n"
            f"Total PnL: ${total_pnl:.2f}\n"
            f"Win Rate: {win_rate:.1%}"
        )
        _post(NTFY_TRADES, message, title, priority=3, tags="summary")
    except Exception as exc:
        logger.error("Failed to send daily summary: %s", exc)


def send_status_message(message: str, priority: int = 3, tags: str = "status") -> None:
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        body = f"Time: {now_et}\n{message}"
        _post(NTFY_STATUS, body, "Trading System", priority=priority, tags=tags)
    except Exception as exc:
        logger.error("Failed to send status message: %s", exc)


def send_system_start(system_name: str) -> None:
    """Send notification when system starts (scheduled startup)."""
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        body = f"Time: {now_et}\n\n{system_name} is starting for the trading session"
        _post(
            NTFY_STATUS,
            body,
            f"{system_name} Starting",
            priority=3,
            tags="white_check_mark",
        )
        logger.info("System start notification sent: %s", system_name)
    except Exception as exc:
        logger.error("Failed to send system start notification: %s", exc)


def send_system_end(system_name: str, reason: str = "End of trading session") -> None:
    """Send notification when system ends (orderly shutdown)."""
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        body = f"Time: {now_et}\n\n{system_name} ended\nReason: {reason}"
        _post(
            NTFY_STATUS,
            body,
            f"{system_name} Ended",
            priority=3,
            tags="white_check_mark",
        )
        logger.info("System end notification sent: %s", system_name)
    except Exception as exc:
        logger.error("Failed to send system end notification: %s", exc)


def send_system_recovery(system_name: str) -> None:
    """Send notification when system recovers from unexpected failure."""
    try:
        now_et = datetime.now().strftime("%H:%M ET")
        body = (
            f"Time: {now_et}\n\n{system_name} has recovered and is resuming operation"
        )
        _post(
            NTFY_STATUS,
            body,
            f"{system_name} Recovered",
            priority=4,
            tags="rotating_light",
        )
        logger.info("System recovery notification sent: %s", system_name)
    except Exception as exc:
        logger.error("Failed to send system recovery notification: %s", exc)


def send_api_event(event_type: str, details: str, priority: int = 4) -> None:
    """Send notification for API events (connect, disconnect, timeout, etc)."""
    try:
        now_et = datetime.now().strftime("%H:%M:%S ET")
        body = f"Time: {now_et}\n\n{details}"
        title = f"API: {event_type}"
        tags = "warning" if priority >= 4 else "info"
        _post(NTFY_STATUS, body, title, priority=priority, tags=tags)
        logger.info("API event notification sent: %s", event_type)
    except Exception as exc:
        logger.error("Failed to send API event notification: %s", exc)
