#!/usr/bin/env python3
"""
Audit logging utility for all trading systems.
Provides consistent trade-level audit logging.
"""
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def log_trade_entry(
    system: str,
    symbol: str,
    side: str,
    quantity: int,
    entry_price: float,
    signal_price: float,
    order_id: int,
    trade_id: str,
    rule_name: Optional[str] = None,
    strategy: Optional[str] = None,
) -> None:
    """Log trade entry to audit log."""
    context = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "entry_price": entry_price,
        "signal_price": signal_price,
        "order_id": order_id,
        "trade_id": trade_id,
    }
    if rule_name:
        context["rule_name"] = rule_name
    if strategy:
        context["strategy"] = strategy

    slippage = (
        entry_price - signal_price if side == "BUY" else signal_price - entry_price
    )
    context["slippage"] = slippage

    logger.info(
        f"[{system}] TRADE_SIGNAL: ENTRY {side} {quantity} {symbol} @ {entry_price:.4f} | Context: {context}"
    )


def log_trade_exit(
    system: str,
    symbol: str,
    side: str,
    quantity: int,
    exit_price: float,
    order_id: int,
    trade_id: str,
    reason: str,
    pnl: float,
    strategy: Optional[str] = None,
) -> None:
    """Log trade exit to audit log."""
    context = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "exit_price": exit_price,
        "order_id": order_id,
        "trade_id": trade_id,
        "reason": reason,
        "pnl": pnl,
    }
    if strategy:
        context["strategy"] = strategy

    logger.info(
        f"[{system}] TRADE_SIGNAL: EXIT {side} {quantity} {symbol} @ {exit_price:.4f} | Context: {context}"
    )


def log_fill(
    system: str,
    symbol: str,
    side: str,
    quantity: int,
    price: float,
    order_id: int,
    exec_id: str,
) -> None:
    """Log fill event to audit log."""
    context = {
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "price": price,
        "order_id": order_id,
        "exec_id": exec_id,
    }

    logger.info(
        f"[{system}] FILL: {side} {quantity} {symbol} @ {price:.4f} | Context: {context}"
    )
