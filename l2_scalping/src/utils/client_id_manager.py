"""
Dynamic Client ID Manager for IBKR Gateway connections.

Handles client ID allocation within assigned ranges to avoid Gateway's
client ID caching behavior that prevents reconnection with same ID.
"""

import logging
from pathlib import Path
from typing import Dict, Any

logger = logging.getLogger(__name__)


class ClientIDManager:
    """Manages dynamic client ID allocation within assigned ranges"""
    
    def __init__(self, config: Dict[str, Any], service_name: str):
        self.config = config
        self.service_name = service_name
        self.state_file = Path(f"data/{service_name}_client_ids.txt")
        
        # Get ID ranges from config
        self.order_base = config.get("order_client_id_base", 40)
        self.data_base = config.get("data_client_id_base", 50) 
        self.max_id = config.get("client_id_max", 59)
        
        # Load current IDs or start fresh
        self.current_order_id, self.current_data_id = self._load_current_ids()
        
    def _load_current_ids(self) -> tuple[int, int]:
        """Load current client IDs from state file"""
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    line = f.read().strip()
                    if line:
                        order_id, data_id = map(int, line.split(','))
                        logger.info(f"Loaded client IDs: order={order_id}, data={data_id}")
                        return order_id, data_id
        except Exception as e:
            logger.warning(f"Could not load client IDs: {e}")
            
        # Start with base IDs
        logger.info(f"Starting with base client IDs: order={self.order_base}, data={self.data_base}")
        return self.order_base, self.data_base
    
    def _save_current_ids(self):
        """Save current client IDs to state file"""
        try:
            self.state_file.parent.mkdir(exist_ok=True)
            with open(self.state_file, 'w') as f:
                f.write(f"{self.current_order_id},{self.current_data_id}")
        except Exception as e:
            logger.error(f"Could not save client IDs: {e}")
    
    def get_next_order_id(self) -> int:
        """Get next available order client ID"""
        self.current_order_id += 1
        if self.current_order_id > self.max_id:
            self.current_order_id = self.order_base
            logger.info(f"Order client ID wrapped to {self.current_order_id}")
        
        self._save_current_ids()
        logger.info(f"Allocated order client ID: {self.current_order_id}")
        return self.current_order_id
    
    def get_next_data_id(self) -> int:
        """Get next available data client ID"""
        self.current_data_id += 1
        if self.current_data_id > self.max_id:
            self.current_data_id = self.data_base
            logger.info(f"Data client ID wrapped to {self.current_data_id}")
            
        self._save_current_ids()
        logger.info(f"Allocated data client ID: {self.current_data_id}")
        return self.current_data_id
    
    def get_current_ids(self) -> tuple[int, int]:
        """Get current client IDs without incrementing"""
        return self.current_order_id, self.current_data_id
