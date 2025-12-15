"""Live SIP selector with L2 integration."""

import logging
from typing import Any, Optional

from qx_data.live.l2_collector import QuantstackL2Collector, create_l2_collector
from qx_screener.sip.hmm_sip import HMMSIPSelector


class LiveSIPSelector:
    """SIP selector for live trading with L2 data collection."""

    def __init__(self, polygon_config: dict[str, Any], l2_config: dict[str, Any]):
        self.polygon_config = polygon_config
        self.l2_config = l2_config
        self.logger = logging.getLogger(__name__)

        # Keep existing HMM SIP for universe selection
        self.hmm_sip = HMMSIPSelector(polygon_config)
        self.l2_collector: Optional[QuantstackL2Collector] = None

    def get_daily_universe(self) -> tuple[list[str], list[str]]:
        """Get SIP universe and L2 focus symbols."""
        # Use existing HMM logic for full universe
        sip_universe = self.hmm_sip.select_symbols()

        # Select top symbols for L2 collection
        l2_symbols = sip_universe[: self.l2_config.get("max_symbols", 3)]

        self.logger.info(f"SIP universe: {len(sip_universe)} symbols")
        self.logger.info(f"L2 focus: {l2_symbols}")

        return sip_universe, l2_symbols

    def start_l2_collection(self, l2_symbols: list[str]) -> None:
        """Start L2 data collection for selected symbols."""
        if self.l2_collector:
            self.l2_collector.stop_collection()

        self.l2_collector = create_l2_collector(l2_symbols, self.l2_config)
        self.l2_collector.start_collection()

    def get_l2_features(self, symbol: str) -> dict[str, Any]:
        """Get current L2 features for trading decisions."""
        if self.l2_collector:
            return self.l2_collector.get_latest_features(symbol)
        return {}

    def poll_l2_data(self) -> None:
        """Poll L2 collector for new data."""
        if self.l2_collector:
            self.l2_collector.poll_once()

    def stop(self) -> dict[str, Any]:
        """Stop all data collection."""
        metadata: dict[str, Any] = {}
        if self.l2_collector:
            metadata = self.l2_collector.stop_collection()
        return metadata
