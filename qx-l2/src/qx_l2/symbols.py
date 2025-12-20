"""Independent L2 symbol selection."""

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class L2SymbolSelector:
    """Independent symbol selection for L2 collection."""

    def __init__(self, config: dict):
        symbols_cfg = config.get("symbols", {})
        self.mode = symbols_cfg.get("mode", "hybrid")
        self.core_symbols = symbols_cfg.get("core", [])
        self.rotating_pool = symbols_cfg.get("rotating_pool", [])
        self.max_symbols = symbols_cfg.get("max_symbols", 6)
        self._external_symbols: Optional[list[str]] = None

        storage_cfg = config.get("storage", {})
        self.log_dir = Path(storage_cfg.get("base_dir", "./data/l2")) / "selection_log"

    def get_symbols(self, date_str: str = None) -> list[str]:
        """Get symbols for collection based on mode."""
        if date_str is None:
            date_str = datetime.now().strftime("%Y-%m-%d")

        if self.mode == "static":
            symbols = self._get_static()
        elif self.mode == "rotating":
            symbols = self._get_rotating(date_str)
        elif self.mode == "hybrid":
            symbols = self._get_hybrid(date_str)
        elif self.mode == "external":
            symbols = self._get_external()
        else:
            logger.warning(f"Unknown mode '{self.mode}', using static")
            symbols = self._get_static()

        self._log_selection(date_str, symbols)
        return symbols

    def _get_static(self) -> list[str]:
        """Static: use core symbols only."""
        return self.core_symbols[: self.max_symbols]

    def _get_rotating(self, date_str: str) -> list[str]:
        """Rotating: round-robin through pool."""
        if not self.rotating_pool:
            return self.core_symbols[: self.max_symbols]

        # Deterministic rotation based on date
        day_hash = self._stable_hash(date_str) % len(self.rotating_pool)
        rotated = self.rotating_pool[day_hash:] + self.rotating_pool[:day_hash]
        return rotated[: self.max_symbols]

    def _get_hybrid(self, date_str: str) -> list[str]:
        """Hybrid: core symbols + rotating from pool."""
        symbols = list(self.core_symbols)

        if self.rotating_pool:
            # Exclude core from rotating pool
            available = [s for s in self.rotating_pool if s not in self.core_symbols]
            if available:
                day_hash = self._stable_hash(date_str) % len(available)
                rotated = available[day_hash:] + available[:day_hash]
                remaining = self.max_symbols - len(symbols)
                symbols.extend(rotated[:remaining])

        return symbols[: self.max_symbols]

    def _get_external(self) -> list[str]:
        """External: use injected symbols."""
        if self._external_symbols:
            return self._external_symbols[: self.max_symbols]
        return self.core_symbols[: self.max_symbols]

    def set_external_symbols(self, symbols: list[str]):
        """Inject external symbols (e.g., from SIP)."""
        self._external_symbols = symbols
        logger.info(f"External symbols set: {symbols}")

    @staticmethod
    def _stable_hash(value: str) -> int:
        """Stable hash for deterministic rotations."""
        digest = hashlib.md5(value.encode("utf-8")).hexdigest()
        return int(digest, 16)

    def _log_selection(self, date_str: str, symbols: list[str]):
        """Log symbol selection for tracking."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            log_file = self.log_dir / f"{date_str}.json"

            selection = {
                "date": date_str,
                "timestamp": datetime.now().isoformat(),
                "mode": self.mode,
                "symbols": symbols,
                "core": [s for s in symbols if s in self.core_symbols],
                "rotating": [s for s in symbols if s not in self.core_symbols],
            }

            with open(log_file, "w") as f:
                json.dump(selection, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to log selection: {e}")
