"""L2 data collector integrated from transalpha/l2."""

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Import existing L2 system
transalpha_l2 = Path.home() / "transalpha" / "l2"
if transalpha_l2.exists():
    sys.path.insert(0, str(transalpha_l2))

try:
    from multi_l2_collector import CollectorConfig, MultiL2Collector
    from time_windows import parse_windows
except ImportError as e:
    raise ImportError(f"Cannot import L2 modules from {transalpha_l2}: {e}") from e


class QuantstackL2Collector:
    """Wrapper for existing L2 collector with quantstack integration."""

    def __init__(self, symbols: list[str], config: dict[str, Any]):
        self.symbols = symbols
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Map quantstack config to CollectorConfig
        collector_cfg = CollectorConfig(
            host=config.get("host", "127.0.0.1"),
            port=config.get("port", 7497),
            client_id=config.get("client_id", 310),  # qx-data L2 range: 300-399
            symbols=symbols,
            levels=config.get("levels", 10),
            max_depth_symbols=config.get("max_symbols", 3),
            rotate_every_sec=config.get("rotate_seconds", 300),  # 5min rotation
            out_dir=config.get(
                "output_dir",
                f"{os.environ.get('L2_DATA_ROOT', '/home/jacobw/quantstack/data/l2')}/live_l2",
            ),
            run_id=config.get("run_id", "quantstack_live"),
            session_windows_et=parse_windows(config.get("windows", ["09:30-16:00"])),
        )

        self.collector = MultiL2Collector(collector_cfg, self.logger)

    def start_collection(self) -> None:
        """Start L2 data collection."""
        self.collector.start()

    def poll_once(self) -> None:
        """Poll for new data."""
        self.collector.poll_once()

    def stop_collection(self) -> dict[str, Any]:
        """Stop collection and return metadata."""
        return self.collector.stop()

    def get_latest_features(self, symbol: str) -> dict[str, Any]:
        """Get latest L2 features for a symbol."""
        # Access internal state for live features
        if symbol in self.collector._states:
            state = self.collector._states[symbol]
            if state.ticker:
                # Create snapshot and compute features
                snap = self.collector._make_snapshot_row(symbol, time.time())
                return state.fe.update_and_compute(snap, self.collector.cfg.levels)
        return {}


def create_l2_collector(
    sip_symbols: list[str], config: dict[str, Any]
) -> QuantstackL2Collector:
    """Factory function to create L2 collector from SIP universe."""
    # Select top 3 for L2 collection
    l2_symbols = sip_symbols[: config.get("max_symbols", 3)]
    return QuantstackL2Collector(l2_symbols, config)
