"""
Client ID Manager for IBKR Gateway connections.

Handles client ID allocation within assigned ranges to avoid Gateway's
client ID caching behavior that prevents reconnection with same ID.

Range Allocation:
  1-99:    l2-collector
  100-199: intraday-paper  
  200-299: l2-scalping
  300-399: l2-vwap-reversion
  400-499: reserved
  900-999: utilities (preflight, monitoring)
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

STATE_DIR = Path.home() / ".quantstack" / "client_ids"


class ClientIDManager:
    """Manages dynamic client ID allocation within assigned ranges."""

    def __init__(self, service_name: str, order_base: int, data_base: int, max_id: int):
        self.service_name = service_name
        self.order_base = order_base
        self.data_base = data_base
        self.max_id = max_id
        self.state_file = STATE_DIR / f"{service_name}.json"
        self.current_order_id, self.current_data_id = self._load_state()

    def _load_state(self) -> tuple[int, int]:
        """Load current client IDs from state file."""
        try:
            if self.state_file.exists():
                data = json.loads(self.state_file.read_text())
                order_id = data.get("order", self.order_base)
                data_id = data.get("data", self.data_base)
                logger.info(
                    f"[{self.service_name}] Loaded client IDs: order={order_id}, data={data_id}"
                )
                return order_id, data_id
        except Exception as e:
            logger.warning(f"[{self.service_name}] Could not load client IDs: {e}")
        return self.order_base, self.data_base

    def _save_state(self) -> None:
        """Save current client IDs to state file."""
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(
                json.dumps(
                    {
                        "order": self.current_order_id,
                        "data": self.current_data_id,
                    }
                )
            )
        except Exception as e:
            logger.error(f"[{self.service_name}] Could not save client IDs: {e}")

    def get_order_id(self) -> int:
        """Get next order client ID (increments within range)."""
        self.current_order_id += 1
        if self.current_order_id > min(self.data_base - 1, self.max_id):
            self.current_order_id = self.order_base
        self._save_state()
        logger.info(
            f"[{self.service_name}] Allocated order client ID: {self.current_order_id}"
        )
        return self.current_order_id

    def get_data_id(self) -> int:
        """Get next data client ID (increments within range)."""
        self.current_data_id += 1
        if self.current_data_id > self.max_id:
            self.current_data_id = self.data_base
        self._save_state()
        logger.info(
            f"[{self.service_name}] Allocated data client ID: {self.current_data_id}"
        )
        return self.current_data_id

    @classmethod
    def from_config(cls, service_name: str, config: dict) -> "ClientIDManager":
        """Create manager from config dict with ibkr section."""
        ibkr = config.get("ibkr", config)
        return cls(
            service_name=service_name,
            order_base=ibkr.get("order_client_id_base", ibkr.get("order_client_id", 1)),
            data_base=ibkr.get("data_client_id_base", ibkr.get("data_client_id", 50)),
            max_id=ibkr.get("client_id_max", 99),
        )
