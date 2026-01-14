"""
Position Monitor - Queries IBKR Platform for positions and P&L.
"""

import json
import logging
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo

from cpapi.platform_client import IBKRPlatformClient, PlatformConfig
from position_monitor.models import PnLData, Position, PositionsOutput

logger = logging.getLogger(__name__)

# Market hours (US Eastern)
MARKET_OPEN = time(9, 30, tzinfo=ZoneInfo("America/New_York"))
MARKET_CLOSE = time(16, 30, tzinfo=ZoneInfo("America/New_York"))
TIMEZONE = ZoneInfo("America/New_York")


class PositionMonitor:
    """
    Queries IBKR Platform for positions and P&L, writes to JSON file.

    Args:
        platform_url: URL of IBKR Platform (default: http://127.0.0.1:8000)
        output_file: Path to output JSON file (default: /tmp/positions.json)
        account_id: IBKR account ID (if None, will fetch from platform)
    """

    def __init__(
        self,
        platform_url: str = "http://127.0.0.1:8000",
        output_file: str = "/tmp/positions.json",
        account_id: str = None,
    ):
        self.platform_url = platform_url
        self.output_file = Path(output_file)
        self.account_id = account_id

        # Initialize platform client
        config = PlatformConfig(base_url=platform_url)
        self.client = IBKRPlatformClient(
            service_id="position-monitor",
            service_name="Position Monitor",
            config=config,
        )

        self._registered = False

    def connect(self) -> bool:
        """Connect to IBKR Platform."""
        try:
            if not self.client.is_healthy():
                logger.error(f"Platform not healthy at {self.platform_url}")
                return False

            success = self.client.register(endpoints=["positions", "pnl"])
            if success:
                self._registered = True
                logger.info("Connected to IBKR Platform")

                # Fetch account ID if not provided
                if not self.account_id:
                    # Get full accounts response to retrieve selected account
                    import requests

                    response = requests.get(
                        f"{self.platform_url}/api/accounts", timeout=10
                    )
                    if response.status_code == 200:
                        data = response.json()
                        accounts = data.get("accounts", [])
                        selected = data.get("selected", "")

                        # Use selected account if available, otherwise first account
                        if selected:
                            self.account_id = selected
                            logger.info(f"Using selected account: {self.account_id}")
                        elif accounts:
                            self.account_id = accounts[0]
                            logger.info(f"Using account: {self.account_id}")
                        else:
                            logger.warning("No accounts found")
                    else:
                        logger.warning("Failed to get accounts from platform")

            return success
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False

    def is_market_hours(self) -> bool:
        """Check if current time is within market hours (0930-1630 ET)."""
        from datetime import datetime

        now = datetime.now(TIMEZONE).time()
        return MARKET_OPEN <= now <= MARKET_CLOSE

    def get_open_positions(self) -> list[Position]:
        """Get open positions from IBKR Platform."""
        if not self.account_id:
            logger.warning("No account ID available")
            return []

        try:
            positions_data = self.client.get_positions(self.account_id, page=0)

            positions = []
            for pos in positions_data:
                # Extract position data
                # IBKR API returns various fields; we need to parse them
                symbol = pos.get("contractdesc", "UNKNOWN")
                if symbol == "UNKNOWN":
                    symbol = pos.get("symbol", "UNKNOWN")

                quantity = int(pos.get("pos", 0))
                if quantity == 0:
                    continue  # Skip positions with zero quantity

                avg_price = float(pos.get("avgpx", 0))
                current_price = float(
                    pos.get("mark_price", pos.get("last_price", avg_price))
                )
                market_value = float(pos.get("mktval", 0))

                # Calculate unrealized P&L
                # IBKR may provide this directly, or we calculate it
                unrealized_pnl = float(pos.get("unrealized_pnl", 0))
                if unrealized_pnl == 0 and quantity != 0:
                    # Calculate from market value and cost basis
                    cost_basis = float(pos.get("cost_basis", market_value))
                    unrealized_pnl = market_value - cost_basis

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

            logger.info(f"Retrieved {len(positions)} open positions")
            return positions

        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return []

    def get_daily_pnl(self) -> PnLData:
        """Get daily P&L from IBKR Platform."""
        try:
            pnl_data = self.client.get_pnl()

            # Parse P&L from response
            # IBKR response format varies; we need to extract daily P&L
            daily_pnl = 0.0

            # Try common fields
            if "upnl" in pnl_data:
                daily_pnl = float(pnl_data["upnl"])
            elif "unrealized_pnl" in pnl_data:
                daily_pnl = float(pnl_data["unrealized_pnl"])
            elif "dailypnl" in pnl_data:
                daily_pnl = float(pnl_data["dailypnl"])

            return PnLData(daily_pnl=daily_pnl)

        except Exception as e:
            logger.error(f"Failed to get P&L: {e}")
            return PnLData(daily_pnl=0.0)

    def write_positions_json(
        self, positions: list[Position] = None, pnl: PnLData = None
    ) -> bool:
        """Write positions and P&L to JSON file for Conky to read."""
        try:
            is_market_hours = self.is_market_hours()

            # If not market hours, write empty data
            if not is_market_hours:
                output = PositionsOutput(
                    positions=[],
                    daily_pnl="+$0.00",
                    daily_color="#FFFF00",
                    market_hours=False,
                )
            else:
                # Fetch data if not provided
                if positions is None:
                    positions = self.get_open_positions()
                if pnl is None:
                    pnl = self.get_daily_pnl()

                # Build position list for JSON
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

            # Write to file
            self.output_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.output_file, "w") as f:
                json.dump(output.to_dict(), f, indent=2)

            logger.debug(
                f"Wrote {len(output.positions)} positions to {self.output_file}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to write positions JSON: {e}")
            return False

    def update(self) -> bool:
        """Perform a single update cycle."""
        try:
            # Send heartbeat
            if self._registered:
                self.client.heartbeat()

            # Check market hours and write JSON
            return self.write_positions_json()

        except Exception as e:
            logger.error(f"Update failed: {e}")
            return False

    def disconnect(self):
        """Disconnect from IBKR Platform."""
        if self._registered:
            self.client.unregister()
            self._registered = False
            logger.info("Disconnected from IBKR Platform")
