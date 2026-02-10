"""
Position Monitor - Queries IBKR Gateway for positions and P&L.
"""

import json
import logging
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from qx_broker.ibkr import (
    IBKRAccount,
    IBKRConnectionConfig,
    IBKRSession,
    IBKRSessionConfig,
)
from position_monitor.models import PnLData, Position, PositionsOutput

logger = logging.getLogger(__name__)

# Market hours (US Eastern)
MARKET_OPEN = time(9, 30, tzinfo=ZoneInfo("America/New_York"))
MARKET_CLOSE = time(16, 30, tzinfo=ZoneInfo("America/New_York"))
TIMEZONE = ZoneInfo("America/New_York")


class PositionMonitor:
    """
    Queries IBKR Gateway for positions and P&L, writes to JSON file.

    Args:
        host: IBKR Gateway host (default: 127.0.0.1)
        port: IBKR Gateway port (default: 7497)
        client_id: IBKR client ID (default: 900)
        output_file: Path to output JSON file (default: /tmp/positions.json)
        account_id: IBKR account ID (optional)
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 7497,
        client_id: int = 900,
        output_file: str = "/tmp/positions.json",
        account_id: str | None = None,
    ):
        self.host = host
        self.port = port
        self.client_id = client_id
        self.output_file = Path(output_file)
        self.account_id = account_id

        connection = IBKRConnectionConfig(host=host, port=port, client_id=client_id)
        session_cfg = IBKRSessionConfig(system_name="POSITION_MONITOR", connection=connection)
        self.session = IBKRSession(session_cfg)
        self.account = IBKRAccount(self.session)
        self._pnl_subscription = None

    def connect(self) -> bool:
        """Connect to IBKR Gateway."""
        if not self.session.connect():
            logger.error("Failed to connect to IBKR Gateway")
            return False

        if not self.account_id:
            self.account_id = self._resolve_account_id()
            if self.account_id:
                logger.info("Using account: %s", self.account_id)
            else:
                logger.warning("No account ID resolved from IBKR")

        if self.account_id:
            try:
                self._pnl_subscription = self.account.subscribe_pnl(self.account_id)
            except Exception as exc:
                logger.warning("PnL subscription failed: %s", exc)

        logger.info("Connected to IBKR Gateway")
        return True

    def _resolve_account_id(self) -> str | None:
        try:
            accounts = self.session.call(self.session.ib.managedAccounts, timeout=5)
            if accounts:
                return accounts[0]
        except Exception as exc:
            logger.warning("managedAccounts lookup failed: %s", exc)

        try:
            summary = self.session.call(self.session.ib.accountSummary, timeout=10)
            if summary:
                return summary[0].account
        except Exception as exc:
            logger.warning("accountSummary lookup failed: %s", exc)

        return None

    def is_market_hours(self) -> bool:
        """Check if current time is within market hours (0930-1630 ET)."""
        now = datetime.now(TIMEZONE).time()
        return MARKET_OPEN <= now <= MARKET_CLOSE

    def get_open_positions(self) -> list[Position]:
        """Get open positions from IBKR Gateway."""
        if not self.account_id:
            logger.warning("No account ID available")
            return []

        try:
            positions = []
            for pos in self.account.positions():
                quantity = int(pos.position)
                if quantity == 0:
                    continue

                symbol = pos.contract.symbol
                avg_price = float(pos.avgCost or 0.0)
                current_price = float(pos.marketPrice or avg_price or 0.0)
                market_value = float(pos.marketValue or (quantity * current_price))
                unrealized_pnl = float(
                    pos.unrealizedPNL
                    if pos.unrealizedPNL is not None
                    else market_value - (avg_price * quantity)
                )

                positions.append(
                    Position(
                        symbol=symbol,
                        quantity=quantity,
                        avg_price=avg_price,
                        current_price=current_price,
                        unrealized_pnl=unrealized_pnl,
                        market_value=market_value,
                    )
                )

            logger.info("Retrieved %s open positions", len(positions))
            return positions

        except Exception as exc:
            logger.error("Failed to get positions: %s", exc)
            return []

    def get_daily_pnl(self) -> PnLData:
        """Get daily P&L from IBKR Gateway."""
        if not self._pnl_subscription:
            return PnLData(daily_pnl=0.0)

        try:
            pnl = self._pnl_subscription
            daily = float(pnl.dailyPnL or 0.0)
            realized = float(pnl.realizedPnL or 0.0)
            unrealized = float(pnl.unrealizedPnL or 0.0)
            return PnLData(daily_pnl=daily, realized_pnl=realized, unrealized_pnl=unrealized)
        except Exception as exc:
            logger.error("Failed to get P&L: %s", exc)
            return PnLData(daily_pnl=0.0)

    def write_positions_json(
        self, positions: list[Position] | None = None, pnl: PnLData | None = None
    ) -> bool:
        """Write positions and P&L to JSON file for Conky to read."""
        try:
            if not self.is_market_hours():
                output = PositionsOutput(
                    positions=[],
                    daily_pnl="+$0.00",
                    daily_color="#FFFF00",
                    market_hours=False,
                )
            else:
                if positions is None:
                    positions = self.get_open_positions()
                if pnl is None:
                    pnl = self.get_daily_pnl()

                positions_json = [
                    {
                        "symbol": p.symbol,
                        "pnl": p.pnl_value,
                        "color": p.color,
                    }
                    for p in positions
                ]

                output = PositionsOutput(
                    positions=positions_json,
                    daily_pnl=pnl.daily_value,
                    daily_color=pnl.color,
                    market_hours=True,
                )

            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w") as f:
                json.dump(output.to_dict(), f, indent=2)

            logger.debug("Wrote %s positions to %s", len(output.positions), self.output_file)
            return True

        except Exception as exc:
            logger.error("Failed to write positions JSON: %s", exc)
            return False

    def update(self) -> bool:
        """Perform a single update cycle."""
        try:
            return self.write_positions_json()
        except Exception as exc:
            logger.error("Update failed: %s", exc)
            return False

    def disconnect(self) -> None:
        """Disconnect from IBKR Gateway."""
        if self._pnl_subscription and self.account_id:
            try:
                self.account.cancel_pnl(self.account_id)
            except Exception as exc:
                logger.warning("Failed to cancel PnL subscription: %s", exc)
            self._pnl_subscription = None

        self.session.disconnect()
        logger.info("Disconnected from IBKR Gateway")
